"""Bootstrap-only: freeze expected result hashes for the fixed corpus.

Never run this after a benchmark has been used for acceptance. It exists so the
initial expected file can be created and inspected, not so the optimizer can move
the target.
"""

from __future__ import annotations

import hashlib
import json
import sys

from tools.bench import _canonical, _corpus_hash, _load_tasks
from tools.security import ROOT, Workspace
from tools.search_baseline import search


def main() -> int:
    ws = Workspace(ROOT)
    tasks = _load_tasks(ws, ["benchmarks/tasks_dev.json", "benchmarks/tasks_heldout.json"])
    queries = {}
    for task in tasks:
        result = search(
            task["corpus"],
            task["pattern"],
            include=task["include"],
            max_results=task["max_results"],
        )
        queries[task["id"]] = {
            "sha256": _canonical(result),
            "count": len(result["results"]),
            "pattern": task["pattern"],
        }
    corpus = ws.resolve("benchmarks/corpus")
    payload = {
        "schema": 1,
        "generated_by": "tools/search_baseline.py",
        "corpus_sha256": _corpus_hash(corpus),
        "queries": queries,
    }
    ws.write_json("benchmarks/expected.json", payload, allow_protected=True)
    print(f"frozen {len(queries)} queries corpus={payload['corpus_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
