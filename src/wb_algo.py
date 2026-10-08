"""«Алгоритм WB» по дневным рядам всех сохранённых карточек (2026-10-08). 0 запросов.

    python -m src.wb_algo        # → wb_algorithm/data/*.json + wb_algorithm/wb_algorithm_data_2026-10-08.xlsx

Что считается (только дни с остатком, окно ≤ 2026-07-31 — август–сентябрь в Saleflow неполные):
  1. drivers   — регрессия с фиксированным эффектом карточки (внутри карточки):
                 log(позиция) и log(1+продажи) ~ реклама, акция, log(цена покупателя), log(1+отзывы вчера), рейтинг,
                 log(1+продажи за 7 дн. до), склады, флаг «новинка». Плюс знаки по каждой нише отдельно (устойчивость).
  2. response  — кривая реакции позиции и продаж по дням −7…+14 вокруг: вкл./выкл. рекламы, вкл./выкл. акции,
                 цена −10% / +10%, возврат после дефектуры.
  3. novelty   — сколько дней карточка с флагом is_new и что происходит после его снятия.
  4. changes   — что менялось в WB по месяцам: комиссия FBS/FBO (для продавцов РФ), доля дней с рекламой и акциями,
                 доля поисковых запросов «из рекламы», скидка продавца, склады, внешняя реклама (adv_stats).
  5. hours     — часы пиковых продаж (top_hours).
Источник рядов — каталог (src.datastore): все kind=daily, по SKU берётся самый длинный ряд.
"""
from __future__ import annotations

import collections
import json
import math
import os
import statistics as st
import sys

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from src.datastore import catalog, rows

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-08"
CUT = "2026-07-31"
OUT = "wb_algorithm/data"
XLSX = f"wb_algorithm/wb_algorithm_data_{RUN}.xlsx"


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 3) if xs else None


def panel() -> dict[int, dict]:
    """sku → {'niche', 'rows'}; самый длинный ряд по SKU."""
    best: dict[int, dict] = {}
    for c in catalog():
        if c["kind"] != "daily" or not c["sku"]:
            continue
        R = [r for r in rows(c["path"]) if isinstance(r, dict) and r.get("data") and r["data"] <= CUT]
        if len(R) > len(best.get(c["sku"], {}).get("rows", [])):
            best[c["sku"]] = {"niche": c["niche"], "rows": sorted(R, key=lambda r: r["data"])}
    return {k: v for k, v in best.items() if len(v["rows"]) >= 30}


