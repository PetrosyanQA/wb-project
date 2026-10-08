"""Արտանետումների մաքրում — առանց սրա մեդիանները և սքորերը ստում են.

Երեք տիպի աղբ.
  1. գին ≫ մեդիան  → комплект/оптом/набор, ոչ թե նույն ապրանքը
  2. գին ≪ մեդիան  → պարագա (чехол, фильтр), ոչ թե ապրանքը
  3. 1 օրվա վաճառք → ակցիա կամ ինքնագնում, ոչ թե պահանջարկ
  4. ուրիշ subject_id → MPStats-ի կատեգորիան «հոսում է» հարևան предмет-ներից
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .fields import fnum, median, pick

SUBJECT_KEYS = ("subject_id", "subjectId", "subject_ID", "subjectID")
SUBJECT_NAME_KEYS = ("subject", "subject_name", "subjectName", "предмет")
DAYS_SALES_KEYS = ("days_with_sales", "sales_days", "days_sales", "days_on_sale")


def _subject_id(row: dict) -> Any:
    for key in SUBJECT_KEYS:
        if row.get(key) not in (None, "", 0):
            return row[key]
    for key in SUBJECT_NAME_KEYS:
        if row.get(key):
            return str(row[key]).strip().lower()
    return None


def dominant_subject(items: list[dict]) -> Any:
    """Որ предмет-ն է իրականում գերիշխում այս կտրվածքում (ըստ շրջանառության)."""
    weight: Counter = Counter()
    for row in items:
        sid = _subject_id(row)
        if sid is not None:
            weight[sid] += fnum(row, "revenue")
    return weight.most_common(1)[0][0] if weight else None


def clean_items(items: list[dict], cfg: dict | None = None,
                expected_subject: Any = None) -> tuple[list[dict], dict]:
    """→ (մաքուր տողեր, հաշվետվություն ինչ և ինչու դուրս մնաց)"""
    rules = (cfg or {}).get("outliers", {})
    up = float(rules.get("price_upper_ratio", 4.0))
    low = float(rules.get("price_lower_ratio", 0.25))
    min_days = int(rules.get("min_days_with_sales", 2))
    drop_foreign = bool(rules.get("drop_foreign_subject", True))

    if not items:
        return [], {"kept": 0, "dropped": 0, "reasons": {}}

    prices = [fnum(i, "price") for i in items if fnum(i, "price") > 0]
    med = median(prices) if prices else 0.0
    subject = expected_subject if expected_subject is not None else dominant_subject(items)

    kept, reasons = [], Counter()
    examples: dict[str, str] = {}
    for row in items:
        price = fnum(row, "price")
        reason = None

        if med and price > med * up:
            reason = "գին ≫ մեդիան (комплект/оптом)"
        elif med and 0 < price < med * low:
            reason = "գին ≪ մեդիան (պարագա)"
        else:
            days = None
            for key in DAYS_SALES_KEYS:
                if row.get(key) not in (None, ""):
                    days = fnum(row, key) if key in row else None
                    try:
                        days = float(row[key])
                    except (TypeError, ValueError):
                        days = None
                    break
            if days is not None and 0 < days < min_days and fnum(row, "sales") > 0:
                reason = "վաճառք միայն 1 օր (ակցիա/ինքնագնում)"
            elif drop_foreign and subject is not None:
                sid = _subject_id(row)
                if sid is not None and sid != subject:
                    reason = "այլ предмет"

        if reason:
            reasons[reason] += 1
            examples.setdefault(reason, str(pick(row, "name", ""))[:48])
        else:
            kept.append(row)

    dropped = len(items) - len(kept)
    share = round(dropped / len(items) * 100, 1)
    report = {
        "kept": len(kept),
        "dropped": dropped,
        "dropped_pct": share,
        "median_price_before": round(med),
        "median_price_after": round(median([fnum(i, "price") for i in kept
                                            if fnum(i, "price") > 0])) if kept else 0,
        "subject_used": subject,
        "reasons": dict(reasons),
        "examples": examples,
        "suspicious": share > float(rules.get("max_share_dropped_pct", 40)),
    }
    return (kept or items), report


def report_lines(rep: dict) -> list[str]:
    if not rep.get("dropped"):
        return ["- Արտանետումներ չեն գտնվել"]
    out = [f"- Մաքրվեց **{rep['dropped']}** տող ({rep['dropped_pct']}%), "
           f"մնաց {rep['kept']}",
           f"- Մեդիան գինը՝ {rep['median_price_before']:,} ₽ → "
           f"**{rep['median_price_after']:,} ₽**"]
    for reason, count in rep["reasons"].items():
        example = rep["examples"].get(reason, "")
        out.append(f"  - {reason}: {count}" + (f" (օր. «{example}»)" if example else ""))
    if rep.get("suspicious"):
        out.append("- ⚠️ Մաքրվեց >40% — կատեգորիան խառն է, ստուգիր path-ը")
    return out
