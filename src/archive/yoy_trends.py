"""Тренды WB год к году: какие предметы выросли сильнее всех (июль-2025 → июль-2026, окна 30 дней Saleflow).

    python -m src.yoy_trends                  # → reports/yoy_trends_<дата>.md + data/processed/yoy_trends_<дата>.json

Снимки: data/raw/saleflow/2026-10-11/all/jul2026*/ (2026-07-31) и data/raw/saleflow/2026-10-23/yoy/2025-07/ (2025-07-31),
топ ≈ 3 000 предметов по выручке. Июль, а не сентябрь: Saleflow после 2026-07-31 отдаёт неполные продажи.
Два списка: «всё растущее» (для понимания рынка) и «нам подходит» — фильтры all_niches (без электроники/ЧЗ/химии/одежды,
без магнитов/аккумуляторов/жидкостей и крупногабарита по названию) + цена покупателя 700–3 500 ₽ + ≥ 30 продавцов с продажами.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from src.all_niches import BULKY, DROP_NAME, DROP_ROOTS, load, real_rev

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date.today().isoformat()
MIN_REV = 10_000_000        # реальная выручка июля-2026, ₽/мес
MIN_BASE = 2_000_000        # база июля-2025: ниже — «рост с нуля», не тренд
PRICE = (700, 3500)


def main() -> None:
    raw = ROOT / "data" / "raw" / "saleflow"
    now = load(str(raw / "2026-10-11/all/jul2026/page_*.json")) | load(str(raw / "2026-10-11/all/jul2026_rev15m/page_*.json"))
    old = load(str(raw / "2026-10-23/yoy/2025-07/page_*.json"))
    rows = []
    for i, r in now.items():
        a, b = real_rev(r), real_rev(old[i]) if i in old else 0
        if a < MIN_REV or b < MIN_BASE:
            continue
        s0, s1 = (old[i].get("sellers_with_sells") or 0), (r.get("sellers_with_sells") or 0)
        rows.append({"id": i, "name": r["name"], "rev26": round(a / 1e6, 1), "rev25": round(b / 1e6, 1),
                     "growth": round((a / b - 1) * 100), "price": r.get("median_price_final_with_sells"),
                     "sellers": s1, "sellers_growth": round((s1 / s0 - 1) * 100) if s0 else None,
                     "per_seller_k": round(a / s1 / 1e3) if s1 else None, "season": r.get("seasonality_level"),
                     "rating": r.get("comment_valuation_with_sells"), "buyout": r.get("purchase_after_return"),
                     "ok": (r["name"].split(" / ")[0] not in DROP_ROOTS and not DROP_NAME.search(r["name"]) and not BULKY.search(r["name"])
                            and PRICE[0] <= (r.get("median_price_final_with_sells") or 0) <= PRICE[1] and s1 >= 30)})
    rows.sort(key=lambda x: -x["growth"])
    fit = [x for x in rows if x["ok"]]
    out = ROOT / "data" / "processed" / f"yoy_trends_{TODAY}.json"
    json.dump({"all": rows, "fit": fit, "now": len(now), "old": len(old)}, open(out, "w", encoding="utf-8"), ensure_ascii=False)

    def table(R, n):
        L = ["| # | Предмет | Выручка 07.2026, млн ₽ | 07.2025 | Рост | Медиана цены, ₽ | Продавцов | Рост продавцов | На продавца, тыс ₽ |",
             "|---|---|---|---|---|---|---|---|---|"]
        for k, x in enumerate(R[:n], 1):
            sg = f"{x['sellers_growth']:+d} %" if x["sellers_growth"] is not None else "—"
            L.append(f"| {k} | {x['name']} | {x['rev26']} | {x['rev25']} | **{x['growth']:+d} %** | {x['price']} | {x['sellers']} | {sg} | {x['per_seller_k']} |")
        return L
    T = [f"# Тренды WB год к году — {TODAY}",
         f"Снимки Saleflow `wb_subjects_list`: 2025-07-01 … 2025-07-31 и 2026-07-01 … 2026-07-31 (30 дней), реальная выручка = заказы × выкуп. "
         f"Предметов: {len(now)} / {len(old)}; с выручкой ≥ {MIN_REV // 10**6} млн и базой ≥ {MIN_BASE // 10**6} млн: {len(rows)}. [факт], погрешность Saleflow ±10–20 %.",
         "", "## Нам подходит (без электроники, ЧЗ, магнитов, батарей; цена 700–3 500 ₽; ≥ 30 продавцов)", *table(fit, 30),
         "", "## Весь рынок: самые быстрорастущие предметы", *table(rows, 25),
         "", "Рост продавцов быстрее выручки = ниша перегревается; «на продавца» — сколько в среднем зарабатывает продавец с продажами в месяц."]
    rep = ROOT / "reports" / f"yoy_trends_{TODAY}.md"
    rep.write_text("\n".join(T), encoding="utf-8")
    print("\n".join(T)); print("→", rep.relative_to(ROOT))


if __name__ == "__main__":
    main()
