"""Растущие товары WB по всем нишам (0 запросов): октябрь-2026 (2026-11-01/p500) против июля-2026 (v3_products500 / arena).

    python -m src.wb_risers [--min-price 1500] [--top 60]
Товар = карточка. «Растущий» = старт ≥ 2026-05-01 (без склейки), продажи в октябре ≥ 150 шт, и либо в июле её не было
в топ-500, либо продажи выросли ≥ ×1,5. Цена ≥ min-price (наша схема белого ввоза не работает на дешёвом).
Магниты исключены (по названию и флагам ниши); ЧЗ/документы — пометкой. → data/processed/wb_risers_2026-11-01.json
"""
from __future__ import annotations

import argparse, datetime as dt, json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")
from src.niche_v7 import P500, req, _load

OLD = ["data/raw/saleflow/v3_products500", ".arena/run-20261025-153238-s146793/scratch/a001/p500"]


def rows(p):
    d = json.load(open(p, encoding="utf-8"))
    return (d.get("data") if isinstance(d, dict) else d) or []


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--min-price", type=int, default=1500); ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()
    names = {k: v["name"] for k, v in _load("p*.json").items()}
    out = []
    for f in os.listdir(P500):
        if not f[:-5].isdigit():
            continue
        sid = int(f[:-5]); rq = req(sid, names.get(sid, ""))
        if "магнит" in rq["flags"].lower() or "запрет" in rq["verdict"]:
            continue
        old = next((f"{d}/{sid}.json" for d in OLD if os.path.exists(f"{d}/{sid}.json")), None)
        jul = {r["id"]: r for r in rows(old)} if old else {}
        for r in rows(f"{P500}/{f}"):
            p = r.get("final_price_average") or r.get("final_price") or 0
            s = r.get("sales") or 0
            st, fc = r.get("sku_first_date") or "", r.get("firstcommentdate") or ""
            if p < a.min_price or s < 150 or st < "2026-05-01" or (fc and fc < st[:7]) or re.search(r"магнит", r["name"], re.I):
                continue
            j = jul.get(r["id"]); js = (j or {}).get("sales") or 0
            if j and js and s < js * 1.5:
                continue
            out.append(dict(sid=sid, niche=names.get(sid, str(sid))[:45], id=r["id"], name=r["name"][:70], price=round(p), sales_oct=s, sales_jul=js,
                            rev_oct=r.get("revenue"), start=st, seller=(r.get("seller") or "")[:25], comments=r.get("comments"), rating=r.get("rating"),
                            country=r.get("country"), in_ads=None, docs=rq["docs"][:45], verdict=rq["verdict"][:25], has_jul=bool(old)))
    out.sort(key=lambda x: -(x["rev_oct"] or 0))
    json.dump(out, open("data/processed/wb_risers_2026-11-01.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"растущих карточек: {len(out)} в {len({x['sid'] for x in out})} нишах")
    for x in out[:a.top]:
        print(f"{x['id']} {x['price']}₽ окт {x['sales_oct']} (июль {x['sales_jul']}) {x['rev_oct']//1000}т ₽ старт {x['start'][:7]} ★{x['rating']}({x['comments']}) {x['country']} | {x['niche'][:30]} | {x['name'][:55]} | {x['verdict']}")


if __name__ == "__main__":
    main()
