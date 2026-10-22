from __future__ import annotations

import json
import unittest

from tests.helpers import make_root
from tools import experiment
from tools.security import Workspace


class ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp, self.root = make_root()
        self.ws = Workspace(self.root)
        self.ws.write_text("tools/search.py", "value = 1\n")
        self.ws.write_text("experiments/E-test/search_candidate.py", "value = 2\n")
        self.proposal = {
            "id": "E-test",
            "title": "test",
            "weakness": "w",
            "hypothesis": "h",
            "candidate": "experiments/E-test/search_candidate.py",
            "target": "tools/search.py",
            "acceptance": {"min_correctness": 1.0, "max_latency_ratio": 0.75, "max_cold_ratio": 1.25},
        }
        self.ws.write_json("experiments/E-test/proposal.json", self.proposal)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validate_and_evaluate(self) -> None:
        experiment.validate(self.proposal)
        baseline = {"median_batch_ms": 100.0}
        candidate = {"median_batch_ms": 50.0, "cold_batch_ms": 20.0, "correctness": 1.0, "failed_queries": []}
        accepted = experiment.evaluate(self.proposal, baseline, candidate, tests_ok=True)
        self.assertTrue(accepted["accepted"])
        rejected = experiment.evaluate(self.proposal, baseline, candidate, tests_ok=False)
        self.assertFalse(rejected["accepted"])
        slow = dict(candidate, median_batch_ms=90.0)
        self.assertFalse(experiment.evaluate(self.proposal, baseline, slow, tests_ok=True)["accepted"])

    def test_promote_and_rollback(self) -> None:
        result = experiment.promote(self.proposal, self.root)
        self.assertEqual(self.ws.read_text("tools/search.py"), "value = 2\n")
        self.assertTrue((self.root / result["backup"]).exists())
        experiment.rollback(self.proposal, result["backup"], self.root)
        self.assertEqual(self.ws.read_text("tools/search.py"), "value = 1\n")

    def test_syntax_error_is_not_promoted(self) -> None:
        self.ws.write_text("experiments/E-test/search_candidate.py", "def broken(:\n")
        with self.assertRaises(SyntaxError):
            experiment.promote(self.proposal, self.root)
        self.assertEqual(self.ws.read_text("tools/search.py"), "value = 1\n")
