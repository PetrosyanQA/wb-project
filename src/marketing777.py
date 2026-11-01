"""⚠️ СНИМОК 2026-10-08 (товар 777 снят: магниты). Считает по СТАРОЙ модели load_config() (FBO, налог 6 %) — цифры не актуальны,
для новых расчётов — src/unit_econ (схема am_fbs) + src/white_import. Оставлен для воспроизводимости wb_algorithm/.

Маркетинг-калькулятор 777: цена × ДРР → маржа, СПП ниши, чувствительность к комиссии и базе удержаний (2026-10-08). 0 запросов.

    python -m src.marketing777      # → wb_algorithm/data/marketing777.json + таблицы в stdout

Допущения те же, что в reports/strategy_777_2026-10-07.md §2.4: себестоимость ¥18 × 17 = 306 ₽, объём 0.72 л,
выкуп 84.6 %, комиссия FBS кабинета 20 % (WB API), упаковка+ФФ 50 ₽; цена в unit_econ = цена ДО СПП (её платит WB).
"""
from __future__ import annotations

import json
import statistics as st
import sys

from src.datastore import latest, rows
from src.unit_econ import load_config, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
COST, VOL, BUYOUT, COMM, PACK = 306, 0.72, 84.6, 20, 15
OUT = "wb_algorithm/data/marketing777.json"
CFG = load_config()


def econ(price, drr, comm=COMM, comm_base=None):
    """comm_base — цена, от которой WB считает комиссию (по умолчанию = price, т.е. до СПП)."""
    e = unit_economics(price, COST, VOL, CFG, buyout_pct=BUYOUT, ad_share_of_revenue_pct=drr, commission_pct=comm, packaging_rub=PACK)
    if comm_base is not None:                       # удержание от цены покупателя: комиссия меньше в рублях, но и выплата меньше
        e = unit_economics(comm_base, COST, VOL, CFG, buyout_pct=BUYOUT, ad_share_of_revenue_pct=drr * price / comm_base,
                           commission_pct=comm, packaging_rub=PACK)
    return e


def spp_of_niche(niche: int) -> dict:
    P = sorted(rows(latest(niche, "products500")), key=lambda p: -(p.get("revenue") or 0))[:100]
    s = [1 - p["final_price_average"] / p["final_price"] for p in P if p.get("final_price") and p.get("final_price_average")]
    s.sort()
    return {"n": len(s), "p25": round(s[len(s) // 4] * 100, 1), "median": round(st.median(s) * 100, 1), "p75": round(s[3 * len(s) // 4] * 100, 1)}


def main() -> None:
    prices = list(range(1100, 2001, 100))
    drrs = [0, 5, 10, 15, 20, 25, 30, 35]
    grid = {p: {d: econ(p, d)["net_margin_pct"] for d in drrs} for p in prices}
    max_drr = {}
    for p in prices:
        ok18 = [d for d in range(0, 61) if econ(p, d)["net_margin_pct"] >= 18]
        ok0 = [d for d in range(0, 81) if econ(p, d)["net_profit"] >= 0]
        max_drr[p] = {"for_margin18": max(ok18) if ok18 else None, "breakeven": max(ok0) if ok0 else None}
    spp = {n: spp_of_niche(n) for n in (777, 2486, 249, 2264, 1203, 1520, 731)}
    comm = {c: econ(1590, 15, comm=c) for c in (20, 25, 30, 35)}
    stage = {name: econ(p, d) for name, p, d in (("Старт 790 ₽ (до СПП 1 258)", 1258, 25), ("Рост 890 ₽ (1 417)", 1417, 18),
                                                 ("Зрелость 999 ₽ (1 591)", 1591, 15))}
    res = {"assumptions": {"cost": COST, "volume_l": VOL, "buyout_pct": BUYOUT, "commission_fbs_pct": COMM, "packaging_rub": PACK},
           "margin_grid_pct": grid, "max_drr": max_drr, "spp_top100": spp,
           "commission_sensitivity_1590_drr15": {c: {"profit": e["net_profit"], "margin": e["net_margin_pct"], "roi": e["roi_on_goods_pct"]} for c, e in comm.items()},
           "stages": {k: {"profit": e["net_profit"], "margin": e["net_margin_pct"], "roi": e["roi_on_goods_pct"], "breakeven": e["breakeven_price"]} for k, e in stage.items()}}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Маржа %, цена до СПП × ДРР:")
    print("цена  " + " ".join(f"{d:>5}%" for d in drrs) + " | max ДРР (маржа≥18% / в ноль)")
    for p in prices:
        print(f"{p:5} " + " ".join(f"{grid[p][d]:6}" for d in drrs) + f" | {max_drr[p]['for_margin18']} / {max_drr[p]['breakeven']}")
    print("СПП top-100 (1 − цена покупателя / цена до СПП):", spp)
    print("Комиссия (1590 ₽, ДРР 15%):", res["commission_sensitivity_1590_drr15"])
    print("Этапы:", res["stages"])
    print("→", OUT)


if __name__ == "__main__":
    main()
