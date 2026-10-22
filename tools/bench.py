"""Stage E measurement: correctness hashes and batch latency on frozen tasks."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import resource
import statistics
import sys
import time
from pathlib import Path

from tools import state as state_mod
from tools.security import ROOT, Workspace


def _load_module(label: str, ws: Workspace):
    if label == "baseline":
        return importlib.import_module("tools.search_baseline")
    if label == "active":
        return importlib.import_module("tools.search")
    path = ws.resolve(label)
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location("candidate_search", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(result: dict) -> str:
    payload = {
        "results": result.get("results", []),
        "truncated": bool(result.get("truncated", False)),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _corpus_hash(corpus: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(corpus.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(corpus).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_tasks(ws: Workspace, task_paths: list[str]) -> list[dict]:
    tasks: list[dict] = []
    for item in task_paths:
        data = json.loads(ws.read_text(item))
        corpus = ws.resolve(data["corpus"])
        include = data.get("include", "*.py")
        max_results = int(data.get("max_results", 500))
        for query in data["queries"]:
            tasks.append(
                {
                    "id": query["id"],
                    "pattern": query["pattern"],
                    "include": include,
                    "max_results": max_results,
                    "corpus": corpus,
                    "source": item,
                }
            )
    return tasks


def run_benchmark(
    module_label: str,
    tasks: list[dict],
    expected: dict,
    repetitions: int,
    ws: Workspace,
) -> dict:
    module = _load_module(module_label, ws)
    per_query: dict[str, dict] = {}
    correctness: dict[str, bool] = {}
    for task in tasks:
        key = task["id"]
        try:
            result = module.search(
                task["corpus"],
                task["pattern"],
                include=task["include"],
                max_results=task["max_results"],
            )
            digest = _canonical(result)
            want = expected["queries"].get(key)
            ok = bool(want and want.get("sha256") == digest and want.get("count") == len(result.get("results", [])))
            per_query[key] = {"sha256": digest, "count": len(result.get("results", [])), "ok": ok}
            correctness[key] = ok
        except Exception as exc:
            per_query[key] = {"error": f"{type(exc).__name__}: {exc}", "ok": False}
            correctness[key] = False
    batches: list[float] = []
    cold_ms = None
    for repetition in range(max(1, repetitions)):
        started = time.perf_counter()
        for task in tasks:
            try:
                result = module.search(
                    task["corpus"],
                    task["pattern"],
                    include=task["include"],
                    max_results=task["max_results"],
                )
                digest = _canonical(result)
                if digest != per_query[task["id"]].get("sha256"):
                    per_query[task["id"]]["ok"] = False
                    correctness[task["id"]] = False
            except Exception as exc:
                per_query[task["id"]] = {"error": f"{type(exc).__name__}: {exc}", "ok": False}
                correctness[task["id"]] = False
        elapsed = (time.perf_counter() - started) * 1000
        if repetition == 0:
            cold_ms = round(elapsed, 3)
        else:
            batches.append(elapsed)
    if not batches:
        batches = [cold_ms or 0.0]
    batches_sorted = sorted(batches)
    p95_index = max(0, min(len(batches_sorted) - 1, int(round(0.95 * (len(batches_sorted) - 1)))))
    corpus_hash = _corpus_hash(Path(tasks[0]["corpus"])) if tasks else ""
    correct_count = sum(1 for value in correctness.values() if value)
    return {
        "schema": 1,
        "module": module_label,
        "timestamp": state_mod.utc_now(),
        "corpus_sha256": corpus_hash,
        "repetitions": repetitions,
        "total_queries": len(tasks),
        "correct_queries": correct_count,
        "correctness": round(correct_count / len(tasks), 6) if tasks else 0.0,
        "failed_queries": [key for key, ok in correctness.items() if not ok],
        "cold_batch_ms": cold_ms,
        "warm_batches_ms": [round(value, 3) for value in batches],
        "median_batch_ms": round(statistics.median(batches), 3),
        "min_batch_ms": round(min(batches), 3),
        "p95_batch_ms": round(batches_sorted[p95_index], 3),
        "rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "per_query": per_query,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen search benchmark")
    parser.add_argument("--module", default="baseline", help="baseline | active | path to candidate module")
    parser.add_argument("--tasks", nargs="+", default=["benchmarks/tasks_dev.json", "benchmarks/tasks_heldout.json"])
    parser.add_argument("--expected", default="benchmarks/expected.json")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    ws = Workspace(ROOT)
    tasks = _load_tasks(ws, args.tasks)
    expected = json.loads(ws.read_text(args.expected))
    result = run_benchmark(args.module, tasks, expected, args.repetitions, ws)
    ws.write_json(args.output, result)
    print(
        f"module={result['module']} correct={result['correct_queries']}/{result['total_queries']} "
        f"cold={result['cold_batch_ms']}ms median={result['median_batch_ms']}ms "
        f"p95={result['p95_batch_ms']}ms rss={result['rss_kb']}KB"
    )
    return 0 if result["correctness"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
