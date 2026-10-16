"""Тесты ключевых расчётов (stdlib unittest, без сети и без квоты).

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v

Ловят классы ошибок, которые уже случались в проекте: двойной учёт СПП, не та комиссия, сломанный парсинг путей,
регрессия юнит-экономики, неверные правила решений.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import os
import random
import tempfile
import unittest


class UnitEcon(unittest.TestCase):
    def test_strategy_777_baseline(self):
        """strategy_777_2026-10-07 §2.4: 1 590 ₽ до СПП, ДРР 15% → ≈ 447 ₽, 28.1%."""
        from src.marketing777 import econ
        e = econ(1590, 15)
        self.assertAlmostEqual(e["net_profit"], 446, delta=3)
        self.assertAlmostEqual(e["net_margin_pct"], 28.1, delta=0.2)

    def test_stages(self):
        from src.marketing777 import econ
        self.assertAlmostEqual(econ(1258, 25)["net_margin_pct"], 9.9, delta=0.2)
        self.assertAlmostEqual(econ(1417, 18)["net_margin_pct"], 21.3, delta=0.2)

    def test_margin_monotonic(self):
        """Маржа растёт с ценой и падает с ДРР и комиссией."""
        from src.marketing777 import econ
        self.assertLess(econ(1300, 15)["net_margin_pct"], econ(1600, 15)["net_margin_pct"])
        self.assertGreater(econ(1600, 10)["net_margin_pct"], econ(1600, 20)["net_margin_pct"])
        self.assertGreater(econ(1600, 15, comm=20)["net_margin_pct"], econ(1600, 15, comm=30)["net_margin_pct"])

    def test_commission_30_still_passes(self):
        from src.marketing777 import econ
        self.assertGreaterEqual(econ(1590, 15, comm=30)["net_margin_pct"], 18)
        self.assertLess(econ(1590, 15, comm=35)["net_margin_pct"], 18)


class PriceBasis(unittest.TestCase):
    def test_spp_not_double_counted(self):
        """products.final_price — уже цена ДО СПП; цена покупателя = final_price_average. СПП = 1 − avg/final."""
        final_price, buyer = 1591, 1128
        spp = 1 - buyer / final_price
        self.assertAlmostEqual(spp, 0.291, delta=0.005)
        wrong = final_price / (1 - spp)                       # ошибка 2026-10-06: делили ещё раз
        self.assertGreater(wrong, final_price * 1.3)


class Regression(unittest.TestCase):
    def test_ols_recovers_coefficients(self):
        from src.wb_algo import ols
        rnd = random.Random(1)
        X, y = [], []
        for _ in range(400):
            a, b = rnd.gauss(0, 1), rnd.gauss(0, 1)
            X.append([a, b]); y.append(2 * a - 0.5 * b + rnd.gauss(0, 0.01))
        c = ols(X, y)
        self.assertAlmostEqual(c[0], 2, delta=0.02)
        self.assertAlmostEqual(c[1], -0.5, delta=0.02)


class Launch(unittest.TestCase):
    def _rows(self, sales):
        d0 = dt.date(2026, 1, 1)
        return [{"data": (d0 + dt.timedelta(days=i)).isoformat(), "sales": s, "balance": 100, "final_price": 700,
                 "in_ads": 1, "in_action": 0, "comments": i, "search_words_count": 100, "search_position_avg": 50,
                 "warehouses_count": 3} for i, s in enumerate(sales)]

    def test_breakout_detected(self):
        from src.launch_patterns import breakouts
        R = self._rows([2] * 40 + [12] * 20)
        b = breakouts(R, 0)
        self.assertEqual(len(b), 1)
        self.assertGreaterEqual(b[0]["sales_after"], 2 * b[0]["sales_before"])

    def test_no_breakout_on_flat(self):
        from src.launch_patterns import breakouts
        self.assertEqual(breakouts(self._rows([5] * 60), 0), [])


class Catalog(unittest.TestCase):
    def test_kind_and_niche(self):
        from src.catalog import kind_of, niche_of
        self.assertEqual(kind_of("2026-10-08/launch/777/494403950.json"), "daily")
        self.assertEqual(kind_of("2026-10-05/dna/777/products500_2026-07.json"), "products500")
        self.assertEqual(kind_of("2026-10-05/dna/777/keywords_2025-09.json"), "keywords")
        self.assertEqual(niche_of("2026-10-08/launch/777/494403950.json", {})[0], 777)
        self.assertEqual(niche_of("2026-10-07/strategy2486/trends_month.json", {})[0], 2486)
        self.assertEqual(niche_of("2026-10-03/termos/items.json", {"2026-10-03/termos": 511}), (511, "termos"))


class Rules(unittest.TestCase):
    def test_kill_and_reorder(self):
        from src.weekly_report import decide
        r = " ".join(decide(35, {"orders_day": 1.0}, 10, 60, 20, 1258))
        self.assertIn("СТОП", r)
        r = " ".join(decide(40, {"orders_day": 5.0}, 60, 15, 20, 1258))
        self.assertIn("ДОЗАКАЗАТЬ", r)
        self.assertIn("1 417", r)
        r = " ".join(decide(40, {"orders_day": 2.5}, 20, 60, 30, 1258))
        self.assertIn("держать цену", r)
        self.assertIn("ДРР 30", r)


class Ledger(unittest.TestCase):
    def test_cover_and_reorder(self):
        import src.ledger as L
        with tempfile.TemporaryDirectory() as d:
            old = L.DIR
            L.DIR = d
            try:
                L.ensure()
                with open(os.path.join(d, "batches.csv"), "a", newline="", encoding="utf-8-sig") as f:
                    csv.writer(f).writerow(["B1", "2026-11-01", "X", 300, 18, 12.43, 15000, 0, "на складе", "", 300])
                with open(os.path.join(d, "sales.csv"), "a", newline="", encoding="utf-8-sig") as f:
                    csv.writer(f).writerow(["2026-12-01", 70, 0])
                s = L.summary()
            finally:
                L.DIR = old
        self.assertEqual(s["stock"], 230)
        self.assertAlmostEqual(s["orders_day"], 10, delta=0.01)
        self.assertEqual(s["cover_days"], 23)
        self.assertTrue(s["reorder"])
        self.assertAlmostEqual(s["batches"][0]["unit_cost"], 18 * 12.43 + 50, delta=0.5)


class Backup(unittest.TestCase):
    def test_secrets_never_included(self):
        from src.backup import files
        names = {os.path.basename(p) for p in files()}
        self.assertNotIn(".env", names)
        self.assertNotIn(".mcp.json", names)


if __name__ == "__main__":
    unittest.main()


class CompetitorWatch(unittest.TestCase):
    def _rows(self, n, **over):
        d0 = dt.date(2026, 9, 1)
        R = []
        for i in range(n):
            r = {"data": (d0 + dt.timedelta(days=i)).isoformat(), "sales": 10, "balance": 50, "final_price": 700,
                 "in_ads": 1, "in_action": 0, "search_position_avg": 50, "comments": 100 + i}
            for k, f in over.items():
                r[k] = f(i)
            R.append(r)
        return R

    def test_ads_off_and_price_signals(self):
        from src.competitor_watch import analyse
        a = analyse(self._rows(21, in_ads=lambda i: 1 if i < 14 else 0, final_price=lambda i: 700 if i < 14 else 600))
        s = " ".join(a["signals"])
        self.assertIn("реклама почти выключена", s)
        self.assertIn("−14%", s.replace("-", "−"))
        self.assertTrue(a["data_ok"])

    def test_broken_saleflow_guard(self):
        from src.competitor_watch import analyse
        a = analyse(self._rows(21, balance=lambda i: 0))
        self.assertFalse(a["data_ok"])
        self.assertNotIn("sales_7d", a)


class CompetitorWatchWindow(unittest.TestCase):
    def test_guard_uses_recent_window_only(self):
        """Длинная хорошая история + сломанные последние 3 недели (как Saleflow в окт. 2026) → данные НЕ ок."""
        from src.competitor_watch import analyse
        d0 = dt.date(2026, 1, 1)
        R = [{"data": (d0 + dt.timedelta(days=i)).isoformat(), "sales": 10 if i < 200 else 0, "balance": 50 if i < 200 else 0,
              "final_price": 700, "in_ads": 1, "in_action": 0, "search_position_avg": 50, "comments": i} for i in range(230)]
        a = analyse(R)
        self.assertFalse(a["data_ok"])
        self.assertNotIn("дефектура", " ".join(a["signals"]))


class SchemeAmFbs(unittest.TestCase):
    """Схема 2026-10-15 (config/scheme_am_fbs.yaml): FBS ≤ 1 л = 30 ₽, налог 10 %, ДРР от заказов, эквайринг."""

    def test_scheme_does_not_touch_legacy_config(self):
        from src.unit_econ import load_config, load_scheme
        self.assertEqual(load_config()["tax"]["rate_pct"], 6.0)          # 777-отчёты и marketing777 — по старой схеме
        s = load_scheme("am_fbs")
        self.assertEqual(s["tax"]["rate_pct"], 10.0)
        self.assertEqual(s["operations"]["ad_basis"], "orders")

    def test_wb_fbs_tariff_plus_ff_per_order(self):
        from src.unit_econ import load_scheme, unit_economics, wb_logistics
        s = load_scheme("am_fbs")
        self.assertAlmostEqual(wb_logistics(0.6, s), 78.2)                # WB API «Свой склад РФ», 1-й литр
        self.assertAlmostEqual(wb_logistics(2.0, s), 78.2 + 23.8)
        e = unit_economics(1000, 200, 0.6, s, buyout_pct=100, commission_pct=20, with_breakeven=False)
        self.assertAlmostEqual(e["logistics_with_returns"], 78.2 + 30.0)  # + ФФ 30 ₽ до пункта приёма

    def test_ads_from_orders_divided_by_buyout(self):
        from src.unit_econ import load_scheme, unit_economics
        s = load_scheme("am_fbs")
        e = unit_economics(1000, 200, 0.5, s, buyout_pct=50, ad_share_of_revenue_pct=10, commission_pct=20)
        self.assertAlmostEqual(e["ads"], 200.0)                          # 10 % от заказов при выкупе 50 % = 20 % от продаж
        self.assertAlmostEqual(e["tax"], 100.0)
        self.assertAlmostEqual(e["acquiring"], 15.0)

    def test_fixed_per_unit_lowers_profit_exactly(self):
        from src.unit_econ import load_scheme, unit_economics
        s = load_scheme("am_fbs")
        a = unit_economics(1500, 250, 0.6, s, buyout_pct=70, commission_pct=28, with_breakeven=False)
        b = unit_economics(1500, 250, 0.6, s, buyout_pct=70, commission_pct=28, with_breakeven=False, fixed_per_unit_rub=80)
        self.assertAlmostEqual(a["net_profit"] - b["net_profit"], 80.0, delta=0.01)

    def test_payback_money_not_later_than_strict(self):
        from src import finplan as F
        prod = {"name": "t", "price": 1590, "yuan": 15, "vol": 0.6, "kg": 0.25, "buyout": 71.0, "commission": 28.0}
        season = [100] * 12
        r = F.run("t", prod, [6.0] * 12, season, 300)
        if r["payback"] is not None:
            self.assertIsNotNone(r["payback_money"])
            self.assertLessEqual(r["payback_money"], r["payback"])
