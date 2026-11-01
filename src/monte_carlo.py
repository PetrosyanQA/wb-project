"""Стресс-тест прибыли (Монте-Карло): 10 000 сценариев, где цена, СПП, себестоимость, выкуп и реклама одновременно «гуляют».

    python -m src.monte_carlo --buyer 990 --spp 24 --yuan 4.8 --kg 0.25 --vol 0.5 --com 21 --buyout 81
    python -m src.monte_carlo ... --batch 400 --runs 10000

Модель — та же, что везде: src.unit_econ, схема am_fbs, себестоимость белого ввоза 1,446 × ¥ × 13,29 + $1,5/кг + 15 800 ₽ / партия.
Разброс в каждом сценарии [допущения, идея WB Analyzer 2026-10-27, расширена под нашу схему]:
  цена покупателя ×0,80–1,00 (демпинг, акции), СПП ±10 п.п. (Evirma прыгала 4–31 %), ¥ ×1,00–1,30,
  доставка $/кг ×1,0–1,5, выкуп ±15 % от базы, ДРР 8–20 %.
Итог: вероятность убытка, P10 / P50 / P90 прибыли с продажи и маржи. Риск убытка > 15 % — слабое место, < 15 % — ок.
"""
from __future__ import annotations

import argparse
import random
import statistics as st
import sys

from src.unit_econ import load_scheme, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
from src.white_import import CNY, CUSTOMS, K, USD, USD_PER_KG  # noqa: E402 — параметры белого ввоза в config/landed_cost.yaml


def simulate(buyer, spp, yuan, kg, vol, com, buyout, batch=400, runs=10_000, seed=1):
    cfg, rnd, prof, marg = load_scheme("am_fbs"), random.Random(seed), [], []
    for _ in range(runs):
        b = buyer * rnd.uniform(0.80, 1.00)
        s = max(0.0, min(45.0, spp + rnd.uniform(-10, 10)))
        seller = b / (1 - s / 100)
        landed = K * yuan * rnd.uniform(1.0, 1.3) * CNY + USD_PER_KG * rnd.uniform(1.0, 1.5) * USD * kg + CUSTOMS / batch
        bo = max(30.0, min(98.0, buyout * rnd.uniform(0.85, 1.15)))
        e = unit_economics(seller, landed, vol, cfg, with_breakeven=False, buyout_pct=bo,
                           ad_share_of_revenue_pct=rnd.uniform(8, 20), commission_pct=com, tax_rate_pct=10)
        prof.append(e["net_profit"])
        marg.append(e["net_margin_pct"])
    q = lambda xs, p: sorted(xs)[int(len(xs) * p)]
    return dict(loss_pct=round(sum(p < 0 for p in prof) / runs * 100, 1),
                p10=round(q(prof, .1)), p50=round(st.median(prof)), p90=round(q(prof, .9)),
                m10=round(q(marg, .1), 1), m50=round(st.median(marg), 1), m90=round(q(marg, .9), 1))


def main():
    ap = argparse.ArgumentParser()
    for k in ("buyer", "spp", "yuan", "kg", "vol", "com", "buyout"):
        ap.add_argument(f"--{k}", type=float, required=True)
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--runs", type=int, default=10_000)
    a = ap.parse_args()
    r = simulate(a.buyer, a.spp, a.yuan, a.kg, a.vol, a.com, a.buyout, a.batch, a.runs)
    print(f"Сценариев: {a.runs}. Вероятность убытка: **{r['loss_pct']} %** {'⚠️ высокий' if r['loss_pct'] > 15 else '✅ ок'}")
    print(f"Прибыль с продажи: P10 {r['p10']} ₽ | P50 {r['p50']} ₽ | P90 {r['p90']} ₽")
    print(f"Маржа: P10 {r['m10']} % | P50 {r['m50']} % | P90 {r['m90']} %")


if __name__ == "__main__":
    main()
