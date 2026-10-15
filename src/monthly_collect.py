"""Top-100 ниши за каждый месяц 2025-08 … 2026-07 (для src.evolution). 1 запрос на месяц, кэш.

    python -m src.monthly_collect --niche 52 [--dry-run]

Папка: <base пресета strategy>/monthly/products_YYYY-MM.json. 3 сбоя подряд → пауза 30 с, 4 → стоп.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
MONTHS = [(2025, m) for m in range(8, 13)] + [(2026, m) for m in range(1, 8)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    from src.strategy import PRESETS
    out = f"{os.path.dirname(PRESETS[a.niche]['trends'])}/monthly"
    todo = [(y, m) for y, m in MONTHS if not os.path.exists(f"{out}/products_{y}-{m:02d}.json")]
    print(f"месяцев к скачиванию: {len(todo)}")
    if a.dry_run or not todo:
        return
    from src.strategy_collect import Client, fetch
    os.makedirs(out, exist_ok=True)
    c, streak = Client(), 0
    try:
        for y, m in todo:
            try:
                r = fetch(c, "wb_subject", {"subject_id": a.niche, "report": "products", "d1": f"{y}-{m:02d}-01",
                                            "d2": f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}", "limit": 100})
                json.dump(r, open(f"{out}/products_{y}-{m:02d}.json", "w", encoding="utf-8"), ensure_ascii=False)
                print("ok", y, m)
                streak = 0
            except Exception as e:                       # noqa: BLE001 — upstream Saleflow нестабилен
                print("fail", y, m, str(e)[:80])
                streak += 1
                if streak >= 4:
                    print("4 сбоя подряд — стоп")
                    break
                if streak == 3:
                    time.sleep(30)
    finally:
        c.close()


if __name__ == "__main__":
    main()
