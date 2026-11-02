"""Пересчёт ниш по ЦЕНЕ ПОКУПАТЕЛЯ (кабинет из Армении: СПП ≈ 0) поверх niche_nocargo. 0 запросов Saleflow, 1 запрос Evirma.

    python -m src.rescreen_buyer [--evirma]     # → data/processed/rescreen_buyer_<дата>.json, reports/rescreen_buyer_<дата>.md

Маржа считается при цене = медиана цены покупателя рабочей полосы (buyer_med), схема am_fbs, ДРР 15 %.
¥ закупки: реальная из 1688 (weights_1688_*.json), иначе допущение 7 % цены покупателя [допущение].
Evirma: СПП конкурентов FBO/FBS в полосе (чем выше — тем сильнее WB субсидирует конкурентов).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys

from src.cargo import per_unit
from src.unit_econ import load_scheme, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
TODAY = dt.date.today().isoformat()
CFG = load_scheme("am_fbs")
YUAN_SHARE = 0.07                                   # [допущение] ¥ ≈ 7 % цены покупателя, если нет данных 1688


def real_yuan() -> dict[int, float]:
    """Медиана двух лучших предложений 1688 по нише (Bright Data, 2026-10-18)."""
    out = {}
    for f in glob.glob("data/processed/weights_1688_*.json"):
        d = json.load(open(f, encoding="utf-8")) or {}
        for k, v in (d.items() if isinstance(d, dict) else []):
            pr = sorted(t["price"] for t in (v or {}).get("top", []) if t.get("price"))
            if pr:
                out[int(k)] = pr[len(pr) // 2] if len(pr) > 1 else pr[0]
    return out


def econ(price, yuan, kg, vol, buyout, com, drr=15.0):
    landed = per_unit(yuan, kg, vol)["landed_rub"]
    return unit_economics(price, landed, vol, CFG, with_breakeven=False, buyout_pct=buyout, commission_pct=com,
                          ad_share_of_revenue_pct=drr, packaging_rub=15)


def max_yuan(price, kg, vol, buyout, com) -> float:
    lo, hi = 0.0, 200.0
    for _ in range(35):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if econ(price, m, kg, vol, buyout, com)["net_margin_pct"] >= 18 else (lo, m)
    return round(lo, 1)


def run(use_evirma: bool) -> list[dict]:
    src = sorted(glob.glob("data/processed/niche_nocargo_*.json"))
    N = json.load(open([f for f in src if "batmag" not in f][-1], encoding="utf-8"))
    G = {r["id"]: r for r in json.load(open("data/processed/checkable_2026-10-18.json", encoding="utf-8"))}
    RY = real_yuan()
    out = []
    for r in N:
        b = r.get("best")
        if not b or not b.get("buyer_med") or not r.get("kg") or not r.get("vol_l"):
            continue
        if G.get(r["id"], {}).get("group", "можно") != "можно":               # ЧЗ, батарейки, магниты — правило владельца
            continue
        buy, com = r.get("buyout_real") or r.get("buyout") or 75, r.get("com") or 20
        pb, ps = b["buyer_med"], b.get("seller_price_med") or b["buyer_med"]
        y_real = RY.get(r["id"])
        y = y_real or round(pb * YUAN_SHARE / CFG["cargo"]["cny_to_rub"], 1)
        e = econ(pb, y, r["kg"], r["vol_l"], buy, com)
        e25 = econ(pb, y, r["kg"], r["vol_l"], buy, com, 25)
        out.append(dict(id=r["id"], name=r["name"].split(" / ")[-1], band=b["band"], buyer=pb, seller=ps,
                        spp_jul=round((1 - pb / ps) * 100) if ps else None, p50=b.get("p50"), newcomers=b.get("newcomers"),
                        winners=b.get("winners5"), winner_sellers=b.get("winner_sellers"), top1=b.get("top1_pct"),
                        buyout=buy, com=com, kg=r["kg"], vol=r["vol_l"], yuan=y, yuan_src="1688" if y_real else "допущение 7 %",
                        margin_seller_old=r.get("margin_drr15"), margin=e["net_margin_pct"], profit=round(e["net_profit"]),
                        profit_drr25=round(e25["net_profit"]), max_yuan=max_yuan(pb, r["kg"], r["vol_l"], buy, com),
                        top_ids=b.get("top_ids", [])[:3], status_old=r.get("status")))
    if use_evirma and out:
        try:
            from src import evirma as E
            cand = sorted(out, key=lambda o: -o["margin"])[:100]
            rg = E.ranges([o["id"] for o in cand], retries=2)
            for o in out:
                g = rg.get(o["id"])
                if g:
                    o["spp_fbo"], o["spp_fbs"] = E.spp_at(g, o["seller"], "fbo"), E.spp_at(g, o["seller"], "fbs")
        except Exception as ex:                                             # noqa: BLE001
            print("Evirma недоступен:", str(ex)[:80])
    out.sort(key=lambda o: (-(o["margin"] >= 18), -o["profit"] * (o["p50"] or 0)))
    json.dump(out, open(f"data/processed/rescreen_buyer_{TODAY}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evirma", action="store_true")
    a = ap.parse_args()
    out = run(a.evirma)
    ok = [o for o in out if o["margin"] >= 18]
    print(f"ниш с полосой: {len(out)} | маржа ≥ 18 % по цене покупателя: {len(ok)}")
    for o in out[:40]:
        print(f"{o['id']:5} {o['name'][:30]:30} {o['band']} покуп {o['buyer']} СПП-июль {o['spp_jul']}% "
              f"Evirma FBO/FBS {o.get('spp_fbo', '—')}/{o.get('spp_fbs', '—')} P50 {o['p50']} поб {o['winners']}/{o['winner_sellers']} "
              f"top1 {o['top1']}% {o['kg']}кг/{o['vol']}л ¥{o['yuan']}({o['yuan_src']}) маржа {o['margin_seller_old']}→{o['margin']}% "
              f"прибыль {o['profit']} (ДРР25 {o['profit_drr25']}) maxY {o['max_yuan']}")


if __name__ == "__main__":
    main()
