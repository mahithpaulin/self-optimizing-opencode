"""Bounded, resumable Stage A-E runner.

One invocation: inspect -> checkpoint -> test a candidate -> promote -> test and
measure -> keep or roll it back -> checkpoint -> persist state -> local commit ->
one free-model proposal. No network, no deploy, no paid provider, no unbounded loop.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from tools import baseline as baseline_mod
from tools import checkpoint, experiment, model, state as state_mod
from tools.bench import _load_tasks, run_benchmark
from tools.inspect import snapshot
from tools.security import ROOT, Workspace


def _bench(ws: Workspace, module: str, tasks: list[dict], expected: dict, repetitions: int) -> dict:
    return run_benchmark(module, tasks, expected, repetitions, ws)


def _git_commit(ws: Workspace, message: str) -> dict:
    status = ws.run(["git", "status", "--short"])
    if not status["stdout"].strip():
        return {"committed": False, "reason": "nothing to commit", "status": status}
    paths = [
        ".gitignore",
        "README.md",
        "REPORT.md",
        "STATE.md",
        "ROADMAP.md",
        "ARCHITECTURE.md",
        "opencode.jsonc",
        ".opencode",
        "config",
        "tools",
        "experiments",
        "benchmarks",
        "tests",
        "model-host",
        "logs",
        "proposals",
        "campaign",
        "rollback",
        "state.json",
        "state.json.bak",
    ]
    paths = [path for path in paths if (ws.root / path).exists()]
    added = ws.run(["git", "add", *paths])
    committed = ws.run(["git", "commit", "-m", message])
    log = ws.run(["git", "log", "--oneline", "-3"])
    return {
        "committed": committed["ok"],
        "add": added["stdout"].strip(),
        "commit": committed["stdout"].strip(),
        "stderr": committed["stderr"].strip()[:1000],
        "log": log["stdout"].strip(),
    }


def _write_run_log(ws: Workspace, record: dict) -> None:
    stamp = state_mod.utc_now().replace(":", "").replace("-", "")
    ws.write_json(f"logs/runs/run-{stamp}.json", record)


def run(
    root: str | Path | None = None,
    *,
    allow_model: bool = True,
    max_experiments: int | None = None,
) -> dict:
    ws = Workspace(root or ROOT)
    limits = ws.limits
    started = time.monotonic()
    state = state_mod.load_state(ws.root)
    lock = state_mod.acquire_lock(ws.root, stale_seconds=int(limits["lock_stale_seconds"]))
    record: dict = {"schema": 1, "started_at": state_mod.utc_now(), "steps": [], "errors": []}
    try:
        available = model.free_mb()
        if available < int(limits["min_free_mb"]):
            raise RuntimeError(f"insufficient free memory: {available} MB < {limits['min_free_mb']} MB")
        state.setdefault("failed_experiments", {})
        state.setdefault("experiments", {})
        state.setdefault("model_calls", 0)
        if int(state.get("failure_streak", 0)) >= int(limits["max_failure_streak"]):
            raise RuntimeError(f"failure streak {state.get('failure_streak')} reached max_failure_streak")
        state["run_count"] = int(state.get("run_count", 0)) + 1
        state["last_run_started"] = state_mod.utc_now()
        if state.get("pending_experiments"):
            state["next_task"] = "Execute the next pending experiment, then one proposal call."
        else:
            state["next_task"] = "Review evidence and gate the next experiment."
        state_mod.save_state(state, ws.root)
        snap = snapshot(ws.root, run_id=f"run-{state['run_count']:03d}")
        record["inspect"] = snap
        record["steps"].append({"step": "inspect", "ok": True, "mem_available_mb": snap["host"]["mem_available_mb"]})

        baseline = json.loads(ws.read_text(state.get("baseline_path", "benchmarks/results/baseline.json")))
        expected = json.loads(ws.read_text("benchmarks/expected.json"))
        tasks = _load_tasks(ws, ["benchmarks/tasks_dev.json", "benchmarks/tasks_heldout.json"])
        proposal_ids = list(state.get("pending_experiments", []))
        limit = int(max_experiments if max_experiments is not None else limits["max_iterations"])
        proposal_ids = proposal_ids[:limit]
        decisions: list[dict] = []

        for experiment_id in proposal_ids:
            if state_mod.stop_requested(ws.root):
                record["steps"].append({"step": "stop_file", "experiment": experiment_id})
                break
            if time.monotonic() - started > float(limits["max_seconds"]):
                record["errors"].append("max_seconds reached before experiment")
                break
            proposal = experiment.load(experiment_id, ws.root)
            state["current_experiment"] = experiment_id
            state_mod.save_state(state, ws.root)
            pre = checkpoint.create(f"pre-{experiment_id}", ws.root)
            pre_verify = checkpoint.verify(f"checkpoints/{pre['name']}.json", ws.root)
            state["last_checkpoint"] = f"checkpoints/{pre['name']}.json"
            state_mod.save_state(state, ws.root)
            record["steps"].append(
                {"step": "checkpoint", "experiment": experiment_id, "manifest": state["last_checkpoint"], "verify": pre_verify}
            )
            if not pre_verify["ok"]:
                raise RuntimeError("pre-experiment checkpoint failed verification")

            direct = _bench(
                ws,
                proposal["candidate"],
                tasks,
                expected,
                int(limits["benchmark_repetitions"]),
            )
            record["steps"].append({"step": "candidate_bench", "experiment": experiment_id, "result": direct})
            if direct["correctness"] < float(proposal["acceptance"]["min_correctness"]):
                decision = experiment.evaluate(proposal, baseline["bench"], direct, tests_ok=False, corpus_ok=False)
                decision["stage"] = "precheck"
                decisions.append(decision)
                state["failed_experiments"][experiment_id] = decision
                state["pending_experiments"].remove(experiment_id)
                state["failure_streak"] = int(state.get("failure_streak", 0)) + 1
                state["current_experiment"] = None
                state_mod.save_state(state, ws.root)
                state_mod.append_history(
                    {"event": "experiment_precheck_rejected", "experiment": experiment_id, "decision": decision},
                    ws.root,
                )
                state_mod.append_state_md(
                    f"E {experiment_id} rejected before promotion",
                    [f"Reason: {reason}" for reason in decision["reasons"]] or ["Candidate output was not correct."],
                    ws.root,
                )
                record["steps"].append({"step": "decision", "experiment": experiment_id, "decision": decision})
                break

            promoted = experiment.promote(proposal, ws.root)
            record["steps"].append({"step": "promote", "experiment": experiment_id, "result": promoted})
            tests = baseline_mod.suite(ws)
            active = _bench(ws, "active", tasks, expected, int(limits["benchmark_repetitions"]))
            corpus_ok = (
                active.get("corpus_sha256") == expected.get("corpus_sha256")
                and active.get("corpus_sha256") == baseline["bench"].get("corpus_sha256")
            )
            decision = experiment.evaluate(
                proposal,
                baseline["bench"],
                active,
                tests_ok=bool(tests["ok"]),
                corpus_ok=corpus_ok,
            )
            decision["stage"] = "post-promotion"
            decisions.append(decision)
            record["steps"].append(
                {"step": "verify", "experiment": experiment_id, "tests": tests, "bench": active, "decision": decision}
            )
            state["tests"] = tests
            state["last_benchmark"] = active
            if decision["accepted"]:
                post = checkpoint.create(f"post-{experiment_id}", ws.root)
                post_verify = checkpoint.verify(f"checkpoints/{post['name']}.json", ws.root)
                state["last_checkpoint"] = f"checkpoints/{post['name']}.json"
                state["completed_experiments"] = list(state.get("completed_experiments", [])) + [experiment_id]
                state["pending_experiments"].remove(experiment_id)
                state["failure_streak"] = 0
                state["current_experiment"] = None
                state["experiments"] = dict(state.get("experiments", {}))
                state["experiments"][experiment_id] = {
                    "status": "accepted",
                    "decision": decision,
                    "tests": tests["ok"],
                    "benchmark": active,
                    "candidate": proposal["candidate"],
                    "target": proposal["target"],
                    "checkpoint": state["last_checkpoint"],
                }
                state["next_task"] = f"{experiment_id} accepted; review the next gate."
                state_mod.save_state(state, ws.root)
                experiment.record(proposal, {"decision": decision, "promoted": promoted, "checkpoint": post}, ws.root)
                state_mod.append_history(
                    {"event": "experiment_accepted", "experiment": experiment_id, "decision": decision}, ws.root
                )
                state_mod.append_state_md(
                    f"E {experiment_id} accepted",
                    [
                        f"warm ratio {decision['warm_ratio']} (limit {proposal['acceptance']['max_latency_ratio']})",
                        f"cold ratio {decision['cold_ratio']} (limit {proposal['acceptance']['max_cold_ratio']})",
                        f"correctness {decision['correctness']}",
                        f"tests {tests['ok']}",
                        f"checkpoint {state['last_checkpoint']}",
                        f"checkpoint verified {post_verify['ok']}",
                    ],
                    ws.root,
                )
                record["steps"].append({"step": "accepted", "experiment": experiment_id, "checkpoint": post})
            else:
                restored = experiment.rollback(proposal, promoted["backup"], ws.root)
                restored_tests = baseline_mod.suite(ws)
                post = checkpoint.create(f"rollback-{experiment_id}", ws.root)
                state["last_checkpoint"] = f"checkpoints/{post['name']}.json"
                state["failed_experiments"][experiment_id] = decision
                state["pending_experiments"].remove(experiment_id)
                state["failure_streak"] = int(state.get("failure_streak", 0)) + 1
                state["current_experiment"] = None
                state["experiments"] = dict(state.get("experiments", {}))
                state["experiments"][experiment_id] = {
                    "status": "rejected",
                    "decision": decision,
                    "tests_before_rollback": tests["ok"],
                    "tests_after_rollback": restored_tests["ok"],
                    "rollback": restored,
                    "checkpoint": state["last_checkpoint"],
                }
                state["next_task"] = f"{experiment_id} was rejected and rolled back; inspect the negative result."
                state_mod.save_state(state, ws.root)
                experiment.record(
                    proposal,
                    {"decision": decision, "promoted": promoted, "rollback": restored, "checkpoint": post},
                    ws.root,
                )
                state_mod.append_history(
                    {"event": "experiment_rejected", "experiment": experiment_id, "decision": decision}, ws.root
                )
                state_mod.append_state_md(
                    f"E {experiment_id} rejected and rolled back",
                    [f"Reason: {reason}" for reason in decision["reasons"]]
                    + [f"tests before rollback: {tests['ok']}", f"tests after rollback: {restored_tests['ok']}"],
                    ws.root,
                )
                record["steps"].append({"step": "rolled_back", "experiment": experiment_id, "result": restored})

        if allow_model and time.monotonic() - started < float(limits["max_seconds"]):
            calls = int(state.get("model_calls", 0))
            if calls < int(limits["max_model_calls"]) and not state_mod.stop_requested(ws.root):
                summary = {
                    "objective": "improve measured search latency without weakening correctness, tests, or permissions",
                    "environment": snap["host"],
                    "baseline": baseline["bench"],
                    "experiments": state.get("experiments", {}),
                    "completed": state.get("completed_experiments", []),
                    "failed": state.get("failed_experiments", {}),
                    "tests_passing": state.get("tests", {}).get("ok"),
                    "next_task": state.get("next_task"),
                }
                model_result = model.call(json.dumps(summary, indent=2), ws.root, timeout=int(limits["max_model_seconds"]))
                state["model_calls"] = calls + 1
                state["last_model_call"] = {
                    "ok": model_result.get("ok"),
                    "elapsed_ms": model_result.get("elapsed_ms"),
                    "path": model_result.get("path"),
                    "error": model_result.get("error"),
                    "proposal": model_result.get("proposal"),
                }
                state["model_proposals"] = list(state.get("model_proposals", []))
                if model_result.get("proposal"):
                    state["model_proposals"].append(model_result["proposal"])
                state_mod.save_state(state, ws.root)
                if model_result.get("proposal"):
                    ws.write_json(
                        f"proposals/model-proposal-{state['model_calls']}.json",
                        model_result,
                    )
                state_mod.append_history(
                    {"event": "model_proposal", "ok": model_result.get("ok"), "path": model_result.get("path")},
                    ws.root,
                )
                state_mod.append_state_md(
                    "Free-model proposal recorded",
                    [
                        f"ok: {model_result.get('ok')}",
                        f"elapsed_ms: {model_result.get('elapsed_ms')}",
                        f"path: {model_result.get('path')}",
                        "The proposal was recorded only; it was not executed.",
                    ],
                    ws.root,
                )
                record["steps"].append({"step": "model", "ok": model_result.get("ok"), "path": model_result.get("path")})
            else:
                record["steps"].append({"step": "model", "skipped": "budget exhausted"})

        final_checkpoint = checkpoint.create("final", ws.root)
        final_verify = checkpoint.verify(f"checkpoints/{final_checkpoint['name']}.json", ws.root)
        state["last_checkpoint"] = f"checkpoints/{final_checkpoint['name']}.json"
        state["last_run_finished"] = state_mod.utc_now()
        state["last_run_seconds"] = round(time.monotonic() - started, 3)
        state["next_task"] = state.get("next_task") or "Review evidence and gate the next experiment."
        state_mod.save_state(state, ws.root)
        record["state"] = state
        record["decisions"] = decisions
        record["checkpoint"] = {"manifest": final_checkpoint, "verify": final_verify}
        _write_run_log(ws, record)
        commit = _git_commit(ws, f"soo: run {state['run_count']} checkpoint and evidence")
        record["git"] = commit
        _write_run_log(ws, record)
        _git_commit(ws, f"soo: run {state['run_count']} evidence log")
        print(
            f"run={state['run_count']} completed={state.get('completed_experiments')} "
            f"failed={list(state.get('failed_experiments', {}))} model={state.get('model_calls')} "
            f"checkpoint={state['last_checkpoint']} git={commit.get('committed')}"
        )
        return record
    except Exception as exc:
        record["errors"].append(f"{type(exc).__name__}: {exc}")
        record["traceback"] = traceback.format_exc()[-4000:]
        state = state_mod.load_state(ws.root)
        state["failure_streak"] = int(state.get("failure_streak", 0)) + 1
        state["last_error"] = record["errors"][-1]
        state["last_run_finished"] = state_mod.utc_now()
        state["last_run_seconds"] = round(time.monotonic() - started, 3)
        state_mod.save_state(state, ws.root)
        try:
            checkpoint.create("error", ws.root)
        except Exception:
            pass
        state_mod.append_history({"event": "run_error", "error": record["errors"][-1]}, ws.root)
        _write_run_log(ws, record)
        print(f"RUN FAILED: {record['errors'][-1]}", file=sys.stderr)
        return record
    finally:
        state_mod.release_lock(lock, ws.root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded self-optimization cycle")
    parser.add_argument("--no-model", action="store_true", help="skip the free-model call")
    parser.add_argument("--max-experiments", type=int, default=None)
    args = parser.parse_args(argv)
    record = run(allow_model=not args.no_model, max_experiments=args.max_experiments)
    return 0 if not record.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
