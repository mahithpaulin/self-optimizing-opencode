from __future__ import annotations

import unittest

from tests.helpers import make_root
from tools import runner
from tools.security import Workspace


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp, self.root = make_root()
        self.ws = Workspace(self.root)
        self.ws.write_text(".gitignore", "__pycache__/\n")
        self.ws.write_text("README.md", "test\n")
        self.ws.run(["git", "init", "-q"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_git_commit(self) -> None:
        first = runner._git_commit(self.ws, "initial")
        self.assertTrue(first["committed"], first)
        second = runner._git_commit(self.ws, "empty")
        self.assertFalse(second["committed"])
