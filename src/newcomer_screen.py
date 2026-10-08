"""Скрининг «сколько реально заработает новичок» (2026-10-07). Одна модель для всех ниш — та же, что в strategy_777/2486.

    python -m src.newcomer_screen collect --ids 2264 1126 … [--dry-run]   # products500 + price_segmentation июль + trends: 3 запроса/нишу
    python -m src.newcomer_screen rank --ids 777 2486 2264 1126 …          # 0 запросов → data/processed/newcomer_screen_2026-10-07.json

Для каждой ниши:
  полоса цены = полоса price_segmentation (июль) с max выручкой на продающую карточку (≥ 60 продающих карточек, ≥ 3% выручки);
  цена = середина полосы; ¥ = цена / 78 (правило пользователя); карго $2/кг сверх 0.5 кг по max(вес, 0.2 кг/л);
  спрос новичка = P25/P50 продаж/день новых карточек (старт 2025-10 … 2026-04) в products500 в полосе цена × 0.82 … 1.13,
  делённые на индекс сезона июля; форма разгона 50% → 90% → 90% → 90% → 100% (как у 777/2486);
  финплан = src.finplan.run (бюджет $2 000, партия до 300 шт, ДРР 25% → 15%, ФФ 10 000 ₽/мес), лучший месяц старта дек 2026 … мар 2027.
Гейты пользователя: маржа ≥ 18% и ROI ≥ 60% при медиане top-100, ≥ 150 шт/карточку, top-1 ≤ 25%, ≤ 2 кг (оплачиваемый вес), партия ≥ 200.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

from src.dna_rank import commissions, econ as econ78
from src.finplan import BUDGET_USD, START_COSTS, run, season_from, unit
from src.strategy import FX, R5, R6, R7, RUN, rows_of

sys.stdout.reconfigure(encoding="utf-8")
OUT = f"data/processed/newcomer_screen_{RUN}.json"
SHAPE = [0.5, 0.9, 0.9, 0.9] + [1.0] * 8
KG_PER_L, MAX_KG = 0.2, 2.0
LAUNCHES = ("2026-12", "2027-01", "2027-02", "2027-03")
SPECIAL = {
    777: {"p500": f"{R5}/dna/777/products500_2026-07.json", "seg": f"{R6}/strategy777/price_seg_2026-07.json",
          "trends": f"{R7}/strategy777/trends_month.json", "top": f"{R5}/dna/777/top100/top100_products_2026-07.json"},
    2486: {"p500": f"{R7}/strategy2486/products500_2026-07.json", "seg": f"{R7}/strategy2486/price_seg_2026-07.json",
           "trends": f"{R7}/strategy2486/trends_month.json", "top": f"{R7}/strategy2486/top100/top100_products_2026-07.json"},
}


def paths(n: int) -> dict:
    if n in SPECIAL:
        return SPECIAL[n]
    d = f"{R7}/newcomer/{n}"
    top = next((f for f in (f"{R6}/fresh/products_{n}_2026-07.json", f"{R7}/fresh2kg/products_{n}_2026-07.json") if os.path.exists(f)), None)
    p500 = f"{d}/products500_2026-07.json"
    return {"p500": p500, "seg": f"{d}/price_seg_2026-07.json", "trends": f"{d}/trends_month.json", "top": top or p500}   # top-100 = первые 100 из 500


def load(p):
    return json.load(open(p, encoding="utf-8"))


def collect(ids: list[int], dry: bool) -> None:
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch, quota
    todo = []
    for n in ids:
        P = paths(n)
        jul = {"subject_id": n, "d1": "2026-07-01", "d2": "2026-07-31"}
        for key, args in (("p500", {**jul, "report": "products", "limit": 500}), ("seg", {**jul, "report": "price_segmentation"}),
                          ("trends", {"subject_id": n, "report": "trends", "d1": "2024-09-01", "d2": "2026-09-30", "group_by": "month"})):
            if not os.path.exists(P[key]):
                todo.append((P[key], args))
    print(f"новых файлов {len(todo)} = запросов к квоте Saleflow {len(todo)}")
    if dry or not todo:
        return
    c = Client()
    streak, fails = 0, []
    try:
        print("квота до:", quota(c), flush=True)
        for i, (path, args) in enumerate(todo, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                json.dump(fetch(c, "wb_subject", args), open(path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{i}/{len(todo)}] → {path}", flush=True)
                streak = 0
            except Exception as e:                          # noqa: BLE001 — upstream нестабилен
                print(f"[{i}/{len(todo)}] {args['subject_id']} {args['report']}: {str(e)[:120]}", flush=True)
                fails.append(path)
                streak += 1
                if "закрылся" in str(e):
                    c = Client()
                if streak >= 3:
                    print("3 сбоя подряд — стоп")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()
    print("не скачано:", fails)


def q(vals: list[float], p: float):
    v = sorted(vals)
    return round(v[min(len(v) - 1, int(round(p * (len(v) - 1))))], 1) if v else None


def evaluate(n: int, com: dict, override: dict | None = None, band_pick: dict | None = None) -> dict | None:
    """override = {'vol': л, 'kg': кг} — оценка по карточкам, когда WB скрывает габариты."""
    P = paths(n)
    if not all(P[k] and os.path.exists(P[k]) for k in ("p500", "seg", "trends", "top")):
        return None
    t = {r["label_date"]: r for r in rows_of(load(P["trends"]))}
    months = [m for m in sorted(t) if "2024-09" <= m <= "2026-07"]
    mean_all = st.mean(t[m]["sales"] for m in months) or 1
    by = {}
    for m in months:
        by.setdefault(m[5:], []).append(t[m]["sales"])
    season = {mm: max(1, round(st.mean(v) / mean_all * 100)) for mm, v in sorted(by.items())}
    peak = max(season, key=season.get)
    trough = min(season, key=season.get)
    y12 = sum(t[m]["sales"] for m in sorted(t) if "2025-08" <= m <= "2026-07")
    y12p = sum(t[m]["sales"] for m in sorted(t) if "2024-08" <= m <= "2025-07")
    top = sorted(rows_of(load(P["top"])), key=lambda p: -(p.get("revenue") or 0))[:100]
    name = top[0].get("subject") if top else str(n)
    tot = sum(p.get("revenue") or 0 for p in top) or 1
    by_s: dict = {}
    for p in top:
        by_s[p.get("supplier_id") or p.get("seller")] = by_s.get(p.get("supplier_id") or p.get("seller"), 0) + (p.get("revenue") or 0)
    t1 = round(max(by_s.values()) / tot * 100, 1)
    med_price = st.median(p["final_price"] for p in top if p.get("final_price"))
    spp = st.median((1 - p["revenue"] / p["sales"] / p["final_price"]) * 100 for p in top if p.get("sales") and p.get("final_price"))
    buyout = st.median(p.get("purchase_after_return") or 80 for p in top)
    sales_med = st.median((p.get("sales_estimated") or p.get("sales") or 0) for p in top)
    vols = [(p.get("package_length") or 0) * (p.get("package_width") or 0) * (p.get("package_height") or 0) / 1000 for p in top]
    vols = [v for v in vols if v > 0]
    vol = round(st.median(vols), 2) if len(vols) >= 10 else None
    c = com.get(n)
    if c is None:
        return None
    segs = rows_of(load(P["seg"]))
    rev_tot = sum(s["revenue"] for s in segs) or 1
    ok = [s for s in segs if s["items_with_sells"] >= 60 and s["revenue"] / rev_tot >= 0.03 and s["max_range_price"] < 50000]
    if not ok:
        return None
    best = band_pick or max(ok, key=lambda s: s["revenue"] / s["items_with_sells"])   # band_pick — перебор полос (sweep)
    price = round((best["min_range_price"] + best["max_range_price"]) / 2)
    R = rows_of(load(P["p500"]))
    newc = [p for p in R if "2025-10-01" <= (p.get("sku_first_date") or "") <= "2026-04-30"]
    k = season["07"] / 100
    lv, wide = None, False
    for lo, hi in ((0.82, 1.13), (0.7, 1.3)):
        band = [(p.get("sales") or 0) / 31 / k for p in newc if lo * price <= (p.get("final_price") or 0) < hi * price]
        if len(band) >= 8:
            lv = band
            wide = lo == 0.7
            break
    v_eff = vol if vol is not None else 0.5
    kg = max(v_eff * KG_PER_L, 0.3)
    if override:
        v_eff = override["vol"]
        kg = max(override["kg"], v_eff * KG_PER_L)
        vol = v_eff
    yuan = round(price / 78, 1)
    prod = {"price": price, "yuan": yuan, "vol": v_eff, "kg": kg, "buyout": buyout, "commission": c}
    goods = unit(prod, 15.0, price)["goods"]
    room = BUDGET_USD * FX - sum(START_COSTS.values()) - 15000          # резерв ≥ 15 000 ₽
    batch = min(300, int(room / goods // 50 * 50))
    e_med = econ78(med_price, spp, v_eff, buyout, c)
    base = unit(prod, 15.0, price)
    res = {"id": n, "name": name, "commission": c, "buyout": buyout, "spp_real": round(spp, 1), "top1": t1,
           "sales_med_top100": sales_med, "med_price": med_price, "vol": vol, "kg_billable": round(kg, 2),
           "season": season, "peak": peak, "trough_pct": round(season[trough] / season[peak] * 100),
           "yoy_12m": round((y12 / y12p - 1) * 100, 1) if y12p else None, "rev_12m": sum(t[m]["revenue"] for m in sorted(t)
                                                                                         if "2025-08" <= m <= "2026-07"),
           "band": best["range"], "band_iws": best["items_with_sells"], "band_rev_per_iws": round(best["revenue"] / best["items_with_sells"]),
           "price": price, "yuan": yuan, "profit_unit": round(base["profit"]), "goods": round(goods), "batch": batch,
           "n_new": len(lv) if lv else 0, "wide_band": wide, "p25": q(lv, 0.25) if lv else None, "p50": q(lv, 0.5) if lv else None,
           "margin_med": e_med["margin"], "roi_med": e_med["roi"]}
    res["gates"] = {"маржа при медиане": e_med["margin"] >= 18 and e_med["roi"] >= 60, "≥150 шт/карт": sales_med >= 150,
                    "top-1 ≤ 25%": t1 <= 25, "≤ 2 кг": None if vol is None else kg <= MAX_KG, "партия ≥ 200": batch >= 200}
    if lv and batch >= 100:
        best_run = None
        for start in LAUNCHES:
            sea = season_from(season, start)
            r50 = run("p50", prod, [res["p50"] * s for s in SHAPE], sea, batch)
            if best_run is None or r50["rows"][-1]["cum_profit"] > best_run[1]["rows"][-1]["cum_profit"]:
                best_run = (start, r50, sea)
        start, r50, sea = best_run
        r25 = run("p25", prod, [res["p25"] * s for s in SHAPE], sea, batch)
        rspp = run("spp", prod, [res["p50"] * s for s in SHAPE], sea, batch, price * (1 - spp / 100))
        res.update({"launch": start, "invest": r50["invest"], "profit12_p50": r50["rows"][-1]["cum_profit"],
                    "payback_p50": r50["payback"], "roi12_p50": r50["roi"][12], "profit12_p25": r25["rows"][-1]["cum_profit"],
                    "profit12_spp": rspp["rows"][-1]["cum_profit"], "roi12_spp": rspp["roi"][12], "min_cash_p50": r50["min_cash"]})
    res["fails"] = [g for g, v in res["gates"].items() if v is False]
    return res


def sweep(n: int, com: dict, override: dict | None = None) -> list[dict]:
    """Все полосы (≥ 60 продающих карточек, ≥ 3% выручки) → прибыль 12 мес. P50 новичка в каждой."""
    P = paths(n)
    segs = rows_of(load(P["seg"]))
    tot = sum(s["revenue"] for s in segs) or 1
    out = []
    for s in segs:
        if s["items_with_sells"] >= 60 and s["revenue"] / tot >= 0.03 and s["max_range_price"] < 50000:
            r = evaluate(n, com, override, s)
            if r and r.get("profit12_p50") is not None:
                out.append(r)
    return sorted(out, key=lambda r: -r["profit12_p50"])


def rank(ids: list[int], overrides: dict | None = None, out_path: str = OUT) -> None:
    com = commissions()
    overrides = overrides or {}
    out = [r for r in (evaluate(n, com, overrides.get(n)) for n in ids) if r]
    for r in out:
        r["override"] = overrides.get(r["id"])
    out.sort(key=lambda r: -(r.get("profit12_p50") or -1e9))
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    f = lambda v: "—" if v is None else f"{v:,.0f}".replace(",", " ")
    print("| id | Ниша | Полоса (выручка/прод. карт.) | Цена до СПП | ¥ | Прибыль/шт | Новичок P25/P50 шт/день (n) | Старт | "
          "Прибыль 12 мес P50 | P25 | СПП-сцен. | Окуп. | top-1 | шт/карт | маржа при медиане | кг | Не прошла |")
    print("|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in out:
        print(f"| {r['id']} | {str(r['name'])[:28]} | {r['band']} ({f(r['band_rev_per_iws'])}) | {f(r['price'])} | {r['yuan']} | "
              f"{f(r['profit_unit'])} | {r['p25']}/{r['p50']} ({r['n_new']}{'*' if r['wide_band'] else ''}) | {r.get('launch', '—')} | "
              f"{f(r.get('profit12_p50'))} | {f(r.get('profit12_p25'))} | {f(r.get('profit12_spp'))} | {r.get('payback_p50') or '—'} | "
              f"{r['top1']} | {f(r['sales_med_top100'])} | {r['margin_med']} | {r['kg_billable']}{'' if r['vol'] else '?'} | "
              f"{', '.join(r['fails']) or '✅'} |")
    print(f"saved {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "rank"])
    ap.add_argument("--ids", type=int, nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--override", nargs="*", default=[], help="id:объём_л:вес_кг — оценка по карточкам")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    ov = {int(x.split(":")[0]): {"vol": float(x.split(":")[1]), "kg": float(x.split(":")[2])} for x in a.override}
    collect(a.ids, a.dry_run) if a.cmd == "collect" else rank(a.ids, ov, a.out)


if __name__ == "__main__":
    main()
