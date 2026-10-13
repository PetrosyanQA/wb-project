"""Глубокий разбор пары 2486 «Катушки» + 729 «Поводки (рулетки)» «всеми механизмами» (2026-10-11). 0 запросов.

    python -m src.deep_pair            # → data/processed/deep_pair_2026-10-11.json + reports/deep_pair_2026-10-11.xlsx
    python -m src.deep_pair plans      # варианты товара → экономика + финплан → data/processed/deep_pair_plans_2026-10-11.json

Что собирает в одном месте (все входы уже на диске):
  strategy  — src.strategy.build: рынок, сезон, YoY двумя углами, top-20, запросы, цены, контент, жалобы, барьеры,
              концентрация, траектории новичков, сегменты; экономика — по ФАКТ-тарифу FBS «Свой склад РФ» (WB API).
  ladder    — ценовая лестница products500 июля: карточки / продажи / выручка на карточку / новички по полосам цены.
  segment   — внутри нашего сегмента: лидеры, их цена, отзывы, доля, кто новичок.
  algo      — «алгоритм WB» только на карточках ниши (src.wb_algo: драйверы позиции/продаж, кривые реакции, новинка,
              изменения по месяцам, часы продаж).
  launch    — победители vs слабые новички ниши (src.launch_patterns: 2486 — выборка 2026-10-08, 729 — 2026-10-11).
  stories   — 5 лучших новичков top-100 (старт ≥ 2025-06): путь по неделям 1–12 (продажи, цена, реклама, отзывы, позиция).
Окно дневных данных ≤ 2026-07-31 (дальше Saleflow неполный).
"""
from __future__ import annotations

import collections
import copy
import datetime as dt
import json
import os
import statistics as st
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from src import strategy as S
from src.outliers import clean_items

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-11"
OUT = f"data/processed/deep_pair_{RUN}.json"
XLSX = f"reports/deep_pair_{RUN}.xlsx"
CUT = "2026-07-31"
NICHES = (2486, 729)
# [факт] WB API /api/v1/tariffs/box, кэш data/cache_wb (2026-10-11): «Свой склад РФ» — FBS 78,2 ₽ за 1-й литр, 23,8 ₽ за
# каждый следующий; хранения у WB нет (товар лежит у фулфилмента — его минимум 10 000 ₽/мес в FIXED).
FBS_RF = {"base": 78.2, "liter": 23.8}
LAUNCH = {2486: "data/processed/launch_patterns_2026-10-08.json", 729: "data/processed/launch_patterns_2026-10-11.json"}
STEP = {2486: 200, 729: 100, 2499: 500}                     # шаг ценовой лестницы, ₽ (цена покупателя)


def med(xs, nd=1):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), nd) if xs else None


def fbs_config(base_cfg: dict) -> dict:
    cfg = copy.deepcopy(base_cfg)
    lg = cfg["logistics"]
    lg["tiers_under_1l"] = {k: FBS_RF["base"] for k in lg.get("tiers_under_1l", {0.2: 0, 0.4: 0, 0.6: 0, 0.8: 0, 1.0: 0})}
    lg["first_liter_over_1l"], lg["extra_liter"], lg["warehouse_coef"] = FBS_RF["base"], FBS_RF["liter"], 1.0
    cfg["storage"]["per_liter_per_day"], cfg["storage"]["warehouse_coef"] = 0.0, 1.0
    cfg["_tariffs_source"] = "WB API tariffs/box: «Свой склад РФ» (FBS) 78,2 ₽ + 23,8 ₽/л; хранение у фулфилмента"
    return cfg


