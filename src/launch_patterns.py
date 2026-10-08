"""Как заходили победители WB: недельные траектории новичков, типы старта, триггеры взлёта, «алгоритм» (2026-10-08). 0 запросов.

    python -m src.launch_patterns          # → data/processed/launch_patterns_2026-10-08.json + reports/launch_patterns_2026-10-08.xlsx

Вход: data/processed/launch_sample_2026-10-08.json (src.launch_collect select) + дневные ряды wb_sku by_period.
Поля ряда: final_price = цена покупателя (после СПП), price = цена «до скидок», in_ads, in_action, balance, comments, rating,
search_words_count (запросов, где карточка есть в выдаче), search_position_avg, category_position_avg, warehouses_count.
Окно анализа ≤ 2026-07-31: август–сентябрь в Saleflow неполные (остаток 0 при продажах).
День 0 = первый день с продажей не раньше sku_first_date − 7.
"""
from __future__ import annotations

import collections
import json
import os
import statistics as st
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from src.launch_collect import RUN, SAMPLE, existing, series_path

sys.stdout.reconfigure(encoding="utf-8")
CUT = "2026-07-31"
WEEKS = 16
OUT = f"data/processed/launch_patterns_{RUN}.json"
XLSX = f"reports/launch_patterns_{RUN}.xlsx"


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 2) if xs else None


def load(niche: int, p: dict) -> list[dict] | None:
    f = existing(p["id"], p["sku_first_date"][:10]) or series_path(niche, p["id"])
    if not os.path.exists(f):
        return None
    d = json.load(open(f, encoding="utf-8"))
    if not isinstance(d, list):
        return None
    return sorted([r for r in d if r.get("data") and r["data"] <= CUT], key=lambda r: r["data"])


def day0(rows: list[dict], start: str) -> int | None:
    import datetime as dt
    lo = (dt.date.fromisoformat(start[:10]) - dt.timedelta(days=7)).isoformat()
    for i, r in enumerate(rows):
        if r["data"] >= lo and (r.get("sales") or 0) > 0:
            return i
    return None


def week_stats(w: list[dict]) -> dict:
    stock = [r for r in w if r.get("balance")]
    return {
        "sales": mean([r.get("sales") or 0 for r in w]),
        "price": med([r.get("final_price") for r in w if r.get("final_price")]),
        "list_price": med([r.get("price") for r in w if r.get("price")]),
        "ads": round(sum(1 for r in w if r.get("in_ads")) / len(w) * 100),
        "promo": round(sum(1 for r in w if r.get("in_action")) / len(w) * 100),
        "words": med([r.get("search_words_count") for r in w]),
        "pos": med([r.get("search_position_avg") for r in w if r.get("search_position_avg")]),
        "cat_pos": med([r.get("category_position_avg") for r in w if r.get("category_position_avg")]),
        "reviews": w[-1].get("comments"),
        "rating": w[-1].get("commentsvaluation") or w[-1].get("rating"),
        "oos": len(w) - len(stock),
        "wh": med([r.get("warehouses_count") for r in w]),
    }


def launch_type(W: list[dict], rows0: list[dict], niche_p25: float | None) -> str:
    if not W:
        return "—"
    if (rows0[0].get("comments") or 0) >= 50:
        return "склейка (отзывы с 1-го дня)"
    if (W[0]["sales"] or 0) >= 8:
        return "реклама/трафик с 1-й недели" if W[0]["ads"] >= 50 else "сильный старт без рекламы"
    rev21 = W[2]["reviews"] if len(W) > 2 else None
    if rev21 is not None and rev21 >= 50:
        return "отзывы/выкупы (≥ 50 за 21 день)"
    if niche_p25 and W[0]["price"] and W[0]["price"] < niche_p25:
        return "демпинг (цена < P25 ниши)"
    if W[0]["ads"] >= 50:
        return "медленный старт с рекламой"
    return "органика"


