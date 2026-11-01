"""Финплан запуска для ниши-пресета (обобщение src/finplan777.py, 2026-10-07). 0 запросов.

    python -m src.finplan --niche 777 --legacy     # сценарии 2026-10-06 → должно совпасть с data/processed/finplan777_2026-10-06.json
    python -m src.finplan --niche 777              # сценарии из strategy_777_2026-10-07.json (newcomer_levels × форма разгона)
    python -m src.finplan --niche 2486 [--start 2027-03]

Модель (месяц = шаг) — как в finplan777:
  спрос (заказов/день, без сезона) × индекс сезона календарного месяца × выкуп → продажи, но не больше остатка;
  деньги от продаж приходят в тот же месяц (WB платит еженедельно) [допущение];
  закупка в начале месяца на спрос следующего месяца × 1.2, только на свободные деньги, минимум 100 шт
  (если остатка не хватит — заказываем max(нехватка, 100); правило finplan777 — только в --legacy);
  приходит через 1 месяц (производство 10–15 дн + карго 15–25 дн) [допущение];
  юнит-экономика — src/unit_econ.py (ДРР 25% мес. 1–2, 15% далее), фулфилмент 10 000 ₽/мес.
Сценарии (одно правило для всех ниш; заказов/день без сезона × форма разгона из P50 траекторий top-100):
  пессимистичный = P25 новых карточек top-500 (июль), реалистичный = P50 их же, оптимистичный = P50 «победителей» top-100.
  Траектории top-100 одни дали бы ошибку выжившего (P25 победителей ≈ P75 новичков top-500) — поэтому только оптимизм.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.strategy import FIXED, FX, PRESETS, RUN, cost_rub
from src.unit_econ import load_config, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
BUDGET_USD = 2000
START_COSTS = {"образцы (2 шт × 3 поставщика + доставка)": 5000, "контент: фото, инфографика, видео": 15000,
               "WB «Отзывы за баллы» (30 отзывов × 100 ₽)": 3000, "реклама: предоплата первых 2 недель": 15000}
MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def unit(prod: dict, drr: float, price: float) -> dict:
    """Схема бизнеса — strategy.econ_config() (с 2026-10-15: ИП Армения, FBS РФ, налог 10 %, ДРР от заказов)."""
    from src.strategy import econ_config
    cfg = econ_config()
    cost, _ = cost_rub(prod["yuan"], prod.get("kg", 0.3), prod["vol"])
    e = unit_economics(price, cost, prod["vol"], cfg, buyout_pct=prod["buyout"], commission_pct=prod["commission"],
                       ad_share_of_revenue_pct=drr, packaging_rub=15)
    cash_in = price - e["commission"] - e["acquiring"] - e["logistics_with_returns"] - e["storage"] - e["ads"] - e["tax"]
    return {"profit": e["net_profit"], "goods": e["goods_cost_full"], "cash_in": cash_in}


def run(name: str, prod: dict, demand: list[float], season: list[int], batch: int, price: float | None = None,
        legacy_moq: bool = False) -> dict:
    """legacy_moq=True — правило finplan777 (заказ < 100 шт не делаем → при спросе ≈ 100 шт/мес модель сама рвёт остаток);
    иначе — как живой продавец: если остатка не хватит на следующий месяц × 1.2, заказываем max(нехватка, 100 шт)."""
    price = price or prod["price"]
    from src.strategy import econ_config
    fixed = econ_config().get("fixed_month_rub", FIXED)          # схема am_fbs: 0 (только 30 ₽ за отправку)
    budget = BUDGET_USD * FX
    start = dict(START_COSTS)
    u1, u2 = unit(prod, 25.0, price), unit(prod, 15.0, price)
    start[f"партия 1: {batch} шт × {u2['goods']:.0f} ₽ (товар+упаковка+ФФ+брак)"] = round(batch * u2["goods"])
    invest = sum(start.values())
    cash = budget - invest
    stock, incoming, cum_profit, rows = batch, 0, 0.0, []
    buyout = prod["buyout"]
    for m in range(12):
        u = u1 if m < 2 else u2
        stock += incoming
        orders = demand[m] * 30 * season[m] / 100
        want = orders * buyout / 100
        sold = min(want, stock)
        stock -= sold
        revenue = sold * price
        profit = sold * u["profit"] - fixed
        cash += sold * u["cash_in"] - fixed
        nxt = demand[m + 1] * 30 * season[(m + 1) % 12] / 100 * buyout / 100 * 1.2 if m < 11 else 0
        need = max(0.0, nxt - stock)
        if legacy_moq:
            buy = min(need, max(cash, 0) / u2["goods"])
            buy = buy if buy >= 100 else (0 if need < 100 else min(100, max(cash, 0) / u2["goods"]))   # мин. заказ 100 шт
        else:
            buy = min(max(need, 100.0), max(cash, 0) / u2["goods"]) if need > 0 else 0.0
        cash -= buy * u2["goods"]
        incoming = buy
        cum_profit += profit
        rows.append({"month": m + 1, "orders_day": round(demand[m] * season[m] / 100, 1), "sold": round(sold),
                     "lost": round(want - sold), "revenue": round(revenue), "profit": round(profit),
                     "cum_profit": round(cum_profit), "bought": round(buy), "stock_end": round(stock), "cash_end": round(cash),
                     "worth_end": round(cash + (stock + incoming) * u2["goods"])})   # деньги + товар (на складе и в пути) по себестоимости
    # payback — строгий: накопленная прибыль ≥ всем вложениям (партия 1 учтена дважды: в прибыли уже вычтена её себестоимость);
    # payback_money — «деньги вернулись»: деньги + товар по себестоимости ≥ стартовому бюджету (2026-10-15, аудит §2.11)
    payback = next((r["month"] for r in rows if r["cum_profit"] >= invest), None)
    payback_money = next((r["month"] for r in rows if r["worth_end"] >= budget), None)
    roi = {k: round(rows[k - 1]["cum_profit"] / invest * 100) for k in (3, 6, 12)}
    return {"name": name, "start": start, "invest": invest, "budget": round(budget), "rows": rows, "payback": payback,
            "payback_money": payback_money, "roi": roi, "unit_launch": u1, "unit_base": u2,
            "min_cash": min(r["cash_end"] for r in rows), "lost_units": sum(r["lost"] for r in rows), "batch": batch,
            "net_12m": rows[-1]["worth_end"] - round(budget)}


def season_from(index: dict, start: str) -> list[int]:
    m0 = int(start[5:7])
    return [index[f"{(m0 - 1 + i) % 12 + 1:02d}"] for i in range(12)]


def demand_from(pct: dict, key: str) -> list[float]:
    """Траектория по месяцам от первой продажи; после последнего известного месяца — плато."""
    out, last = [], None
    for k in range(1, 13):
        v = pct.get(str(k), pct.get(k))
        last = v[key] if v else last
        out.append(last)
    return out


def fit_batch(prod: dict) -> int:
    """Наибольшая партия (кратно 50, 200…300 шт), которая помещается в бюджет вместе со стартовыми расходами."""
    goods = unit(prod, 15.0, prod["price"])["goods"]
    room = BUDGET_USD * FX - sum(START_COSTS.values())
    b = min(300, int(room / goods // 50 * 50))
    return b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, required=True)
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--start")
    a = ap.parse_args()
    if a.legacy:
        from src.finplan777 import SCEN, SEASON                       # сценарии и сезон 2026-10-06
        prod = PRESETS[777]["product"]
        R = [run(n, prod, d, SEASON, 300, legacy_moq=True) for n, d in SCEN.items()]
        R.append(run("реалистичный, удержания от цены покупателя 1 000 ₽", prod, SCEN["реалистичный"], SEASON, 300, 1000,
                     legacy_moq=True))
        old = json.load(open("data/processed/finplan777_2026-10-06.json", encoding="utf-8"))
        same = all(x["invest"] == y["invest"] and x["payback"] == y["payback"] and x["roi"] == {int(k): v for k, v in y["roi"].items()}
                   and [r["cash_end"] for r in x["rows"]] == [r["cash_end"] for r in y["rows"]] for x, y in zip(R, old))
        print(f"legacy 777: вложения {R[0]['invest']} ₽, окупаемость {[r['payback'] for r in R]}, совпадает с 2026-10-06: {same}")
        return
    S = json.load(open(f"data/processed/strategy_{a.niche}_{RUN}.json", encoding="utf-8"))
    P = PRESETS[a.niche]
    prod = S["product"]
    start = a.start or P["launch"]
    L = S["newcomer_levels"]
    season = season_from(S["overview"]["season_index"], start)
    batch = P.get("first_batch") or fit_batch(prod)
    scen = {"пессимистичный (P25 новичков top-500)": L["p25"], "реалистичный (P50 новичков top-500)": L["p50"],
            "оптимистичный (P50 победителей top-100)": L["winners_plateau_p50"]}
    dem = lambda lvl: [round(lvl * L["shape"][k], 2) for k in range(12)]
    R = [run(n, prod, dem(v), season, batch) for n, v in scen.items()]
    R.append(run(f"реалистичный, удержания от цены покупателя {prod['buyer_price']:.0f} ₽", prod, dem(L["p50"]),
                 season, batch, prod["buyer_price"]))
    sens = {}
    m0 = int(start[5:7])
    for shift in (-1, 1):                                            # чувствительность к месяцу старта
        s2 = f"{int(start[:4]) + (m0 - 1 + shift) // 12}-{(m0 - 1 + shift) % 12 + 1:02d}"
        r = run(f"реалистичный, старт {s2}", prod, dem(L["p50"]), season_from(S["overview"]["season_index"], s2), batch)
        sens[s2] = {"payback": r["payback"], "roi": r["roi"], "min_cash": r["min_cash"], "lost_units": r["lost_units"]}
    out = {"niche": a.niche, "start": start, "season": season, "batch": batch, "product": prod, "runs": R, "start_sensitivity": sens,
           "month_names": [MONTHS_RU[(m0 - 1 + i) % 12] for i in range(12)]}
    path = f"data/processed/finplan_{a.niche}_{RUN}.json"
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in R:
        print(f"\n== {r['name']}: вложения {r['invest']} ₽ из {r['budget']} ₽ | партия {r['batch']} | окупаемость: мес. {r['payback']} | "
              f"ROI {r['roi']} | мин. деньги {r['min_cash']} | упущено шт {r['lost_units']}")
        print("мес | заказов/день | продано | упущено | выручка | прибыль | накоп. | закуплено | остаток | деньги")
        for x, mn in zip(r["rows"], out["month_names"]):
            print(f"{x['month']} {mn} | {x['orders_day']} | {x['sold']} | {x['lost']} | {x['revenue']} | {x['profit']} | "
                  f"{x['cum_profit']} | {x['bought']} | {x['stock_end']} | {x['cash_end']}")
    print("\nчувствительность к старту:", sens)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
