"""Финплан запуска 777 (вакуум-магнит MagSafe, 1 590 ₽ до СПП, ¥18) с ограничением по деньгам и остатку. 0 запросов.

    python -m src.finplan777        # → data/processed/finplan777_2026-10-06.json + таблицы

Модель (месяц = шаг):
  спрос (заказов/день) по сценарию × выкуп 84.6% → продажи, но не больше остатка;
  деньги от продаж приходят в тот же месяц (WB платит еженедельно) [допущение];
  закупка в начале месяца на спрос следующего месяца × 1.2, только на свободные деньги; приходит через 1 месяц
  (производство 10–15 дн + карго 15–25 дн) [допущение];
  юнит-экономика — src/unit_econ.py (ДРР 25% мес. 1–2, 15% далее), фулфилмент 10 000 ₽/мес.
"""
from __future__ import annotations

import json
import sys

from src.unit_econ import load_config, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
FX, BUDGET_USD = 83.48, 2000
PRICE, YUAN, VOL, BUYOUT, COM = 1590, 18, 0.4, 84.6, 20.0
FIXED = 10000                                    # фулфилмент Подмосковье, минимум/мес [со слов пользователя]
FIRST_BATCH = 300
SCEN = {"пессимистичный": [3, 5, 7, 8, 8, 8, 8, 8, 8, 9, 8, 8],
        "реалистичный": [5, 12, 20, 25, 25, 25, 25, 25, 25, 28, 25, 25],
        "оптимистичный": [10, 25, 40, 50, 50, 50, 50, 50, 50, 55, 50, 50]}
# ориентиры: 494403950 — 10/день через 3 нед., 30/день через 3.7 мес.; 485786521 — 30 → 105/день; 1146446018 — 0 → 21/день за 3 мес.
SEASON = [113, 93, 109, 102, 102, 104, 100, 92, 90, 91, 102, 98]     # дек…ноя: продажи стартуют ~1 декабря; индекс сезона 777 (2024-09…2026-07)


def unit(drr: float, price: float = PRICE) -> dict:
    cfg = load_config()
    e = unit_economics(price, YUAN * 17, VOL, cfg, buyout_pct=BUYOUT, commission_pct=COM,
                       ad_share_of_revenue_pct=drr, packaging_rub=50.0)
    cash_in = price - e["commission"] - e["logistics_with_returns"] - e["storage"] - e["ads"] - e["tax"]
    return {"profit": e["net_profit"], "goods": e["goods_cost_full"], "cash_in": cash_in}


def run(name: str, demand: list[int], price: float = PRICE) -> dict:
    budget = BUDGET_USD * FX
    start = {"образцы (2 шт × 3 поставщика + доставка)": 5000, "контент: фото, инфографика, видео": 15000,
             "WB «Отзывы за баллы» (30 отзывов × 100 ₽)": 3000, "реклама: предоплата первых 2 недель": 15000}
    u1, u2 = unit(25.0, price), unit(15.0, price)
    start[f"партия 1: {FIRST_BATCH} шт × {u2['goods']:.0f} ₽ (товар+упаковка+ФФ+брак)"] = round(FIRST_BATCH * u2["goods"])
    invest = sum(start.values())
    cash = budget - invest
    stock, incoming, cum_profit, rows = FIRST_BATCH, 0, 0.0, []
    for m in range(12):
        u = u1 if m < 2 else u2
        stock += incoming
        orders = demand[m] * 30 * SEASON[m] / 100
        want = orders * BUYOUT / 100
        sold = min(want, stock)
        stock -= sold
        revenue = sold * price
        profit = sold * u["profit"] - FIXED
        cash += sold * u["cash_in"] - FIXED
        nxt = demand[m + 1] * 30 * SEASON[(m + 1) % 12] / 100 * BUYOUT / 100 * 1.2 if m < 11 else 0
        need = max(0.0, nxt - stock)
        buy = min(need, max(cash, 0) / u2["goods"])
        buy = buy if buy >= 100 else (0 if need < 100 else min(100, max(cash, 0) / u2["goods"]))   # мин. заказ 100 шт
        cash -= buy * u2["goods"]
        incoming = buy
        cum_profit += profit
        rows.append({"month": m + 1, "orders_day": demand[m], "sold": round(sold), "lost": round(want - sold),
                     "revenue": round(revenue), "profit": round(profit), "cum_profit": round(cum_profit),
                     "bought": round(buy), "stock_end": round(stock), "cash_end": round(cash)})
    payback = next((r["month"] for r in rows if r["cum_profit"] >= invest), None)
    roi = {k: round(rows[k - 1]["cum_profit"] / invest * 100) for k in (3, 6, 12)}
    return {"name": name, "start": start, "invest": invest, "budget": round(budget), "rows": rows, "payback": payback,
            "roi": roi, "unit_launch": u1, "unit_base": u2}


def main() -> None:
    R = [run(n, d) for n, d in SCEN.items()]
    R.append(run("реалистичный, удержания от цены покупателя 1 000 ₽", SCEN["реалистичный"], 1000))
    json.dump(R, open("data/processed/finplan777_2026-10-06.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in R:
        print(f"\n== {r['name']}: вложения {r['invest']} ₽ из {r['budget']} ₽ | окупаемость: мес. {r['payback']} | ROI {r['roi']}")
        for k, v in r["start"].items():
            print(f"   {k}: {v}")
        print("мес | заказов/день | продано | упущено | выручка | прибыль | накоп. | закуплено | остаток | деньги")
        for x in r["rows"]:
            print(f"{x['month']} | {x['orders_day']} | {x['sold']} | {x['lost']} | {x['revenue']} | {x['profit']} | "
                  f"{x['cum_profit']} | {x['bought']} | {x['stock_end']} | {x['cash_end']}")
    print("\nunit:", R[0]["unit_launch"], R[0]["unit_base"])


if __name__ == "__main__":
    main()
