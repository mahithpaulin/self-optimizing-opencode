"""Stage A: bounded, read-only inspection of the workspace and host."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools import state as state_mod
from tools.security import ROOT, Workspace


def _version(argv: list[str], timeout: float = 10) -> dict:
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        )
        return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr).strip()[:200]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "output": f"{type(exc).__name__}: {exc}"}


def _mem_available_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def _protected_hashes(ws: Workspace) -> dict[str, str]:
    prefixes = tuple(
        prefix for prefix in ws.policy.get("protected_write_prefixes", [])
        if prefix not in {".git/", "checkpoints/"}
    )
    result: dict[str, str] = {}
    for path in ws.files():
        rel = path.relative_to(ws.root).as_posix()
        if not any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in prefixes):
            continue
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def snapshot(root: str | os.PathLike[str] | None = None, *, run_id: str | None = None) -> dict:
    ws = Workspace(root or ROOT)
    root_path = ws.root
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    files = list(ws.files())
    by_suffix: dict[str, int] = {}
    total_bytes = 0
    for path in files:
        suffix = path.suffix or "<none>"
        by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
    tests = [p for p in files if p.relative_to(root_path).as_posix().startswith("tests/") and p.suffix == ".py"]
    test_count = 0
    for path in tests:
        test_count += sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip().startswith("def test_"))
    try:
        disk = shutil.disk_usage(root_path)
        disk_free_mb = disk.free // (1024 * 1024)
    except OSError:
        disk_free_mb = None
    git_status = ws.run(["git", "status", "--short", "--branch"])
    git_log = ws.run(["git", "log", "--oneline", "-5"])
    st = state_mod.load_state(root_path)
    baseline = root_path / "benchmarks" / "results" / "baseline.json"
    result = {
        "schema": 1,
        "run_id": run_id,
        "timestamp": state_mod.utc_now(),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "node": _version(["node", "--version"]),
            "opencode_v1": _version(["opencode", "--version"]),
            "opencode_v2": _version([str(Path.home() / ".local/opencode-v2/bin/opencode2"), "--version"]),
            "mem_available_mb": _mem_available_mb(),
            "disk_free_mb": disk_free_mb,
            "cpu_count": os.cpu_count(),
        },
        "workspace": {
            "path": str(root_path),
            "file_count": len(files),
            "total_bytes": total_bytes,
            "by_suffix": dict(sorted(by_suffix.items())),
            "tree_hash": ws.tree_hash(),
            "test_files": len(tests),
            "test_functions": test_count,
        },
        "git": {
            "status_ok": git_status["ok"],
            "status": git_status["stdout"].strip(),
            "log": git_log["stdout"].strip(),
        },
        "state": {
            "run_count": st.get("run_count", 0),
            "pending": st.get("pending_experiments", []),
            "completed": st.get("completed_experiments", []),
            "current": st.get("current_experiment"),
            "failure_streak": st.get("failure_streak", 0),
            "next_task": st.get("next_task"),
        },
        "baseline_present": baseline.exists(),
        "protected_hashes": _protected_hashes(ws),
        "limitations": [
            "same-UID worker; no container or kernel namespace",
            "network egress restricted by environment and allowlist, not a netns",
        ],
    }
    ws.write_json(f"logs/inspect-{run_id}.json", result)
    return result
