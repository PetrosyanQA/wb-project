"""Сводка по data/processed/launch_patterns_2026-10-08.json: победители vs контроль, триггеры взлёта, «алгоритм». 0 запросов.

    python -m src.launch_summary            # таблицы в stdout + data/processed/launch_summary_2026-10-08.json
"""
from __future__ import annotations

import collections
import json
import statistics as st
import sys

from src.launch_patterns import OUT as CARDS, RUN

sys.stdout.reconfigure(encoding="utf-8")
OUT = f"data/processed/launch_summary_{RUN}.json"


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None


def share(xs, cond):
    xs = list(xs)
    return round(sum(1 for x in xs if cond(x)) / len(xs) * 100) if xs else None


def weekly(cards, field, weeks=(1, 2, 3, 4, 6, 8, 12, 16)):
    return {w: med([c["weeks"][w - 1][field] for c in cards if len(c["weeks"]) >= w]) for w in weeks}


def main() -> None:
    C = json.load(open(CARDS, encoding="utf-8"))
    G = {g: [c for c in C if c["group"] == g] for g in ("win", "mid", "ctl")}
    S = {"n": {g: len(v) for g, v in G.items()},
         "n_by_niche": {f"{n} {nm}": {g: sum(1 for c in G[g] if c["niche"] == n) for g in G}
                        for n, nm in sorted({(c["niche"], c["niche_name"]) for c in C})}}
    print("Карточек:", S["n"], S["n_by_niche"])

    for c in C:                                   # цена недели относительно медианы top-100 ниши
        for w in c["weeks"]:
            w["price_rel"] = round(w["price"] / c["niche_p50"], 2) if w["price"] and c.get("niche_p50") else None
    S["weekly"] = {f: {g: weekly(v, f) for g, v in G.items()} for f in ("price_rel",)}
    S["weekly"] |= {f: {g: weekly(v, f) for g, v in G.items()} for f in ("sales", "price", "ads", "promo", "words", "pos", "reviews", "wh", "oos")}
    for f, d in S["weekly"].items():
        print(f"\n{f}:"); [print(f"  {g}: {w}") for g, w in d.items()]

    # Цена недели 1 относительно цены недели 12 (стартовая скидка)
    S["price_w1_vs_w8"] = {g: med([c["weeks"][0]["price"] / c["weeks"][7]["price"] for c in v
                                   if len(c["weeks"]) >= 8 and c["weeks"][0]["price"] and c["weeks"][7]["price"]]) for g, v in G.items()}
    print("\nЦена нед.1 / нед.8:", S["price_w1_vs_w8"])

    S["launch_types"] = {g: dict(collections.Counter(c["launch"] for c in v).most_common()) for g, v in G.items()}
    print("\nТипы старта:", json.dumps(S["launch_types"], ensure_ascii=False, indent=1))

    S["days_to_reviews"] = {g: {k: med([c["days_to"][str(k)] if str(k) in c["days_to"] else c["days_to"].get(k) for c in v]) for k in (10, 50, 100)}
                            for g, v in G.items()}
    S["reach_50_reviews_pct"] = {g: share(v, lambda c: (c["days_to"].get("50") if "50" in c["days_to"] else c["days_to"].get(50)) is not None) for g, v in G.items()}
    print("\nДней до N отзывов (медиана):", S["days_to_reviews"], "| дошли до 50:", S["reach_50_reviews_pct"])
    S["reviews_day0_ge50_pct"] = {g: share(v, lambda c: (c["reviews_day0"] or 0) >= 50) for g, v in G.items()}
    print("Склейка (≥ 50 отзывов в день 0), %:", S["reviews_day0_ge50_pct"])

    S["start_months"] = {g: dict(sorted(collections.Counter(c["start_month"] for c in v).items())) for g, v in G.items()}
    print("\nМесяц старта:", S["start_months"])

    # Взлёты
    B = [dict(b, niche=c["niche"], id=c["id"], group=c["group"]) for c in C for b in c["breakouts"]]
    BW = [b for b in B if b["group"] == "win"]
    def trig(b):
        t = []
        if b["ads_at"] - b["ads_before"] >= 30: t.append("реклама включена/усилена")
        if b["promo_at"] - b["promo_before"] >= 30: t.append("акция")
        if b["price_before"] and b["price_at"] and b["price_at"] <= 0.95 * b["price_before"]: t.append("цена −5%+")
        if b["price_before"] and b["price_at"] and b["price_at"] >= 1.05 * b["price_before"]: t.append("цена +5%+")
        if (b["reviews_before"] or 0) < 50 <= (b["reviews_at"] or 0) or ((b["reviews_at"] or 0) >= 2 * max(b["reviews_before"] or 0, 5)): t.append("скачок отзывов")
        if b["wh_before"] and b["wh_at"] and b["wh_at"] >= b["wh_before"] + 2: t.append("больше складов")
        if b["oos_before"] >= 3: t.append("возврат после дефектуры")
        if b["pos_before"] and b["pos_at"] and b["pos_at"] <= 0.7 * b["pos_before"]: t.append("позиция в поиске ↑30%+")
        return t or ["без явной причины"]
    tc = collections.Counter(x for b in BW for x in trig(b))
    S["breakouts"] = {"n_win_events": len(BW), "n_ctl_events": len(B) - len(BW),
                      "cards_with_breakout_pct": {g: share(v, lambda c: bool(c["breakouts"])) for g, v in G.items()},
                      "first_breakout_day_med": {g: med([c["breakouts"][0]["day"] for c in v if c["breakouts"]]) for g, v in G.items()},
                      "triggers_pct": {k: round(v / len(BW) * 100) for k, v in tc.most_common()} if BW else {},
                      "sales_jump_med": med([b["sales_after"] / b["sales_before"] for b in BW if b["sales_before"]])}
    print("\nВзлёты:", json.dumps(S["breakouts"], ensure_ascii=False, indent=1))

    # События и корреляции
    S["events"] = {}
    for g, v in G.items():
        ev = collections.defaultdict(list)
        for c in v:
            for k, L in c["events"].items():
                ev[k] += L
        S["events"][g] = {k: {"n": len(L), "sales_x_med": med([e["sales_x"] for e in L]),
                              "pos_delta_med": med([e.get("pos_delta") for e in L]),
                              **({"oos_days_med": med([e["oos_days"] for e in L])} if k == "restock" else {})}
                          for k, L in ev.items()}
    print("\nСобытия:", json.dumps(S["events"], ensure_ascii=False, indent=1))
    S["corr"] = {g: {k: med([c["corr"][k] for c in v]) for k in C[0]["corr"]} for g, v in G.items()}
    print("\nКорреляции (медиана по карточкам):", S["corr"])

    # 777 отдельно
    S["n777"] = {g: {"weekly_sales": weekly([c for c in v if c["niche"] == 777], "sales"),
                     "weekly_ads": weekly([c for c in v if c["niche"] == 777], "ads"),
                     "weekly_price": weekly([c for c in v if c["niche"] == 777], "price"),
                     "weekly_reviews": weekly([c for c in v if c["niche"] == 777], "reviews"),
                     "weekly_wh": weekly([c for c in v if c["niche"] == 777], "wh")} for g, v in G.items()}
    print("\n777:", json.dumps(S["n777"], ensure_ascii=False, indent=1))
    json.dump(S, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", OUT)


if __name__ == "__main__":
    main()
