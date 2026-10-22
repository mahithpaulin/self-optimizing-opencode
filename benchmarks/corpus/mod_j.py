import unittest


class StateTests(unittest.TestCase):
    def test_round_trip(self):
        state = {"ok": True}
        self.assertEqual(state["ok"], True)
        with self.assertRaises(KeyError):
            state["missing"]
