"""winner_decisions: в признаки момента T0 не попадают данные после T0 (no-leakage)."""
import json
import os
import unittest

from src import winner_decisions as W

FAKE = 999999


def months(a: str, b: str):
    m = a
    while m <= b:
        yield m
        m = W.add_months(m, 1)


class NoLeakage(unittest.TestCase):
    def setUp(self):
        W._NM[FAKE] = {m: {"sales": 1000 + i * 10, "revenue": 500000 + i, "sellers": 100 + i, "items": 300, "aov": 500}
                       for i, m in enumerate(months("2023-01", "2026-07"))}

    def tearDown(self):
        W._NM.pop(FAKE, None)

    def test_future_months_do_not_change_features(self):
        t0 = "2025-12-15"
        before = W.market_at(FAKE, t0)
        self.assertEqual(before["src_max"], "2025-11")
        for m in months("2025-12", "2026-07"):          # «будущее» относительно T0 — портим
            W._NM[FAKE][m] = {"sales": 10 ** 7, "revenue": 10 ** 9, "sellers": 1, "items": 1, "aov": 99999}
        self.assertEqual(W.market_at(FAKE, t0), before)

    def test_season_index_uses_only_past(self):
        a = W.season_index(FAKE, "2025-12")
        W._NM[FAKE]["2025-12"]["sales"] = 10 ** 7
        self.assertEqual(W.season_index(FAKE, "2025-12"), a)

    def test_missing_history_gives_no_features(self):
        self.assertIsNone(W.market_at(FAKE, "2023-01-10")["src_max"])

    @unittest.skipUnless(os.path.exists(W.OUT), "нет сохранённого результата")
    def test_saved_cards_use_only_months_before_t0(self):
        d = json.load(open(W.OUT, encoding="utf-8"))
        for c in d["cards"]:
            if c.get("m_src_max"):
                self.assertLess(c["m_src_max"], c["t0"][:7], c["id"])
            self.assertLess(c["t0"], c["start"], c["id"])


if __name__ == "__main__":
    unittest.main()
