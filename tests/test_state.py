from __future__ import annotations

import json
import time
import unittest

from tests.helpers import make_root
from tools import state


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp, self.root = make_root()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_init_save_and_recover_backup(self) -> None:
        initial = state.init_state(self.root, force=True)
        self.assertEqual(initial["run_count"], 0)
        initial["run_count"] = 7
        state.save_state(initial, self.root)
        state.save_state(initial, self.root)
        self.assertEqual(state.load_state(self.root)["run_count"], 7)
        (self.root / "state.json").write_text("{broken", encoding="utf-8")
        recovered = state.load_state(self.root)
        self.assertEqual(recovered["run_count"], 7)

    def test_lock_is_exclusive_and_stale_safe(self) -> None:
        lock = state.acquire_lock(self.root, stale_seconds=60)
        with self.assertRaises(state.RunnerBusy):
            state.acquire_lock(self.root, stale_seconds=60)
        state.release_lock(lock, self.root)
        (self.root / "logs" / "runner.lock").write_text(
            json.dumps({"pid": 999999, "created_epoch": time.time()}), encoding="utf-8"
        )
        lock2 = state.acquire_lock(self.root, stale_seconds=60)
        state.release_lock(lock2, self.root)
        self.assertFalse((self.root / "logs" / "runner.lock").exists())

    def test_append_history_and_state_md(self) -> None:
        state.append_history({"event": "x"}, self.root)
        state.append_state_md("title", ["one"], self.root)
        record = json.loads((self.root / "experiments" / "history.jsonl").read_text().splitlines()[0])
        self.assertEqual(record["event"], "x")
        self.assertIn("one", (self.root / "STATE.md").read_text())
