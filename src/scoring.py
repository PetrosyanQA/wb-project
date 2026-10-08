"""Նիշայի մետրիկաների հաշվարկ և սքորինգ (0–100)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from .fields import fnum, median, num, parse_date, percentile, pick

ROOT = Path(__file__).resolve().parents[1]
NEW_SKU_DAYS = 120


def load_config(path: Path | str = ROOT / "config" / "scoring.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def lin_score(value: float | None, bad: float, good: float) -> float | None:
    """Գծային նորմալիզացիա 0..100՝ bad→0, good→100 (աշխատում է երկու ուղղությամբ)."""
    if value is None:
        return None
    if good == bad:
        return 50.0
    score = (value - bad) / (good - bad) * 100.0
    return max(0.0, min(100.0, score))


# ----------------------------------------------------------------- metrics
def plateau_score(slope: float | None, lo: float = -1.5, hi: float = 4.0,
                  hard_lo: float = -8.0, hard_hi: float = 12.0) -> float | None:
    """100 = սարահարթ։ Ե՛վ անկումը, և՛ պայթուցիկ աճը իջեցնում են միավորը.
    պայթուցիկ աճը սովորաբար պահում է մեկ վաղ խաղացող — նորեկի տեղ չկա."""
    if slope is None:
        return None
    if lo <= slope <= hi:
        return 100.0
    if slope < lo:
        return max(0.0, 100.0 * (slope - hard_lo) / (lo - hard_lo))
    return max(0.0, 100.0 * (hard_hi - slope) / (hard_hi - hi))


def niche_metrics(items: list[dict], by_date: list[dict] | None = None,
                  today: date | None = None) -> dict[str, Any]:
    """Հումք տողերից (category/items) հաշվում է որոշման համար կարևոր ցուցանիշները."""
    today = today or date.today()
    total_revenue = sum(fnum(i, "revenue") for i in items)
    total_sales = sum(fnum(i, "sales") for i in items)
    selling = [i for i in items if fnum(i, "revenue") > 0]
    ranked = sorted(items, key=lambda i: fnum(i, "revenue"), reverse=True)

    seller_rev: dict[str, float] = defaultdict(float)
    brand_rev: dict[str, float] = defaultdict(float)
    for item in items:
        if (seller := pick(item, "seller")) is not None:
            seller_rev[str(seller)] += fnum(item, "revenue")
        brand_rev[str(pick(item, "brand", "—"))] += fnum(item, "revenue")

    prices = [fnum(i, "price") for i in selling if fnum(i, "price") > 0]
    top20 = ranked[:20]
    top50 = ranked[:50]
    fresh = [i for i in top50
             if (d := parse_date(pick(i, "start_date"))) and (today - d).days <= NEW_SKU_DAYS]
    has_dates = any(parse_date(pick(i, "start_date")) for i in top50)

    growth = None
    if by_date:
        series = [(parse_date(pick(r, "date")), fnum(r, "revenue")) for r in by_date]
        series = sorted([(d, v) for d, v in series if d])
        if len(series) >= 14:
            half = len(series) // 2
            prev = sum(v for _, v in series[:half])
            curr = sum(v for _, v in series[half:])
            growth = ((curr - prev) / prev * 100.0) if prev > 0 else None

    from .gates import trend_slope_pct_month, yoy_peak as _yoy_peak
    yoy_info = _yoy_peak(by_date) if by_date else {"ok": False}
    slope = trend_slope_pct_month(by_date) if by_date else None

    return {
        "sku_total": len(items),
        "sku_with_sales": len(selling),
        "pct_sku_with_sales": round(len(selling) / len(items) * 100, 1) if items else 0.0,
        "total_revenue": round(total_revenue),
        "total_sales": round(total_sales),
        "revenue_per_selling_sku": round(median([fnum(i, "revenue") for i in selling])),
        "avg_revenue_per_selling_sku": round(total_revenue / len(selling)) if selling else 0,
        "top10_revenue_share": round(sum(fnum(i, "revenue") for i in ranked[:10]) / total_revenue * 100, 1)
        if total_revenue else 0.0,
        "top_seller_share": round(max(seller_rev.values()) / total_revenue * 100, 1)
        if total_revenue and seller_rev else 0.0,
        "sellers_total": len(seller_rev),
        "brands_total": len(brand_rev),
        "median_price": round(median(prices)),
        "price_p10": round(percentile(prices, 0.10)),
        "price_p90": round(percentile(prices, 0.90)),
        "price_dispersion_ratio": round(percentile(prices, 0.90) / percentile(prices, 0.10), 2)
        if percentile(prices, 0.10) > 0 else None,
        "median_comments_top": round(median([fnum(i, "comments") for i in top20])),
        "median_rating_top": round(median([fnum(i, "rating") for i in top20]), 2),
        "new_sku_success_pct": round(len(fresh) / len(top50) * 100, 1) if (top50 and has_dates) else None,
        "growth_mom_pct": round(growth, 1) if growth is not None else None,
        "yoy_peak_pct": yoy_info.get("yoy_pct") if yoy_info.get("ok") else None,
        "yoy_peak_month": yoy_info.get("peak_month") if yoy_info.get("ok") else None,
        "trend_slope_pct_month": slope,
        "plateau_fit": plateau_score(slope),
        "median_balance_top": round(median([fnum(i, "balance") for i in top20])),
        "top_sellers": sorted(seller_rev.items(), key=lambda kv: kv[1], reverse=True)[:5],
        "top_brands": sorted(brand_rev.items(), key=lambda kv: kv[1], reverse=True)[:5],
    }


def price_fit_score(median_price: float, cfg: dict) -> float:
    """Որքան է մեդիան գինը համապատասխանում բյուջեի միջանցքին (0–100)."""
    lo = cfg["constraints"]["price_min_rub"]
    hi = cfg["constraints"]["price_max_rub"]
    if median_price <= 0:
        return 0.0
    if lo <= median_price <= hi:
        return 100.0
    if median_price < lo:
        return max(0.0, 100.0 * median_price / lo)
    return max(0.0, 100.0 * hi / median_price)


def score_niche(metrics: dict, cfg: dict) -> dict:
    """Կշռված սքոր + կոշտ ֆիլտրեր + կարմիր դրոշներ."""
    values = dict(metrics)
    values["price_fit_score"] = price_fit_score(metrics.get("median_price", 0), cfg)

    parts, used_weight = {}, 0.0
    total = 0.0
    for name, rule in cfg["metrics"].items():
        value = values.get(name)
        score = lin_score(None if value is None else float(value), rule["bad"], rule["good"])
        if score is None:
            parts[name] = {"value": None, "score": None, "weight": rule["weight"]}
            continue
        parts[name] = {"value": value, "score": round(score, 1), "weight": rule["weight"]}
        total += score * rule["weight"]
        used_weight += rule["weight"]
    final = round(total / used_weight, 1) if used_weight else 0.0

    # կոշտ ֆիլտրեր
    con = cfg["constraints"]
    fails = []
    if metrics["total_revenue"] < con["min_niche_revenue_rub"]:
        fails.append(f"շրջանառությունը ցածր է ({metrics['total_revenue']:,} ₽)")
    if metrics["total_revenue"] > con["max_niche_revenue_rub"]:
        fails.append(f"նիշան չափից մեծ է ({metrics['total_revenue']:,} ₽) — խոշոր խաղացողների դաշտ")
    if metrics["top10_revenue_share"] > con["max_top10_revenue_share"]:
        fails.append(f"տոպ-10-ը վերցնում է {metrics['top10_revenue_share']}%")
    if metrics["pct_sku_with_sales"] < con["min_pct_sku_with_sales"]:
        fails.append(f"քարտերի միայն {metrics['pct_sku_with_sales']}%-ն ունի վաճառք")
    if not (con["price_min_rub"] <= metrics["median_price"] <= con["price_max_rub"]):
        fails.append(f"մեդիան գինը {metrics['median_price']} ₽ դուրս է բյուջեի միջանցքից")

    # կարմիր դրոշներ (զգուշացում, ոչ մերժում)
    rf = cfg.get("red_flags", {})
    flags = []
    if metrics["top10_revenue_share"] > rf.get("top10_revenue_share", 100):
        flags.append("մոնոպոլացված տոպ")
    if metrics["top_seller_share"] > rf.get("top_seller_share", 100):
        flags.append("մեկ վաճառողի գերիշխանություն")
    if metrics["median_comments_top"] > rf.get("median_comments_top", 10**9):
        flags.append("կարծիքների բարձր բարիեր")
    if (metrics.get("growth_mom_pct") or 0) < rf.get("growth_mom_pct", -10**9):
        flags.append("նիշան ընկնում է")
    if (metrics.get("price_dispersion_ratio") or 0) > rf.get("price_dispersion_ratio", 10**9):
        flags.append("գների մեծ ցրվածություն (տարբեր ապրանքներ մեկ նիշում)")

    verdict = "❌ մերժել" if fails else ("🟢 վերցնել խորը վերլուծության" if final >= 65
                                        else "🟡 պահեստային" if final >= 50 else "⚪️ թույլ")
    return {"score": final, "parts": parts, "fails": fails, "flags": flags, "verdict": verdict}
