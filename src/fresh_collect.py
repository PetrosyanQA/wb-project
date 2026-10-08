"""Свежие данные по 5 главным конкурентам 777 (Saleflow, по одному запросу; уже скачанное пропускается).

    python -m src.fresh_collect --dry-run
    python -m src.fresh_collect                  # keywords (позиции по запросам) × 5 + comments × 3
    python -m src.fresh_collect --watch          # только by_period за 21 день × 5 — для еженедельной слежки

Сохраняет в data/raw/saleflow/<сегодня>/fresh777/. Конкуренты — из reports/top100_777_analysis + strategy_777:
487711855 (вакуум+магнит, №2 top-100), 485786521 (MagSafe-премиум, лидер без жалоб), 494403950 (вакуум, ИП Бракар),
566117039 (зажим+вакуум, демпинг), 148983914 (HYRO, №1 по выручке в сентябре).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
COMPETITORS = [487711855, 485786521, 494403950, 566117039, 148983914]
COMMENTS = [487711855, 485786521, 494403950]


def tasks(watch: bool) -> list[tuple[str, dict]]:
    today = dt.date.today()
    d2 = (today - dt.timedelta(days=1)).isoformat()
    base = f"data/raw/saleflow/{today.isoformat()}/fresh777"
    if watch:
        d1 = (today - dt.timedelta(days=45)).isoformat()   # короткое окно (21 дн.) upstream отдаёт с ошибкой (2026-10-08)
        return [(f"{base}/watch/{s}_by_period.json", {"sku": s, "report": "by_period", "d1": d1, "d2": d2}) for s in COMPETITORS]
    d1 = (today - dt.timedelta(days=30)).isoformat()
    L = [(f"{base}/keywords/{s}.json", {"sku": s, "report": "keywords", "d1": d1, "d2": d2}) for s in COMPETITORS]
    L += [(f"{base}/comments/{s}.json", {"sku": s, "report": "comments"}) for s in COMMENTS]
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--only", choices=["keywords", "comments"], help="скачать только этот тип")
    a = ap.parse_args()
    T = [t for t in tasks(a.watch) if not os.path.exists(t[0]) and (not a.only or t[1]["report"] == a.only)]
    print(f"к скачиванию: {len(T)} (= запросов Saleflow)")
    if a.dry_run or not T:
        return
    from src.strategy_collect import Client, fetch, quota
    c = Client()
    try:
        print("квота до:", quota(c))
        streak = 0
        for k, (path, args) in enumerate(T, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            for attempt in range(2):
                try:
                    json.dump(fetch(c, "wb_sku", args), open(path, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"[{k}/{len(T)}] → {path}")
                    streak = 0
                    break
                except Exception as e:                      # noqa: BLE001 — upstream Saleflow нестабилен
                    print(f"[{k}/{len(T)}] {args['sku']} {args['report']}: {str(e)[:160]} (попытка {attempt + 1})")
                    if "закрылся" in str(e):
                        c = Client()
                    if attempt == 0:
                        time.sleep(30)
            else:
                streak += 1
                if streak >= 3:                              # неудачные вызовы тоже списываются с квоты
                    print("3 сбоя подряд — стоп, чтобы не жечь квоту")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()


if __name__ == "__main__":
    main()
