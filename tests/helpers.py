from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from tools.security import ROOT


def make_root() -> tuple[tempfile.TemporaryDirectory, Path]:
    base = ROOT / "sandbox"
    base.mkdir(parents=True, exist_ok=True)
    temp = tempfile.TemporaryDirectory(dir=base, prefix="test-")
    root = Path(temp.name)
    (root / "config").mkdir()
    shutil.copy(ROOT / "config" / "limits.json", root / "config" / "limits.json")
    shutil.copy(ROOT / "config" / "permissions.json", root / "config" / "permissions.json")
    (root / "config" / "initial_state.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "run_count": 0,
                "completed_experiments": [],
                "pending_experiments": [],
                "failure_streak": 0,
                "failures": {},
                "next_task": "test",
            }
        ),
        encoding="utf-8",
    )
    return temp, root
