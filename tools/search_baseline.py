"""Reference search backend: one grep subprocess per query.

This file is immutable to the worker. It is both the baseline implementation and the
compatibility fallback for the indexed backend.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

IGNORE_DIRS = (".git", "__pycache__", "node_modules", "checkpoints", "logs", "sandbox")


class SearchError(RuntimeError):
    pass


def search(
    root: str | Path,
    pattern: str,
    include: str | None = "*.py",
    max_results: int = 500,
) -> dict:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise SearchError(f"not a directory: {root_path}")
    if not pattern:
        raise SearchError("empty pattern")
    max_results = int(max_results)
    if max_results < 1:
        raise SearchError("max_results must be positive")
    argv = [
        "grep",
        "-rnE",
        "--binary-files=without-match",
    ]
    for name in IGNORE_DIRS:
        argv.append(f"--exclude-dir={name}")
    if include:
        argv.extend(["--include", include])
    argv.extend(["-e", pattern, str(root_path)])
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SearchError("search timed out") from exc
    if proc.returncode not in (0, 1):
        raise SearchError(proc.stderr.decode("utf-8", "replace").strip()[:500] or f"grep rc={proc.returncode}")
    results = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        rel, sep, rest = line.partition(":")
        if not sep:
            continue
        lineno, sep2, text = rest.partition(":")
        if not sep2:
            continue
        try:
            number = int(lineno)
        except ValueError:
            continue
        results.append(
            {
                "path": Path(rel).resolve().relative_to(root_path).as_posix(),
                "line": number,
                "text": text[:400],
            }
        )
    results.sort(key=lambda item: (item["path"], item["line"]))
    truncated = len(results) > max_results
    return {
        "engine": "grep",
        "results": results[:max_results],
        "truncated": truncated,
    }
