"""Scan validation cache: reuse the file snapshot while stats are unchanged.

A file content change is detected by mtime/size; an add/remove/rename is detected by
the cached directory mtimes. On any mismatch the full walk runs and rebuilds the cache,
so results are never served from a stale snapshot in the normal mutation cases the
previous fingerprint caught.
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from pathlib import Path

from tools.search_baseline import IGNORE_DIRS, SearchError, search as baseline_search

_CACHE: dict[tuple[str, str | None], dict] = {}
_UNSAFE = re.compile(r"\\[dDwWsSbB]|\[\[:|\\[1-9]")


def reset_cache() -> None:
    _CACHE.clear()


def _full_scan(root_s: str, include: str | None) -> dict:
    entries: list[tuple[str, int, int, str]] = []
    directories: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root_s, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORE_DIRS)
        try:
            dst = os.stat(dirpath, follow_symlinks=False)
        except OSError:
            continue
        directories.append((dirpath, dst.st_mtime_ns))
        for name in sorted(filenames):
            if include and not fnmatch.fnmatch(name, include):
                continue
            raw = os.path.join(dirpath, name)
            try:
                st = os.stat(raw, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                continue
            rel = os.path.relpath(raw, root_s).replace(os.sep, "/")
            entries.append((rel, st.st_mtime_ns, st.st_size, raw))
    files: list[tuple[str, tuple[str, ...]]] = []
    for rel, _mtime, _size, raw in entries:
        try:
            with open(raw, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        files.append((rel, tuple(data.decode("utf-8", "replace").splitlines())))
    return {"directories": directories, "entries": entries, "files": files}


def _unchanged(record: dict) -> bool:
    for path, mtime in record["directories"]:
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            return False
        if st.st_mtime_ns != mtime:
            return False
    for _rel, mtime, size, raw in record["entries"]:
        try:
            st = os.stat(raw, follow_symlinks=False)
        except OSError:
            return False
        if st.st_mtime_ns != mtime or st.st_size != size:
            return False
    return True


def _scan(root: Path, include: str | None) -> dict:
    root_s = os.fspath(root)
    key = (root_s, include)
    cached = _CACHE.get(key)
    if cached is not None and _unchanged(cached):
        return cached
    record = _full_scan(root_s, include)
    _CACHE[key] = record
    return record


def search(
    root: str | Path,
    pattern: str,
    include: str | None = "*.py",
    max_results: int = 500,
) -> dict:
    if not pattern:
        raise SearchError("empty pattern")
    if _UNSAFE.search(pattern):
        return baseline_search(root, pattern, include=include, max_results=max_results)
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise SearchError(f"not a directory: {root_path}")
    max_results = int(max_results)
    if max_results < 1:
        raise SearchError("max_results must be positive")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise SearchError(f"invalid pattern: {exc}") from exc
    record = _scan(root_path, include)
    results = []
    for rel, lines in record["files"]:
        for number, line in enumerate(lines, start=1):
            if regex.search(line):
                results.append({"path": rel, "line": number, "text": line[:400]})
    results.sort(key=lambda item: (item["path"], item["line"]))
    truncated = len(results) > max_results
    return {
        "engine": "python-index",
        "results": results[:max_results],
        "truncated": truncated,
    }