def breakouts(rows: list[dict], d0: int) -> list[dict]:
    """Все взлёты (не чаще раза в 28 дней): среднее продаж за 7 дней ≥ max(2 × среднее за 14 дней до, +3) и ≥ 5/день."""
    s = [r.get("sales") or 0 for r in rows]
    found, t = [], d0 + 21
    while t < len(rows) - 7:
        nxt, prv = st.mean(s[t:t + 7]), st.mean(s[t - 14:t])
        if nxt >= 5 and nxt >= max(2 * prv, prv + 3):
            before, at = rows[t - 28:t - 14], rows[t - 7:t + 7]
            if len(before) < 7:
                t += 1
                continue
            def m(L, k, f=mean):
                return f([r.get(k) for r in L if r.get(k) is not None])
            found.append({
                "date": rows[t]["data"], "day": t - d0, "sales_before": round(prv, 1), "sales_after": round(nxt, 1),
                "price_before": m(before, "final_price", med), "price_at": m(at, "final_price", med),
                "ads_before": round(sum(1 for r in before if r.get("in_ads")) / len(before) * 100),
                "ads_at": round(sum(1 for r in at if r.get("in_ads")) / len(at) * 100),
                "promo_before": round(sum(1 for r in before if r.get("in_action")) / len(before) * 100),
                "promo_at": round(sum(1 for r in at if r.get("in_action")) / len(at) * 100),
                "reviews_before": before[-1].get("comments"), "reviews_at": rows[t].get("comments"),
                "words_before": m(before, "search_words_count", med), "words_at": m(at, "search_words_count", med),
                "pos_before": m(before, "search_position_avg", med), "pos_at": m(at, "search_position_avg", med),
                "wh_before": m(before, "warehouses_count", med), "wh_at": m(at, "warehouses_count", med),
                "oos_before": sum(1 for r in before if not r.get("balance")),
            })
            t += 28
        else:
            t += 1
    return found


