"""Динамика ниши по месяцам (май–октябрь 2026) по карточкам топ-500 Saleflow: держатся ли победители, сколько продавцов
реально зарабатывают каждый месяц, чем взлетевшие новички отличаются от провалившихся. 0 запросов (файлы уже скачаны).

    python -m src.niche_months 1717 --include "триммер" --price 1800 2800
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def load(sid: int, m: str) -> list[dict]:
    for p in (f"data/raw/saleflow/2026-11-01/monthly/{sid}_{m}.json",
              *( [f"data/raw/saleflow/v3_products500/{sid}.json"] if m == "2026-07" else []),
              *( [f"data/raw/saleflow/2026-11-01/p500/{sid}.json"] if m == "2026-10" else [])):
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            return (d.get("data") if isinstance(d, dict) else d) or []
    return []


def run(sid: int, include: str | None, price: tuple[int, int]) -> dict:
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0          # noqa: E731
    ok = lambda r: price[0] <= P(r) < price[1] and (not include or re.search(include, r.get("name") or "", re.I))   # noqa: E731
    seg = {m: [r for r in load(sid, m) if ok(r)] for m in MONTHS}
    rows, cards = [], collections.defaultdict(dict)
    for m in MONTHS:
        s = seg[m]
        for r in s:
            cards[r["id"]][m] = r
        bysel = collections.Counter()
        for r in s:
            bysel[r.get("seller")] += r.get("revenue") or 0
        rows.append(dict(m=m, cards=len(s), sales=sum(r.get("sales") or 0 for r in s), rev=round(sum(r.get("revenue") or 0 for r in s) / 1e6, 1),
                         price=round(st.median(P(r) for r in s)) if s else 0,
                         cards100=sum(1 for r in s if (r.get("revenue") or 0) >= 100_000),
                         sellers100=sum(1 for v in bysel.values() if v >= 100_000), sellers=len(bysel),
                         new=sum(1 for r in s if (r.get("sku_first_date") or "") >= f"{m[:4]}-{int(m[5:]) - 3:02d}")))
    # удержание: карточки с ≥ 100 тыс. в мае — сколько ещё ≥ 100 тыс. в октябре
    may = [i for i, d in cards.items() if (d.get("2026-05", {}).get("revenue") or 0) >= 100_000]
    kept = [i for i in may if (cards[i].get("2026-10", {}).get("revenue") or 0) >= 100_000]
    # новички: старт 05–08.2026, судьба к октябрю
    newc = [d for d in cards.values() if any("2026-05" <= (r.get("sku_first_date") or "") <= "2026-08-31" for r in d.values())]
    win = [d for d in newc if (d.get("2026-10", {}).get("revenue") or 0) >= 150_000]
    lose = [d for d in newc if d not in win]
    def feat(group):
        last = [d[max(d)] for d in group]
        f = lambda k: round(st.median((r.get(k) or 0) for r in last), 1) if last else 0                 # noqa: E731
        return dict(n=len(group), price=f("final_price"), comments=f("comments"), rating=f("rating"), pics=f("picscount"),
                    video=round(sum(1 for r in last if r.get("hasvideo")) / len(last) * 100) if last else 0,
                    words=f("search_words_count"), stock_days=f("days_in_stock"), warehouses=f("warehouses_count"),
                    spp=f("spp_avg"), china=round(sum(1 for r in last if r.get("country") == "Китай") / len(last) * 100) if last else 0)
    top_new = sorted(win, key=lambda d: -(d["2026-10"].get("revenue") or 0))[:6]
    traj = [dict(id=d["2026-10"]["id"], name=d["2026-10"]["name"][:45], start=d["2026-10"].get("sku_first_date"), seller=d["2026-10"].get("seller"),
                 price=round(P(d["2026-10"])), sales=[(d.get(m) or {}).get("sales") for m in MONTHS],
                 comments=d["2026-10"].get("comments"), rating=d["2026-10"].get("rating")) for d in top_new]
    return dict(sid=sid, months=rows, may_winners=len(may), still_oct=len(kept), new=len(newc), win=feat(win), lose=feat(lose), top_new=traj)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sid", type=int)
    ap.add_argument("--include")
    ap.add_argument("--price", type=int, nargs=2, default=[0, 10 ** 7])
    a = ap.parse_args()
    r = run(a.sid, a.include, tuple(a.price))
    json.dump(r, open(f"data/processed/niche_months_{a.sid}_2026-11-01.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"== {a.sid} {a.include} {a.price}")
    for x in r["months"]:
        print(f"  {x['m']}: карточек {x['cards']:>3} продажи {x['sales']:>6} выручка {x['rev']:>6} млн медиана {x['price']} ₽ | карточек ≥100т {x['cards100']:>3} | продавцов ≥100т {x['sellers100']:>3} из {x['sellers']}")
    print(f"  удержание: в мае ≥100 тыс. {r['may_winners']} карточек → в октябре ещё ≥100 тыс. {r['still_oct']}")
    print(f"  новички 05–08.2026: {r['new']} → взлетели (≥150 тыс. в окт) {r['win']['n']}")
    print(f"  победители: {r['win']}")
    print(f"  не взлетели: {r['lose']}")
    for t in r["top_new"]:
        print(f"   {t['id']} {t['name']} | старт {t['start']} | {t['price']} ₽ | продажи май→окт {t['sales']} | отзывов {t['comments']} ★{t['rating']} | {t['seller']}")


if __name__ == "__main__":
    main()
