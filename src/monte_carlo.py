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


def load_ranges(path: str | None = None) -> dict:
    import yaml
    from pathlib import Path
    return yaml.safe_load(Path(path or Path(__file__).resolve().parents[1] / "config" / "monte_carlo.yaml").read_text(encoding="utf-8"))


def _draw(rnd, r: dict) -> float:
    if r.get("distribution") == "triangular":
        return rnd.triangular(r["min"], r["max"], r["mode"])
    return rnd.uniform(r["min"], r["max"])


def _apply(base: float, r: dict, x: float) -> float:
    v = base * x if r["kind"] == "mult" else base + x if r["kind"] == "add" else x
    lo, hi = r.get("clip", (None, None))
    return min(hi, max(lo, v)) if lo is not None else v


def _fixed(r: dict) -> float:
    """Значение фактора «без разброса» (середина/мода) — для анализа чувствительности."""
    return r.get("mode", (r["min"] + r["max"]) / 2)


def simulate(buyer, spp, yuan, kg, vol, com, buyout, batch=400, runs=10_000, seed=1, ranges=None, freeze=None):
    R, cfg, rnd, prof, marg = ranges or load_ranges(), load_scheme("am_fbs"), random.Random(seed), [], []
    x = lambda k: _fixed(R[k]) if freeze == k else _draw(rnd, R[k])          # noqa: E731
    for _ in range(runs):
        b = buyer * x("price")
        s = _apply(spp, R["spp"], x("spp"))
        seller = b / (1 - s / 100)
        landed = K * yuan * x("yuan") * CNY + USD_PER_KG * x("freight") * USD * kg + CUSTOMS / batch
        bo = _apply(buyout, R["buyout"], x("buyout"))
        e = unit_economics(seller, landed, vol, cfg, with_breakeven=False, buyout_pct=bo,
                           ad_share_of_revenue_pct=x("drr"), commission_pct=com, tax_rate_pct=10)
        prof.append(e["net_profit"])
        marg.append(e["net_margin_pct"])
    q = lambda xs, p: sorted(xs)[int(len(xs) * p)]                              # noqa: E731
    return dict(loss_pct=round(sum(p < 0 for p in prof) / runs * 100, 1),
                p10=round(q(prof, .1)), p50=round(st.median(prof)), p90=round(q(prof, .9)),
                m10=round(q(marg, .1), 1), m50=round(st.median(marg), 1), m90=round(q(marg, .9), 1))


def sensitivity(args: tuple, runs: int, seed: int, ranges: dict) -> list[tuple[str, float, float]]:
    """Один фактор фиксируем в середине → насколько падает риск убытка (чем больше, тем важнее фактор)."""
    base = simulate(*args, runs=runs, seed=seed, ranges=ranges)
    out = []
    for k in ranges:
        r = simulate(*args, runs=runs, seed=seed, ranges=ranges, freeze=k)
        out.append((k, round(base["loss_pct"] - r["loss_pct"], 1), r["p50"] - base["p50"]))
    return sorted(out, key=lambda z: -abs(z[1]))


def main():
    ap = argparse.ArgumentParser()
    for k in ("buyer", "spp", "yuan", "kg", "vol", "com", "buyout"):
        ap.add_argument(f"--{k}", type=float, required=True)
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--runs", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--config", help="диапазоны (по умолчанию config/monte_carlo.yaml)")
    ap.add_argument("--sensitivity", action="store_true", help="влияние каждого фактора на риск убытка")
    a = ap.parse_args()
    R = load_ranges(a.config)
    args = (a.buyer, a.spp, a.yuan, a.kg, a.vol, a.com, a.buyout, a.batch)
    r = simulate(*args, runs=a.runs, seed=a.seed, ranges=R)
    print(f"Сценариев: {a.runs} (seed {a.seed}). Вероятность убытка: **{r['loss_pct']} %** {'⚠️ высокий' if r['loss_pct'] > 15 else '✅ ок'}")
    print(f"Прибыль с продажи: P10 {r['p10']} ₽ | P50 {r['p50']} ₽ | P90 {r['p90']} ₽")
    print(f"Маржа: P10 {r['m10']} % | P50 {r['m50']} % | P90 {r['m90']} %")
    print("Диапазоны: " + "; ".join(f"{k} {v['min']}…{v['max']} ({v.get('source', '?')})" for k, v in R.items()))
    if a.sensitivity:
        print("Чувствительность (фактор зафиксирован → риск убытка меньше на, п.п. / P50 прибыли +₽):")
        for k, d_loss, d_p50 in sensitivity(args, max(1000, a.runs // 5), a.seed, R):
            print(f"  {k:<8} {d_loss:+.1f} п.п. / {d_p50:+} ₽")


if __name__ == "__main__":
    main()
