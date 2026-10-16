"""Что видели победители-новички в момент решения и что решили → проверенные правила выбора (2026-10-16). 0 запросов.

    python -m src.winner_decisions            # → data/processed/winner_decisions_<RUN>.json + reports/winner_decisions_<RUN>.xlsx
    python -m src.winner_decisions apply      # применить checklist из config/filters.yaml к нашим кандидатам

Два уровня:
  1. Карточка (10 ниш launch_sample): исход = средние продажи на днях 60–180 от первой продажи, очищенные от сезона;
     win ≥ 5/день, fail < 1/день (пороги — config/filters.yaml → newcomer_rules). Признаки «что видел» — только из месяцев
     ниши, закончившихся ДО T0 = первая продажа − 60 дней; «что решил» — карточка + первые 8 недель.
  2. Ниша (≈ 31 ниша с trends + products500 за июль): сколько новичков когорты дошли до ≥ 5/день на 100 продавцов
     с продажами в месяц T0, против того, что было видно в нише до T0.
Survivorship: products500 — top-500 июля по выручке; провалившиеся новички в нём не видны. Поэтому уровень 1 — case-control
(lift считается относительно доли победителей в выборке, а не в рынке), уровень 2 считает только победителей (они видны все,
если отсечка выручки top-500 < 5 шт/день × 31 × цена; иначе ниша помечена undercount).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import math
import os
import re
import statistics as st
import sys

import yaml

from src.launch_collect import rows as prod_rows
from src.launch_patterns import day0, week_stats
from src import datastore as D

RUN = "2026-10-16"
OUT = f"data/processed/winner_decisions_{RUN}.json"
XLSX = f"reports/winner_decisions_{RUN}.xlsx"
SAMPLES = sorted(glob.glob("data/processed/launch_sample_2026-10-*.json"))
CFG = yaml.safe_load(open("config/filters.yaml", encoding="utf-8"))["newcomer_rules"]
CUT = CFG["data_cut"]
# products500 июля для ниш, которых нет в каталоге datastore
P500_EXTRA = {7640: "data/raw/saleflow/2026-10-14/strategy7640/products500_2026-07.json",
              52: "data/raw/saleflow/2026-10-15/strategy52/products500_2026-07.json"}
TOP100_MONTHLY = {7640: "data/raw/saleflow/2026-10-14/strategy7640/monthly",
                  52: "data/raw/saleflow/2026-10-15/strategy52/monthly"}
BUNDLE = re.compile(r"набор|комплект|\b\d+\s*(шт|предм)|2 в 1|3 в 1|\bсет\b", re.I)


# ── утилиты ──────────────────────────────────────────────────────────────────
def ym(d: str) -> str:
    return d[:7]


def add_months(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:7]) - 1 + k
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


def wilson(k: int, n: int, z: float = CFG["wilson_z"]) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, c - h), min(1.0, c + h))


def pct(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b else None


def tercile_cuts(xs: list[float]) -> list[float]:
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < 6:
        return []
    return sorted({xs[len(xs) // 3], xs[2 * len(xs) // 3]})


# ── ряды ниши (месяцы) ───────────────────────────────────────────────────────
_NM: dict[int, dict] = {}


def trends_path(n: int) -> str | None:
    p = f"data/raw/saleflow/2026-10-16/weekly/{n}/trends_full.json"
    if os.path.exists(p):
        return p
    fs = sorted(D.files(n, "trends"), key=lambda c: c["date"])
    if fs:
        return fs[-1]["path"]
    for p in glob.glob(f"data/raw/saleflow/*/strategy{n}/trends_month.json"):
        return p
    return None


def niche_months(n: int) -> dict[str, dict]:
    """month → {sales, revenue, sellers, items, aov}; только месяцы ≤ CUT."""
    if n in _NM:
        return _NM[n]
    out = {}
    p = trends_path(n)
    if p:
        d = json.load(open(p, encoding="utf-8"))
        d = d.get("data", d) if isinstance(d, dict) else d
        for r in d:
            m = (r.get("label_date") or r.get("date", ""))[:7]
            if not m or m > ym(CUT):
                continue
            out[m] = {"sales": r.get("sales") or 0, "revenue": r.get("revenue") or 0,
                      "sellers": r.get("sellers_with_sells") or 0, "items": r.get("items_with_sells") or 0,
                      "aov": r.get("average_order_value")}
    _NM[n] = out
    return out


def season_index(n: int, upto: str) -> dict[int, float]:
    """Профиль сезона по 12 месяцам, закончившимся ДО upto (YYYY-MM): номер месяца → продажи / среднее."""
    M = niche_months(n)
    last = [add_months(upto, -k) for k in range(12, 0, -1)]
    if not all(m in M for m in last):
        return {}
    avg = st.mean(M[m]["sales"] for m in last) or 1
    return {int(m[5:7]): M[m]["sales"] / avg for m in last}


def market_at(n: int, t0: str) -> dict:
    """Что было видно в нише до T0 (дата). Используются только месяцы, которые ЗАКОНЧИЛИСЬ до T0."""
    M = niche_months(n)
    last = add_months(ym(t0), -1)            # последний полный месяц до T0
    if last not in M:
        return {"src_max": None}
    g = lambda m, k: (M.get(m) or {}).get(k)
    prev = [add_months(last, -k) for k in range(12)]              # 12 месяцев до T0
    if any(m not in M for m in prev):
        return {"src_max": last, "note": "меньше 12 месяцев истории"}
    peak = max(prev, key=lambda m: M[m]["sales"])
    s3 = sum(M[add_months(last, -k)]["sales"] for k in range(3))
    s3_ly = sum(g(add_months(last, -12 - k), "sales") or 0 for k in range(3)) or None
    sel3 = st.mean(M[add_months(last, -k)]["sellers"] for k in range(3)) or None
    sel3_ly = st.mean((g(add_months(last, -12 - k), "sellers") or 0) for k in range(3)) or None
    prof = season_index(n, ym(t0))
    m60 = int(add_months(ym(t0), 2)[5:7])
    peak_m = int(peak[5:7])
    t0m = int(t0[5:7])
    f = {
        "src_max": last,
        "yoy_peak": pct(M[peak]["sales"], g(add_months(peak, -12), "sales")),
        "yoy_3m": pct(s3, s3_ly),
        "sellers": M[last]["sellers"],
        "sellers_6m": pct(M[last]["sellers"], g(add_months(last, -6), "sellers")),
        "sps_3m": round(s3 / 3 / sel3, 1) if sel3 else None,                    # продаж в месяц на продавца
        "sps_yoy": pct(s3 / sel3 if sel3 else None, s3_ly / sel3_ly if (s3_ly and sel3_ly) else None),
        "aov": M[last]["aov"],
        "months_to_peak": (peak_m - t0m) % 12,
        "season_idx_t0_60": round(prof.get(m60, 0), 2) if prof else None,       # индекс месяца первой продажи
    }
    f.update(top100_at(n, last))
    return f


def top100_at(n: int, month: str) -> dict:
    """Лидеры из месячных снимков top-100 (есть только для 7640 и 52)."""
    d = TOP100_MONTHLY.get(n)
    p = f"{d}/products_{month}.json" if d else None
    if not p or not os.path.exists(p):
        return {}
    R = prod_rows(p)
    rev = sum(r.get("revenue") or 0 for r in R) or 1
    new_from = add_months(month, -5) + "-01"
    return {
        "top1_share100": round((R[0].get("revenue") or 0) / rev * 100, 1),
        "top10_share100": round(sum(r.get("revenue") or 0 for r in R[:10]) / rev * 100, 1),
        "new6m_share100": round(sum(r.get("revenue") or 0 for r in R if (r.get("sku_first_date") or "") >= new_from) / rev * 100, 1),
        "lead_price_p50": st.median([r["final_price_average"] for r in R[:20] if r.get("final_price_average")] or [0]) or None,
    }


# ── уровень 1: карточки ─────────────────────────────────────────────────────
def load_series(sku: int, start: str) -> list[dict]:
    rows = D.daily(sku)
    return [r for r in rows if r["data"] <= CUT]


def outcome(rows: list[dict], d0: int, n: int) -> dict:
    a, b = CFG["outcome_days"]
    w = rows[d0 + a: d0 + b]
    if len(w) < CFG["outcome_min_days"]:
        return {"out": "censored", "obs_days": len(w)}
    raw = st.mean(r.get("sales") or 0 for r in w)
    prof = season_index(n, "2026-08")                 # профиль за 2025-08…2026-07 (исход, будущее допустимо)
    idx = st.mean(prof.get(int(r["data"][5:7]), 1.0) for r in w) if prof else 1.0
    adj = raw / idx if idx else raw
    jul = [r.get("sales") or 0 for r in rows if r["data"].startswith("2026-07")]
    alive = bool(jul) and st.mean(jul) > 0
    g = "win" if adj >= CFG["win_per_day"] and alive else "fail" if adj < CFG["fail_per_day"] else "mid"
    return {"out": g, "obs_days": len(w), "m3_6": round(raw, 2), "m3_6_adj": round(adj, 2),
            "season_adj": bool(prof), "jul_per_day": round(st.mean(jul), 1) if jul else None}


def decisions(W: list[dict], rows0: list[dict], p: dict, mk: dict) -> dict:
    E = CFG["early_weeks"]
    W8 = W[:E]
    pr4 = st.median([w["price"] for w in W[:4] if w.get("price")] or [0]) or None
    pr8 = W[7]["price"] if len(W) > 7 else None
    lp = W[0].get("list_price") if W else None
    d50 = next((i for i, r in enumerate(rows0) if (r.get("comments") or 0) >= 50), None)
    return {
        "price_w1_4": pr4,
        "price_rel_aov": round(pr4 / mk["aov"], 2) if pr4 and mk.get("aov") else None,
        "price_rel_lead": round(pr4 / mk["lead_price_p50"], 2) if pr4 and mk.get("lead_price_p50") else None,
        "price_chg_w8": pct(pr8, pr4),
        "discount_w1": round((1 - W[0]["price"] / lp) * 100) if W and W[0].get("price") and lp else None,
        "ads_w1_4": st.mean(w["ads"] for w in W[:4]) if W else None,
        "ads_w1_8": st.mean(w["ads"] for w in W8) if W8 else None,
        "promo_w1_8": st.mean(w["promo"] for w in W8) if W8 else None,
        "oos_w1_8": sum(w["oos"] for w in W8) if W8 else None,
        "wh_w4": W[3]["wh"] if len(W) > 3 else None,
        "words_w4": W[3]["words"] if len(W) > 3 else None,
        "reviews_day0": rows0[0].get("comments") or 0,
        "glued": (rows0[0].get("comments") or 0) >= 50,
        "reviews_w4": W[3]["reviews"] if len(W) > 3 else None,
        "days_to_50": d50,
        "sales_w1": W[0]["sales"] if W else None,
        "bundle": bool(BUNDLE.search(p.get("name") or "")),
    }


def p500(n: int) -> list[dict]:
    if n in P500_EXTRA:
        return prod_rows(P500_EXTRA[n])
    fs = [c for c in D.files(n, "products500") if c.get("month") == "2026-07"]
    if not fs:
        return []
    return prod_rows(sorted(fs, key=lambda c: c["date"])[-1]["path"])


def cards(lag: int = CFG["t0_lag_days"]) -> list[dict]:
    out, seen = [], set()
    for f in SAMPLES:
        for n, s in json.load(open(f, encoding="utf-8")).items():
            n = int(n)
            P = p500(n)
            # провал (< 1/день) виден в top-500 июля, только если цена ≥ отсечка выручки / 31 → «честная зона» сравнения
            floor = round(min(r.get("revenue") or 0 for r in P) / 31) if len(P) >= 450 else 0
            for grp in ("win", "mid", "ctl"):
                for p in s.get(grp, []):
                    if p["id"] in seen:
                        continue
                    seen.add(p["id"])
                    rows = load_series(p["id"], p["sku_first_date"][:10])
                    if not rows:
                        continue
                    d0 = day0(rows, p["sku_first_date"])
                    if d0 is None:
                        continue
                    start = rows[d0]["data"]
                    if not (CFG["newcomer_from"] <= start <= CFG["newcomer_to"]):
                        continue
                    t0 = (dt.date.fromisoformat(start) - dt.timedelta(days=lag)).isoformat()
                    W = []
                    for k in range(16):
                        w = rows[d0 + 7 * k: d0 + 7 * k + 7]
                        if len(w) < 7:
                            break
                        W.append(week_stats(w))
                    mk = market_at(n, t0)
                    prior = [q for q in P if q.get("seller") == p["seller"] and q["id"] != p["id"]
                             and (q.get("sku_first_date") or "9") < t0]
                    rec = {"niche": n, "niche_name": s["name"], "sample_group": grp, "id": p["id"], "name": p["name"],
                           "seller": p["seller"], "start": start, "t0": t0, "entry_half": "train" if start <= CFG["train_until"] else "test",
                           "seller_in_niche_before": bool(prior), "is_fbs": p.get("is_fbs") == 1}
                    rec.update(outcome(rows, d0, n))
                    rec.update({f"m_{k}": v for k, v in mk.items()})
                    rec.update(decisions(W, rows[d0:], p, mk))
                    rec["visible_floor"] = floor
                    rec["fair"] = bool(rec.get("price_w1_4")) and rec["price_w1_4"] >= floor
                    out.append(rec)
    return out


# ── статистика правил ───────────────────────────────────────────────────────
SELECTION = ["m_yoy_peak", "m_yoy_3m", "m_sellers", "m_sellers_6m", "m_sps_3m", "m_sps_yoy", "m_months_to_peak",
             "m_season_idx_t0_60", "m_top1_share100", "m_top10_share100", "m_new6m_share100",
             "price_rel_aov", "price_rel_lead", "bundle", "seller_in_niche_before", "is_fbs"]
EXECUTION = ["ads_w1_4", "ads_w1_8", "promo_w1_8", "oos_w1_8", "wh_w4", "words_w4", "glued", "reviews_w4",
             "days_to_50", "discount_w1", "price_chg_w8", "sales_w1"]


def is_win(c):
    return c["out"] == "win"


def cond(c, feat, op, cut):
    v = c.get(feat)
    if v is None:
        return None
    if isinstance(v, bool):
        return v == bool(cut)
    return v >= cut if op == ">=" else v <= cut


def rate(C, feat, op, cut):
    on = [c for c in C if cond(c, feat, op, cut) is True]
    off = [c for c in C if cond(c, feat, op, cut) is False]
    return on, off


def evaluate(C, feat, op, cut):
    on, off = rate(C, feat, op, cut)
    k = sum(map(is_win, on))
    allc = on + off
    base = sum(map(is_win, allc)) / len(allc) if allc else 0
    lo, hi = wilson(k, len(on))
    return {"n_on": len(on), "n_off": len(off), "win_on": k, "p_on": round(k / len(on), 3) if on else None,
            "p_off": round(sum(map(is_win, off)) / len(off), 3) if off else None, "base": round(base, 3),
            "lift": round(k / len(on) / base, 2) if on and base else None,
            "lift_lo": round(lo / base, 2) if base else None, "lift_hi": round(hi / base, 2) if base else None,
            "win_pass": k, "fail_pass": sum(1 for c in on if c["out"] == "fail"),
            "win_total": sum(map(is_win, allc)), "fail_total": sum(1 for c in allc if c["out"] == "fail")}


def candidates(C, feat):
    vals = [c.get(feat) for c in C if c.get(feat) is not None]
    if not vals:
        return []
    if isinstance(vals[0], bool):
        return [("==", True), ("==", False)]
    return [(op, cut) for cut in tercile_cuts(vals) for op in (">=", "<=")]


def best_rule(C, feat):
    best = None
    for op, cut in candidates(C, feat):
        e = evaluate(C, feat, op, cut)
        if e["n_on"] < CFG["min_n"] or e["lift"] is None or e["n_off"] < 5:
            continue
        if best is None or e["lift"] > best[2]["lift"]:
            best = (op, cut, e)
    return best


def lono(C, feat):
    """Порог выбирается без ниши X, проверяется в нише X: P(win|on) > P(win|off)."""
    held, total = 0, 0
    for n in sorted({c["niche"] for c in C}):
        tr = [c for c in C if c["niche"] != n]
        te = [c for c in C if c["niche"] == n]
        b = best_rule(tr, feat)
        if not b:
            continue
        on, off = rate(te, feat, b[0], b[1])
        if len(on) < CFG["lono_min_side"] or len(off) < CFG["lono_min_side"]:
            continue
        total += 1
        held += (sum(map(is_win, on)) / len(on)) > (sum(map(is_win, off)) / len(off))
    return held, total


def rules(C):
    C = [c for c in C if c["out"] in ("win", "fail")]
    tr = [c for c in C if c["entry_half"] == "train"]
    te = [c for c in C if c["entry_half"] == "test"]
    R = []
    for kind, feats in (("selection", SELECTION), ("execution", EXECUTION)):
        for f in feats:
            b = best_rule(C, f)
            if not b:
                R.append({"feature": f, "kind": kind, "status": "rejected: n<15 или нет порога"})
                continue
            op, cut, e = b
            bt = best_rule(tr, f)
            t_ok = None
            if bt:
                et = evaluate(te, f, bt[0], bt[1])
                t_ok = et["lift"] is not None and et["n_on"] >= 5 and et["lift"] > 1
            h, tot = lono(C, f)
            ci_ok = e["lift_lo"] is not None and e["lift_lo"] > 1
            ok = ci_ok and bool(t_ok) and tot >= 3 and h / tot >= 0.6
            R.append({"feature": f, "kind": kind, "op": op, "cut": cut, **e, "time_ok": t_ok,
                      "time_cut": bt[1] if bt else None, "lono": f"{h}/{tot}",
                      "status": "VALID" if ok else ("observation" if ci_ok else "rejected: CI includes 1")})
    return R


# ── уровень 2: ниши ──────────────────────────────────────────────────────────
def niche_universe() -> list[int]:
    ns = {c["niche"] for c in D.catalog() if c["kind"] == "products500" and c.get("month") == "2026-07"}
    return sorted(n for n in ns | set(P500_EXTRA) if niche_months(n))


def niche_level() -> list[dict]:
    out = []
    for n in niche_universe():
        P = p500(n)
        if not P:
            continue
        M = niche_months(n)
        prof = season_index(n, "2026-08")
        jul_idx = prof.get(7, 1.0) if prof else 1.0
        cutoff = min(r.get("revenue") or 0 for r in P) if len(P) >= 450 else 0
        p50 = st.median([r["final_price_average"] for r in P if r.get("final_price_average")] or [0])
        complete = (cutoff / 31 / p50 < CFG["win_per_day"] * jul_idx) if p50 else False
        for co in CFG["niche_cohorts"]:
            mk = market_at(n, co["t0"])
            if mk.get("yoy_peak") is None:
                continue
            new = [r for r in P if co["from"] <= (r.get("sku_first_date") or "")[:10] <= co["to"]]
            wins = [r for r in new if (r.get("sales") or 0) / 31 / jul_idx >= CFG["win_per_day"]]
            sel = M.get(add_months(ym(co["t0"]), -1), {}).get("sellers") or None
            out.append({"niche": n, "cohort": co["name"], "t0": co["t0"], **{f"m_{k}": v for k, v in mk.items()},
                        "winners": len(wins), "winners_per100": round(len(wins) / sel * 100, 2) if sel else None,
                        "win_sellers": len({r.get("seller") for r in wins}),
                        "complete": complete, "cutoff_rev": cutoff, "p50_jul": p50, "jul_idx": round(jul_idx, 2)})
    return out


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 8:
        return None, len(pairs)
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
        for i, j in enumerate(o):
            r[j] = i
        return r
    a, b = rk([p[0] for p in pairs]), rk([p[1] for p in pairs])
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return (round(num / den, 2) if den else None), len(pairs)


def niche_rules(NL):
    res = []
    for f in ["m_yoy_peak", "m_yoy_3m", "m_sellers", "m_sellers_6m", "m_sps_3m", "m_sps_yoy", "m_months_to_peak", "m_aov"]:
        row = {"feature": f}
        for co in [c["name"] for c in CFG["niche_cohorts"]] + ["all"]:
            L = [r for r in NL if co == "all" or r["cohort"] == co]
            rho, n = spearman([r.get(f) for r in L], [r["winners_per100"] for r in L])
            row[co] = rho
            row[f"n_{co}"] = n
        L = sorted([r for r in NL if r.get(f) is not None and r["winners_per100"] is not None], key=lambda r: r[f])
        if len(L) >= 9:
            t = len(L) // 3
            row["low_t_w100"] = round(st.median(r["winners_per100"] for r in L[:t]), 2)
            row["high_t_w100"] = round(st.median(r["winners_per100"] for r in L[-t:]), 2)
            row["low_t_max"] = L[t - 1][f]
            row["high_t_min"] = L[-t][f]
        res.append(row)
    return res


# ── отчётные выборки ─────────────────────────────────────────────────────────
def pairs(C, k=5):
    """Победитель и провалившийся новичок той же ниши: ближайший T0 (≤ 75 дн) и похожая цена (×0.6…1.6), по одной паре на нишу."""
    W = sorted([c for c in C if c["out"] == "win"], key=lambda c: -(c.get("m3_6_adj") or 0))
    F = [c for c in C if c["out"] == "fail"]
    days = lambda a, b: abs((dt.date.fromisoformat(a["t0"]) - dt.date.fromisoformat(b["t0"])).days)
    res, used, niches = [], set(), set()
    for w in W:
        if w["niche"] in niches or not w.get("price_w1_4"):
            continue
        cand = [f for f in F if f["niche"] == w["niche"] and f["id"] not in used and f.get("price_w1_4")
                and 0.6 <= f["price_w1_4"] / w["price_w1_4"] <= 1.6 and days(f, w) <= 75]
        if not cand:
            continue
        f = min(cand, key=lambda f: days(f, w))
        used.add(f["id"])
        niches.add(w["niche"])
        res.append((w, f))
        if len(res) >= k:
            break
    return res


def sensitivity(base_rules):
    """Те же пороги правил выбора при T0 = старт − 30 и − 90 дней."""
    out = {}
    for lag in CFG["t0_sensitivity"]:
        C = [c for c in cards(lag) if c["out"] in ("win", "fail")]
        out[lag] = {}
        for r in base_rules:
            if r.get("kind") != "selection" or "op" not in r or not r["feature"].startswith("m_"):
                continue
            e = evaluate(C, r["feature"], r["op"], r["cut"])
            out[lag][r["feature"]] = {"lift": e["lift"], "n_on": e["n_on"], "lift_lo": e["lift_lo"]}
    return out


def checklist_eval(C):
    """Сколько победителей и провалившихся проходят ВСЕ правила каждой группы checklist:
    all / no_ctl — пороги cut; fair — только «честная зона» цены и пороги cut_fair (если заданы)."""
    ck = CFG.get("checklist") or {}
    out = {}
    for grp in sorted({r["group"] for r in ck.values()}):
        R = {f: r for f, r in ck.items() if r["group"] == grp}
        for scope, CC, key in (("all", C, "cut"), ("no_ctl", [c for c in C if c["sample_group"] != "ctl"], "cut"),
                               ("fair", [c for c in C if c["fair"]], "cut_fair")):
            L = [c for c in CC if c["out"] in ("win", "fail") and all(c.get(f) is not None for f in R)]
            ok = [c for c in L if all(cond(c, f, r["op"], r.get(key, r["cut"])) for f, r in R.items())]
            w, fl = sum(map(is_win, L)), sum(1 for c in L if c["out"] == "fail")
            wp, fp = sum(map(is_win, ok)), sum(1 for c in ok if c["out"] == "fail")
            out[f"{grp}/{scope}"] = {"rules": list(R), "n": len(L), "win_total": w, "fail_total": fl, "win_pass": wp,
                                     "fail_pass": fp, "precision": round(wp / len(ok), 3) if ok else None,
                                     "recall": round(wp / w, 3) if w else None,
                                     "niches": len({c["niche"] for c in L})}
    return out


def price_bands(C):
    """Доля win среди win+fail по полосам цена/AOV: в штуках и в выручке (m3_6_adj × price_rel ≥ win / < fail)."""
    bands = [(0, 1.2), (1.2, 2), (2, 3), (3, 99)]
    W, Fl = CFG["win_per_day"], CFG["fail_per_day"]
    out = []
    for lo, hi in bands:
        B = [c for c in C if c["out"] != "censored" and c.get("price_rel_aov") is not None and lo < c["price_rel_aov"] <= hi]
        for scope, BB in (("all", B), ("no_ctl", [c for c in B if c["sample_group"] != "ctl"]), ("fair", [c for c in B if c["fair"]])):
            w = sum(1 for c in BB if c["out"] == "win")
            f = sum(1 for c in BB if c["out"] == "fail")
            rv = [c["m3_6_adj"] * c["price_rel_aov"] for c in BB]
            out.append({"band": f"{lo}–{hi}", "scope": scope, "win": w, "fail": f, "win_share": round(w / (w + f), 3) if w + f else None,
                        "rev_win": sum(1 for x in rv if x >= W), "rev_fail": sum(1 for x in rv if x < Fl),
                        "win_niches": sorted({c["niche"] for c in BB if c["out"] == "win"})})
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    C = cards()
    R = rules(C)
    RF = {r["feature"]: r for r in rules([c for c in C if c["fair"]])}
    for r in R:                                    # та же проверка только в «честной зоне» цены
        f = RF.get(r["feature"], {})
        r.update({"fair_" + k: f.get(k) for k in ("op", "cut", "n_on", "p_on", "p_off", "lift", "lift_lo", "lono", "time_ok", "status")})
    NL = niche_level()
    NR = niche_rules(NL)
    S = sensitivity(R)
    P = [(w["id"], f["id"]) for w, f in pairs(C)]
    CK = checklist_eval(C)
    res = {"checklist_eval": CK, "candidates": apply_candidates(), "run": RUN, "config": CFG, "cards": C, "rules": R, "niche_level": NL, "niche_rules": NR,
           "sensitivity": S, "pairs": P, "price_bands": price_bands(C)}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    from collections import Counter
    print("карточек:", len(C), Counter(c["out"] for c in C), "| ниш:", len({c["niche"] for c in C}))
    print("по нишам:", {n: dict(Counter(c["out"] for c in C if c["niche"] == n)) for n in sorted({c["niche"] for c in C})})
    for r in R:
        if "op" in r:
            print(f"{r['kind'][:3]} {r['feature']:22} {r['op']} {r['cut']!s:8} n={r['n_on']:3} p_on={r['p_on']} p_off={r['p_off']} "
                  f"lift={r['lift']} [{r['lift_lo']}–{r['lift_hi']}] time={r['time_ok']} lono={r['lono']} → {r['status']} | FAIR {r['fair_op']} {r['fair_cut']} n={r['fair_n_on']} "
                  f"p={r['fair_p_on']}/{r['fair_p_off']} lift={r['fair_lift']} lo={r['fair_lift_lo']} lono={r['fair_lono']} → {r['fair_status']}")
        else:
            print(f"{r['kind'][:3]} {r['feature']:22} {r['status']}")
    print("ниш (уровень 2):", len({r['niche'] for r in NL}), "строк:", len(NL))
    for r in NR:
        print(r)
    for k, v in CK.items():
        print("checklist", k, v)
    print("чувствительность:", json.dumps(S, ensure_ascii=False))
    write_xlsx(res)
    print("→", OUT, XLSX)


def write_xlsx(res):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    for title, data in (("Карточки", res["cards"]), ("Правила", res["rules"]), ("Ниши", res["niche_level"]),
                        ("Ниши_правила", res["niche_rules"])):
        ws = wb.active if title == "Карточки" else wb.create_sheet(title)
        ws.title = title
        keys = []
        for d in data:
            keys += [k for k in d if k not in keys]
        ws.append(keys)
        for c in ws[1]:
            c.font = Font(bold=True)
        for d in data:
            ws.append([d.get(k) if not isinstance(d.get(k), (list, dict)) else json.dumps(d.get(k), ensure_ascii=False) for k in keys])
        ws.freeze_panes = "A2"
    wb.save(XLSX)


# ── применение к кандидатам ─────────────────────────────────────────────────
def apply_candidates() -> list[dict]:
    """Правила групп select + niche к нашим кандидатам. Цена кандидата — до СПП; цена покупателя = × (1 − spp)."""
    ck = CFG.get("checklist") or {}
    out = []
    for cd in CFG.get("candidates") or []:
        mk = market_at(cd["niche"], cd["t0"])
        buyer = round(cd["price"] * (1 - cd.get("spp", 0) / 100))
        rec = {**{f"m_{k}": v for k, v in mk.items()}, "price_w1_4": buyer,
               "price_rel_aov": round(buyer / mk["aov"], 2) if mk.get("aov") else None}
        checks = [{"feature": f, "value": rec.get(f), "op": r["op"], "cut": r["cut"], "status": r["status"],
                   "pass": cond(rec, f, r["op"], r["cut"])} for f, r in ck.items() if r["group"] in ("select", "niche", "info")]
        out.append({**cd, "buyer_price": buyer, "aov": mk.get("aov"), "src_max": mk.get("src_max"), "checks": checks})
    return out


def apply() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    for a in apply_candidates():
        print(f"{a['name']} | цена {a['price']} → покупатель {a['buyer_price']} | AOV {a['aov']} | данные ≤ {a['src_max']}")
        for c in a["checks"]:
            print(f"    {c['feature']:15} {c['value']!s:8} {c['op']} {c['cut']:<6} → {c['pass']}  ({c['status']})")

if __name__ == "__main__":
    apply() if sys.argv[1:] == ["apply"] else main()
