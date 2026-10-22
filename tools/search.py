"""Candidate search backend: in-process index with per-query regex matching.

Compatibility guard: patterns that use constructs where GNU grep ERE and Python `re`
differ (PCRE-style character classes, POSIX classes, backreferences) fall back to the
immutable grep baseline, so the replacement is safe beyond the frozen benchmark.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from tools.search_baseline import IGNORE_DIRS, SearchError, search as baseline_search

_CACHE: dict[tuple[str, str | None], dict] = {}
_UNSAFE = re.compile(r"\\[dDwWsSbB]|\[\[:|\\[1-9]")


def reset_cache() -> None:
    _CACHE.clear()


def _scan(root: Path, include: str | None) -> dict:
    entries: list[tuple[str, int, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORE_DIRS)
        for name in sorted(filenames):
            if include and not fnmatch.fnmatch(name, include):
                continue
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            entries.append((rel, stat.st_mtime_ns, stat.st_size, str(path)))
    fingerprint = tuple((rel, mtime, size) for rel, mtime, size, _ in entries)
    key = (str(root), include)
    cached = _CACHE.get(key)
    if cached is not None and cached["fingerprint"] == fingerprint:
        return cached
    files: list[tuple[str, str]] = []
    for rel, _mtime, _size, raw in entries:
        try:
            data = Path(raw).read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        files.append((rel, data.decode("utf-8", "replace")))
    record = {"fingerprint": fingerprint, "files": files}
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
    for rel, text in record["files"]:
        for number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                results.append({"path": rel, "line": number, "text": line[:400]})
    results.sort(key=lambda item: (item["path"], item["line"]))
    truncated = len(results) > max_results
    return {
        "engine": "python-index",
        "results": results[:max_results],
        "truncated": truncated,
    }
