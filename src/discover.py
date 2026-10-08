"""ԶՐՈՅԻՑ ՈՐՈՆՈՒՄ — երբ դեռ չգիտես որ նիշան ես ուզում.

  python -m src.discover --depth 2 --top 20          # ամբողջ WB-ն, էժան սքրինինգ
  python -m src.discover --depth 2 --deep 5          # + խորը սքան տոպ-5-ի վրա
  python -m src.discover --demo

Ձագարի տրամաբանությունը (API լիմիտը խնայելու համար).

  ՓՈՒԼ A  կատեգորիաների ծառ            1 հարցում     ~40 արմատային ճյուղ
  ՓՈՒԼ B  ագրեգատներ ըստ ենթակատեգ.    ~20 հարցում   ~600 նիշայի ընդհանուր թվեր
          (revenue, sales, SKU քանակ — ԱՌԱՆՑ առանձին քարտեր քաշելու)
  ՓՈՒԼ C  էժան սքոր + բյուջեի ֆիլտր    0 հարցում     → տոպ-20 թեկնածու
  ՓՈՒԼ D  խորը սքան միայն տոպ-5-ի վրա  ~10 հարցում   → վերջնական ռեյտինգ

Ընդամենը ~30 հարցում ամբողջ շուկան մաղելու համար, փոխարենը հազարավորի։
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .fields import fnum, median as _median, num, parse_date, pick
from .mpstats_client import MpstatsClient, rows
from .html_report import tier_of, write_html
from .scoring import lin_score, load_config, niche_metrics, score_niche

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

DEFAULT_DISCOVERY = {
    "exclude_paths": ["Продукты", "Цифровые товары", "Билеты", "Лекарства",
                      "Ювелирные", "Автомобили", "Книги", "Здоровье"],
    "min_revenue_rub": 5_000_000,
    "max_revenue_rub": 400_000_000,
    "min_sku": 30,
    "max_sku": 5000,
    "weights": {"revenue_per_sku": 40, "price_fit": 25, "size_fit": 15, "crowding": 20},
    "anchors": {"revenue_per_sku": [8000, 120000], "crowding": [3000, 150]},
}


def discovery_cfg(cfg: dict) -> dict:
    out = dict(DEFAULT_DISCOVERY)
    out.update(cfg.get("discovery") or {})
    return out


# ────────────────────────────────────────────────────────── ՓՈՒԼ A + B
def root_categories(client: MpstatsClient, dcfg: dict) -> list[str]:
    tree = client.category_tree(limit=5000)
    roots, seen = [], set()
    for row in tree:
        path = str(pick(row, "path") or pick(row, "name") or "")
        if not path or "/" in path or path in seen:
            continue
        if any(bad.lower() in path.lower() for bad in dcfg["exclude_paths"]):
            continue
        seen.add(path)
        roots.append(path)
    return roots


def _agg_rows(client: MpstatsClient, parent: str, report: str, d1: str, d2: str) -> list[dict]:
    return rows(client.category_report(parent, report, d1, d2, limit=500))


def children_aggregates(client: MpstatsClient, parent: str, d1: str, d2: str) -> list[dict]:
    """1 հարցում → ենթակատեգորիաների ամփոփ թվերը, ԱՌԱՆՑ 500 քարտ քաշելու։

    Դիմացկունություն. ոչ բոլոր տարիֆներում է հասանելի `categories` հաշվետվությունը,
    ուստի փորձում ենք հերթով և վերջում՝ ագրեգացնում ենք հենց քարտերից։
    """
    data: list[dict] = []
    for report in ("categories", "subjects"):
        try:
            data = _agg_rows(client, parent, report, d1, d2)
        except Exception as exc:                              # noqa: BLE001
            print(f"[fallback] {parent}: `{report}` անհասանելի ({exc})")
            continue
        if data:
            break

    if data:
        out = []
        for row in data:
            name = pick(row, "name") or pick(row, "path")
            if not name:
                continue
            path = str(name) if str(name).startswith(parent) else f"{parent}/{name}"
            revenue = fnum(row, "revenue")
            sales = fnum(row, "sales")
            sku = (num(row.get("items")) or num(row.get("sku")) or num(row.get("goods"))
                   or num(row.get("items_count")) or num(row.get("sku_total")))
            out.append({
                "path": path, "revenue": revenue, "sales": sales, "sku": sku,
                "sku_with_sales": (num(row.get("items_with_sells"))
                                   or num(row.get("goods_with_sales"))
                                   or num(row.get("sku_with_sales"))),
                "avg_price": revenue / sales if sales else 0.0,
                "revenue_per_sku": revenue / sku if sku else 0.0,
                "sellers": num(row.get("sellers")) or num(row.get("sellers_count")),
                "brands": num(row.get("brands")) or num(row.get("brands_count")),
                "_source": "aggregate",
            })
        return out

    # ── Վերջին ելք՝ հաշվում ենք ինքներս 500 քարտից (մոտարկում, բայց աշխատում է միշտ) ──
    print(f"[fallback] {parent}: ագրեգատ չկա → հաշվում ենք քարտերից")
    try:
        items = _agg_rows(client, parent, "items", d1, d2)
    except Exception as exc:                                  # noqa: BLE001
        print(f"[skip] {parent}: {exc}")
        return []
    buckets: dict[str, dict] = {}
    for row in items:
        sub = str(pick(row, "subject") or pick(row, "category") or "").strip()
        if not sub:
            continue
        path = sub if sub.startswith(parent) else f"{parent}/{sub}"
        b = buckets.setdefault(path, {"path": path, "revenue": 0.0, "sales": 0.0, "sku": 0.0,
                                      "sku_with_sales": 0.0, "sellers_set": set(),
                                      "_source": "items~"})
        rev, sal = fnum(row, "revenue"), fnum(row, "sales")
        b["revenue"] += rev
        b["sales"] += sal
        b["sku"] += 1
        b["sku_with_sales"] += 1 if sal > 0 else 0
        b["sellers_set"].add(str(pick(row, "seller", "")))
    out = []
    for b in buckets.values():
        sellers = len(b.pop("sellers_set") - {""})
        out.append({**b, "sellers": sellers, "brands": 0,
                    "avg_price": b["revenue"] / b["sales"] if b["sales"] else 0.0,
                    "revenue_per_sku": b["revenue"] / b["sku"] if b["sku"] else 0.0})
    return out


# ───────────────────────────────────────────────────────────── ՓՈՒԼ C
def band_fit(value: float, lo: float, hi: float) -> float:
    """100 եթե միջանցքում է, սահուն ընկնում է դուրս գալիս."""
    if value <= 0:
        return 0.0
    if lo <= value <= hi:
        return 100.0
    return max(0.0, 100.0 * (value / lo if value < lo else hi / value))


def cheap_score(cand: dict, cfg: dict, dcfg: dict) -> dict:
    con = cfg["constraints"]
    w = dcfg["weights"]
    a = dcfg["anchors"]

    s_rev_per_sku = lin_score(cand["revenue_per_sku"], *a["revenue_per_sku"]) or 0
    s_price = band_fit(cand["avg_price"], con["price_min_rub"], con["price_max_rub"])
    s_size = band_fit(cand["revenue"], dcfg["min_revenue_rub"], dcfg["max_revenue_rub"])
    s_crowd = lin_score(cand["sku"], *a["crowding"]) or 0

    total = (s_rev_per_sku * w["revenue_per_sku"] + s_price * w["price_fit"]
             + s_size * w["size_fit"] + s_crowd * w["crowding"]) / sum(w.values())

    reasons = []
    if cand["revenue"] < dcfg["min_revenue_rub"]:
        reasons.append("փոքր շուկա")
    if cand["revenue"] > dcfg["max_revenue_rub"]:
        reasons.append("խոշոր խաղացողների դաշտ")
    if cand["sku"] and cand["sku"] > dcfg["max_sku"]:
        reasons.append(f"{cand['sku']:.0f} SKU — գերբնակեցված")
    if cand["sku"] and cand["sku"] < dcfg["min_sku"]:
        reasons.append("չափազանց նեղ")
    if cand["avg_price"] and not (con["price_min_rub"] <= cand["avg_price"] <= con["price_max_rub"]):
        reasons.append(f"միջին գին {cand['avg_price']:,.0f} ₽ դուրս է բյուջեից")

    return {"score": round(total, 1), "rejected": reasons,
            "parts": {"revenue_per_sku": round(s_rev_per_sku), "price": round(s_price),
                      "size": round(s_size), "crowding": round(s_crowd)}}


# ──────────────────────────────────────────────── ՓՈՒԼ C2 — «զոնդ» (էժան խորացում)
def probe(client: MpstatsClient, cand: dict, d1: str, d2: str, d0: str,
          with_growth: bool = True) -> dict:
    """1–2 հարցում մեկ թեկնածուի վրա, բայց տալիս է մոնոպոլիան և մուտքի բարիերը.

    Հնարքը՝ քաշում ենք ընդամենը ՏՈՊ-20 քարտը (ոչ թե 500) և համեմատում
    ագրեգատի ընդհանուր շրջանառության հետ → top-10-ի բաժինը։
    """
    out: dict = {"top10_share": None, "top_seller_share": None, "comments_barrier": None,
                 "fresh_pct": None, "yoy_peak_pct": None, "peak_month": None,
                 "slope_pct_month": None, "rating_top": None}
    try:
        top = rows(client.category_report(cand["path"], "items", d1, d2, limit=20))
    except Exception as exc:                                  # noqa: BLE001
        print(f"[probe skip] {cand['path']}: {exc}")
        return out
    if not top:
        return out

    total = cand["revenue"] or sum(fnum(r, "revenue") for r in top)
    ranked = sorted(top, key=lambda r: fnum(r, "revenue"), reverse=True)
    out["top10_share"] = round(sum(fnum(r, "revenue") for r in ranked[:10]) / total * 100, 1) if total else None

    seller_rev: dict[str, float] = {}
    for row in ranked:
        seller = pick(row, "seller")
        if seller is None:
            continue
        seller_rev[str(seller)] = seller_rev.get(str(seller), 0.0) + fnum(row, "revenue")
    if total and seller_rev:
        out["top_seller_share"] = round(max(seller_rev.values()) / total * 100, 1)

    out["comments_barrier"] = round(_median([fnum(r, "comments") for r in ranked]))
    out["rating_top"] = round(_median([fnum(r, "rating") for r in ranked]), 2)
    dates = [parse_date(pick(r, "start_date")) for r in ranked]
    if any(dates):
        fresh = [d for d in dates if d and (date.today() - d).days <= 120]
        out["fresh_pct"] = round(len(fresh) / len([d for d in dates if d]) * 100, 1)

    if with_growth:
        # 400 օր = 1 հարցում → YoY ՊԻԿ ամսով (ամսական աճը աղմուկ է՝ սեզոնը խեղաթյուրում է)
        try:
            from .gates import trend_slope_pct_month, yoy_peak
            series = rows(client.category_report(cand["path"], "by_date", d0, d2,
                                                 limit=420, sort_by=None))
            res = yoy_peak(series)
            out["yoy_peak_pct"] = res.get("yoy_pct") if res.get("ok") else None
            out["peak_month"] = res.get("peak_month") if res.get("ok") else None
            out["slope_pct_month"] = trend_slope_pct_month(series)
        except Exception as exc:                              # noqa: BLE001
            print(f"[yoy skip] {cand['path']}: {exc}")
    return out


def _plateau(slope):
    from .scoring import plateau_score
    return plateau_score(slope)


def probe_score(pr: dict, cfg: dict) -> float | None:
    """Զոնդի արդյունքից սքոր՝ օգտագործելով scoring.yaml-ի նույն խարիսխները."""
    m = cfg["metrics"]
    pairs = [
        (pr.get("top10_share"), m["top10_revenue_share"]),
        (pr.get("comments_barrier"), m["median_comments_top"]),
        (pr.get("yoy_peak_pct"), m["yoy_peak_pct"]),
        (_plateau(pr.get("slope_pct_month")), m["plateau_fit"]),
        (pr.get("fresh_pct"), m["new_sku_success_pct"]),
        (pr.get("top_seller_share"), m["top_seller_share"]),
    ]
    total = weight = 0.0
    for value, rule in pairs:
        if value is None:
            continue
        s = lin_score(float(value), rule["bad"], rule["good"])
        if s is None:
            continue
        total += s * rule["weight"]
        weight += rule["weight"]
    return round(total / weight, 1) if weight else None


def probe_flags(pr: dict, cfg: dict) -> list[str]:
    rf = cfg.get("red_flags", {})
    flags = []
    if (pr.get("top10_share") or 0) > rf.get("top10_revenue_share", 78):
        flags.append(f"🔴 մոնոպոլիա (տոպ-10 = {pr['top10_share']}%)")
    if (pr.get("top_seller_share") or 0) > rf.get("top_seller_share", 45):
        flags.append(f"🔴 մեկ վաճառող {pr['top_seller_share']}%")
    if (pr.get("comments_barrier") or 0) > rf.get("median_comments_top", 800):
        flags.append(f"🟠 կարծիքների բարիեր {pr['comments_barrier']:,}")
    yoy = pr.get("yoy_peak_pct")
    slope = pr.get("slope_pct_month")
    if yoy is not None and yoy < -10:
        flags.append(f"🔴 YoY պիկ ամսով {yoy}%")
    if yoy is not None and yoy > 80:
        flags.append(f"🟠 պայթուցիկ աճ +{yoy}% (սովորաբար մեկ վաղ խաղացող)")
    if slope is not None and -1.5 <= slope <= 4.0:
        flags.append(f"🟢 սարահարթ {slope:+.1f}%/ամիս — թիրախային պրոֆիլ")
    if pr.get("fresh_pct") is not None and pr["fresh_pct"] < rf.get("fresh_low_pct", 5):
        flags.append("🟠 նոր քարտեր տոպ չեն մտնում")
    if pr.get("fresh_pct") is not None and pr["fresh_pct"] >= rf.get("fresh_high_pct", 25):
        flags.append(f"🟢 թարմ քարտերը բեկում են անում ({pr['fresh_pct']}%)")
    return flags


# ───────────────────────────────────────────────────────────── demo
def demo_candidates() -> list[dict]:
    """Demo՝ ագրեգատ + զոնդ։ Ուշադրություն «Дом/Кухня/Органайзеры»-ին.
    էժան սքորը բարձր է, բայց զոնդը բացահայտում է մոնոպոլիա։"""
    presets = [
        # path, revenue, avg_price, sku, growth, top10, seller, comments, fresh
        ("Дом/Хранение вещей",            34_000_000,  890,  310,  31.2, 41.0,  12.0,  150, 33.0),
        ("Автотовары/Аксессуары салона",  28_000_000, 1180,  240,  18.4, 34.0,   9.0,  210, 28.0),
        ("Дом/Кухня/Органайзеры",         42_000_000, 1450,  380,  12.1, 83.0,  51.0,  430,  6.0),
        ("Спорт/Йога/Коврики",            61_000_000, 2300,  520,   4.2, 47.0,  18.0,  640, 12.0),
        ("Дом/Ванная/Аксессуары",         23_000_000, 1290,  260,   8.0, 55.0,  21.0,  320, 15.0),
        ("Детям/Развивающие игрушки",     18_000_000, 1650,  190, -22.0, 72.0,  38.0,  980,  3.0),
        ("Канцтовары/Органайзеры",         6_800_000,  970,  120,   2.4, 38.0,  14.0,   90, 20.0),
        ("Красота/Аксессуары для волос",  190_000_000, 420, 4200,   9.0, 29.0,   7.0, 1450, 18.0),
        ("Электроника/Кабели",            240_000_000, 380, 6100,   3.0, 44.0,  16.0, 2100,  9.0),
        ("Зоотовары/Игрушки для кошек",     9_500_000,  640,  150,  14.0, 36.0,  11.0,  120, 24.0),
    ]
    out = []
    for path, revenue, price, sku, growth, top10, seller, comments, fresh in presets:
        sales = revenue / price
        out.append({"path": path, "revenue": revenue, "sales": sales, "sku": sku,
                    "sku_with_sales": sku * 0.5, "avg_price": price,
                    "revenue_per_sku": revenue / sku, "sellers": sku * 0.6, "brands": sku * 0.4,
                    "_probe": {"top10_share": top10, "top_seller_share": seller,
                               "comments_barrier": comments, "fresh_pct": fresh,
                               "yoy_peak_pct": growth, "slope_pct_month": growth / 12,
                               "rating_top": 4.7}})
    return out


# ───────────────────────────────────────────────────────────── ելք
def write_report(cands: list[dict], scanned: int, requests_used: int, deep: list[dict],
                 cfg: dict, show: int = 40) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    tag = date.today().strftime("%Y%m%d")
    csv_path = REPORTS / f"discovery_{tag}.csv"
    md_path = REPORTS / f"discovery_{tag}.md"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["tier", "path", "score", "cheap_score", "probe_score", "growth_pct",
                         "top10_share", "top_seller_share", "comments_barrier", "fresh_pct",
                         "revenue", "sku", "revenue_per_sku", "avg_price", "sellers",
                         "flags", "rejected"])
        for c in cands:
            pr = c.get("_probe") or {}
            writer.writerow([c.get("tier", ""), c["path"], c["score"],
                             c.get("cheap_score", c["score"]), c.get("_probe_score", ""),
                             pr.get("growth_pct", ""), pr.get("top10_share", ""),
                             pr.get("top_seller_share", ""), pr.get("comments_barrier", ""),
                             pr.get("fresh_pct", ""), round(c["revenue"]), round(c["sku"]),
                             round(c["revenue_per_sku"]), round(c["avg_price"]),
                             round(c["sellers"]), " ".join(c.get("_flags") or []),
                             "; ".join(c["rejected"])])

    ok = [c for c in cands if not c["rejected"]]
    bad = [c for c in cands if c["rejected"]]
    ok = ok[:show]
    lines = [f"# Զրոյից որոնում — {tag}", "",
             f"Մաղվել է **{scanned}** ենթակատեգորիա, ծախսվել է **{requests_used}** API հարցում։",
             f"Անցել է ֆիլտրերը՝ **{len(ok)}**, մերժվել՝ **{len(bad)}**։", "",
             "## 🎯 Թեկնածուներ (անցել են բյուջեի և չափի ֆիլտրերը)", "",
             "| # | Նիշա | Սքոր | YoY պիկ % | %/ամիս | Տոպ-10 % | 1 վաճ. % | Կարծիք | Թարմ % | Շրջ. ₽ | SKU | Միջին գին |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def _f(v, suffix=""):
        return f"{v:,.0f}{suffix}" if isinstance(v, (int, float)) else "—"
    for i, c in enumerate(ok[:25], 1):
        pr = c.get("_probe") or {}
        approx = "~" if c.get("_source") == "items~" else ""
        lines.append(f"| {i} | `{c['path']}`{approx} | **{c['score']}** | "
                     f"{_f(pr.get('yoy_peak_pct'))} | {_f(pr.get('slope_pct_month'))} | "
                     f"{_f(pr.get('top10_share'))} | {_f(pr.get('top_seller_share'))} | "
                     f"{_f(pr.get('comments_barrier'))} | {_f(pr.get('fresh_pct'))} | "
                     f"{c['revenue']:,.0f} | {c['sku']:,.0f} | {c['avg_price']:,.0f} |")
    if any(c.get("_source") == "items~" for c in ok):
        lines.append("")
        lines.append("> `~` = ագրեգատ հաշվետվությունը հասանելի չէր տարիֆում, թվերը հաշվված են "
                     "տոպ-500 քարտից → թերագնահատված են, բայց համեմատելի միմյանց հետ։")
    flagged = [c for c in ok[:25] if c.get("_flags")]
    if flagged:
        lines += ["", "### Ազդանշաններ", ""]
        for c in flagged:
            lines.append(f"- `{c['path']}` — {', '.join(c['_flags'])}")

    lines += ["", "## ❌ Մերժվածներ (ինչու)", "", "| Նիշա | Շրջ. ₽ | Պատճառ |", "|---|---|---|"]
    for c in bad[:20]:
        lines.append(f"| `{c['path']}` | {c['revenue']:,.0f} | {'; '.join(c['rejected'])} |")

    if deep:
        lines += ["", "## 🔬 Խորը սքան տոպ թեկնածուների վրա", "",
                  "| Նիշա | Սքոր | Վերդիկտ | ₽/վաճառվող քարտ | %վաճառքով | Տոպ-10 % | Կարծիք բարիեր |",
                  "|---|---|---|---|---|---|---|"]
        for d in deep:
            m = d["metrics"]
            lines.append(f"| `{d['niche']}` | **{d['score']}** | {d['verdict']} | "
                         f"{m['revenue_per_selling_sku']:,} | {m['pct_sku_with_sales']} | "
                         f"{m['top10_revenue_share']} | {m['median_comments_top']:,} |")

    top = (deep or ok)[:3]
    lines += ["", "---", "", "## Հաջորդ քայլերը", ""]
    for c in top:
        path = c.get("niche") or c["path"]
        lines += [f"**`{path}`**",
                  f"```bash",
                  f'python -m src.trend_scan --path "{path}" --days 540 --snapshots 4',
                  f'python -m src.niche_scan --path "{path}" --children subjects --top 8',
                  f"```", ""]
    lines += ["> Էժան սքրինինգը օգտագործում է միայն ագրեգատներ (շրջանառություն, SKU քանակ, "
              "միջին գին)։ Այն **չի** տեսնում մոնոպոլացումը, կարծիքների բարիերը և թարմ քարտերի "
              "հաջողությունը — դրանք երևում են միայն խորը սքանում։ Ուստի տոպ-3-ը պարտադիր "
              "անցկացրու `trend_scan` + `niche_scan` միջով։"]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def main() -> None:
    p = argparse.ArgumentParser(description="Զրոյից նիշայի որոնում ամբողջ WB-ում")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--depth", type=int, default=1, choices=[1, 2],
                   help="1 = արմատային ճյուղերի երեխաները, 2 = + տոպ ճյուղերի թոռները")
    p.add_argument("--expand", type=int, default=2, help="depth=2-ում քանի ճյուղ բացել ամեն արմատից")
    p.add_argument("--top", type=int, default=40, help="քանի տող ցույց տալ MD-ում")
    p.add_argument("--probe", type=int, default=25,
                   help="քանի թեկնածուի վրա անել զոնդ (մոնոպոլիա/բարիեր) — 1 հարցում ամեն մեկի")
    p.add_argument("--growth-top", type=int, default=10,
                   help="քանիսի համար քաշել նաև աճը (+1 հարցում ամեն մեկի)")
    p.add_argument("--deep", type=int, default=0, help="քանի թեկնածուի վրա գործարկել խորը սքան")
    p.add_argument("--max-requests", type=int, default=40)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = load_config()
    dcfg = discovery_cfg(cfg)
    today = date.today()
    d2, d1 = str(today - timedelta(days=1)), str(today - timedelta(days=args.days))

    deep_results: list[dict] = []
    if args.demo:
        raw = demo_candidates()
        scanned, used, client = len(raw), 0, None
    else:
        client = MpstatsClient()
        print(f"[limit] {json.dumps(client.api_limit(), ensure_ascii=False)}")
        roots = root_categories(client, dcfg)
        print(f"[plan] {len(roots)} արմատային ճյուղ → ~{min(len(roots), args.max_requests)} հարցում")
        for r in roots:
            print(f"   • {r}")
        if args.dry_run:
            return
        raw = []
        for root in roots:
            if client.api_calls >= args.max_requests:
                print(f"[stop] հասանք {args.max_requests} հարցման սահմանին")
                break
            try:
                raw += children_aggregates(client, root, d1, d2)
            except Exception as exc:                        # noqa: BLE001
                print(f"[skip] {root}: {exc}")
        if args.depth == 2:
            ranked = sorted(raw, key=lambda c: c["revenue_per_sku"], reverse=True)
            for cand in ranked[: args.expand * 3]:
                if client.api_calls >= args.max_requests:
                    break
                try:
                    raw += children_aggregates(client, cand["path"], d1, d2)
                except Exception as exc:                    # noqa: BLE001
                    print(f"[skip] {cand['path']}: {exc}")
        scanned, used = len(raw), client.api_calls

    cands = []
    for cand in raw:
        cands.append({**cand, **cheap_score(cand, cfg, dcfg)})
    cands.sort(key=lambda c: (not c["rejected"], c["score"]), reverse=True)
    shortlist = [c for c in cands if not c["rejected"]][: args.top]

    # ── ՓՈՒԼ C2 — զոնդ. մոնոպոլիա, աճ, կարծիքների բարիեր, թարմ քարտեր ──
    d0 = str(today - timedelta(days=args.days * 2))
    probed = shortlist[: args.probe] if args.probe else []
    for i, cand in enumerate(probed):
        pr = cand.get("_probe")
        if pr is None and not args.demo and client:
            pr = probe(client, cand, d1, d2, d0, with_growth=i < args.growth_top)
            cand["_probe"] = pr
        if not pr:
            continue
        ps = probe_score(pr, cfg)
        cand["_probe_score"] = ps
        cand["_flags"] = probe_flags(pr, cfg)

        # Կոնցենտրացիայի ԿՈՇՏ շեմերը config/filters.yaml-ից — ոչ թե «փափուկ» սքոր
        try:
            from .gates import load_filters
            conc = load_filters()["concentration"]
            yoy_cfg = load_filters()["yoy_peak"]
        except Exception:                                      # noqa: BLE001
            conc, yoy_cfg = {}, {}
        t10, t1 = pr.get("top10_share"), pr.get("top_seller_share")
        if t10 is not None and t10 > conc.get("top10_share_max", 40):
            cand["rejected"].append(f"տոպ-10 {t10:.0f}% > {conc['top10_share_max']:.0f}%")
        if t1 is not None and t1 > conc.get("top1_seller_share_max", 25):
            cand["rejected"].append(f"մեկ վաճառող {t1:.0f}% > {conc['top1_seller_share_max']:.0f}%")
        yoy = pr.get("yoy_peak_pct")
        if yoy is not None and yoy < yoy_cfg.get("min_yoy_pct", -5):
            cand["rejected"].append(f"YoY պիկ ամսով {yoy:+.0f}%")
        if ps is not None:
            cand["cheap_score"] = cand["score"]
            cand["score"] = round(cand["score"] * 0.4 + ps * 0.6, 1)   # զոնդն ավելի կարևոր է
    shortlist.sort(key=lambda c: c["score"], reverse=True)
    cands.sort(key=lambda c: (not c["rejected"], c["score"]), reverse=True)
    if not args.demo and client:
        used = client.api_calls

    if args.deep and not args.demo and client:
        for cand in shortlist[: args.deep]:
            try:
                items = client.category_items_all(cand["path"], d1, d2, max_rows=500)
                by_date = rows(client.category_report(cand["path"], "by_date",
                                                      str(today - timedelta(days=args.days * 2)),
                                                      d2, limit=200, sort_by=None))
            except Exception as exc:                        # noqa: BLE001
                print(f"[skip deep] {cand['path']}: {exc}")
                continue
            if not items:
                continue
            metrics = niche_metrics(items, by_date)
            scored = score_niche(metrics, cfg)
            deep_results.append({"niche": cand["path"], "metrics": metrics, **scored})
            print(f"[deep] {cand['path']}: {scored['score']} {scored['verdict']}")
        deep_results.sort(key=lambda r: (not r["fails"], r["score"]), reverse=True)
        used = client.api_calls

    for c in cands:
        c["tier"] = tier_of(c["score"], c["rejected"])
    csv_path, md_path = write_report(cands, scanned, used, deep_results, cfg, args.top)
    html_path = write_html(cands, scanned, used,
                           REPORTS / f"discovery_{date.today():%Y%m%d}.html")
    print(f"\nՄաղվեց {scanned} նիշա | {used} API հարցում | անցավ {len(shortlist)}")
    for c in shortlist[:10]:
        pr = c.get("_probe") or {}
        extra = ""
        if pr.get("top10_share") is not None:
            extra = (f" | YoY {pr.get('yoy_peak_pct', '—')}% | տոպ-10 {pr['top10_share']}%"
                     f" | կարծիք {pr.get('comments_barrier', '—')}")
        print(f"  {c['score']:>5}  {c['path']}{extra}")
        for f in c.get("_flags", []):
            print(f"         {f}")
    tiers = {}
    for c in cands:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    print(f"\nԽմբեր՝ 🟢A={tiers.get('A',0)}  🟡B={tiers.get('B',0)}  "
          f"⚪️C={tiers.get('C',0)}  ❌={tiers.get('X',0)}")
    print(f"\n✔ {md_path}\n✔ {csv_path}\n✔ {html_path}  ← բաց արա բրաուզերով (սորտավորվող աղյուսակ)")


if __name__ == "__main__":
    main()
