from __future__ import annotations

import json
import unittest

from tools.model import free_mb, parse


class ModelTests(unittest.TestCase):
    def test_parse_event_stream(self) -> None:
        proposal = {"weakness": "w", "hypothesis": "h", "metric": "m", "change": "c", "risk": "r", "reversible": True}
        raw = json.dumps({"type": "text", "part": {"type": "text", "text": json.dumps(proposal)}})
        self.assertEqual(parse(raw)["weakness"], "w")

    def test_parse_fenced_json(self) -> None:
        raw = json.dumps({"type": "text", "part": {"type": "text", "text": "```json\n{\"weakness\":\"w\",\"hypothesis\":\"h\",\"metric\":\"m\",\"change\":\"c\",\"risk\":\"r\",\"reversible\":false}\n```"}})
        self.assertFalse(parse(raw)["reversible"])

    def test_invalid_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse('{"type":"text","part":{"type":"text","text":"not json"}}')

    def test_memory_reading(self) -> None:
        self.assertGreater(free_mb(), 0)
