"""Глубокий недельный разбор ниш (2026-10-16). 0 запросов — читает то, что скачал src.weekly_collect.

    python -m src.weekly_analysis      # → data/processed/weekly_niches_2026-10-16.json + reports/weekly_niches_2026-10-16.xlsx

Ниша (by_date, дневные ряды → ISO-недели):
  год-2 = 2025-08-04 … 2026-07-26 (52 недели), год-1 = те же недели годом раньше;
  YoY продаж за год и за последние 13 недель; недельная сезонность и пики (с датами); волатильность (CV);
  конкуренция: продавцов с продажами, продаж на 1 активного продавца («пирог на продавца») YoY;
  цена продажи (avg_sale_price) YoY; запас (balance / недельные продажи) YoY; рейтинг ниши;
  окно запуска: индекс сезона январь–март.
История (trends с 2020): продажи по годам.
Подтипы ниши 52 (дневные ряды топ-10 карточек): продажи по неделям, цена, доля дней с рекламой/акцией, дни без остатка.
⚠️ 2025-09 Saleflow сменил методику продаж — YoY через сентябрь 2025 читать как ориентир, не как факт до процента.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import statistics as st
import sys

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

sys.stdout.reconfigure(encoding="utf-8")
BASE = "data/raw/saleflow/2026-10-16/weekly"
OUT = "data/processed/weekly_niches_2026-10-16.json"
XLSX = "reports/weekly_niches_2026-10-16.xlsx"
Y2 = (dt.date(2025, 8, 4), dt.date(2026, 7, 26))          # 52 полные ISO-недели (пн–вс)
HOLIDAYS = {"11.11": "11-11", "Чёрная пятница": "11-28", "Новый год": "12-24", "14 февраля": "02-14", "23 февраля": "02-23",
            "8 марта": "03-08", "1 сентября": "09-01"}


def load(p):
    return json.load(open(p, encoding="utf-8"))


def daily_niche(n: int) -> dict[str, dict]:
    D = {}
    for f in glob.glob(f"{BASE}/{n}/by_date_*.json"):
        d = load(f)
        for r in (d.get("data", d) if isinstance(d, dict) else d):
            if isinstance(r, dict) and r.get("period"):
                D[r["period"]] = r
    return D


def monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def weeks(D: dict[str, dict], start: dt.date, n: int = 52) -> list[dict]:
    out = []
    for k in range(n):
        a = start + dt.timedelta(weeks=k)
        days = [D.get((a + dt.timedelta(days=i)).isoformat()) for i in range(7)]
        days = [x for x in days if x]
        if len(days) < 5:
            out.append({"week": a.isoformat(), "days": len(days)})
            continue
        f = 7 / len(days)
        mean = lambda key: st.mean(x.get(key) or 0 for x in days)
        out.append({"week": a.isoformat(), "days": len(days), "sales": round(sum(x.get("sales") or 0 for x in days) * f),
                    "revenue": round(sum(x.get("revenue") or 0 for x in days) * f),
                    "sellers_ws": round(mean("sellers_with_sells")), "items_ws": round(mean("items_with_sells")),
                    "sellers": round(mean("sellers")), "price": round(mean("avg_sale_price")), "balance": round(mean("balance")),
                    "rating": round(mean("rating"), 2)})
    return out


def pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def niche_report(n: int, name: str) -> dict | None:
    D = daily_niche(n)
    if not D:
        return None
    w2 = weeks(D, Y2[0])
    w1 = weeks(D, Y2[0] - dt.timedelta(weeks=52))
    ok2 = [w for w in w2 if "sales" in w]
    ok1 = [w for w in w1 if "sales" in w]
    if len(ok2) < 40:
        return {"id": n, "name": name, "error": f"мало недель: {len(ok2)}"}
    s2, s1 = sum(w["sales"] for w in ok2), sum(w["sales"] for w in ok1)
    pair = [(a, b) for a, b in zip(w2, w1) if "sales" in a and "sales" in b]
    last13 = pair[-13:]
    mean2 = st.mean(w["sales"] for w in ok2)
    idx = {w["week"]: round(w["sales"] / mean2 * 100) for w in ok2}
    peaks = sorted(ok2, key=lambda w: -w["sales"])[:5]
    trough = sorted(ok2, key=lambda w: w["sales"])[:3]
    jan_mar = [idx[w["week"]] for w in ok2 if w["week"][5:7] in ("01", "02", "03")]
    pie2 = [w["sales"] / max(w["sellers_ws"], 1) for w in ok2]
    pie1 = [w["sales"] / max(w["sellers_ws"], 1) for w in ok1]
    stock2 = [w["balance"] / max(w["sales"], 1) for w in ok2]
    stock1 = [w["balance"] / max(w["sales"], 1) for w in ok1]
    trimmed = sorted(w["sales"] for w in ok2)[:-4]                     # без 4 пиковых недель
    hol = {}
    for h, md in HOLIDAYS.items():
        for w in ok2:
            a = dt.date.fromisoformat(w["week"])
            if any((a + dt.timedelta(days=i)).strftime("%m-%d") == md for i in range(7)):
                hol[h] = {"week": w["week"], "index": idx[w["week"]]}
    T = load(f"{BASE}/{n}/trends_full.json") if os.path.exists(f"{BASE}/{n}/trends_full.json") else []
    T = T.get("data", T) if isinstance(T, dict) else T
    years = collections.defaultdict(int)
    for r in T:
        if isinstance(r, dict) and r.get("label_date", "") <= "2026-07":
            years[r["label_date"][:4]] += r.get("sales") or 0
    return {
        "id": n, "name": name, "weeks2": len(ok2), "weeks1": len(ok1),
        "sales_y2": s2, "sales_y1": s1, "yoy_sales": pct(s2, s1),
        "revenue_y2_mln": round(sum(w["revenue"] for w in ok2) / 1e6), "yoy_revenue": pct(sum(w["revenue"] for w in ok2), sum(w["revenue"] for w in ok1)),
        "yoy_last13": pct(sum(a["sales"] for a, _ in last13), sum(b["sales"] for _, b in last13)),
        "sales_per_week_y2": round(mean2), "cv_weekly_pct": round(st.pstdev(trimmed) / st.mean(trimmed) * 100),
        "peaks": [(w["week"], idx[w["week"]]) for w in peaks], "troughs": [(w["week"], idx[w["week"]]) for w in trough],
        "holidays": hol, "launch_jan_mar_index": round(st.mean(jan_mar)) if jan_mar else None,
        "sellers_ws_y2": round(st.mean(w["sellers_ws"] for w in ok2)), "sellers_ws_y1": round(st.mean(w["sellers_ws"] for w in ok1)) if ok1 else None,
        "yoy_sellers_ws": pct(st.mean(w["sellers_ws"] for w in ok2), st.mean(w["sellers_ws"] for w in ok1)) if ok1 else None,
        "sellers_total_last": ok2[-1]["sellers"], "sellers_total_first": ok2[0]["sellers"],
        "pie_per_seller_y2": round(st.mean(pie2), 1), "yoy_pie_per_seller": pct(st.mean(pie2), st.mean(pie1)) if pie1 else None,
        "price_y2": round(st.mean(w["price"] for w in ok2)), "yoy_price": pct(st.mean(w["price"] for w in ok2), st.mean(w["price"] for w in ok1)) if ok1 else None,
        "stock_weeks_y2": round(st.median(stock2), 1), "stock_weeks_y1": round(st.median(stock1), 1) if stock1 else None,
        "rating": round(st.mean(w["rating"] for w in ok2), 2), "years": dict(sorted(years.items())),
        "weekly": [{"week": a["week"], "y2": a.get("sales"), "y1": b.get("sales"), "sellers_ws": a.get("sellers_ws"), "price": a.get("price")}
                   for a, b in zip(w2, w1)],
    }


def seg52() -> dict:
    from src.weekly_collect import seg_cards
    out = {}
    for seg, skus in seg_cards().items():
        D = collections.defaultdict(lambda: {"sales": 0, "prices": [], "ads": 0, "promo": 0, "oos": 0, "n": 0})
        used = 0
        for sku in skus:
            rows = []
            for f in glob.glob(f"{BASE}/seg52/{sku}_*.json"):
                d = load(f)
                rows += [r for r in (d if isinstance(d, list) else d.get("data", [])) if isinstance(r, dict) and r.get("data")]
            if not rows:
                continue
            used += 1
            for r in rows:
                day = dt.date.fromisoformat(r["data"])
                if not (Y2[0] <= day <= Y2[1] + dt.timedelta(days=6)):
                    continue
                w = monday(day).isoformat()
                D[w]["sales"] += r.get("sales") or 0
                if r.get("final_price"):
                    D[w]["prices"].append(r["final_price"])
                D[w]["ads"] += 1 if r.get("in_ads") else 0
                D[w]["promo"] += 1 if r.get("in_action") else 0
                D[w]["oos"] += 0 if r.get("balance") else 1
                D[w]["n"] += 1
        W = [{"week": w, "sales": v["sales"], "price": round(st.median(v["prices"])) if v["prices"] else None,
              "ads_pct": round(v["ads"] / max(v["n"], 1) * 100), "promo_pct": round(v["promo"] / max(v["n"], 1) * 100),
              "oos_pct": round(v["oos"] / max(v["n"], 1) * 100)} for w, v in sorted(D.items())]
        if not W:
            out[seg] = {"cards": used}
            continue
        h1, h2 = W[:26], W[26:52]
        m = st.mean(x["sales"] for x in W[:52])
        out[seg] = {"cards": used, "sales_per_week": round(m), "h2_vs_h1": pct(sum(x["sales"] for x in h2), sum(x["sales"] for x in h1)),
                    "price_first8": round(st.median(x["price"] for x in W[:8] if x["price"])), "price_last8": round(st.median(x["price"] for x in W[-8:] if x["price"])),
                    "ads_pct": round(st.mean(x["ads_pct"] for x in W)), "promo_pct": round(st.mean(x["promo_pct"] for x in W)),
                    "oos_pct": round(st.mean(x["oos_pct"] for x in W)),
                    "peaks": [(x["week"], round(x["sales"] / m * 100)) for x in sorted(W[:52], key=lambda x: -x["sales"])[:4]],
                    "weekly": W}
    return out


def main() -> None:
    from src.weekly_collect import NICHES
    R = [r for r in (niche_report(n, name) for n, name in NICHES.items()) if r]
    S = seg52()
    json.dump({"niches": R, "seg52": S}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка"
    cols = ["id", "Ниша", "Продажи год-2, шт", "YoY продаж %", "YoY посл. 13 нед %", "Выручка год-2, млн ₽", "Продавцов с продажами",
            "YoY продавцов %", "Продаж на продавца/нед", "YoY на продавца %", "Цена продажи ₽", "YoY цены %", "Запас, нед (год-2 / год-1)",
            "CV недель %", "Индекс янв–мар", "Рейтинг"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496")
    for r in R:
        if "error" in r:
            ws.append([r["id"], r["name"], r["error"]])
            continue
        ws.append([r["id"], r["name"], r["sales_y2"], r["yoy_sales"], r["yoy_last13"], r["revenue_y2_mln"], r["sellers_ws_y2"], r["yoy_sellers_ws"],
                   r["pie_per_seller_y2"], r["yoy_pie_per_seller"], r["price_y2"], r["yoy_price"], f"{r['stock_weeks_y2']} / {r['stock_weeks_y1']}",
                   r["cv_weekly_pct"], r["launch_jan_mar_index"], r["rating"]])
    for r in R:
        if "weekly" not in r:
            continue
        sh = wb.create_sheet(str(r["id"]))
        sh.append(["Неделя (пн)", "Продажи год-2", "Продажи год-1 (та же неделя)", "Продавцов с продажами", "Цена продажи ₽"])
        for w in r["weekly"]:
            sh.append([w["week"], w["y2"], w["y1"], w["sellers_ws"], w["price"]])
    for seg, v in S.items():
        if "weekly" not in v:
            continue
        sh = wb.create_sheet(f"52 {seg}".replace("/", "-")[:31])
        sh.append(["Неделя", "Продажи топ-10", "Цена покупателя ₽", "Реклама % дней", "Акция % дней", "Без остатка % дней"])
        for w in v["weekly"]:
            sh.append([w["week"], w["sales"], w["price"], w["ads_pct"], w["promo_pct"], w["oos_pct"]])
    wb.save(XLSX)
    print("→", OUT, XLSX)


if __name__ == "__main__":
    main()
