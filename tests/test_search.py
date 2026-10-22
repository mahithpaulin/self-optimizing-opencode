from __future__ import annotations

import importlib.util
import json
import unittest

from tools.bench import _load_tasks
from tools.search import search as active_search
from tools.search_baseline import SearchError, search as baseline_search
from tools.security import ROOT, Workspace


def load_candidate():
    path = ROOT / "experiments" / "E001-search-index" / "search_candidate.py"
    spec = importlib.util.spec_from_file_location("test_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ws = Workspace(ROOT)
        cls.tasks = _load_tasks(cls.ws, ["benchmarks/tasks_dev.json", "benchmarks/tasks_heldout.json"])
        cls.candidate = load_candidate()

    def test_all_frozen_queries_match(self) -> None:
        for task in self.tasks:
            expected = baseline_search(task["corpus"], task["pattern"], task["include"], task["max_results"])
            actual = self.candidate.search(task["corpus"], task["pattern"], task["include"], task["max_results"])
            self.assertEqual(expected["results"], actual["results"], task["id"])
            self.assertEqual(expected["truncated"], actual["truncated"], task["id"])

    def test_active_backend_matches_baseline(self) -> None:
        for task in self.tasks[:6]:
            expected = baseline_search(task["corpus"], task["pattern"], task["include"], task["max_results"])
            actual = active_search(task["corpus"], task["pattern"], task["include"], task["max_results"])
            self.assertEqual(expected["results"], actual["results"], task["id"])

    def test_unsafe_pattern_falls_back(self) -> None:
        task = self.tasks[0]
        expected = baseline_search(task["corpus"], r"\bTODO\b", task["include"], 20)
        actual = self.candidate.search(task["corpus"], r"\bTODO\b", task["include"], 20)
        self.assertEqual(expected["results"], actual["results"])

    def test_truncation(self) -> None:
        result = self.candidate.search("benchmarks/corpus", "def ", "*.py", max_results=1)
        self.assertEqual(len(result["results"]), 1)
        self.assertTrue(result["truncated"])

    def test_invalid_regex(self) -> None:
        with self.assertRaises(SearchError):
            self.candidate.search("benchmarks/corpus", "(")

    def test_empty_pattern(self) -> None:
        with self.assertRaises(SearchError):
            self.candidate.search("benchmarks/corpus", "")
