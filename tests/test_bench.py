from __future__ import annotations

import copy
import json
import unittest

from tools.bench import _canonical, _load_tasks, run_benchmark
from tools.security import ROOT, Workspace


class BenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ws = Workspace(ROOT)
        cls.tasks = _load_tasks(cls.ws, ["benchmarks/tasks_dev.json", "benchmarks/tasks_heldout.json"])
        cls.expected = json.loads(cls.ws.read_text("benchmarks/expected.json"))

    def test_canonical_ignores_engine(self) -> None:
        result = {"engine": "a", "results": [], "truncated": False}
        self.assertEqual(_canonical(result), _canonical({"engine": "b", "results": [], "truncated": False}))

    def test_baseline_is_correct_and_wrong_expected_fails(self) -> None:
        result = run_benchmark("baseline", self.tasks, self.expected, 1, self.ws)
        self.assertEqual(result["correctness"], 1.0)
        bad = copy.deepcopy(self.expected)
        bad["queries"]["d01"]["sha256"] = "0" * 64
        failed = run_benchmark("baseline", self.tasks, bad, 1, self.ws)
        self.assertLess(failed["correctness"], 1.0)
        self.assertIn("d01", failed["failed_queries"])