# ── 1. Драйверы: OLS с фиксированным эффектом карточки (demeaning), без numpy ──────────────────────────────
def ols(X: list[list[float]], y: list[float]) -> list[float] | None:
    k = len(X[0])
    A = [[sum(X[i][a] * X[i][b] for i in range(len(X))) for b in range(k)] for a in range(k)]
    v = [sum(X[i][a] * y[i] for i in range(len(X))) for a in range(k)]
    for col in range(k):                                   # Гаусс с выбором главного элемента
        piv = max(range(col, k), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-9:
            return None
        A[col], A[piv], v[col], v[piv] = A[piv], A[col], v[piv], v[col]
        for r in range(k):
            if r != col:
                f = A[r][col] / A[col][col]
                A[r] = [A[r][j] - f * A[col][j] for j in range(k)]
                v[r] -= f * v[col]
    return [v[i] / A[i][i] for i in range(k)]


FEATS = ["реклама (in_ads)", "акция (in_action)", "log цена покупателя", "log(1+отзывы вчера)", "рейтинг вчера",
         "log(1+продажи 7 дн. до)", "склады", "флаг новинки"]


def design(R: list[dict]):
    out = []
    for t in range(7, len(R)):
        r, p = R[t], R[t - 1]
        if not r.get("balance") or not r.get("search_position_avg") or not r.get("final_price"):
            continue
        rating = p.get("commentsvaluation") or p.get("rating") or 0
        x = [1.0 if r.get("in_ads") else 0.0, 1.0 if r.get("in_action") else 0.0, math.log(r["final_price"]),
             math.log1p(p.get("comments") or 0), float(rating), math.log1p(st.mean([q.get("sales") or 0 for q in R[t - 7:t]])),
             float(r.get("warehouses_count") or 0), 1.0 if r.get("is_new") else 0.0]
        out.append((x, math.log(r["search_position_avg"]), math.log1p(r.get("sales") or 0)))
    return out


def demean(block):
    if len(block) < 20:
        return []
    k = len(block[0][0])
    mx = [st.mean(b[0][j] for b in block) for j in range(k)]
    m1, m2 = st.mean(b[1] for b in block), st.mean(b[2] for b in block)
    return [([b[0][j] - mx[j] for j in range(k)], b[1] - m1, b[2] - m2) for b in block]


def drivers(P: dict) -> dict:
    by_niche = collections.defaultdict(list)
    for sku, v in P.items():
        by_niche[v["niche"]] += demean(design(v["rows"]))
    allrows = [x for L in by_niche.values() for x in L]
    res = {"n_obs": len(allrows), "n_cards": len(P)}
    for name, idx in (("log_position", 1), ("log1p_sales", 2)):
        b = ols([r[0] for r in allrows], [r[idx] for r in allrows])
        res[name] = {f: round(c, 4) for f, c in zip(FEATS, b)} if b else None
        signs = {}
        for n, L in by_niche.items():
            if len(L) >= 500:
                bn = ols([r[0] for r in L], [r[idx] for r in L])
                if bn:
                    signs[str(n)] = {f: round(c, 4) for f, c in zip(FEATS, bn)}
        res[name + "_by_niche"] = signs
        if b:
            res[name + "_same_sign_pct"] = {f: round(sum(1 for s in signs.values() if (s[f] > 0) == (b[j] > 0)) / len(signs) * 100) if signs else None
                                             for j, f in enumerate(FEATS)}
    return res


# ── 2. Кривые реакции ─────────────────────────────────────────────────────────────────────────────────────
def response(P: dict) -> dict:
    curves = collections.defaultdict(lambda: collections.defaultdict(lambda: {"pos": [], "sales": []}))
    for v in P.values():
        R = v["rows"]
        s = [r.get("sales") or 0 for r in R]
        pos = [r.get("search_position_avg") for r in R]
        last = collections.defaultdict(lambda: -99)
        for t in range(8, len(R) - 15):
            ev = []
            for flag, on, off in (("in_ads", "реклама ВКЛ", "реклама ВЫКЛ"), ("in_action", "акция ВКЛ", "акция ВЫКЛ")):
                prev7 = [bool(R[i].get(flag)) for i in range(t - 7, t)]
                next7 = [bool(R[i].get(flag)) for i in range(t, t + 7)]
                if not any(prev7) and all(next7):
                    ev.append(on)
                if all(prev7) and not any(next7):
                    ev.append(off)
            p0 = [r.get("final_price") for r in R[t - 7:t] if r.get("final_price")]
            p1 = [r.get("final_price") for r in R[t:t + 7] if r.get("final_price")]
            if p0 and p1:
                if st.median(p1) <= 0.9 * st.median(p0):
                    ev.append("цена −10%")
                elif st.median(p1) >= 1.1 * st.median(p0):
                    ev.append("цена +10%")
            if not R[t - 1].get("balance") and all(R[i].get("balance") for i in range(t, t + 14)):
                k = t - 1
                while k > 0 and not R[k].get("balance"):
                    k -= 1
                if t - 1 - k >= 3 and k >= 7:
                    ev.append("возврат после дефектуры ≥3 дн.")
            for e in ev:
                if t - last[e] < 21:
                    continue
                if e != "возврат после дефектуры ≥3 дн." and not all(R[i].get("balance") for i in range(t - 7, t + 15)):
                    continue
                last[e] = t
                base_t = t if e != "возврат после дефектуры ≥3 дн." else k + 1
                bs = st.mean(s[base_t - 7:base_t]) if base_t >= 7 else None
                bp = [x for x in pos[base_t - 7:base_t] if x]
                if not bs or not bp:
                    continue
                bp = st.median(bp)
                for d in range(-7, 15):
                    curves[e][d]["sales"].append(s[t + d] / bs)
                    if pos[t + d]:
                        curves[e][d]["pos"].append(pos[t + d] / bp)
    out = {}
    for e, D in curves.items():
        n = len(D[0]["sales"])
        out[e] = {"n": n, "days": {d: {"sales_x": med(D[d]["sales"]), "pos_x": med(D[d]["pos"])} for d in sorted(D)}}
    return out


# ── 3. Новинка ───────────────────────────────────────────────────────────────────────────────────────────
def novelty(P: dict) -> dict:
    L = []
    for v in P.values():
        R = v["rows"]
        idx = [i for i, r in enumerate(R) if r.get("is_new")]
        if not idx or idx[0] < 1 or idx[-1] + 15 >= len(R) or (R[0].get("is_new") and idx[0] == 0 and R[0]["data"] > "2025-05-20"):
            pass
        if idx and idx[-1] + 15 < len(R) and len(idx) >= 7:
            e = idx[-1]
            a, b = R[e - 6:e + 1], R[e + 1:e + 15]
            pa, pb = [r["search_position_avg"] for r in a if r.get("search_position_avg")], [r["search_position_avg"] for r in b if r.get("search_position_avg")]
            sa, sb = st.mean([r.get("sales") or 0 for r in a]), st.mean([r.get("sales") or 0 for r in b])
            L.append({"days_new": len(idx), "sales_after_x": round(sb / sa, 2) if sa else None,
                      "pos_after_x": round(st.median(pb) / st.median(pa), 2) if pa and pb else None})
    return {"n": len(L), "days_new_med": med([x["days_new"] for x in L]), "sales_after_x_med": med([x["sales_after_x"] for x in L]),
            "pos_after_x_med": med([x["pos_after_x"] for x in L])}


# ── 4. Что менялось по месяцам ───────────────────────────────────────────────────────────────────────────
def changes(P: dict) -> dict:
    M = collections.defaultdict(lambda: collections.defaultdict(list))
    for v in P.values():
        for r in v["rows"]:
            m = r["data"][:7]
            M[m]["fbs"].append(r.get("commission_fbs"))
            M[m]["fbo"].append(r.get("commission_fbo"))
            M[m]["ads"].append(1 if r.get("in_ads") else 0)
            M[m]["promo"].append(1 if r.get("in_action") else 0)
            if r.get("search_words_count"):
                M[m]["ad_words_share"].append((r.get("search_words_in_ad") or 0) / r["search_words_count"])
            M[m]["discount"].append(r.get("discount"))
            if r.get("balance"):
                M[m]["wh"].append(r.get("warehouses_count"))
            M[m]["ext_ads"].append(1 if (r.get("adv_stats") or {}).get("posts") else 0)
            M[m]["cards"].append(1)
    out = {}
    for m in sorted(M):
        D = M[m]
        out[m] = {"card_days": len(D["cards"]), "commission_fbs_med": med(D["fbs"]), "commission_fbo_med": med(D["fbo"]),
                  "ads_days_pct": round(st.mean(D["ads"]) * 100, 1), "promo_days_pct": round(st.mean(D["promo"]) * 100, 1),
                  "search_words_from_ads_pct": round(st.mean(D["ad_words_share"]) * 100, 1) if D["ad_words_share"] else None,
                  "seller_discount_med": med(D["discount"]), "warehouses_med": med(D["wh"]),
                  "external_ads_days_pct": round(st.mean(D["ext_ads"]) * 100, 2)}
    return out


def hours(P: dict) -> dict:
    c = collections.Counter()
    for v in P.values():
        for r in v["rows"]:
            for h in r.get("top_hours") or []:
                c[int(h)] += 1
    tot = sum(c.values())
    return {h: round(c[h] / tot * 100, 1) for h in range(24)} if tot else {}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    P = panel()
    print(f"карточек с рядом ≥ 30 дн.: {len(P)}; ниш: {len({v['niche'] for v in P.values()})}; карточко-дней: {sum(len(v['rows']) for v in P.values())}")
    res = {"panel": {"cards": len(P), "niches": dict(collections.Counter(str(v["niche"]) for v in P.values())),
                     "card_days": sum(len(v["rows"]) for v in P.values()), "window_to": CUT},
           "drivers": drivers(P), "response": response(P), "novelty": novelty(P), "changes": changes(P), "hours": hours(P)}
    for k, v in res.items():
        json.dump(v, open(f"{OUT}/{k}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("panel", "drivers", "novelty", "hours")}, ensure_ascii=False, indent=1)[:6000])
    for e, d in res["response"].items():
        print(e, d["n"], {k: (v["sales_x"], v["pos_x"]) for k, v in d["days"].items() if k in (-3, 0, 1, 3, 7, 14)})
    for m, d in res["changes"].items():
        print(m, d)
    write_xlsx(res)


def write_xlsx(res: dict) -> None:
    wb = Workbook()
    hdr = lambda ws: [setattr(c, "font", Font(bold=True, color="FFFFFF")) or setattr(c, "fill", PatternFill("solid", fgColor="305496")) for c in ws[1]]
    ws = wb.active; ws.title = "Драйверы"
    ws.append(["Фактор", "→ log(позиция) (минус = выше в поиске)", "ниш с тем же знаком %", "→ log(1+продажи)", "ниш с тем же знаком %"])
    d = res["drivers"]
    for f in FEATS:
        ws.append([f, d["log_position"][f], d["log_position_same_sign_pct"][f], d["log1p_sales"][f], d["log1p_sales_same_sign_pct"][f]])
    hdr(ws)
    ws = wb.create_sheet("Реакция")
    ws.append(["Событие", "n", "День"] + ["продажи ×", "позиция ×"])
    for e, D in res["response"].items():
        for day, v in D["days"].items():
            ws.append([e, D["n"], int(day), v["sales_x"], v["pos_x"]])
    hdr(ws)
    ws = wb.create_sheet("Изменения по месяцам")
    keys = list(next(iter(res["changes"].values())).keys())
    ws.append(["Месяц"] + keys)
    for m, v in res["changes"].items():
        ws.append([m] + [v[k] for k in keys])
    hdr(ws)
    ws = wb.create_sheet("Часы продаж")
    ws.append(["Час", "% пиковых часов"])
    for h, p in res["hours"].items():
        ws.append([h, p])
    hdr(ws)
    wb.save(XLSX)
    print("→", XLSX)


if __name__ == "__main__":
    main()
