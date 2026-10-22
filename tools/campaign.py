"""Time-boxed measured campaign: run pending candidates, then soak the active result.

Each experiment runs in a fresh Python subprocess so module caches cannot hide a
promotion. Measurements also run in fresh subprocesses. Everything is written
incrementally, so a killed campaign can be diagnosed from campaign/rate.json and the
runner checkpoints.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from tools import checkpoint, runner, state as state_mod
from tools.security import ROOT, Workspace

EXPERIMENTS = ("E002-scan-fast", "E003-scan-snapshot")


def _bench(ws: Workspace, name: str) -> dict:
    output = f"campaign/{name}.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.bench",
            "--module",
            "active",
            "--tasks",
            "benchmarks/tasks_dev.json",
            "benchmarks/tasks_heldout.json",
            "--repetitions",
            "5",
            "--output",
            output,
        ],
        cwd=ws.root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"benchmark failed rc={proc.returncode}: {proc.stderr.strip()[:500]}")
    return json.loads(ws.read_text(output))


def _run_experiment(ws: Workspace, experiment_id: str) -> dict:
    state = state_mod.load_state(ws.root)
    pending = list(state.get("pending_experiments", []))
    if experiment_id not in pending:
        pending.append(experiment_id)
        state["pending_experiments"] = pending
        state_mod.save_state(state, ws.root)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "tools.runner", "--no-model", "--max-experiments", "1"],
        cwd=ws.root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    elapsed = time.monotonic() - started
    return {
        "experiment": experiment_id,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip()[-2000:],
        "stderr": proc.stderr.strip()[-2000:],
        "elapsed_seconds": round(elapsed, 3),
    }


def _append_timeline(ws: Workspace, record: dict) -> None:
    path = ws.root / "campaign" / "timeline.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()


def _write_rate(ws: Workspace, result: dict) -> None:
    ws.write_json("campaign/rate.json", result)


def run(minutes: float = 30.0, root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    started_wall = state_mod.utc_now()
    started = time.monotonic()
    deadline = started + max(0.1, minutes) * 60
    initial = _bench(ws, "bench-initial")
    previous_median = float(initial["median_batch_ms"])
    rows: list[dict] = []
    errors: list[str] = []

    for experiment_id in EXPERIMENTS:
        if time.monotonic() >= deadline:
            break
        state = state_mod.load_state(ws.root)
        if experiment_id in state.get("completed_experiments", []) or experiment_id in state.get(
            "failed_experiments", {}
        ):
            continue
        before = _bench(ws, f"bench-{experiment_id}-before")
        before_ms = float(before["median_batch_ms"])
        run_record = _run_experiment(ws, experiment_id)
        state = state_mod.load_state(ws.root)
        after = _bench(ws, f"bench-{experiment_id}-after")
        after_ms = float(after["median_batch_ms"])
        delta_pct = round((before_ms - after_ms) / before_ms * 100, 3) if before_ms else 0.0
        row = {
            "experiment": experiment_id,
            "accepted": state.get("experiments", {}).get(experiment_id, {}).get("status") == "accepted",
            "before_median_ms": before_ms,
            "after_median_ms": after_ms,
            "delta_pct": delta_pct,
            "elapsed_seconds": run_record["elapsed_seconds"],
            "rate_pct_per_min": round(delta_pct / (run_record["elapsed_seconds"] / 60), 3)
            if run_record["elapsed_seconds"]
            else None,
            "runner_returncode": run_record["returncode"],
            "runner_stdout": run_record["stdout"],
            "runner_stderr": run_record["stderr"],
        }
        rows.append(row)
        previous_median = after_ms
        _append_timeline(
            ws,
            {
                "timestamp": state_mod.utc_now(),
                "kind": "experiment",
                "elapsed_min": round((time.monotonic() - started) / 60, 3),
                **row,
            },
        )
        if run_record["returncode"] != 0:
            errors.append(f"{experiment_id}: runner rc={run_record['returncode']}")
            break

    soak: list[dict] = []
    next_sample = time.monotonic() + 60
    last_checkpoint_at = time.monotonic()
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        time.sleep(max(0.0, min(remaining, next_sample - time.monotonic())))
        if time.monotonic() >= deadline:
            break
        sample = _bench(ws, f"bench-soak-{len(soak):02d}")
        entry = {
            "elapsed_min": round((time.monotonic() - started) / 60, 3),
            "median_batch_ms": sample["median_batch_ms"],
            "cold_batch_ms": sample["cold_batch_ms"],
            "p95_batch_ms": sample["p95_batch_ms"],
            "correctness": sample["correctness"],
        }
        soak.append(entry)
        _append_timeline(ws, {"timestamp": state_mod.utc_now(), "kind": "soak", **entry})
        next_sample += 60
        if time.monotonic() - last_checkpoint_at >= 300:
            checkpoint.create("campaign-soak", ws.root)
            last_checkpoint_at = time.monotonic()

    final = _bench(ws, "bench-final")
    finished = time.monotonic()
    wall_minutes = (finished - started) / 60
    final_ms = float(final["median_batch_ms"])
    total_reduction = round((initial["median_batch_ms"] - final_ms) / initial["median_batch_ms"] * 100, 3)
    result = {
        "schema": 1,
        "started_at": started_wall,
        "finished_at": state_mod.utc_now(),
        "requested_minutes": minutes,
        "wall_minutes": round(wall_minutes, 3),
        "initial_median_ms": initial["median_batch_ms"],
        "initial_cold_ms": initial["cold_batch_ms"],
        "final_median_ms": final["median_batch_ms"],
        "final_cold_ms": final["cold_batch_ms"],
        "total_reduction_pct": total_reduction,
        "total_rate_pct_per_min": round(total_reduction / wall_minutes, 4) if wall_minutes else None,
        "experiments": rows,
        "soak": soak,
        "soak_median_ms": statistics.median([s["median_batch_ms"] for s in soak]) if soak else None,
        "errors": errors,
    }
    _write_rate(ws, result)
    manifest = checkpoint.create("campaign-final", ws.root)
    verify = checkpoint.verify(f"checkpoints/{manifest['name']}.json", ws.root)
    result["checkpoint"] = f"checkpoints/{manifest['name']}.json"
    result["checkpoint_verified"] = verify["ok"]
    _write_rate(ws, result)
    state = state_mod.load_state(ws.root)
    state["last_checkpoint"] = result["checkpoint"]
    state["last_campaign"] = {
        "minutes": round(wall_minutes, 3),
        "initial_median_ms": result["initial_median_ms"],
        "final_median_ms": result["final_median_ms"],
        "total_reduction_pct": total_reduction,
        "checkpoint": result["checkpoint"],
    }
    state["next_task"] = "Review the 30-minute campaign and gate the next experiment."
    state_mod.save_state(state, ws.root)
    _write_rate(ws, result)
    runner._git_commit(ws, f"soo: {minutes:g}-minute measured campaign")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measured campaign with a hard wall-clock budget")
    parser.add_argument("--minutes", type=float, default=30.0)
    args = parser.parse_args(argv)
    result = run(args.minutes)
    print(
        f"campaign minutes={result['wall_minutes']} initial={result['initial_median_ms']}ms "
        f"final={result['final_median_ms']}ms reduction={result['total_reduction_pct']}% "
        f"rate={result['total_rate_pct_per_min']}%/min"
    )
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
