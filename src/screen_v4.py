"""Скрин v4 (2026-10-16): лёгкие (≤ 1 л) товары 2 000–3 000 ₽, выкуп ≥ 70 %, экономика по схеме am_fbs.

    python -m src.screen_v4 collect      # products500 июля для кандидатов без кэша (1 запрос на нишу) → data/raw/saleflow/v3_products500/
    python -m src.screen_v4 score        # новички в полосе 2 000–3 000 ₽ + экономика → data/processed/screen_v4_<дата>.json

Кандидаты: data/processed/screen_v4_keep_2026-10-16.json (фильтр по названию/корню/габариту/цене/выкупу — см. отчёт).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
KEEP = "data/processed/screen_v4_keep_2026-10-16.json"
OUT = f"data/processed/screen_v4_{dt.date.today().isoformat()}.json"
SKIP = re.compile(r"светильник|пеленк|лампы|отпугив|мульч|торф|уголь|паст[ыа]|щетки стекл|тазы|паяльник|печать фото|воски|ленты чек|лопаты сад|домики", re.I)
BAND = (2000, 3000)
NEW = ("2025-08-01", "2026-05-31")


def collect() -> None:
    from src import niche_v3 as V
    from src.strategy_collect import Client, fetch
    U = [u for u in json.load(open(KEEP, encoding="utf-8")) if not V.p500_path(u["id"]) and not SKIP.search(u["name"])]
    print("к скачиванию:", len(U))
    os.makedirs(V.RAW, exist_ok=True)
    c, streak = Client(), 0
    try:
        for k, u in enumerate(U, 1):
            try:
                r = fetch(c, "wb_subject", {"subject_id": u["id"], "report": "products", "d1": "2026-07-01", "d2": "2026-07-31", "limit": 500},
                          timeout=200)
                json.dump(r, open(f"{V.RAW}/{u['id']}.json", "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{k}/{len(U)}] ok {u['id']}")
                streak = 0
            except Exception as e:                       # noqa: BLE001 — upstream Saleflow нестабилен
                print(f"[{k}/{len(U)}] fail {u['id']}: {str(e)[:80]}")
                streak += 1
                if streak >= 4:
                    print("4 сбоя подряд — стоп")
                    break
    finally:
        c.close()


def max_yuan(price: float, vol: float, kg: float, buyout: float, comm: float, drr: float, ff: float) -> float:
    """Максимальный ¥, при котором маржа ≥ 18 % и ROI ≥ 60 % (схема am_fbs: налог 10 %, FBS РФ + ФФ 30 ₽, ДРР от заказов)."""
    from src import strategy as S
    from src.unit_econ import unit_economics
    cfg = S.econ_config()
    t = cfg["targets"]
    extra = S.cost_rub(0, kg, vol)[1]
    lo, hi = 0.0, float(price)
    for _ in range(40):
        mid = (lo + hi) / 2
        e = unit_economics(price, mid + extra, vol, cfg, with_breakeven=False, buyout_pct=buyout, commission_pct=comm,
                           ad_share_of_revenue_pct=drr, packaging_rub=S.PACK, fixed_per_unit_rub=ff)
        ok = e["net_margin_pct"] >= t["min_net_margin_pct"] and e["roi_on_goods_pct"] >= t["min_roi_on_cost_pct"]
        lo, hi = (mid, hi) if ok else (lo, mid)
    return round(lo / S.rub_per_yuan(), 1)


def score(vol: float = 0.8, kg: float = 0.35) -> list[dict]:
    from src import niche_v3 as V
    seas = {r["id"]: r for r in json.load(open("data/processed/all_niches_season_2026-10-11.json", encoding="utf-8"))}
    out = []
    for u in json.load(open(KEEP, encoding="utf-8")):
        p = V.p500_path(u["id"])
        if not p or SKIP.search(u["name"]):
            continue
        d = json.load(open(p, encoding="utf-8"))
        R = [x for x in (d.get("data", d) if isinstance(d, dict) else d) if isinstance(x, dict) and x.get("sales") and x.get("revenue")]
        if len(R) < 50:
            continue
        idx = seas.get(u["id"], {}).get("index", {})
        k = (idx.get("07") or 100) / 100
        tot = sum(x["revenue"] for x in R)
        B = [x for x in R if BAND[0] <= x["revenue"] / x["sales"] <= BAND[1]]
        if len(B) < 10:
            out.append({**u, "band_cards": len(B), "verdict": "мало карточек в полосе"})
            continue
        new = [x for x in B if NEW[0] <= (x.get("sku_first_date") or "") <= NEW[1]]
        lv = sorted(x["sales"] / 31 / k for x in new)
        q = lambda a: round(lv[min(len(lv) - 1, int(round(a * (len(lv) - 1))))], 1) if lv else None
        win = [x for x in new if x["sales"] / 31 / k >= 5]
        by_s = {}
        for x in B:
            by_s[x.get("seller")] = by_s.get(x.get("seller"), 0) + x["revenue"]
        price = st.median(x.get("final_price") or x["revenue"] / x["sales"] for x in B)
        buyout = R[0].get("purchase_after_return") or u["buyout"]
        comm = u["com"] or 25.0
        p50 = q(.5) or 0
        ff = 10000 / (p50 * 30 * buyout / 100) if p50 else 0
        o = {**u, "band_cards": len(B), "band_rev_pct": round(sum(x["revenue"] for x in B) / tot * 100, 1),
             "band_sales_day_med": round(st.median(x["sales"] / 31 for x in B), 1), "newcomers": len(new),
             "nc_p25": q(.25), "nc_p50": q(.5), "nc_p75": q(.75), "winners5": len(win), "winner_sellers": len({x.get("seller") for x in win}),
             "top1_band_pct": round(max(by_s.values()) / sum(by_s.values()) * 100, 1),
             "china_band_pct": round(sum(x["revenue"] for x in B if "кита" in str(x.get("country") or "").lower()) / max(1, sum(x["revenue"] for x in B)) * 100),
             "seller_price_med": round(price), "buyout_niche": buyout, "season_jul": idx.get("07"),
             "trough_pct": round(min(idx.values()) / max(idx.values()) * 100) if idx else None,
             "max_yuan_drr15": max_yuan(price, vol, kg, buyout, comm, 15, 0), "max_yuan_drr10": max_yuan(price, vol, kg, buyout, comm, 10, 0),
             "max_yuan_drr10_ff": max_yuan(price, vol, kg, buyout, comm, 10, ff) if ff else None,
             "examples": [{"id": x["id"], "name": x["name"][:60], "start": (x.get("sku_first_date") or "")[:10], "per_day": round(x["sales"] / 31 / k, 1),
                           "buyer": round(x["revenue"] / x["sales"]), "seller": x.get("seller"), "reviews": x.get("comments")}
                          for x in sorted(win, key=lambda x: -x["sales"])[:4]]}
        fails = []
        if (o["nc_p50"] or 0) < 4: fails.append("новичок P50 < 4/день")
        if o["newcomers"] < 5: fails.append("< 5 новичков в полосе")
        if o["top1_band_pct"] > 35: fails.append("top-1 > 35 % полосы")
        if o["winner_sellers"] < 3: fails.append("< 3 продавцов-победителей")
        o["fails"] = fails
        o["verdict"] = "✅" if not fails else "❌ " + "; ".join(fails)
        out.append(o)
    out.sort(key=lambda o: (bool(o.get("fails", ["x"])), -(o.get("nc_p50") or 0)))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", OUT)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    collect() if cmd == "collect" else score() if cmd == "score" else print(__doc__)
