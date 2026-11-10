"""Offline discovery of recurring topics in negative Wildberries reviews.

Usage:
    python -m src.review_topics data/raw/.../comments/*.json
    python -m src.review_topics --min-reviews 3 --out reports/review_topics.md file1.json file2.json

This intentionally uses transparent lexical n-grams, not a trained ML model. It
complements (and does not replace) the curated theme rules in saleflow_eval.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
STOPWORDS = set("""
а без более бы был была были было быть в вам вас весь во вот все всего всех вы где да даже для до его ее если есть ещё же за здесь и из или им их к как ко когда кто ли либо мне может мы на над надо наш не него нее нет ни них но о об один она они оно от по под при про раз с со такой так также те тем то того той только том ты у уже хоть что чтобы эта эти это я
""".split())
GENERIC = set("""
товар товаре товару товара покупка купила купил заказ заказала заказал пришел пришла пришло пришли
доставка упаковка продавец wb wildberries вайлдберриз маркетплейс
""".split())


def _rows(data: Any) -> list[dict]:
    """Accept common Saleflow/API JSON shapes without assuming one wrapper."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("data", "comments", "items", "reviews", "feedbacks"):
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _rating(row: dict) -> float | None:
    for key in ("valuation", "rating", "star", "stars"):
        value = row.get(key)
        try:
            if value not in (None, ""):
                rating = float(str(value).replace(",", "."))
                if 1 <= rating <= 5:
                    return rating
        except (TypeError, ValueError):
            continue
    return None


def _review_date(row: dict) -> date | None:
    value = row.get("date") or row.get("createdAt") or row.get("created_at")
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _tokens(text: str) -> list[str]:
    result = []
    for token in TOKEN_RE.findall(text.lower().replace("ё", "е")):
        if len(token) < 3 or token in STOPWORDS or token in GENERIC or token.isdigit():
            continue
        result.append(token)
    return result


def _sku(path: Path, row: dict) -> str:
    for key in ("nmId", "nm_id", "sku", "product_id", "imtId", "id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return path.parent.name or path.stem


def analyze_files(files: Iterable[str | Path], *, min_rating: float = 3.0,
                  min_reviews: int = 3, min_skus: int = 2, top: int = 30,
                  since_days: int | None = None, today: date | None = None) -> dict:
    """Mine frequent 1-3 word phrases from negative reviews across SKU files."""
    if min_reviews < 1 or min_skus < 1 or top < 1:
        raise ValueError("min_reviews, min_skus и top должны быть положительными")
    if not 1 <= min_rating <= 5:
        raise ValueError("min_rating должен быть от 1 до 5")
    if since_days is not None and since_days < 1:
        raise ValueError("since_days должен быть положительным")

    today = today or date.today()
    cutoff = today - timedelta(days=since_days) if since_days else None
    phrases: dict[str, Counter] = defaultdict(Counter)
    sku_sets: dict[str, set[str]] = defaultdict(set)
    rating_sums: Counter = Counter()
    rating_counts: Counter = Counter()
    eligible_reviews = 0
    files_read = 0

    for filename in files:
        path = Path(filename)
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = _rows(data)
        if rows:
            files_read += 1
        fallback_sku = path.parent.name or path.stem
        for row in rows:
            rating = _rating(row)
            text = row.get("text") or row.get("textOriginal") or row.get("comment") or ""
            if rating is None or rating > min_rating or not isinstance(text, str) or not text.strip():
                continue
            if cutoff:
                review_date = _review_date(row)
                if review_date is None or review_date < cutoff:
                    continue
            words = _tokens(text)
            if not words:
                continue
            eligible_reviews += 1
            sku = _sku(path, row) if any(row.get(k) for k in ("nmId", "nm_id", "sku", "product_id", "imtId", "id")) else fallback_sku
            # Count each phrase at most once per review, so repeated wording does not dominate.
            found = set()
            for size in (1, 2, 3):
                found.update(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))
            for phrase in found:
                phrases[phrase]["reviews"] += 1
                sku_sets[phrase].add(sku)
                rating_sums[phrase] += rating
                rating_counts[phrase] += 1

    ranked = [
        {"phrase": phrase, "reviews": counts["reviews"], "sku_count": len(sku_sets[phrase]),
         "mean_rating": round(rating_sums[phrase] / rating_counts[phrase], 2)}
        for phrase, counts in phrases.items()
        if counts["reviews"] >= min_reviews and len(sku_sets[phrase]) >= min_skus
    ]
    ranked.sort(key=lambda item: (-item["sku_count"], -item["reviews"], item["phrase"]))
    return {"filters": {"negative_rating_max": min_rating, "min_reviews": min_reviews,
                         "min_skus": min_skus, "since_days": since_days,
                         "cutoff": str(cutoff) if cutoff else None},
            "files_read": files_read, "negative_reviews_analyzed": eligible_reviews,
            "topics": ranked[:top]}


def render_markdown(result: dict) -> str:
    f = result["filters"]
    lines = ["# Повторяющиеся темы негативных отзывов", "",
             f"Файлов: {result['files_read']} · негативных отзывов с текстом: {result['negative_reviews_analyzed']}",
             f"Фильтр: оценка ≤ {f['negative_rating_max']}; минимум отзывов на фразу: {f['min_reviews']}; "
             f"минимум разных SKU: {f['min_skus']}.", "",
             "Фразы — частотные слова/сочетания, а не семантическая классификация. "
             "Проверьте контекст отзывов вручную перед выводами.", "",
             "| Тема / фраза | Отзывов | SKU | Средняя оценка |", "|---|---:|---:|---:|"]
    if not result["topics"]:
        lines.append("| Подходящих повторяющихся фраз не найдено | — | — | — |")
    else:
        for topic in result["topics"]:
            lines.append(f"| {topic['phrase']} | {topic['reviews']} | {topic['sku_count']} | {topic['mean_rating']} |")
    lines += ["", "_Автоматический лексический скрининг не определяет причину жалобы и не заменяет проверку исходных отзывов._", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Поиск повторяющихся тем в негативных отзывах WB (офлайн)")
    parser.add_argument("files", nargs="+", help="JSON-файлы отзывов, например comments/*.json")
    parser.add_argument("--min-rating", type=float, default=3, help="учитывать оценки не выше заданной (по умолчанию 3)")
    parser.add_argument("--min-reviews", type=int, default=3, help="минимум отзывов с фразой")
    parser.add_argument("--min-skus", type=int, default=2, help="минимум разных SKU с фразой")
    parser.add_argument("--since-days", type=int, help="ограничить отзывы последними N днями; без даты отзыв исключается")
    parser.add_argument("--top", type=int, default=30, help="сколько тем вывести")
    parser.add_argument("--out", help="сохранить Markdown-отчёт по указанному пути")
    parser.add_argument("--json-out", help="дополнительно сохранить структурированный JSON")
    args = parser.parse_args()
    result = analyze_files(args.files, min_rating=args.min_rating, min_reviews=args.min_reviews,
                           min_skus=args.min_skus, top=args.top, since_days=args.since_days)
    report = render_markdown(result)
    print(report)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Сохранено: {path}")
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Сохранено: {path}")


if __name__ == "__main__":
    main()
