"""Бюджетные сценарии запуска: сколько денег → сколько штук, карточек, прибыли, дней без остатка (по дням, 6 мес).

    python -m src.budget_sim                       # ножи (config/knives.yaml → economics), бюджеты 100…500 тыс
    python -m src.budget_sim --budgets 167000 200000 --days 180

Модель (0 запросов):
  • себестоимость белого импорта: 1,446 × ¥ × 13,29 + $1,5/кг × 92,37 × кг; на каждую поставку + batch_fixed_rub;
  • прибыль/шт — src.unit_econ (схема am_fbs) при цене продавца, комиссии, выкупе, ДРР, налоге из конфига;
  • спрос/день = кривая новичка (P25/P50/P75, по месяцам с запуска) / 30 × (1 + second_card_share на 2-ю карточку);
  • деньги: товар оплачивается при заказе, приходит через lead_days; выручка за вычетом расходов WB и налога
    приходит через payout_lag_days; реклама списывается в день заказа;
  • дозаказ (по плану P50): когда остаток + в пути < спроса на lead_days + 30 дней, ≥ 80 шт (цель 150), с резервом рекламы на 7 дней.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src.unit_econ import load_scheme, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
from src.white_import import CNY as CNY_RUB, K as IMPORT_K, USD as USD_RUB, landed  # noqa: E402,F401 — config/landed_cost.yaml


def landed_var(e: dict) -> float:
    """Переменная часть себестоимости (без фикса партии — он добавляется на каждую поставку)."""
    return landed(e["yuan"], e["weight_kg"], 10**12)


def unit(e: dict) -> dict:
    return unit_economics(e["seller_price"], landed_var(e), e["volume_l"], load_scheme("am_fbs"), with_breakeven=False,
                          buyout_pct=e["buyout_pct"], ad_share_of_revenue_pct=e["drr_pct"],
                          commission_pct=e["commission_pct"], tax_rate_pct=e["tax_pct"])


def simulate(e: dict, budget: float, curve: list[float], cards: int, days: int = 180) -> dict:
    """Первая партия и резерв рекламы планируются по P50 (будущее неизвестно), реальный спрос — по curve."""
    u, var = unit(e), landed_var(e)
    k = 1 + e["second_card_share"] * (cards - 1)
    plan = [e["curve"]["P50"][min(d // 30, 5)] / 30 * k for d in range(days)]
    demand = [curve[min(d // 30, len(curve) - 1)] / 30 * k for d in range(days)]
    ads_unit = u["ads"]
    inflow_unit = u["payout_from_wb"] - u["tax"]                         # что WB перечислит за 1 продажу, минус налог
    goods_extra = u["goods_cost_full"] - var                             # упаковка, первая миля, брак — платим при отгрузке
    lead, lag = e["lead_days"], e["payout_lag_days"]
    # первая партия: всё, что остаётся после фикс. затрат и резерва рекламы/упаковки на первые 30 дней (план P50)
    ad_reserve = sum(plan[:30]) * (ads_unit + goods_extra)
    cash = budget - e["launch_fixed_rub"] - ad_reserve - e["batch_fixed_rub"]
    n0 = max(0, int(cash // (var + goods_extra)))
    if n0 < 30 * cards:
        return {"budget": budget, "cards": cards, "n0": n0, "fail": True}
    cash = budget - e["launch_fixed_rub"] - e["batch_fixed_rub"] - n0 * var
    stock, pipeline, pending = n0, [], [0.0] * (days + lag + 1)
    sold = oos = orders = units_bought = 0
    min_cash, by_month = cash, [0.0] * ((days + 29) // 30)
    goods_paid = e["batch_fixed_rub"] + n0 * var
    for d in range(days):
        for p in [p for p in pipeline if p[0] == d]:
            stock += p[1]
        pipeline = [p for p in pipeline if p[0] != d]
        cash += pending[d]
        q = min(stock, demand[d])
        if demand[d] > 0 and stock < demand[d] * 0.5:
            oos += 1
        stock -= q
        sold += q
        by_month[d // 30] += q
        cash -= q * (ads_unit + goods_extra)
        pending[d + lag] += q * inflow_unit
        min_cash = min(min_cash, cash)
        # дозаказ
        horizon = sum(plan[d + 1: d + 1 + lead + 30]) + (lead + 30 - len(plan[d + 1: d + 1 + lead + 30])) * plan[-1]
        on_way = sum(p[1] for p in pipeline)
        need = horizon - stock - on_way
        # спрос для дозаказа: план P50, но по факту последних 14 дней (как сделал бы продавец)
        free = cash - sum(plan[d + 1: d + 8]) * (ads_unit + goods_extra)          # резерв рекламы на неделю
        if need >= 80 and d + lead < days and free > e["batch_fixed_rub"] + 80 * var:  # поставка не меньше 80 шт (фикс 15 800 ₽)
            qty = int(min(max(need, 150), (free - e["batch_fixed_rub"]) // var))
            cash -= e["batch_fixed_rub"] + qty * var
            goods_paid += e["batch_fixed_rub"] + qty * var
            pipeline.append((d + lead, qty))
            orders += 1
            units_bought += qty
    receivable = sum(pending[days:])
    inventory_value = (stock + sum(p[1] for p in pipeline)) * var
    profit = sold * u["net_profit"] - e["launch_fixed_rub"] - e["batch_fixed_rub"] * (orders + 1)
    return {"budget": budget, "cards": cards, "n0": n0, "fail": False, "sold": round(sold), "oos_days": oos,
            "reorders": orders, "reorder_units": units_bought, "profit": round(profit),
            "end_value": round(cash + receivable + inventory_value), "cash": round(cash), "min_cash": round(min_cash),
            "by_month": [round(x) for x in by_month], "profit_last_month": round(by_month[-1] * u["net_profit"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/knives.yaml")
    ap.add_argument("--budgets", type=float, nargs="+", default=[100_000, 167_000, 200_000, 300_000, 500_000])
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args()
    e = yaml.safe_load((ROOT / a.config).read_text(encoding="utf-8"))["economics"]
    u = unit(e)
    print(f"Себестоимость (без фикса поставки) {landed_var(e):.0f} ₽; прибыль/шт {u['net_profit']:.0f} ₽ "
          f"({u['net_margin_pct']} %), реклама/шт {u['ads']:.0f} ₽, WB перечисляет {u['payout_from_wb']:.0f} ₽, налог {u['tax']:.0f} ₽")
    print("бюджет | карточек | спрос | 1-я партия шт | продано за 6 мес | по месяцам | дней без товара | дозаказов (шт) | прибыль 6 мес | прибыль 6-го мес | мин. деньги | капитал через 6 мес | ×")
    for b in a.budgets:
        for cards in (1, 2):
            for name, curve in e["curve"].items():
                # карточка, которая не взлетела, тратит на рекламу больше (ДРР fail_drr_pct) [допущение]
                ee = dict(e, drr_pct=e.get("fail_drr_pct", 40)) if name == "Провал" else e
                r = simulate(ee, b, curve, cards, a.days)
                if r["fail"]:
                    print(f"{b/1000:.0f}k | {cards} | {name} | {r['n0']} | — не хватает на партию ≥ {30*cards} шт")
                    continue
                print(f"{b/1000:.0f}k | {cards} | {name} | {r['n0']} | {r['sold']} | {'/'.join(map(str, r['by_month']))} | {r['oos_days']} | {r['reorders']} ({r['reorder_units']}) | "
                      f"{r['profit']/1000:.0f} тыс | {r['profit_last_month']/1000:.0f} тыс | {r['min_cash']/1000:.0f} тыс | {r['end_value']/1000:.0f} тыс | {r['end_value']/b:.2f}")


if __name__ == "__main__":
    main()
