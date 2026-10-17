"""Какие именно товары выигрывают у новичков в прошедших нишах niche_nocargo (2026-10-17). 0 запросов.

    python -m src.niche_picks [дата nocargo]   # → data/processed/niche_picks_<дата>.json

Для каждой ✅ (и сильных 🟡) ниши берём лучшую ценовую полосу из niche_nocargo и products500 (июль 2026, Saleflow):
новички полосы (первый день карточки 2025-08…2026-05), победители ≥ 5 шт/день с поправкой на сезон, слова в названиях,
которые чаще встречаются у победителей, чем у всех карточек полосы (lift), копии брендов, габарит упаковки из products500,
рейтинг/отзывы. Имена продавцов не выводим — только число разных продавцов.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import statistics as st
import sys

from src import niche_v5 as V

sys.stdout.reconfigure(encoding="utf-8")
DAY = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
SRC = f"data/processed/niche_nocargo_{DAY}.json"
OUT = f"data/processed/niche_picks_{DAY}.json"
STOP = set("для и в с на по от из к до шт набор комплект 1 2 3 4 5 подарок женские мужские женский мужской детей новый".split())
COPY = re.compile(r"a\.?pods|airpods|apple|iphone|xiaomi|redmi|samsung|galaxy|huawei|honor|jbl|sony|marshall|dyson|philips|braun|"
                  r"garmin|amazfit|casio|rolex|g-?shock|anker|baseus|ugreen|bosch|makita|xiaomi|lelo|satisfyer|womanizer", re.I)


def words(name: str) -> set[str]:
    return {w for w in re.findall(r"[а-яёa-z0-9]+", name.lower()) if len(w) > 2 and w not in STOP}


def per_day(x, k):
    return x["sales"] / 31 / k


def vol(x):
    d = [x.get(f"package_{s}") for s in ("length", "width", "height")]
    return round(d[0] * d[1] * d[2] / 1000, 2) if all(d) else None


def pick(r: dict) -> dict:
    n = r["id"]
    R = [x for x in V.rows(V.p500(n)) if x.get("sales") and x.get("revenue")]
    k = V.season_k(n)
    lo, hi = r["best"]["band"]
    B = [x for x in R if lo <= x["revenue"] / x["sales"] < hi]
    new = [x for x in B if V.NEW[0] <= (x.get("sku_first_date") or "") <= V.NEW[1]]
    win = sorted([x for x in new if per_day(x, k) >= 5], key=lambda x: -x["sales"])
    lose = [x for x in new if per_day(x, k) < 2]
    cw, ca = collections.Counter(), collections.Counter()
    for x in win:
        cw.update(words(x["name"]))
    for x in B:
        ca.update(words(x["name"]))
    lift = sorted(((w, c, round(c / len(win) / (ca[w] / len(B)), 1)) for w, c in cw.items() if c >= max(2, len(win) // 4)),
                  key=lambda t: (-t[2] * t[1]))[:8] if win else []
    vols = [v for v in (vol(x) for x in win) if v]
    rat = [x["rating"] for x in win if x.get("rating")]
    return {"id": n, "name": r["name"].split(" / ")[-1], "status": r["status"][:2], "strict": r.get("strict"), "band": [lo, hi],
            "season_k": round(k, 2), "cards_band": len(B), "newcomers": len(new), "winners": len(win), "losers_lt2": len(lose),
            "win_rate_pct": round(len(win) / len(new) * 100) if new else None,
            "win_sellers": len({x.get("supplier_id") for x in win}),
            "win_copy_pct": round(sum(1 for x in win if COPY.search(x["name"])) / len(win) * 100) if win else None,
            "band_copy_pct": round(sum(x["revenue"] for x in B if COPY.search(x["name"])) / (sum(x["revenue"] for x in B) or 1) * 100),
            "win_vol_med": round(st.median(vols), 2) if vols else None, "win_rating_med": st.median(rat) if rat else None,
            "win_price_med": round(st.median(x["revenue"] / x["sales"] for x in win)) if win else None,
            "win_comments_med": round(st.median(x.get("comments") or 0 for x in win)) if win else None,
            "lift_words": lift, "margin_drr15": r.get("margin_drr15"), "stress": r.get("stress_margin"),
            "max_yuan_drr10": r["best"].get("max_yuan_drr10"), "vol_l": r.get("vol_l"), "dims_src": r.get("dims_src"),
            "net_12m_p50": ((r.get("finplan") or {}).get("p50") or {}).get("net_12m"), "flags": r.get("flags"),
            "top_winners": [{"id": x["id"], "name": x["name"][:70], "per_day": round(per_day(x, k), 1), "price": round(x["revenue"] / x["sales"]),
                             "start": x.get("sku_first_date"), "comments": x.get("comments"), "rating": x.get("rating"), "vol_l": vol(x),
                             "copy": bool(COPY.search(x["name"]))} for x in win[:8]]}


def main():
    O = json.load(open(SRC, encoding="utf-8"))
    sel = [r for r in O if r["status"][0] == "✅" or (r["status"][0] == "🟡" and (r.get("margin_drr15") or 0) >= 15)]
    out = [pick(r) for r in sel]
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for p in out:
        print(f"\n## {p['id']} {p['name']} {p['status']}{' S' if p['strict'] else ''} | {p['band']} | новичков {p['newcomers']}, "
              f"победителей {p['winners']} ({p['win_rate_pct']}%), продавцов-победителей {p['win_sellers']}, копии брендов: победители "
              f"{p['win_copy_pct']}% / выручка полосы {p['band_copy_pct']}% | V {p['win_vol_med']} л, рейтинг {p['win_rating_med']}, "
              f"отзывов {p['win_comments_med']} | маржа {p['margin_drr15']} / стресс {p['stress']} | max¥ {p['max_yuan_drr10']} | P50 {p['net_12m_p50']}")
        print("   слова:", ", ".join(f"{w}×{c} (lift {l})" for w, c, l in p["lift_words"]))
        for t in p["top_winners"]:
            print(f"   {t['id']} {t['per_day']}/д {t['price']}₽ с {t['start']} отз {t['comments']} V {t['vol_l']}{' КОПИЯ' if t['copy'] else ''} — {t['name']}")


if __name__ == "__main__":
    main()
