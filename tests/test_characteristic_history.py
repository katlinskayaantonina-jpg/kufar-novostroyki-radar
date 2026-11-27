"""Tests of the two additional characteristics; no network or KV writes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
from radar import parse_ad, record_characteristic_changes


class CharacteristicHistoryTest(unittest.TestCase):
    def test_parse_year(self):
        self.assertEqual(parse_ad({"ad_parameters": [{"p": "year_built", "v": 2027}]})["yb"], "2027")
        self.assertEqual(parse_ad({})["yb"], "")

    def test_legacy_baseline_and_reversal(self):
        state = {"r": "1"}
        events = []
        emit = lambda *row: events.append(row)
        record_characteristic_changes(state, {"r": "2", "yb": "2027"}, emit)
        self.assertEqual(events, [("rooms", "1", "2")])
        record_characteristic_changes(state, {"r": "2", "yb": 2027}, emit)
        self.assertEqual(len(events), 1)
        record_characteristic_changes(state, {"r": "1", "yb": "2026"}, emit)
        self.assertEqual(events[1:], [("rooms", "2", "1"), ("year_built", "2027", "2026")])

    def test_missing_is_not_a_change(self):
        state = {"r": "1", "yb": "2027"}
        events = []
        emit = lambda *row: events.append(row)
        record_characteristic_changes(state, {"r": "", "yb": ""}, emit)
        state["r"] = ""  # existing display-state behavior
        record_characteristic_changes(state, {"r": "2", "yb": 2025}, emit)
        self.assertEqual(events, [("rooms", "1", "2"), ("year_built", "2027", "2025")])

    def test_new_ad_no_fabricated_event(self):
        state = {}
        events = []
        record_characteristic_changes(state, {"r": "1", "yb": "2027"}, lambda *row: events.append(row))
        self.assertEqual(events, [])
        self.assertEqual((state["r_hist"], state["yb"]), ("1", "2027"))


if __name__ == "__main__":
    unittest.main()
