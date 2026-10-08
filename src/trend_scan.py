"""12+ ամսվա դինամիկա՝ տրենդ, սեզոնայնություն, հագեցում, մուտքի պատուհան.

  python -m src.trend_scan --path "Автотовары/Органайзеры" --days 540 --snapshots 4
  python -m src.trend_scan --demo

Ի՞նչ է քաշում և ինչ է համեմատում.
  1. ՕՐԱԿԱՆ ՇԱՐՔ (by_date) 540 օր → 2 հարցում (API-ն տալիս է max 500 տող)
     → ամսական ագրեգացիա, տրենդի թեքություն, YoY, սեզոնային ինդեքս, տատանողականություն
  2. ԿՏՐՎԱԾՔՆԵՐ (items) 4 ամսաթվի վրա → 4 հարցում
     → SKU-ների քանակ, ₽/քարտ, տոպ-10 բաժին, մեդիան գին — ՄԵԿ ՏԱՐՎԱ ԸՆԹԱՑՔՈՒՄ
     → սա է ցույց տալիս հագեցումը. շրջանառությունը աճում է, բայց քարտի փողը՝ ընկնում
  3. Ամեն գործարկում պահվում է SQLite-ում (data/history.db) → քո սեփական պատմությունը
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

from .fields import fnum, median, parse_date, pick
from .mpstats_client import MpstatsClient, rows
from .scoring import niche_metrics

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DB = ROOT / "data" / "history.db"
CHUNK_DAYS = 450                      # API-ն 500 տողից ավել չի տալիս
MONTHS_RU = ["", "հունվ", "փետր", "մարտ", "ապր", "մայ", "հուն",
             "հուլ", "օգոս", "սեպտ", "հոկտ", "նոյ", "դեկտ"]


# ─────────────────────────────────────────────────────────── տվյալների քաշում
def fetch_daily(client: MpstatsClient, path: str, days: int, kind: str = "category") -> list[dict]:
    """Օրական շարք՝ կտորներով (API-ի 500 տողի սահմանափակման պատճառով)."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    out: list[dict] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        if kind == "subject":
            data = client.subject_report(path, "by_date", str(cursor), str(chunk_end), limit=500)
        else:
            data = client.category_report(path, "by_date", str(cursor), str(chunk_end),
                                          limit=500, sort_by=None)
        out.extend(rows(data))
        cursor = chunk_end + timedelta(days=1)
    series = []
    for row in out:
        day = parse_date(pick(row, "date"))
        if day:
            series.append({"date": day, "revenue": fnum(row, "revenue"),
                           "sales": fnum(row, "sales"), "sku": fnum(row, "sku_total") or fnum(row, "items")})
    series.sort(key=lambda r: r["date"])
    return series


