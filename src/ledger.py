"""Учёт партий и денег (без API): себестоимость партии, остаток, на сколько дней хватит, когда дозаказать.

    python -m src.ledger                 # сводка по ledger/batches.csv + ledger/payments.csv
    python -m src.ledger --orders-day 5  # пересчитать «хватит на N дней» при другом темпе

ledger/batches.csv  — партии: batch_id, order_date, supplier, units, cny_per_unit, fx_cny_rub, cargo_rub, other_rub,
                      status (заказано / в пути / на складе), eta, received_units
ledger/payments.csv — деньги: date, batch_id, kind (товар / карго / фулфилмент / реклама / образцы / прочее), rub, note
ledger/sales.csv    — продано по неделям (заполняет weekly_report или вручную): week_start, units_sold, units_returned

Правило дозаказа (strategy_777 + winners_playbook): заказать, если остатка хватит меньше чем на lead_time_days + 21 день.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
DIR = "ledger"
LEAD_TIME_DAYS = 35            # [допущение] образцы есть → заказ → производство 7–10 дн. + карго 18–25 дн.
SAFETY_DAYS = 21
HEADERS = {
    "batches.csv": ["batch_id", "order_date", "supplier", "units", "cny_per_unit", "fx_cny_rub", "cargo_rub", "other_rub",
                    "status", "eta", "received_units"],
    "payments.csv": ["date", "batch_id", "kind", "rub", "note"],
    "sales.csv": ["week_start", "units_sold", "units_returned"],
}


def ensure() -> None:
    os.makedirs(DIR, exist_ok=True)
    for f, h in HEADERS.items():
        p = os.path.join(DIR, f)
        if not os.path.exists(p):
            with open(p, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerow(h)


def read(name: str) -> list[dict]:
    with open(os.path.join(DIR, name), encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if any(v.strip() for v in r.values() if v)]


def num(x, d=0.0) -> float:
    try:
        return float(str(x).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return d


def summary(orders_day: float | None = None) -> dict:
    ensure()
    B, P, S = read("batches.csv"), read("payments.csv"), read("sales.csv")
    out = {"batches": [], "stock": 0, "cash_out": sum(num(p["rub"]) for p in P)}
    for b in B:
        units = num(b["units"])
        goods = units * num(b["cny_per_unit"]) * num(b["fx_cny_rub"], 12.43)
        total = goods + num(b["cargo_rub"]) + num(b["other_rub"])
        out["batches"].append({"id": b["batch_id"], "status": b["status"], "units": units,
                               "unit_cost": round(total / units, 1) if units else None, "total_rub": round(total)})
    received = sum(num(b["received_units"]) for b in B if b["status"].strip().lower().startswith("на складе"))
    sold = sum(num(s["units_sold"]) - num(s["units_returned"]) for s in S)
    in_transit = sum(num(b["units"]) for b in B if not b["status"].strip().lower().startswith("на складе"))
    out.update(stock=received - sold, in_transit=in_transit, sold=sold)
    if orders_day is None and S:
        last = S[-4:]
        orders_day = sum(num(s["units_sold"]) for s in last) / (7 * len(last))
    out["orders_day"] = round(orders_day or 0, 2)
    if orders_day:
        cover = out["stock"] / orders_day
        out["cover_days"] = round(cover)
        out["reorder"] = cover < LEAD_TIME_DAYS + SAFETY_DAYS
        out["reorder_units"] = max(100, round(orders_day * (LEAD_TIME_DAYS + SAFETY_DAYS + 30) - out["stock"] - in_transit))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders-day", type=float)
    s = summary(ap.parse_args().orders_day)
    if not s["batches"]:
        print(f"Партий ещё нет. Заполните {DIR}/batches.csv (шапка уже создана) после заказа у поставщика.")
        return
    for b in s["batches"]:
        print(f"партия {b['id']}: {b['status']}, {b['units']:.0f} шт × {b['unit_cost']} ₽ = {b['total_rub']} ₽")
    print(f"на складе {s['stock']:.0f} шт, в пути {s['in_transit']:.0f} шт, продано {s['sold']:.0f} шт, потрачено {s['cash_out']:.0f} ₽")
    if s.get("cover_days") is not None:
        flag = "⚠️ ДОЗАКАЗАТЬ СЕЙЧАС" if s["reorder"] else "✅ запаса хватает"
        print(f"темп {s['orders_day']}/день → хватит на {s['cover_days']} дн. (порог {LEAD_TIME_DAYS}+{SAFETY_DAYS}) → {flag}"
              + (f", ≈ {s['reorder_units']} шт" if s["reorder"] else ""))


if __name__ == "__main__":
    main()