def spearman(a, b):
    n = len(a)
    if n < 20:
        return None
    def rk(x):
        o = sorted(range(n), key=lambda i: x[i]); r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and x[o[j + 1]] == x[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rk(a), rk(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return round(num / den, 2) if den else None


def correlations(rows: list[dict]) -> dict:
    R = [r for r in rows if r.get("balance") and r.get("search_position_avg")]
    s = [r.get("sales") or 0 for r in R]
    return {
        "sales~position": spearman(s, [-r["search_position_avg"] for r in R]),
        "sales~words": spearman(s, [r.get("search_words_count") or 0 for r in R]),
        "sales~warehouses": spearman(s, [r.get("warehouses_count") or 0 for r in R]),
        "sales~price": spearman(s, [-(r.get("final_price") or 0) for r in R]),
        "position~reviews": spearman([-r["search_position_avg"] for r in R], [r.get("comments") or 0 for r in R]),
    }


def events(rows: list[dict]) -> dict:
    """Включение рекламы / акции, снижение цены ≥ 10%, возврат после ≥ 3 дней без остатка → продажи и позиция 7 дн. до/после."""
    out = collections.defaultdict(list)
    s = [r.get("sales") or 0 for r in rows]
    pos = [r.get("search_position_avg") for r in rows]
    def ratio(t, k=7):
        a, b = s[t - k:t], s[t + 1:t + 1 + k]
        if len(a) < k or len(b) < k or st.mean(a) == 0:
            return None
        pa, pb = [x for x in pos[t - k:t] if x], [x for x in pos[t + 1:t + 1 + k] if x]
        return {"sales_x": round(st.mean(b) / st.mean(a), 2),
                "pos_delta": round(st.median(pb) - st.median(pa)) if pa and pb else None}
    last_cut = -99
    for t in range(8, len(rows) - 8):
        for key, flag in (("ads_on", "in_ads"), ("promo_on", "in_action")):
            if rows[t].get(flag) and not any(rows[i].get(flag) for i in range(t - 7, t)):
                r = ratio(t)
                if r and all(rows[i].get("balance") for i in range(t - 7, t + 8)):
                    out[key].append(r)
        for key, flag in (("ads_off", "in_ads"),):
            if not rows[t].get(flag) and all(rows[i].get(flag) for i in range(t - 7, t)) and not any(rows[i].get(flag) for i in range(t, t + 7)):
                r = ratio(t)
                if r and all(rows[i].get("balance") for i in range(t - 7, t + 8)):
                    out[key].append(r)
        p0 = [r.get("final_price") for r in rows[t - 7:t] if r.get("final_price")]
        p1 = [r.get("final_price") for r in rows[t:t + 7] if r.get("final_price")]
        if p0 and p1 and st.median(p1) <= 0.9 * st.median(p0) and t - last_cut > 14:
            r = ratio(t)
            if r and all(rows[i].get("balance") for i in range(t - 7, t + 8)):
                out["price_cut10"].append(r); last_cut = t
    # остатки: серия ≥ 3 дней без остатка
    t = 14
    while t < len(rows) - 14:
        if not rows[t].get("balance") and s[t - 14:t] and st.mean(s[t - 14:t]) > 0:
            e = t
            while e < len(rows) and not rows[e].get("balance"):
                e += 1
            if e - t >= 3 and e + 14 <= len(rows):
                out["restock"].append({"oos_days": e - t, "sales_x": round(st.mean(s[e:e + 14]) / st.mean(s[t - 14:t]), 2)})
            t = e
        t += 1
    return dict(out)


def main() -> None:
    sample = json.load(open(SAMPLE, encoding="utf-8"))
    from src.launch_collect import products_path, rows as prod_rows
    cards = []
    for n, s in sample.items():
        n = int(n)
        P = [p for p in prod_rows(products_path(n)) if p.get("final_price_average")]
        pr = sorted(p["final_price_average"] for p in P)
        p25 = pr[len(pr) // 4] if pr else None
        p50_top = med([p["final_price_average"] for p in P[:100]])       # медиана цены покупателя top-100 ниши
        for grp in ("win", "ctl", "mid"):
            for p in s.get(grp, []):
                rows = load(n, p)
                if not rows:
                    continue
                d0 = day0(rows, p["sku_first_date"])
                if d0 is None:
                    continue
                W = []
                for k in range(WEEKS):
                    w = rows[d0 + 7 * k: d0 + 7 * k + 7]
                    if len(w) < 7:
                        break
                    W.append(week_stats(w))
                jul = [r.get("sales") or 0 for r in rows if r["data"].startswith("2026-07")]
                cards.append({
                    "niche": n, "niche_name": s["name"], "group": grp, "id": p["id"], "name": p["name"], "seller": p["seller"],
                    "niche_p50": p50_top, "start": rows[d0]["data"], "start_month": rows[d0]["data"][:7], "rank_jul": p["rank"],
                    "jul_per_day": round(st.mean(jul), 1) if jul else None, "weeks": W,
                    "reviews_day0": rows[d0].get("comments"), "launch": launch_type(W, rows[d0:], p25),
                    "breakouts": breakouts(rows, d0), "corr": correlations(rows[d0:]), "events": events(rows[d0:]),
                    "days_to": {k: next((i for i, r in enumerate(rows[d0:]) if (r.get("comments") or 0) >= k), None) for k in (10, 50, 100)},
                })
    json.dump(cards, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"карточек с рядом: {len(cards)} (победителей {sum(c['group'] == 'win' for c in cards)}, контроль {sum(c['group'] == 'ctl' for c in cards)}) → {OUT}")
    write_xlsx(cards)


def write_xlsx(cards: list[dict]) -> None:
    wb = Workbook(); ws = wb.active; ws.title = "Карточки"
    head = ["Ниша", "Группа", "Артикул", "Название", "Продавец", "Старт", "Ранг июль", "Шт/день июль", "Тип старта",
            "Отзывов в день 0", "Дней до 10 отз.", "до 50", "до 100", "Взлёт: дата", "день", "шт/д до → после",
            "Цена до → при", "Реклама % до → при", "Акции % до → при", "Отзывы до → при", "Слов в поиске до → при", "Складов до → при"]
    head += [f"Нед{k} шт/д" for k in range(1, 13)] + [f"Нед{k} цена" for k in (1, 4, 8, 12)] + [f"Нед{k} реклама%" for k in (1, 4, 8, 12)]
    ws.append(head)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496"), Alignment(wrap_text=True)
    for c in sorted(cards, key=lambda c: (c["niche"], c["group"] != "win", -(c["jul_per_day"] or 0))):
        b, W = (c["breakouts"] or [{}])[0], c["weeks"]
        g = lambda k, f: W[k - 1][f] if len(W) >= k else None
        ws.append([f"{c['niche']} {c['niche_name']}", "победитель" if c["group"] == "win" else "контроль", c["id"], c["name"], c["seller"],
                   c["start"], c["rank_jul"], c["jul_per_day"], c["launch"], c["reviews_day0"], *[c["days_to"][k] for k in (10, 50, 100)],
                   b.get("date"), b.get("day"), f"{b['sales_before']} → {b['sales_after']}" if b else None,
                   f"{b['price_before']} → {b['price_at']}" if b else None, f"{b['ads_before']} → {b['ads_at']}" if b else None,
                   f"{b['promo_before']} → {b['promo_at']}" if b else None, f"{b['reviews_before']} → {b['reviews_at']}" if b else None,
                   f"{b['words_before']} → {b['words_at']}" if b else None, f"{b['wh_before']} → {b['wh_at']}" if b else None,
                   *[g(k, "sales") for k in range(1, 13)], *[g(k, "price") for k in (1, 4, 8, 12)], *[g(k, "ads") for k in (1, 4, 8, 12)]])
    ws.freeze_panes = "D2"
    for i, w in enumerate([22, 11, 11, 36, 22, 11, 8, 8, 26] + [8] * 60, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    wb.save(XLSX)
    print("→", XLSX)


if __name__ == "__main__":
    main()