def fetch_snapshots(client: MpstatsClient, path: str, count: int, span_days: int,
                    kind: str = "category") -> list[dict]:
    """N հատ 30-օրյա «լուսանկար» անցյալի տարբեր կետերում → կառուցվածքի փոփոխությունը."""
    snaps = []
    step = max(30, span_days // max(count - 1, 1))
    for i in range(count):
        offset = span_days - i * step
        d2 = date.today() - timedelta(days=max(offset, 1))
        d1 = d2 - timedelta(days=29)
        try:
            if kind == "subject":
                items = rows(client.subject_report(path, "items", str(d1), str(d2), limit=500))
            else:
                items = rows(client.category_report(path, "items", str(d1), str(d2), limit=500))
        except Exception as exc:                                   # noqa: BLE001
            print(f"[skip snapshot {d1}] {exc}")
            continue
        if not items:
            continue
        m = niche_metrics(items)
        snaps.append({"period": f"{d1} … {d2}", "end": str(d2), **{
            k: m[k] for k in ("sku_total", "sku_with_sales", "total_revenue",
                              "revenue_per_selling_sku", "top10_revenue_share",
                              "median_price", "median_comments_top", "sellers_total")}})
    return snaps


# ────────────────────────────────────────────────────────────────── հաշվարկներ
def monthly(series: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in series:
        buckets[row["date"].strftime("%Y-%m")].append(row)
    out = []
    for key in sorted(buckets):
        rowset = buckets[key]
        out.append({"month": key, "days": len(rowset),
                    "revenue": sum(r["revenue"] for r in rowset),
                    "sales": sum(r["sales"] for r in rowset),
                    "avg_daily": mean(r["revenue"] for r in rowset)})
    return out


def trend_slope(series: list[dict]) -> tuple[float | None, float | None]:
    """log-գծային ռեգրեսիա → միջին աճ %/ամիս և R² (որքան կայուն է տրենդը)."""
    pts = [(i, math.log(r["revenue"] + 1)) for i, r in enumerate(series) if r["revenue"] >= 0]
    if len(pts) < 30:
        return None, None
    n = len(pts)
    mx = mean(p[0] for p in pts)
    my = mean(p[1] for p in pts)
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    sxx = sum((x - mx) ** 2 for x, y in pts)
    if sxx == 0:
        return None, None
    b = sxy / sxx
    yhat = [my + b * (x - mx) for x, _ in pts]
    ss_res = sum((y - h) ** 2 for (_, y), h in zip(pts, yhat))
    ss_tot = sum((y - my) ** 2 for _, y in pts)
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    return (math.exp(b * 30) - 1) * 100, r2        # %/ամիս


def yoy(series: list[dict], window: int = 90) -> float | None:
    """Վերջին 90 օրը vs ուղիղ մեկ տարի առաջվա նույն 90 օրը (սեզոնից մաքրված աճ)."""
    if not series:
        return None
    end = series[-1]["date"]
    cur = [r["revenue"] for r in series if end - timedelta(days=window) < r["date"] <= end]
    p_end = end - timedelta(days=365)
    prev = [r["revenue"] for r in series if p_end - timedelta(days=window) < r["date"] <= p_end]
    if len(prev) < window * 0.6 or not sum(prev):
        return None
    return (sum(cur) - sum(prev)) / sum(prev) * 100


def seasonality(series: list[dict]) -> dict[int, float]:
    """Ամսական ինդեքս. 1.0 = միջին ամիս, 1.8 = 80% ավելի բարձր միջինից."""
    by_month: dict[int, list[float]] = defaultdict(list)
    for row in series:
        by_month[row["date"].month].append(row["revenue"])
    overall = mean(r["revenue"] for r in series) if series else 0
    if not overall:
        return {}
    return {m: mean(v) / overall for m, v in sorted(by_month.items()) if v}


def volatility(series: list[dict]) -> float | None:
    """Շաբաթական շրջանառության տատանողականություն (CV %). >60% = անկանխատեսելի նիշա."""
    weeks: dict[str, float] = defaultdict(float)
    for row in series:
        weeks[row["date"].strftime("%G-W%V")] += row["revenue"]
    vals = [v for v in weeks.values() if v > 0]
    if len(vals) < 8:
        return None
    m = mean(vals)
    return pstdev(vals) / m * 100 if m else None


def saturation(snaps: list[dict]) -> dict:
    """Հագեցում. շրջանառությունն աճում է, բայց մեկ քարտի փողը՝ ընկնում → վտանգ."""
    if len(snaps) < 2:
        return {}
    first, last = snaps[0], snaps[-1]
    def delta(key: str) -> float | None:
        a, b = first.get(key) or 0, last.get(key) or 0
        return (b - a) / a * 100 if a else None
    return {
        "revenue_delta_pct": delta("total_revenue"),
        "sku_delta_pct": delta("sku_total"),
        "revenue_per_sku_delta_pct": delta("revenue_per_selling_sku"),
        "price_delta_pct": delta("median_price"),
        "top10_delta_pp": (last.get("top10_revenue_share") or 0) - (first.get("top10_revenue_share") or 0),
        "sellers_delta_pct": delta("sellers_total"),
        "comments_barrier_delta_pct": delta("median_comments_top"),
    }


def entry_window(season: dict[int, float], lead_days: int = 45) -> dict:
    """Ե՞րբ պատվիրել, որ պիկին ապրանքը պահեստում լինի."""
    if not season:
        return {}
    peak_month = max(season, key=season.get)
    peak_start = date(date.today().year, peak_month, 1)
    if peak_start < date.today():
        peak_start = date(date.today().year + 1, peak_month, 1)
    ship_by = peak_start - timedelta(days=14)          # պահեստում լինել պիկից 2 շաբաթ առաջ
    order_by = ship_by - timedelta(days=lead_days)
    return {"peak_month": peak_month, "peak_index": round(season[peak_month], 2),
            "low_month": min(season, key=season.get),
            "stock_by": str(ship_by), "order_by": str(order_by),
            "too_late": order_by < date.today()}


# ─────────────────────────────────────────────────────────────────── պատմություն
def save_history(niche: str, payload: dict) -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS trend_runs
                   (id INTEGER PRIMARY KEY, niche TEXT, run_date TEXT, payload TEXT)""")
    con.execute("INSERT INTO trend_runs (niche, run_date, payload) VALUES (?,?,?)",
                (niche, str(date.today()), json.dumps(payload, ensure_ascii=False, default=str)))
    con.commit()
    con.close()


# ──────────────────────────────────────────────────────────────────── ելք
def build_report(niche: str, series: list[dict], snaps: list[dict], lead_days: int) -> str:
    mon = monthly(series)
    slope, r2 = trend_slope(series)
    y = yoy(series)
    season = seasonality(series)
    vol = volatility(series)
    sat = saturation(snaps)
    win = entry_window(season, lead_days)

    total_year = sum(r["revenue"] for r in series[-365:])
    lines = [f"# Դինամիկա — {niche}", "",
             f"Ժամանակահատված՝ {series[0]['date']} … {series[-1]['date']} "
             f"({len(series)} օր, {len(mon)} ամիս)", "",
             "## 1. Ընդհանուր տրենդ", "",
             "| Ցուցանիշ | Արժեք | Ինչպես կարդալ |", "|---|---|---|",
             f"| Շրջանառություն 365 օր | {total_year:,.0f} ₽ | նիշայի «ծավալը» |",
             f"| Տրենդի թեքություն | {slope:+.1f} %/ամիս | log-գծային ռեգրեսիա ամբողջ շարքով |"
             if slope is not None else "| Տրենդի թեքություն | — | տվյալը քիչ է |",
             f"| Տրենդի կայունություն R² | {r2:.2f} | >0.5 = վստահելի, <0.2 = աղմուկ |"
             if r2 is not None else "| R² | — | — |",
             f"| YoY (վերջին 90օր vs տարի առաջ) | {y:+.1f}% | սեզոնից մաքրված իրական աճ |"
             if y is not None else "| YoY | — | 12+ ամսվա տվյալ չկա |",
             f"| Տատանողականություն (CV) | {vol:.0f}% | >60% = անկանխատեսելի |"
             if vol is not None else "| Տատանողականություն | — | — |"]

    lines += ["", "## 2. Ամսական դինամիկա", "", "| Ամիս | Շրջանառություն ₽ | Վաճառք | Միջին/օր ₽ |",
              "|---|---|---|---|"]
    for m in mon[-14:]:
        lines.append(f"| {m['month']} | {m['revenue']:,.0f} | {m['sales']:,.0f} | {m['avg_daily']:,.0f} |")

    if season:
        lines += ["", "## 3. Սեզոնայնություն (ինդեքս, 1.00 = միջին ամիս)", "",
                  "| Ամիս | Ինդեքս | Գրաֆիկ |", "|---|---|---|"]
        for m, idx in sorted(season.items()):
            bar = "█" * max(1, round(idx * 12))
            lines.append(f"| {MONTHS_RU[m]} | {idx:.2f} | `{bar}` |")
        spread = max(season.values()) / max(min(season.values()), 0.01)
        verdict = ("ուժեղ սեզոնային" if spread > 2.5 else
                   "չափավոր սեզոնային" if spread > 1.6 else "ոչ սեզոնային")
        lines += ["", f"**Սեզոնայնության ամպլիտուդ՝ ×{spread:.1f} → {verdict}**"]

    if win:
        lines += ["", "## 4. Մուտքի պատուհան", "",
                  f"- Պիկ ամիս՝ **{MONTHS_RU[win['peak_month']]}** (ինդեքս {win['peak_index']})",
                  f"- Ամենաթույլ ամիս՝ {MONTHS_RU[win['low_month']]}",
                  f"- Ապրանքը պետք է պահեստում լինի՝ **{win['stock_by']}**-ից ոչ ուշ",
                  f"- Պատվերը մատակարարին՝ **{win['order_by']}**-ից ոչ ուշ "
                  f"(lead time {lead_days} օր)",
                  f"- {'🔴 ՈՒՇ Է այս սեզոնի համար — նայիր հաջորդ պիկը' if win['too_late'] else '🟢 Ժամանակ կա'}"]

    if snaps:
        lines += ["", "## 5. Կառուցվածքի փոփոխությունը (հագեցման ստուգում)", "",
                  "| Կտրվածք | SKU | Վաճառքով | Շրջ. ₽ | ₽/քարտ | Տոպ-10 % | Մեդ. գին | Կարծիք բարիեր |",
                  "|---|---|---|---|---|---|---|---|"]
        for s in snaps:
            lines.append(f"| {s['end']} | {s['sku_total']} | {s['sku_with_sales']} | "
                         f"{s['total_revenue']:,.0f} | {s['revenue_per_selling_sku']:,.0f} | "
                         f"{s['top10_revenue_share']} | {s['median_price']:,.0f} | "
                         f"{s['median_comments_top']:,.0f} |")
        if sat:
            def fmt(v, suffix="%"):
                return f"{v:+.1f}{suffix}" if v is not None else "—"
            lines += ["", "**Փոփոխությունը առաջին և վերջին կտրվածքի միջև.**", "",
                      f"- Շրջանառություն՝ {fmt(sat['revenue_delta_pct'])}",
                      f"- SKU-ների քանակ՝ {fmt(sat['sku_delta_pct'])}",
                      f"- **₽ մեկ վաճառվող քարտի վրա՝ {fmt(sat['revenue_per_sku_delta_pct'])}** ← գլխավոր թիվը",
                      f"- Մեդիան գին՝ {fmt(sat['price_delta_pct'])}",
                      f"- Տոպ-10-ի բաժին՝ {fmt(sat['top10_delta_pp'], ' կետ')}",
                      f"- Վաճառողների քանակ՝ {fmt(sat['sellers_delta_pct'])}",
                      f"- Կարծիքների բարիեր՝ {fmt(sat['comments_barrier_delta_pct'])}"]
            rev_d = sat["revenue_delta_pct"] or 0
            per_d = sat["revenue_per_sku_delta_pct"]
            if per_d is not None:
                if rev_d > 10 and per_d < -15:
                    state = ("🟡 **ՀԱԳԵՑՈՒՄ** — նիշան աճում է, բայց նոր վաճառողները "
                             "գալիս են ավելի արագ, քան փողը։ Մեկ քարտի եկամուտն ընկնում է։")
                elif rev_d > 10 and per_d > 0:
                    state = "🟢 **ԱՌՈՂՋ ԱՃ** — շրջանառությունն ու քարտի եկամուտը աճում են միասին։"
                elif rev_d < -10:
                    state = "🔴 **ԸՆԿՆՈՒՄ** — նիշան փոքրանում է, պաշարը կմնա ձեռքիդ։"
                else:
                    state = "⚪️ **ԿԱՅՈՒՆ** — մեծ շարժ չկա, մրցակցությունը գնային է։"
                lines += ["", state]

    lines += ["", "---", "", "## Ի՞նչ ենք անում այս թվերով",
              "1. **Տրենդ + YoY** → վերցնում ենք նիշան, թե ոչ (ընկնողը՝ երբեք)",
              "2. **Սեզոնայնություն** → ե՞րբ պատվիրել, որ չուշանանք պիկից",
              "3. **Հագեցում (₽/քարտ դինամիկա)** → կա՞ դեռ տեղ նոր խաղացողի համար",
              "4. **Տատանողականություն** → որքան պաշար պահել (բարձր CV = ավելի մեծ ապահովագրական պաշար)",
              "5. Այս գործարկումը պահվեց `data/history.db`-ում → ամեն շաբաթ կրկնելով "
              "կունենաս քո սեփական ժամանակային շարքը, որը MPStats-ը չի պահում։"]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────── demo
def demo_series() -> tuple[list[dict], list[dict]]:
    import random
    random.seed(11)
    series, snaps = [], []
    start = date.today() - timedelta(days=540)
    for i in range(540):
        day = start + timedelta(days=i)
        trend = 1.0 + 0.0011 * i                                  # ~+3.4%/ամիս
        season_idx = 1 + 0.75 * math.cos((day.month - 11) / 12 * 2 * math.pi)
        noise = random.uniform(0.8, 1.2)
        rev = 180_000 * trend * season_idx * noise
        series.append({"date": day, "revenue": rev, "sales": rev / 1450, "sku": 0})
    base = {"sku_total": 180, "sku_with_sales": 96, "total_revenue": 4_900_000,
            "revenue_per_selling_sku": 61_000, "top10_revenue_share": 41.0,
            "median_price": 1520, "median_comments_top": 180, "sellers_total": 58}
    for i, mult in enumerate([1.0, 1.25, 1.6, 2.05]):             # SKU-ները աճում են 2×
        d2 = date.today() - timedelta(days=540 - i * 170)
        snaps.append({"period": "demo", "end": str(d2),
                      "sku_total": int(base["sku_total"] * mult),
                      "sku_with_sales": int(base["sku_with_sales"] * mult * 0.92),
                      "total_revenue": int(base["total_revenue"] * (1 + 0.28 * i)),
                      "revenue_per_selling_sku": int(base["revenue_per_selling_sku"] * (1 - 0.13 * i)),
                      "top10_revenue_share": round(base["top10_revenue_share"] + 2.4 * i, 1),
                      "median_price": int(base["median_price"] * (1 - 0.04 * i)),
                      "median_comments_top": int(base["median_comments_top"] * (1 + 0.42 * i)),
                      "sellers_total": int(base["sellers_total"] * mult)})
    return series, snaps


def main() -> None:
    p = argparse.ArgumentParser(description="12+ ամսվա դինամիկայի վերլուծություն")
    p.add_argument("--path", help="կատեգորիայի path կամ предмет")
    p.add_argument("--kind", choices=["category", "subject"], default="category")
    p.add_argument("--days", type=int, default=540, help="պատմության խորությունը (540 ≈ 18 ամիս)")
    p.add_argument("--snapshots", type=int, default=4, help="քանի կտրվածք կառուցվածքի համար")
    p.add_argument("--lead-days", type=int, default=45, help="մատակարարի lead time")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.demo:
        niche, (series, snaps) = "DEMO / սեզոնային նիշա", demo_series()
    else:
        if not args.path:
            p.error("պետք է --path կամ --demo")
        client = MpstatsClient()
        chunks = math.ceil(args.days / CHUNK_DAYS)
        print(f"[plan] օրական շարք՝ {chunks} հարցում + կտրվածքներ՝ {args.snapshots} "
              f"= ~{chunks + args.snapshots} API հարցում")
        if args.dry_run:
            return
        print(f"[limit] {json.dumps(client.api_limit(), ensure_ascii=False)}")
        niche = args.path
        series = fetch_daily(client, args.path, args.days, args.kind)
        if not series:
            raise SystemExit("Դատարկ շարք — ստուգիր path-ը (mpstats_client categories …)")
        snaps = fetch_snapshots(client, args.path, args.snapshots, args.days, args.kind)
        print(f"[api] calls={client.api_calls} cache_hits={client.cache_hits}")

    report = build_report(niche, series, snaps, args.lead_days)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"trend_{date.today():%Y%m%d}_{abs(hash(niche)) % 10000}.md"
    out.write_text(report, encoding="utf-8")
    save_history(niche, {"series_days": len(series), "snapshots": snaps,
                         "slope": trend_slope(series)[0], "yoy": yoy(series)})
    print(report[:2500])
    print(f"\n✔ {out}\n✔ պատմությունը պահվեց {DB}")


if __name__ == "__main__":
    main()
