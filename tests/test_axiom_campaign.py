from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools import axiom_campaign as ac
from tools.security import ROOT


class CampaignUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        (ROOT / "sandbox").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "sandbox", prefix="campaign-")
        self.target = Path(self.temp.name) / "target"
        for directory in ("src", "tests", "docs", "benches", ".github/workflows"):
            (self.target / directory).mkdir(parents=True, exist_ok=True)
        self.campaign = ac.Campaign(
            target_dir=self.target,
            optimizer_dir=ROOT,
            run_id="unit-test",
            branch="ai-optimization/unit-test",
            minutes=60,
            max_iterations=5,
            no_model=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, path: str, text: str) -> None:
        full = self.target / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")

    def test_path_allowlist_blocks_escape_and_protected_paths(self) -> None:
        allowed = self.campaign.path_allowed
        self.assertTrue(allowed("src/lib.rs"))
        self.assertTrue(allowed("./src/lib.rs"))
        self.assertTrue(allowed("crates/axiom-smt/tests/negation.rs"))
        self.assertTrue(allowed("docs/v4/CAPABILITY_MATRIX.md"))
        self.assertFalse(allowed("../src/lib.rs"))
        self.assertFalse(allowed("./../src/lib.rs"))
        self.assertFalse(allowed("src/../tests/x.rs"))
        self.assertFalse(allowed("/etc/passwd"))
        self.assertFalse(allowed(".github/workflows/ci.yml"))
        self.assertFalse(allowed("Cargo.toml"))
        self.assertFalse(allowed("ai-runs/run/state.json"))
        self.assertFalse(allowed(".ai/optimizer/tools/axiom_campaign.py"))
        self.assertFalse(allowed("srcfoo/lib.rs"))

    def test_validate_spec_accepts_safe_edits_and_rejects_traversal(self) -> None:
        self.write("src/lib.rs", "pub fn a() {}\n")
        good = {
            "edits": [{"file": "src/lib.rs", "find": "pub fn a", "replace": "pub fn b"}],
            "create": [{"file": "tests/new.rs", "content": "#[test]\nfn t() {}\n"}],
        }
        self.assertEqual(self.campaign.validate_spec(good), [])
        bad = {
            "edits": [{"file": "../outside.rs", "find": "x", "replace": "y"}],
            "create": [{"file": "/tmp/x.rs", "content": "x"}],
        }
        errors = self.campaign.validate_spec(bad)
        self.assertTrue(any("not allowed" in error for error in errors))
        self.assertTrue(self.campaign.validate_spec({}))
        huge = {"create": [{"file": "tests/x.rs", "content": "x" * 50_000}]}
        self.assertTrue(any("over the" in error for error in self.campaign.validate_spec(huge)))

    def test_apply_spec_edits_creates_and_refuses_ambiguity(self) -> None:
        self.write("src/lib.rs", "one one two\n")
        with self.assertRaises(ac.CampaignError):
            self.campaign.apply_spec({"edits": [{"file": "src/lib.rs", "find": "one", "replace": "x"}]})
        changed = self.campaign.apply_spec(
            {
                "edits": [{"file": "src/lib.rs", "find": "one one", "replace": "one"}],
                "create": [{"file": "tests/new.rs", "content": "// new\n"}],
            }
        )
        self.assertEqual(changed, ["src/lib.rs", "tests/new.rs"])
        self.assertEqual((self.target / "src/lib.rs").read_text(), "one two\n")
        self.assertTrue((self.target / "tests/new.rs").exists())
        with self.assertRaises(ac.CampaignError):
            self.campaign.apply_spec({"create": [{"file": "tests/new.rs", "content": "again"}]})
        self.campaign.apply_spec(
            {"create": [{"file": "tests/new.rs", "content": "again", "overwrite": True}]}
        )
        with self.assertRaises(ac.CampaignError):
            self.campaign.apply_spec(
                {"edits": [{"file": "src/lib.rs", "find": "absent", "replace": "x"}]}
            )

    def test_extract_json_objects_from_prose_and_fences(self) -> None:
        text = 'thinking...\n```json\n{"task_id": "A1", "edits": []}\n```\ntrailing'
        self.assertEqual(ac.extract_json_objects(text), [{"task_id": "A1", "edits": []}])
        self.assertEqual(ac.extract_json_objects("no json"), [])
        self.assertEqual(ac.extract_json_objects('{"a": 1} {"b": 2}'), [{"a": 1}, {"b": 2}])
        self.assertEqual(ac.extract_json_objects('{"broken": '), [])

    def test_extract_event_text_handles_plain_and_json(self) -> None:
        self.assertEqual(ac.extract_event_text("hello"), "hello")
        event = json.dumps({"type": "text", "part": {"text": "world"}})
        self.assertEqual(ac.extract_event_text(event), "world")
        nested = json.dumps({"type": "message", "content": [{"text": "a"}, {"text": "b"}]})
        self.assertEqual(ac.extract_event_text(nested), "a\nb")

    def test_parse_test_counts(self) -> None:
        output = (
            "test result: ok. 274 passed; 0 failed; 8 ignored; 0 measured; 0 filtered out\n"
            "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"
        )
        self.assertEqual(
            ac.parse_test_counts(output),
            {"suites": 2, "passed": 277, "failed": 0, "ignored": 8},
        )
        failed = "test result: FAILED. 1 passed; 2 failed; 0 ignored"
        self.assertEqual(ac.parse_test_counts(failed)["failed"], 2)
        self.assertEqual(ac.parse_test_counts("")["suites"], 0)

    def test_parse_bench_rows(self) -> None:
        output = (
            "  hash_cons_1000_terms                 2000 it      50.12 ms     12.34 Mops/s"
            "         5 allocs/it        120 B/op   12345 rss kB\n"
        )
        row = ac.parse_bench_rows(output)["hash_cons_1000_terms"]
        self.assertEqual(row["iters"], 2000)
        self.assertAlmostEqual(row["wall_ms"], 50.12)
        self.assertAlmostEqual(row["mops"], 12.34)
        self.assertEqual(row["allocs_per_it"], 5)
        self.assertEqual(row["bytes_per_op"], 120)
        self.assertEqual(row["rss_kb"], 12345)
        self.assertEqual(ac.parse_bench_rows("no rows"), {})

    def test_merge_bench_runs_keeps_best_wall_and_rss(self) -> None:
        merged = ac.merge_bench_runs(
            [
                {"rows": {"a": {"iters": 10, "wall_ms": 10.0, "rss_kb": 100}}},
                {"rows": {"a": {"iters": 12, "wall_ms": 9.0, "rss_kb": 120}}},
                {"rows": {"a": {"iters": 11, "wall_ms": 11.0, "rss_kb": 90}}},
            ]
        )
        self.assertEqual(merged["a"]["iters"], 12)
        self.assertEqual(merged["a"]["wall_ms"], 9.0)
        self.assertEqual(merged["a"]["rss_kb"], 90)

    def test_bench_gate_requires_real_improvement(self) -> None:
        task = {"benchmark": True, "metric": "time"}
        self.campaign.baseline_bench = {"row": {"wall_ms": 100.0, "rss_kb": 1000}}
        self.assertFalse(self.campaign.bench_gate(task, None)[0])
        self.assertFalse(
            self.campaign.bench_gate(
                task, {"ok": False, "rows": {"row": {"wall_ms": 90.0, "rss_kb": 900}}}
            )[0]
        )
        self.assertFalse(
            self.campaign.bench_gate(
                task, {"ok": True, "rows": {"row": {"wall_ms": 120.0, "rss_kb": 1000}}}
            )[0]
        )
        self.assertFalse(
            self.campaign.bench_gate(
                task, {"ok": True, "rows": {"row": {"wall_ms": 99.0, "rss_kb": 1000}}}
            )[0]
        )
        ok, comparisons = self.campaign.bench_gate(
            task, {"ok": True, "rows": {"row": {"wall_ms": 95.0, "rss_kb": 1000}}}
        )
        self.assertTrue(ok)
        self.assertEqual(comparisons[0]["ratio"], 0.95)

    def test_memory_gate_uses_rss(self) -> None:
        task = {"benchmark": True, "metric": "memory"}
        self.campaign.baseline_bench = {"row": {"wall_ms": 100.0, "rss_kb": 1000}}
        ok, _ = self.campaign.bench_gate(
            task, {"ok": True, "rows": {"row": {"wall_ms": 110.0, "rss_kb": 930}}}
        )
        self.assertTrue(ok)
        self.assertFalse(
            self.campaign.bench_gate(
                task, {"ok": True, "rows": {"row": {"wall_ms": 110.0, "rss_kb": 990}}}
            )[0]
        )
        self.assertFalse(
            self.campaign.bench_gate(
                task, {"ok": True, "rows": {"row": {"wall_ms": 100.0, "rss_kb": 1100}}}
            )[0]
        )
        self.assertFalse(
            self.campaign.bench_gate(
                task, {"ok": True, "rows": {"row": {"wall_ms": 130.0, "rss_kb": 900}}}
            )[0]
        )

    def test_next_task_respects_dependencies_and_model_availability(self) -> None:
        self.campaign.state["model"]["available"] = False
        self.assertEqual(self.campaign.next_task()["id"], "A001-peak-rss")
        self.campaign.state["accepted"] = [{"task": "A001-peak-rss"}]
        self.assertEqual(self.campaign.next_task()["id"], "A002-smt-negation")
        self.campaign.state["accepted"] = [
            {"task": task_id}
            for task_id in (
                "A001-peak-rss",
                "A002-smt-negation",
                "A003-fol-equality-negative",
                "A004-planning-negative-precondition",
                "A005-docs-peak-rss",
            )
        ]
        self.assertIsNone(self.campaign.next_task())
        statuses = {
            task_id: state.get("status")
            for task_id, state in self.campaign.state["tasks"].items()
        }
        self.assertEqual(statuses.get("A006-db-third-index"), "blocked_model")

        self.campaign.state["model"]["available"] = True
        self.assertEqual(self.campaign.next_task()["id"], "A006-db-third-index")

    def test_redact_removes_credentials(self) -> None:
        secret = "sk-" + "a" * 24
        text = f"token={secret} and gho_{'b' * 24} end"
        cleaned = ac.redact(text, [secret])
        self.assertNotIn(secret, cleaned)
        self.assertIn("REDACTED", cleaned)

    def test_main_rejects_unsafe_branches(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                ac.main(
                    ["--target-dir", str(self.target), "--run-id", "x", "--branch", "main", "--minutes", "30"]
                ),
                2,
            )
            self.assertEqual(
                ac.main(
                    ["--target-dir", str(self.target), "--run-id", "x", "--branch", "v4", "--minutes", "30"]
                ),
                2,
            )
            self.assertEqual(
                ac.main(
                    ["--target-dir", str(self.target), "--run-id", "x", "--branch", "feature/x", "--minutes", "30"]
                ),
                2,
            )
            self.assertEqual(
                ac.main(
                    [
                        "--target-dir",
                        str(self.target),
                        "--run-id",
                        "x",
                        "--branch",
                        "ai-optimization/x",
                        "--minutes",
                        "1",
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