# ── ценовая лестница ───────────────────────────────────────────────────────────────────────────────────────────
def ladder(P: dict, niche: int) -> dict:
    R = [p for p in S.rows_of(S.load(P["products500"])) if p.get("final_price") and p.get("sales")]
    R, rep = clean_items(R, S.filters_cfg(), expected_subject=R[0].get("subject_id"))
    step = STEP[niche]
    B = collections.defaultdict(list)
    for p in R:
        bp = p["revenue"] / p["sales"]
        B[int(bp // step) * step].append(p)
    rows = []
    for lo in sorted(B):
        L = B[lo]
        new = [p for p in L if (p.get("sku_first_date") or "") >= "2025-10-01"]
        rows.append({"buyer_from": lo, "buyer_to": lo + step, "cards": len(L), "sales": sum(p["sales"] for p in L),
                     "rev_mln": round(sum(p["revenue"] for p in L) / 1e6, 2),
                     "rev_per_card": round(sum(p["revenue"] for p in L) / len(L)),
                     "sales_per_card_day": round(sum(p["sales"] for p in L) / len(L) / 31, 1),
                     "seller_price_med": med([p["final_price"] for p in L], 0),
                     "new_cards": len(new), "new_sales_day_med": med([p["sales"] / 31 for p in new]),
                     "rating_med": med([p.get("rating") for p in L], 2), "reviews_med": med([p.get("comments") for p in L], 0)})
    return {"step": step, "kept": rep["kept"], "dropped_pct": rep["dropped_pct"], "rows": rows}


# ── наш сегмент ────────────────────────────────────────────────────────────────────────────────────────────────
def segment_view(P: dict) -> dict:
    T = S.top100_rows(P)
    seg = [c for c in T if c.get("segment") == P["our_segment"]]
    by_seller = collections.Counter()
    for c in seg:
        by_seller[c["seller"]] += c["revenue_jul"]
    tot = sum(by_seller.values()) or 1
    return {"segment": P["our_segment"], "cards": len(seg),
            "rev_share_top100": round(tot / sum(c["revenue_jul"] for c in T) * 100, 1),
            "sellers": [(s, round(v / tot * 100, 1)) for s, v in by_seller.most_common(8)],
            "leaders": [{k: c.get(k) for k in ("rank", "id", "name", "seller", "price_jul", "buyer_price", "sales_jul_products",
                                                "rating", "comments", "start", "ads_pct", "promo_pct", "oos_days", "pos_med",
                                                "length_m", "max_kg", "size", "bearings")} for c in seg[:12]],
            "buyer_price_med": med([c["buyer_price"] for c in seg], 0), "seller_price_med": med([c["price_jul"] for c in seg], 0),
            "reviews_med": med([c["comments"] for c in seg], 0), "rating_med": med([c["rating"] for c in seg], 2),
            "ads_med": med([c.get("ads_pct") for c in seg], 0), "new_cards": sum(1 for c in seg if (c["start"] or "") >= "2025-10-01")}


# ── алгоритм WB на карточках ниши ─────────────────────────────────────────────────────────────────────────────
def algo(niche: int, P: dict) -> dict:
    from src import wb_algo as A
    ids = {c["id"] for c in S.top100_rows(P)}
    panel = {k: v for k, v in A.panel().items() if v["niche"] == niche or k in ids}
    for v in panel.values():
        v["niche"] = niche
    if len(panel) < 10:
        return {"error": f"мало рядов: {len(panel)}"}
    return {"cards": len(panel), "card_days": sum(len(v["rows"]) for v in panel.values()), "drivers": A.drivers(panel),
            "response": A.response(panel), "novelty": A.novelty(panel), "changes": A.changes(panel), "hours": A.hours(panel)}


# ── победители vs слабые новички ─────────────────────────────────────────────────────────────────────────────
def launch(niche: int) -> dict:
    f = LAUNCH[niche]
    if not os.path.exists(f):
        return {"error": f"нет {f}"}
    C = [c for c in json.load(open(f, encoding="utf-8")) if c["niche"] == niche]
    out = {}
    for g in ("win", "mid", "ctl"):
        G = [c for c in C if c["group"] == g]
        if not G:
            continue
        wk = {}
        for k in (1, 2, 3, 4, 6, 8, 12):
            W = [c["weeks"][k - 1] for c in G if len(c["weeks"]) >= k]
            wk[k] = {f: med([w[f] for w in W]) for f in ("sales", "price", "ads", "promo", "reviews", "pos", "words", "oos")}
            wk[k]["n"] = len(W)
        out[g] = {"n": len(G), "weeks": wk, "launch_types": collections.Counter(c["launch"] for c in G).most_common(),
                  "start_months": collections.Counter(c["start_month"] for c in G).most_common(),
                  "days_to_10_reviews": med([c["days_to"].get("10") or c["days_to"].get(10) for c in G], 0),
                  "days_to_50_reviews": med([c["days_to"].get("50") or c["days_to"].get(50) for c in G], 0),
                  "jul_per_day": med([c["jul_per_day"] for c in G]),
                  "price_vs_p50": med([c["weeks"][0]["price"] / c["niche_p50"] for c in G if c["weeks"] and c["weeks"][0]["price"]
                                       and c.get("niche_p50")], 2),
                  "cards": [{"id": c["id"], "name": c["name"][:60], "seller": c["seller"], "start": c["start"], "launch": c["launch"],
                             "jul_per_day": c["jul_per_day"], "w1": c["weeks"][0] if c["weeks"] else None} for c in G]}
    return out


# ── истории лучших новичков top-100 ─────────────────────────────────────────────────────────────────────────
def stories(P: dict, n: int = 6) -> list[dict]:
    T = [c for c in S.top100_rows(P) if (c.get("start") or "") >= "2025-06-01"]
    out = []
    for c in T:
        d = [r for r in S.daily_of(P, c["id"]) if r["data"] <= CUT]
        first = next((i for i, r in enumerate(d) if (r.get("sales") or 0) > 0), None)
        if first is None or d[0]["data"] > c["start"][:10]:
            continue                                       # ряд не покрывает старт
        W = []
        for k in range(12):
            w = d[first + 7 * k: first + 7 * k + 7]
            if len(w) < 7:
                break
            W.append({"wk": k + 1, "sales": round(st.mean(r.get("sales") or 0 for r in w), 1),
                      "price": med([r.get("final_price") for r in w], 0), "ads": round(sum(1 for r in w if r.get("in_ads")) / 7 * 100),
                      "promo": round(sum(1 for r in w if r.get("in_action")) / 7 * 100), "reviews": w[-1].get("comments"),
                      "pos": med([r.get("search_position_avg") for r in w], 0), "words": med([r.get("search_words_count") for r in w], 0),
                      "oos": sum(1 for r in w if not r.get("balance"))})
        out.append({"id": c["id"], "name": c["name"], "seller": c["seller"], "segment": c.get("segment"), "start": c["start"][:10],
                    "first_sale": d[first]["data"], "reviews_day0": d[first].get("comments"), "jul_sales": c["sales_jul_products"],
                    "buyer_price": c["buyer_price"], "weeks": W})
        if len(out) >= n:
            break
    return out


def build_niche(niche: int) -> dict:
    P = S.PRESETS[niche]
    base = S.load_config
    S.load_config = lambda: fbs_config(base())           # экономика по факт-тарифу FBS РФ
    try:
        D = S.build(niche)
    finally:
        S.load_config = base
    D["econ_basis"] = fbs_config(base())["_tariffs_source"]
    D["ladder"] = ladder(P, niche)
    D["segment_view"] = segment_view(P)
    D["algo"] = algo(niche, P)
    D["launch"] = launch(niche)
    D["stories"] = stories(P)
    return D


def write_xlsx(res: dict) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    hdr = lambda ws: [setattr(c, "font", Font(bold=True, color="FFFFFF")) or setattr(c, "fill", PatternFill("solid", fgColor="305496"))
                      or setattr(c, "alignment", Alignment(wrap_text=True)) for c in ws[1]]
    for n, D in res.items():
        ws = wb.create_sheet(f"{n} лестница цен")
        ws.append(["Цена покуп. от ₽", "до ₽", "Карточек", "Продажи июль", "Выручка млн ₽", "Выручка/карт. ₽", "Шт/день на карт.",
                   "Цена до СПП (мед.)", "Новичков", "Новичок шт/день (мед.)", "Рейтинг", "Отзывы"])
        for r in D["ladder"]["rows"]:
            ws.append([r["buyer_from"], r["buyer_to"], r["cards"], r["sales"], r["rev_mln"], r["rev_per_card"], r["sales_per_card_day"],
                       r["seller_price_med"], r["new_cards"], r["new_sales_day_med"], r["rating_med"], r["reviews_med"]])
        hdr(ws)
        ws = wb.create_sheet(f"{n} истории новичков")
        ws.append(["Артикул", "Название", "Продавец", "Старт", "Неделя", "Шт/день", "Цена покуп.", "Реклама %", "Акция %", "Отзывы",
                   "Позиция", "Запросов", "Дней без остатка"])
        for s in D["stories"]:
            for w in s["weeks"]:
                ws.append([s["id"], s["name"][:50], s["seller"], s["first_sale"], w["wk"], w["sales"], w["price"], w["ads"], w["promo"],
                           w["reviews"], w["pos"], w["words"], w["oos"]])
        hdr(ws)
        L = D["launch"]
        if "error" not in L:
            ws = wb.create_sheet(f"{n} победители vs слабые")
            ws.append(["Группа", "Неделя", "n", "Шт/день", "Цена покуп.", "Реклама %", "Акция %", "Отзывы", "Позиция", "Запросов", "Без остатка"])
            for g, G in L.items():
                for k, w in G["weeks"].items():
                    ws.append([g, k, w["n"], w["sales"], w["price"], w["ads"], w["promo"], w["reviews"], w["pos"], w["words"], w["oos"]])
            hdr(ws)
    wb.save(XLSX)


# ── варианты товара: экономика + финплан (src.finplan с факт-тарифом FBS РФ) ─────────────────────────────────
VARIANTS = {   # ¥ — допущение до КП; объём/вес — оценка по аналогам (у карточек WB нет габаритов упаковки)
    729: [{"key": "729-A", "name": "рулетка 8 м, лента, до 50 кг", "price": 1700, "yuan": 20, "vol": 1.2, "kg": 0.45},
          {"key": "729-B", "name": "рулетка 5 м, лента, до 30 кг", "price": 1100, "yuan": 12, "vol": 0.9, "kg": 0.32}],
    2486: [{"key": "2486-A", "name": "катушка 3000, металл. шпуля, 5+1 подш., ручка на резьбе", "price": 1590, "yuan": 20, "vol": 1.8, "kg": 0.45},
           {"key": "2486-B", "name": "катушка 3000 «народная» (покупатель ≈ 1 000–1 100 ₽)", "price": 1240, "yuan": 15, "vol": 1.8, "kg": 0.42}],
}
BUYOUT = {729: 75.0, 2486: 79.0}          # [факт] медиана выкупа top-100 (products, июль 2026)
COMMISSION = {729: 15.0, 2486: 21.0}      # [факт] WB API кабинета, kgvpMarketplace (FBS)
SPP = {729: 9.6, 2486: 15.4}              # [факт] реализованная СПП top-100 = 1 − выручка/шт / цена до СПП
START = {729: "2027-02", 2486: "2027-03"}


def plans() -> dict:
    from src import finplan as F
    base = F.load_config
    F.load_config = lambda: fbs_config(base())
    sbase = S.load_config
    S.load_config = lambda: fbs_config(sbase())
    out = {}
    try:
        for n, V in VARIANTS.items():
            D = json.load(open(f"data/processed/strategy_{n}_{RUN}.json", encoding="utf-8"))
            P = S.PRESETS[n]
            season_idx = D["overview"]["season_index"]
            for v in V:
                prod = {**v, "buyout": BUYOUT[n], "commission": COMMISSION[n], "buyer_price": round(v["price"] * (1 - SPP[n] / 100))}
                curves = {**D["entry_curves"], "percentiles": {int(k): x for k, x in D["entry_curves"]["percentiles"].items()}}   # JSON → int
                L = S.newcomer_levels(P, season_idx, curves, (v["price"] * 0.82, v["price"] * 1.13))
                season = F.season_from(season_idx, START[n])
                batch = F.fit_batch(prod)
                dem = lambda lvl: [round(lvl * L["shape"][k], 2) for k in range(12)]
                scen = {"пессимистичный": L["p25"], "реалистичный": L["p50"], "оптимистичный": L["winners_plateau_p50"]}
                runs = {k: F.run(k, prod, dem(x), season, batch) for k, x in scen.items() if x}
                out[v["key"]] = {"niche": n, "product": prod, "levels": L, "batch": batch, "start": START[n], "econ": S.econ(P, prod),
                                 "runs": {k: {kk: r[kk] for kk in ("invest", "budget", "payback", "roi", "min_cash", "lost_units", "rows",
                                                                  "unit_base", "unit_launch", "start")} for k, r in runs.items()}}
                r = runs.get("реалистичный")
                print(f"{v['key']} {v['name']}: партия {batch}, уровни P25/P50/побед. {L['p25']}/{L['p50']}/{L['winners_plateau_p50']} "
                      f"(n={L['n_new_top500']}), окупаемость P50 {r and r['payback']}, ROI {r and r['roi']}, мин. деньги {r and r['min_cash']}")
    finally:
        F.load_config, S.load_config = base, sbase
    json.dump(out, open(f"data/processed/deep_pair_plans_{RUN}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    return out


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "plans":
        plans()
        return
    res = {}
    for n in NICHES:
        res[n] = build_niche(n)
        json.dump(res[n], open(f"data/processed/strategy_{n}_{RUN}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        print(f"{n}: готово")
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    write_xlsx(res)
    print("→", OUT, XLSX)


if __name__ == "__main__":
    main()
