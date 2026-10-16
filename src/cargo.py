"""Карго Китай → Москва по калькулятору YUANEXIM (2026-10-16). Параметры — config/scheme_am_fbs.yaml → cargo.

    python -m src.cargo carton --kg 35 --cm 55x50x44           # как калькулятор: итог $ за коробку (пример → 87,4 $)
    python -m src.cargo unit --yuan 20 --kg 0.25 --vol 0.6 [--pcs 140]   # себестоимость 1 шт до ФФ, ₽

Формула калькулятора: итог $ = (вес коробки + вес упаковки) × тариф $/кг + объём коробки м³ × цена упаковки $/м³.
Шт в коробке (если не задано): min(вес: carton_max_kg / вес 1 шт, объём: объём коробки × carton_fill / объём 1 шт).
"""
from __future__ import annotations

import argparse
import math


def cfg() -> dict:
    from src.unit_econ import load_scheme
    return load_scheme("am_fbs")["cargo"]


def carton_usd(kg: float, cm: tuple[float, float, float], c: dict | None = None) -> dict:
    c = c or cfg()
    p = c["packaging_types"][c["packaging"]]
    m3 = cm[0] * cm[1] * cm[2] / 1e6
    freight = (kg + p["kg_per_carton"]) * c["rate_usd_per_kg"]
    pack = m3 * p["usd_per_m3"]
    return {"m3": round(m3, 4), "density_kg_m3": round(kg / m3), "freight_usd": round(freight, 2), "packaging_usd": round(pack, 2),
            "total_usd": round(freight + pack, 2)}


def pcs_per_carton(kg: float, vol_l: float, c: dict | None = None) -> int:
    c = c or cfg()
    cm = c["carton_cm"]
    by_kg = math.floor(c["carton_max_kg"] / kg)
    by_vol = math.floor(cm[0] * cm[1] * cm[2] / 1000 * c["carton_fill"] / vol_l)
    return max(1, min(by_kg, by_vol))


def per_unit(yuan: float, kg: float, vol_l: float, pcs: int | None = None, c: dict | None = None) -> dict:
    """→ себестоимость 1 шт до ФФ (₽): товар ¥ × курс × (1 + агент %) + карго коробки / шт + доставка до ФФ."""
    c = c or cfg()
    pcs = pcs or pcs_per_carton(kg, vol_l, c)
    box = carton_usd(pcs * kg, tuple(c["carton_cm"]), c)
    cargo_rub = box["total_usd"] * c["usd_to_rub"] / pcs + c.get("to_ff_rub_per_unit", 0)
    goods_rub = yuan * c["cny_to_rub"] * (1 + c.get("agent_pct", 0) / 100)
    return {"pcs_per_carton": pcs, "carton": box, "goods_rub": round(goods_rub, 1), "cargo_rub": round(cargo_rub, 1),
            "landed_rub": round(goods_rub + cargo_rub, 1)}


def yuan_from_cost(cost_rub: float, kg: float, vol_l: float, c: dict | None = None) -> float:
    """Обратно: какой ¥ даёт такую себестоимость (для max ¥)."""
    c = c or cfg()
    cargo = per_unit(0, kg, vol_l, c=c)["cargo_rub"]
    return max(0.0, (cost_rub - cargo) / (c["cny_to_rub"] * (1 + c.get("agent_pct", 0) / 100)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["carton", "unit"])
    ap.add_argument("--kg", type=float, required=True)
    ap.add_argument("--cm")
    ap.add_argument("--yuan", type=float)
    ap.add_argument("--vol", type=float)
    ap.add_argument("--pcs", type=int)
    a = ap.parse_args()
    if a.cmd == "carton":
        cm = tuple(float(x) for x in (a.cm or "55x50x44").lower().split("x"))
        print(carton_usd(a.kg, cm))
    else:
        print(per_unit(a.yuan or 0, a.kg, a.vol or 0.6, a.pcs))


if __name__ == "__main__":
    main()
