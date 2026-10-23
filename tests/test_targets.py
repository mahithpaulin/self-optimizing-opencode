from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import targets
from tools.security import ROOT


def base_config() -> dict:
    return {
        "schema": 1,
        "name": "demo",
        "repository": "owner/repo",
        "target_branch": "main",
        "optimization_branch_prefix": "ai-optimization/",
        "allowed_edit_prefixes": ["src/", "tests/", "docs/"],
        "forbidden_edit_prefixes": [".github/", ".git/", "ai-runs/", "Cargo.toml"],
        "test_command": ["cargo", "test", "--workspace", "--lib", "--tests"],
        "doc_test_command": ["cargo", "test", "--workspace", "--doc"],
        "format_command": ["cargo", "fmt", "--all", "--", "--check"],
        "format_fix_command": ["cargo", "fmt", "--all"],
        "clippy_command": ["cargo", "clippy", "--workspace", "--lib", "--tests", "--", "-D", "warnings"],
        "benchmark_command": ["cargo", "bench", "-p", "axiom", "--bench", "kernel", "--", "ci"],
        "limits": {
            "max_iterations": 40,
            "max_model_seconds": 180,
            "max_test_seconds": 1200,
            "max_bench_seconds": 1200,
            "max_patch_bytes": 40000,
            "max_changed_lines": 400,
            "max_changed_files": 8,
            "max_failure_streak": 3,
            "min_remaining_seconds": 900,
            "soak_seconds": 300,
        },
    }


def base_task() -> dict:
    return {
        "id": "T1",
        "title": "Test task",
        "description": "Do a safe thing.",
        "kind": "test",
        "files": ["src/lib.rs"],
        "priority": 10,
        "benchmark": False,
    }


class TargetManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        (ROOT / "sandbox").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "sandbox", prefix="targets-")
        self.root = Path(self.temp.name)
        self.target = self.root / "targets" / "demo"
        self.target.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, config: dict, backlog: list[dict]) -> None:
        (self.target / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (self.target / "backlog.json").write_text(json.dumps(backlog), encoding="utf-8")

    def test_real_axiom_manifest_and_backlog_load(self) -> None:
        config = targets.load_target("axiom-v4")
        self.assertEqual(config["repository"], "mahithpaulin/axiom")
        self.assertEqual(config["target_branch"], "v4")
        self.assertIn(".github/", config["forbidden_edit_prefixes"])
        tasks = targets.load_backlog("axiom-v4")
        self.assertGreaterEqual(len(tasks), 8)
        ids = [task["id"] for task in tasks]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids[0], "A001-peak-rss")
        self.assertIn("A011-rdl-chain-memory", ids)
        memory = next(task for task in tasks if task["id"] == "A011-rdl-chain-memory")
        self.assertEqual(memory["metric"], "memory")

    def test_missing_required_field_is_rejected(self) -> None:
        config = base_config()
        del config["limits"]
        self.write(config, [base_task()])
        with self.assertRaises(targets.TargetError):
            targets.load_target("demo", self.root)

    def test_non_cargo_command_is_rejected(self) -> None:
        config = base_config()
        config["test_command"] = ["bash", "-c", "true"]
        self.write(config, [base_task()])
        with self.assertRaises(targets.TargetError):
            targets.load_target("demo", self.root)

    def test_prefixes_must_be_lists(self) -> None:
        config = base_config()
        config["allowed_edit_prefixes"] = "src/"
        self.write(config, [base_task()])
        with self.assertRaises(targets.TargetError):
            targets.load_target("demo", self.root)

    def test_prefix_traversal_is_rejected(self) -> None:
        config = base_config()
        config["allowed_edit_prefixes"].append("../outside/")
        self.write(config, [base_task()])
        with self.assertRaises(targets.TargetError):
            targets.load_target("demo", self.root)

    def test_mandatory_forbidden_prefixes(self) -> None:
        config = base_config()
        config["forbidden_edit_prefixes"].remove(".github/")
        self.write(config, [base_task()])
        with self.assertRaises(targets.TargetError):
            targets.load_target("demo", self.root)

    def test_task_file_outside_allowlist_is_rejected(self) -> None:
        self.write(base_config(), [base_task() | {"files": ["Cargo.toml"]}])
        with self.assertRaises(targets.TargetError):
            targets.load_backlog("demo", self.root)

    def test_unknown_dependency_is_rejected(self) -> None:
        self.write(base_config(), [base_task() | {"depends_on": ["missing"]}])
        with self.assertRaises(targets.TargetError):
            targets.load_backlog("demo", self.root)

    def test_duplicate_task_ids_are_rejected(self) -> None:
        self.write(base_config(), [base_task(), base_task()])
        with self.assertRaises(targets.TargetError):
            targets.load_backlog("demo", self.root)

    def test_missing_patch_is_rejected(self) -> None:
        task = base_task()
        task["patch"] = "patches/nope.json"
        self.write(base_config(), [task])
        with self.assertRaises(targets.TargetError):
            targets.load_backlog("demo", self.root)

    def test_deterministic_task_requires_patch(self) -> None:
        task = base_task()
        task["deterministic_first"] = True
        self.write(base_config(), [task])
        with self.assertRaises(targets.TargetError):
            targets.load_backlog("demo", self.root)

    def test_patch_is_loaded_and_sorted_by_priority(self) -> None:
        task = base_task()
        task["patch"] = "patches/ok.json"
        task["deterministic_first"] = True
        (self.target / "patches").mkdir()
        (self.target / "patches" / "ok.json").write_text("{}", encoding="utf-8")
        second = copy.deepcopy(task)
        second["id"] = "T0"
        second["priority"] = 5
        self.write(base_config(), [task, second])
        loaded = targets.load_backlog("demo", self.root)
        self.assertEqual([item["id"] for item in loaded], ["T0", "T1"])

    def test_metric_must_be_known(self) -> None:
        self.write(base_config(), [base_task() | {"metric": "allocs"}])
        with self.assertRaises(targets.TargetError):
            targets.load_backlog("demo", self.root)


if __name__ == "__main__":
    unittest.main()
