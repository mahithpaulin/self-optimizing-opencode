from __future__ import annotations

import json
import tarfile
import unittest
from pathlib import Path

from tests.helpers import make_root
from tools import checkpoint
from tools.security import Workspace


class CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp, self.root = make_root()
        self.ws = Workspace(self.root)
        self.ws.write_text("a.txt", "alpha")
        self.ws.write_text("sub/b.txt", "beta")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_verify_and_extract(self) -> None:
        manifest = checkpoint.create("unit", self.root)
        report = checkpoint.verify(f"checkpoints/{manifest['name']}.json", self.root)
        self.assertTrue(report["ok"])
        restored = checkpoint.extract(f"checkpoints/{manifest['name']}.json", "restore", self.root)
        self.assertTrue(restored["ok"])
        self.assertEqual((self.root / "restore" / "a.txt").read_text(), "alpha")

    def test_tamper_detected(self) -> None:
        manifest = checkpoint.create("tamper", self.root)
        archive = self.root / manifest["archive"]
        archive.write_bytes(archive.read_bytes() + b"x")
        report = checkpoint.verify(f"checkpoints/{manifest['name']}.json", self.root)
        self.assertFalse(report["ok"])

    def test_unsafe_member_rejected(self) -> None:
        archive = self.root / "checkpoints" / "bad.tar.gz"
        archive.parent.mkdir(exist_ok=True)
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("../evil")
            info.size = 1
            tar.addfile(info, __import__("io").BytesIO(b"x"))
        manifest = self.root / "checkpoints" / "bad.json"
        manifest.write_text(json.dumps({"archive": "checkpoints/bad.tar.gz", "file_count": 1, "sha256": "x"}))
        with self.assertRaises(ValueError):
            checkpoint.verify("checkpoints/bad.json", self.root)
