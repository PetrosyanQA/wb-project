"""Глубокий разбор победителей 777: срез рынка в МЕСЯЦ ВХОДА каждого победителя + отзывы победителей (2026-10-08).

    python -m src.winners_deep_collect --dry-run
    python -m src.winners_deep_collect

Победители — data/processed/launch_sample_2026-10-08.json (777, группа win). Для каждого месяца входа:
wb_subject products (top-500 по выручке за тот месяц) — кто был лидером, по какой цене, сколько карточек каждого типа.
Отзывы — wb_sku comments для победителей, у которых их ещё нет в каталоге. Уже скачанное пропускается;
3 сбоя подряд → стоп (неудачные вызовы тоже списываются с квоты).
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
OUT = "data/raw/saleflow/2026-10-08/winners777"
SAMPLE = "data/processed/launch_sample_2026-10-08.json"


def tasks() -> list[tuple[str, str, dict]]:
    from src.datastore import files
    W = json.load(open(SAMPLE, encoding="utf-8"))["777"]["win"]
    months = sorted({p["sku_first_date"][:7] for p in W})
    import glob, re
    have = {c["sku"] for c in files(777, "comments")} | {int(re.search(r"(\d{6,})", f).group(1)) for f in glob.glob("data/raw/saleflow/*/fresh777/comments/*.json") + glob.glob("data/raw/saleflow/*/strategy777/sku_*_comments.json")}
    L = [(f"{OUT}/comments/{p['id']}.json", "wb_sku", {"sku": p["id"], "report": "comments"}) for p in W if p["id"] not in have]
    for m in months:
        y, mm = map(int, m.split("-"))
        L.append((f"{OUT}/market/products100_{m}.json", "wb_subject",
                  {"subject_id": 777, "report": "products", "d1": f"{m}-01", "d2": f"{m}-{calendar.monthrange(y, mm)[1]:02d}", "limit": 100}))
    return L   # отзывы первыми (стабильны); срезы рынка — top-100 (limit 500 за прошлые месяцы upstream не отдаёт, 2026-10-08)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    T = [t for t in tasks() if not os.path.exists(t[0])]
    print(f"к скачиванию: {len(T)} (= запросов Saleflow)")
    for t in T:
        print("  ", t[0])
    if a.dry_run or not T:
        return
    from src.strategy_collect import Client, fetch, quota
    c = Client()
    streak = 0
    try:
        print("квота до:", quota(c))
        for k, (path, tool, args) in enumerate(T, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            for attempt in range(2):
                try:
                    json.dump(fetch(c, tool, args), open(path, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"[{k}/{len(T)}] → {path}")
                    streak = 0
                    break
                except Exception as e:                      # noqa: BLE001 — upstream Saleflow нестабилен
                    print(f"[{k}/{len(T)}] {tool} {args.get('sku') or args.get('d1')}: {str(e)[:160]} (попытка {attempt + 1})")
                    if "закрылся" in str(e):
                        c = Client()
                    if attempt == 0:
                        time.sleep(30)
            else:
                streak += 1
                if streak >= 3:
                    print("3 сбоя подряд — стоп")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()


if __name__ == "__main__":
    main()
