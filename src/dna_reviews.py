"""Жалобы лидеров ниши: словарные темы и автоматический поиск повторов.

Словарный анализ остаётся источником основного вердикта; лексический скрининг
показывает дополнительные повторяющиеся фразы для ручной проверки.

    python -m src.dna_reviews --subject 731
"""
from __future__ import annotations

import argparse
import glob
from datetime import date
from pathlib import Path

from src.dna_dicts import COMMON_THEMES, get_cfg
from src.review_topics import analyze_files
from src.saleflow_eval import complaints

MIN_SHARE = 12.0
AUTO_MIN_REVIEWS = 3
AUTO_MIN_SKUS = 2


def discover_topics(files: list[str], today: date) -> dict:
    """Find repeated phrases without changing the curated complaint verdict."""
    return analyze_files(files, min_rating=3, min_reviews=AUTO_MIN_REVIEWS,
                         min_skus=AUTO_MIN_SKUS, since_days=365, today=today)


def reviews(run: str, sid: int, today: date | None = None) -> dict:
    today = today or date.today()
    cfg = get_cfg(sid)
    themes = {**COMMON_THEMES, **cfg.get("complaint_themes", {})}
    files = sorted(glob.glob(f"data/raw/saleflow/{run}/dna/{sid}/comments/*.json"))
    s = {"complaint_themes": themes, "complaints_window_days": 365, "complaint_min_negatives": 10,
         "complaint_min_share_pct": MIN_SHARE, "complaint_min_leaders": 2}
    r = complaints(files, s, today)
    total_neg = sum(p["negatives"] for p in r["per_sku"])
    pooled = {}
    for t in themes:
        n = sum(p["themes"].get(t, {}).get("count", 0) for p in r["per_sku"])
        if n:
            pooled[t] = {"count": n, "share": n / total_neg * 100 if total_neg else 0,
                         "quotes": [q for p in r["per_sku"] for q in p["themes"].get(t, {}).get("quotes", [])][:3]}
    top = sorted(pooled.items(), key=lambda kv: -kv[1]["count"])
    fixable = [(t, v) for t, v in top if v["share"] >= MIN_SHARE]
    auto = discover_topics(files, today)
    return {"files": len(files), "per_sku": r["per_sku"], "total_neg": total_neg, "pooled": top,
            "fixable": fixable, "verdict": r["verdict"], "common": r["common_themes"],
            "auto_topics": auto["topics"], "auto_topics_meta": auto}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Анализ словарных и повторяющихся тем негативных отзывов")
    ap.add_argument("--subject", type=int, required=True)
    ap.add_argument("--run", default="2026-10-05")
    a = ap.parse_args()
    R = reviews(a.run, a.subject)
    for p in R["per_sku"]:
        print(f"{p['file']}: отзывов {p['comments']}, негатив с текстом (365 дн) {p['negatives']} ({p['negatives'] / max(p['comments'], 1) * 100:.1f}%)")
    print(f"всего негатива {R['total_neg']}; закрываемые словарные темы (≥ {MIN_SHARE:.0f}%):")
    for t, v in R["pooled"]:
        print(f"  {'✅' if v['share'] >= MIN_SHARE else '  '} {t}: {v['count']} ({v['share']:.0f}%) | {v['quotes'][:2]}")
    print("\nАвтоматически найденные повторяющиеся фразы (кандидаты, проверь вручную):")
    if not R["auto_topics"]:
        print("  подходящих фраз не найдено (нужно ≥3 отзыва и ≥2 SKU)")
    for topic in R["auto_topics"]:
        print(f"  {topic['phrase']}: {topic['reviews']} отзывов, {topic['sku_count']} SKU, средняя оценка {topic['mean_rating']}")
