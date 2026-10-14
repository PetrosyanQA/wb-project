"""Эволюция ниши за 12 месяцев + путь победителей с первого дня (2026-10-14). 0 запросов.

    LAUNCH_RUN=2026-10-14 python -m src.evolution --niche 7640     # → data/processed/evolution_7640_<run>.json + reports/evolution_7640_<run>.xlsx

Входы (уже на диске):
  trends_month.json                 — рынок по месяцам (выручка, продажи, продавцы и карточки с продажами, средний чек)
  monthly/products_YYYY-MM.json     — top-100 каждого месяца 2025-08 … 2026-07 (структура рынка, кто вошёл/вышел)
  keywords/keywords_YYYY-MM.json    — спрос в поиске по месяцам (wb_count)
  launch sample + by_period         — победители / середняки / слабые новички (src.launch_collect, LAUNCH_RUN)
Окно ≤ 2026-07-31 (дальше Saleflow неполный). ⚠️ 2025-09 — смена методики Saleflow (items_with_sells ×2): сравнения через неё
даются и по продажам, и по поисковому спросу.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
CUT = "2026-07-31"
MONTHS = [f"2025-{m:02d}" for m in range(8, 13)] + [f"2026-{m:02d}" for m in range(1, 8)]


def load(p):
    return json.load(open(p, encoding="utf-8"))


def rows(p):
    d = load(p)
    return d.get("data", d) if isinstance(d, dict) else d


def med(xs, nd=1):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), nd) if xs else None


# ── A. рынок по месяцам ─────────────────────────────────────────────────────────────────────────────────────
def market(base: str, segment_fn) -> dict:
    T = {r["label_date"]: r for r in rows(f"{base}/trends_month.json")}
    out, prev_ids, prev_top20 = {}, set(), set()
    for m in MONTHS:
        t = T.get(m, {})
        f = f"{base}/monthly/products_{m}.json"
        row = {"revenue_mln": round((t.get("revenue") or 0) / 1e6, 1), "sales": t.get("sales"), "sales_est": t.get("sales_estimated"),
               "sellers_ws": t.get("sellers_with_sells"), "items_ws": t.get("items_with_sells"), "aov": t.get("average_order_value")}
        if os.path.exists(f):
            R = sorted([p for p in rows(f) if p.get("sales")], key=lambda p: -p["revenue"])[:100]
            tot = sum(p["revenue"] for p in R) or 1
            by_s = collections.Counter()
            for p in R:
                by_s[p.get("seller")] += p["revenue"]
            m_start = dt.date.fromisoformat(m + "-01")
            new6 = [p for p in R if (p.get("sku_first_date") or "") >= (m_start - dt.timedelta(days=183)).isoformat()]
            seg = collections.Counter()
            for p in R:
                seg[segment_fn(p["name"])] += p["revenue"]
            ids, top20 = {p["id"] for p in R}, {p["id"] for p in R[:20]}
            buyer = [p["revenue"] / p["sales"] for p in R]
            row.update({
                "top100_rev_mln": round(tot / 1e6, 1),
                "top1_seller": by_s.most_common(1)[0][0], "top1_pct": round(by_s.most_common(1)[0][1] / tot * 100, 1),
                "top10_sellers_pct": round(sum(v for _, v in by_s.most_common(10)) / tot * 100, 1),
                "sellers_in_top100": len(by_s),
                "new6m_cards": len(new6), "new6m_rev_pct": round(sum(p["revenue"] for p in new6) / tot * 100, 1),
                "buyer_price_med": round(st.median(buyer)), "buyer_price_p25": round(sorted(buyer)[len(buyer) // 4]),
                "black_pct": round(sum(p["revenue"] for p in R if "черн" in str(p.get("color") or "").lower()) / tot * 100, 1),
                "segments_pct": {k: round(v / tot * 100, 1) for k, v in seg.most_common()},
                "stayed_from_prev": len(ids & prev_ids) if prev_ids else None,
                "new_in_top20": [{"id": p["id"], "name": p["name"][:55], "seller": p.get("seller"), "start": (p.get("sku_first_date") or "")[:10],
                                  "sales": p["sales"], "buyer": round(p["revenue"] / p["sales"])} for p in R[:20] if prev_top20 and p["id"] not in prev_top20],
                "top5_sellers": [(s, round(v / tot * 100, 1)) for s, v in by_s.most_common(5)],
            })
            prev_ids, prev_top20 = ids, top20
        out[m] = row
    return out


def keyword_trends(base: str, core_re: str) -> dict:
    core = re.compile(core_re, re.I)
    per = {}
    for m in MONTHS + ["2026-08"]:
        f = f"{base}/keywords/keywords_{m}.json"
        if os.path.exists(f):
            per[m] = {q["word"]: q.get("wb_count") or 0 for q in load(f)["queries"] if core.search(q["word"])}
    if not per:
        return {}
    ms = sorted(per)
    first, last = ms[:3], [m for m in ms if m <= "2026-07"][-3:]
    words = set().union(*[set(per[m]) for m in first + last])
    avg = lambda w, L: st.mean(per[m].get(w, 0) for m in L)
    rows_ = [(w, round(avg(w, first)), round(avg(w, last))) for w in words]
    big = [r for r in rows_ if max(r[1], r[2]) >= 5000]
    rising = sorted([r for r in big if r[1]], key=lambda r: -(r[2] / r[1]))[:15]
    new_q = sorted([r for r in big if r[1] < 500], key=lambda r: -r[2])[:10]
    falling = sorted([r for r in big if r[1]], key=lambda r: r[2] / r[1])[:10]
    totals = {m: sum(per[m].values()) for m in ms}
    top = sorted(rows_, key=lambda r: -(r[1] + r[2]))[:15]
    return {"months_first": first, "months_last": last, "total_by_month": totals, "top": top, "rising": rising,
            "new_queries": new_q, "falling": falling}


# ── B. путь карточек с первого дня ─────────────────────────────────────────────────────────────────────────
def changes(rows_: list[dict], d0: int) -> list[dict]:
    """События после старта: цена ±10 %, реклама вкл/выкл, акция вкл/выкл, дефектура, отзывы 10/50/100/500 → эффект на продажи."""
    ev = []
    R = rows_
    s = [r.get("sales") or 0 for r in R]

    def eff(t):
        a = st.mean(s[max(d0, t - 7):t]) if t - d0 >= 3 else None
        b = st.mean(s[t:t + 7]) if t + 7 <= len(s) else None
        return (round(a, 1) if a is not None else None, round(b, 1) if b is not None else None,
                round(b / a, 2) if a and b is not None and a > 0 else None)
    last = collections.defaultdict(lambda: -99)
    for t in range(d0 + 7, len(R) - 7):
        day = R[t]["data"]
        p0 = [r.get("final_price") for r in R[t - 7:t] if r.get("final_price")]
        p1 = [r.get("final_price") for r in R[t:t + 7] if r.get("final_price")]
        tags = []
        if p0 and p1:
            ch = st.median(p1) / st.median(p0) - 1
            if abs(ch) >= 0.10:
                tags.append(f"цена {'+' if ch > 0 else ''}{ch * 100:.0f}% ({st.median(p0):.0f}→{st.median(p1):.0f} ₽)")
        for flag, on, off in (("in_ads", "реклама ВКЛ", "реклама ВЫКЛ"), ("in_action", "акция ВКЛ", "акция ВЫКЛ")):
            a = [bool(r.get(flag)) for r in R[t - 7:t]]
            b = [bool(r.get(flag)) for r in R[t:t + 7]]
            if sum(a) <= 1 and sum(b) >= 6:
                tags.append(on)
            if sum(a) >= 6 and sum(b) <= 1:
                tags.append(off)
        if R[t - 1].get("balance") and not R[t].get("balance") and not R[t + 1].get("balance"):
            tags.append("закончился остаток")
        for tag in tags:
            key = tag.split(" ")[0] + tag.split(" ")[1] if " " in tag else tag
            if t - last[key] < 10:
                continue
            last[key] = t
            a, b, x = eff(t)
            ev.append({"day": t - d0, "date": day, "event": tag, "sales_before": a, "sales_after": b, "x": x,
                       "reviews": R[t].get("comments"), "pos": R[t].get("search_position_avg")})
    for k in (10, 50, 100, 500, 1000):
        i = next((i for i in range(d0, len(R)) if (R[i].get("comments") or 0) >= k), None)
        if i is not None and i > d0:
            ev.append({"day": i - d0, "date": R[i]["data"], "event": f"{k} отзывов", "sales_before": None,
                       "sales_after": round(st.mean(s[i:i + 7]), 1) if i + 7 <= len(s) else None, "x": None,
                       "reviews": R[i].get("comments"), "pos": R[i].get("search_position_avg")})
    return sorted(ev, key=lambda e: e["day"])


def journeys(niche: int, mk: dict) -> dict:
    from src.launch_collect import SAMPLE, existing, series_path
    from src.launch_patterns import day0
    sample = load(SAMPLE)[str(niche)]
    out = {}
    for grp in ("win", "mid", "ctl"):
        L = []
        for p in sample.get(grp, []):
            f = existing(p["id"], p["sku_first_date"][:10]) or series_path(niche, p["id"])
            if not os.path.exists(f):
                continue
            R = sorted([r for r in rows(f) if isinstance(r, dict) and r.get("data") and r["data"] <= CUT], key=lambda r: r["data"])
            d0 = day0(R, p["sku_first_date"])
            if d0 is None:
                continue
            weeks = []
            for k in range(0, min(30, (len(R) - d0) // 7)):
                w = R[d0 + 7 * k: d0 + 7 * k + 7]
                weeks.append({"wk": k + 1, "sales": round(st.mean(r.get("sales") or 0 for r in w), 1),
                              "price": med([r.get("final_price") for r in w], 0), "list_price": med([r.get("price") for r in w], 0),
                              "ads": round(sum(1 for r in w if r.get("in_ads")) / 7 * 100),
                              "promo": round(sum(1 for r in w if r.get("in_action")) / 7 * 100),
                              "reviews": w[-1].get("comments"), "rating": w[-1].get("commentsvaluation") or w[-1].get("rating"),
                              "pos": med([r.get("search_position_avg") for r in w], 0), "words": med([r.get("search_words_count") for r in w], 0),
                              "oos": sum(1 for r in w if not r.get("balance")), "wh": med([r.get("warehouses_count") for r in w], 0),
                              "neg_pct": med([r.get("latest_negative_comments_percent") for r in w], 1)})
            start_m = R[d0]["data"][:7]
            ctx = mk.get(start_m, {})
            L.append({"id": p["id"], "name": p["name"], "seller": p["seller"], "start": R[d0]["data"], "jul_sales_month": p.get("sales"),
                      "buyer_jul": round(p["revenue"] / p["sales"]) if p.get("sales") else None, "reviews_day0": R[d0].get("comments"),
                      "market_at_entry": {k: ctx.get(k) for k in ("buyer_price_med", "top1_seller", "top1_pct", "new6m_rev_pct", "sellers_ws")},
                      "weeks": weeks, "events": changes(R, d0)})
        out[grp] = L
    return out


def summary(J: dict) -> dict:
    S = {}
    for g, L in J.items():
        wk = {}
        for k in (1, 2, 3, 4, 6, 8, 12, 16, 20, 26):
            W = [c["weeks"][k - 1] for c in L if len(c["weeks"]) >= k]
            if W:
                wk[k] = {f: med([w[f] for w in W]) for f in ("sales", "price", "ads", "promo", "reviews", "pos", "words", "oos", "neg_pct")}
                wk[k]["n"] = len(W)
        ev = collections.Counter()
        effects = collections.defaultdict(list)
        for c in L:
            for e in c["events"]:
                kind = re.sub(r" [+-]?\d+%.*", "", e["event"]) if e["event"].startswith("цена") else e["event"]
                kind = ("цена ↑" if "+" in e["event"] else "цена ↓") if e["event"].startswith("цена") else kind
                ev[kind] += 1
                if e.get("x"):
                    effects[kind].append(e["x"])
        S[g] = {"n": len(L), "weeks": wk, "events": dict(ev),
                "effects_med_x": {k: med(v, 2) for k, v in effects.items()},
                "start_months": collections.Counter(c["start"][:7] for c in L).most_common(),
                "reviews_day0_med": med([c["reviews_day0"] for c in L], 0)}
    return S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, required=True)
    ap.add_argument("--base", default=None)
    a = ap.parse_args()
    from src import strategy as S
    P = S.PRESETS[a.niche]
    base = a.base or os.path.dirname(P["trends"])
    seg = lambda name: P["segment"](P["classify"](name, {}))
    mk = market(base, seg)
    kw = keyword_trends(base, P["core_re"])
    J = journeys(a.niche, mk)
    res = {"niche": a.niche, "market": mk, "keywords": kw, "journeys": J, "summary": summary(J)}
    run = os.environ.get("LAUNCH_RUN", dt.date.today().isoformat())
    out = f"data/processed/evolution_{a.niche}_{run}.json"
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("→", out)


if __name__ == "__main__":
    main()
