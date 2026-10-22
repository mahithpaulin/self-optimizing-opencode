"""Bootstrap baseline: frozen benchmark + suite + expected-deny tool probes + recovery."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

from tools import state as state_mod
from tools.bench import _load_tasks, run_benchmark
from tools.security import ROOT, SecurityError, Workspace
from tools.search_baseline import SearchError, search as baseline_search


def _probe(name: str, func, expected: str) -> dict:
    started = time.perf_counter()
    try:
        func()
        actual = "ok"
        detail = ""
    except (SecurityError, SearchError) as exc:
        actual = "deny" if isinstance(exc, SecurityError) else "error"
        detail = str(exc)[:200]
    except Exception as exc:
        actual = "error"
        detail = f"{type(exc).__name__}: {exc}"[:200]
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "ok": actual == expected,
        "detail": detail,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def tool_probes(ws: Workspace) -> list[dict]:
    link = ws.root / "sandbox" / "escape-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink("/etc/hostname", link)
    except OSError:
        pass
    probes = [
        _probe("read_workspace_file", lambda: ws.read_text("README.md"), "ok"),
        _probe("read_outside", lambda: ws.read_text("/etc/hostname"), "deny"),
        _probe("read_symlink_escape", lambda: ws.read_text("sandbox/escape-link"), "deny"),
        _probe("read_secret_name", lambda: ws.read_text("sandbox/auth.json"), "deny"),
        _probe("write_outside", lambda: ws.write_text("/tmp/soo-escape", "x"), "deny"),
        _probe("write_protected", lambda: ws.write_text("tests/probe.txt", "x"), "deny"),
        _probe("run_git_status", lambda: ws.run(["git", "status", "--short"]), "ok"),
        _probe("run_git_push", lambda: ws.run(["git", "push"]), "deny"),
        _probe("run_shell_echo", lambda: ws.run(["echo", "hi"]), "deny"),
        _probe("run_python_c", lambda: ws.run(["python3", "-c", "print(1)"]), "deny"),
        _probe("search_valid", lambda: baseline_search("benchmarks/corpus", "TODO"), "ok"),
        _probe("search_invalid_regex", lambda: baseline_search("benchmarks/corpus", "("), "error"),
    ]
    try:
        link.unlink()
    except OSError:
        pass
    return probes


def suite(ws: Workspace) -> dict:
    result = ws.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])
    output = result["stdout"] + result["stderr"]
    match = re.search(r"Ran (\d+) tests?", output)
    return {
        "ok": result["ok"] and "FAILED" not in output,
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "tests": int(match.group(1)) if match else None,
        "summary": next((line.strip() for line in reversed(output.splitlines()) if line.strip() in {"OK", "FAILED"} or line.startswith("FAILED (")), ""),
        "duration_ms": result["duration_ms"],
        "tail": "\n".join(output.splitlines()[-12:]),
    }


def recovery_drill(ws: Workspace) -> dict:
    base = ws.root / "sandbox" / "recovery"
    base.mkdir(parents=True, exist_ok=True)
    good = {"schema": 1, "value": 42, "completed_experiments": []}
    (base / "state.json").write_text("{corrupt", encoding="utf-8")
    (base / "state.json.bak").write_text(json.dumps(good), encoding="utf-8")
    recovered = state_mod.load_state(base)
    state_ok = recovered.get("value") == 42
    logs = base / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "runner.lock").write_text(json.dumps({"pid": 999999, "created_epoch": time.time()}), encoding="utf-8")
    lock = state_mod.acquire_lock(base, stale_seconds=60)
    state_mod.release_lock(lock, base)
    lock_ok = not (logs / "runner.lock").exists()
    return {
        "ok": state_ok and lock_ok,
        "state_restore": state_ok,
        "stale_lock_clear": lock_ok,
        "rate": 1.0 if state_ok and lock_ok else 0.0,
    }


def build(ws: Workspace, *, repetitions: int) -> dict:
    tasks = _load_tasks(
        ws,
        ["benchmarks/tasks_dev.json", "benchmarks/tasks_heldout.json"],
    )
    expected = json.loads(ws.read_text("benchmarks/expected.json"))
    bench = run_benchmark("baseline", tasks, expected, repetitions, ws)
    tests = suite(ws)
    probes = tool_probes(ws)
    recovery = recovery_drill(ws)
    capabilities = [
        "security",
        "search",
        "state",
        "checkpoint",
        "benchmark",
        "model-adapter",
        "runner",
    ]
    return {
        "schema": 1,
        "created_at": state_mod.utc_now(),
        "bench": bench,
        "tests": tests,
        "tool_probes": probes,
        "tool_success_rate": round(sum(1 for probe in probes if probe["ok"]) / len(probes), 6),
        "recovery": recovery,
        "capabilities": capabilities if tests["ok"] else [],
        "capability_count": len(capabilities) if tests["ok"] else 0,
        "environment": {
            "path": str(ws.root),
            "baseline_repetitions": repetitions,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture the immutable baseline once")
    parser.add_argument("--force", action="store_true", help="overwrite an existing baseline")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="benchmarks/results/baseline.json")
    args = parser.parse_args(argv)
    ws = Workspace(ROOT)
    target = ws.root / args.output
    if target.exists() and not args.force:
        print(f"baseline already exists: {args.output} (use --force only as bootstrap)")
        return 0
    result = build(ws, repetitions=args.repetitions)
    ws.write_json(args.output, result, allow_protected=True)
    print(
        f"baseline tests={result['tests']['ok']} probes={result['tool_success_rate']} "
        f"median={result['bench']['median_batch_ms']}ms recovery={result['recovery']['rate']}"
    )
    return 0 if result["tests"]["ok"] and result["bench"]["correctness"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
