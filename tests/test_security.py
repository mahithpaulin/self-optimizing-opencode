from __future__ import annotations

import os
import unittest

from tools.security import ROOT, CommandDenied, SecurityError, Workspace


class SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = Workspace(ROOT)
        self.link = self.ws.root / "sandbox" / f"escape-{os.getpid()}"
        try:
            self.link.unlink()
        except FileNotFoundError:
            pass
        os.symlink("/etc/hostname", self.link)

    def tearDown(self) -> None:
        try:
            self.link.unlink()
        except FileNotFoundError:
            pass

    def test_outside_read_denied(self) -> None:
        with self.assertRaises(SecurityError):
            self.ws.read_text("/etc/hostname")

    def test_symlink_escape_denied(self) -> None:
        with self.assertRaises(SecurityError):
            self.ws.read_text(f"sandbox/{self.link.name}")

    def test_secret_name_denied(self) -> None:
        with self.assertRaises(SecurityError):
            self.ws.read_text("sandbox/auth.json")

    def test_outside_write_denied(self) -> None:
        with self.assertRaises(SecurityError):
            self.ws.write_text("/tmp/soo-escape-test", "x")

    def test_protected_write_denied(self) -> None:
        path = f"tests/probe-{os.getpid()}.txt"
        with self.assertRaises(SecurityError):
            self.ws.write_text(path, "x")
        self.assertFalse((self.ws.root / path).exists())

    def test_command_allowlist(self) -> None:
        self.assertTrue(self.ws.run(["git", "status", "--short"])["ok"])
        for argv in (["git", "push"], ["echo", "hi"], ["python3", "-c", "print(1)"], ["sh", "-c", "id"]):
            with self.assertRaises(CommandDenied):
                self.ws.run(argv)
