"""Глубокий недельный разбор ниш (2026-10-16): дневные ряды ниши (by_date) за 2 года + полная месячная история (trends с 2020)
+ дневные ряды топ-карточек подтипов ниши 52. 1 запрос = 1 кусок ≤ 150 дней; уже скачанное пропускается.

    python -m src.weekly_collect [--dry-run]

Папка: data/raw/saleflow/2026-10-16/weekly/<ниша>/… и …/weekly/seg52/<sku>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = "data/raw/saleflow/2026-10-16/weekly"
NICHES = {52: "Кошельки", 316: "Визитницы", 1381: "Кредитницы", 729: "Поводки", 2486: "Катушки рыболовные",
          7640: "Сумки спортивные", 937: "Коробки для хранения", 777: "Держатели в авто", 2499: "Наборы для рыбалки",
          138: "Рюкзаки", 236: "Фигурки и статуэтки", 235: "Фотоальбомы", 2556: "Подарочные боксы"}
D1, D2 = "2024-08-01", "2026-07-31"          # 2 года → YoY по неделям; дальше Saleflow неполный
SEG = {"картхолдер": r"картхолдер|для карт|зажим", "портмоне авто/документы": r"автодок|документ",
       "компактный кошелёк": r"маленьк|компакт|мини"}


def chunks(d1: str, d2: str, days: int = 150) -> list[tuple[str, str]]:
    a, b = dt.date.fromisoformat(d1), dt.date.fromisoformat(d2)
    out = []
    while a <= b:
        e = min(b, a + dt.timedelta(days=days - 1))
        out.append((a.isoformat(), e.isoformat()))
        a = e + dt.timedelta(days=1)
    return out


def seg_cards(top: int = 10) -> dict[str, list[int]]:
    d = json.load(open("data/raw/saleflow/2026-10-15/strategy52/products500_2026-07.json", encoding="utf-8"))
    R = [x for x in (d.get("data", d) if isinstance(d, dict) else d) if isinstance(x, dict) and x.get("sales")]
    R.sort(key=lambda x: -x["revenue"])
    out = {}
    for s, rx in SEG.items():
        L = [x["id"] for x in R if re.search(rx, x["name"].lower()) and re.search(r"натурал|кожан|кожи", x["name"].lower())
             and 1200 <= x["revenue"] / x["sales"] <= 2300]
        out[s] = L[:top]
    return out


def tasks() -> list[tuple[str, str, dict]]:
    T = []
    for n in NICHES:
        T.append((f"{BASE}/{n}/trends_full.json", "wb_subject", {"subject_id": n, "report": "trends", "d1": "2020-01-01", "d2": "2026-09-30",
                                                                    "group_by": "month"}))
        for a, b in chunks(D1, D2):
            T.append((f"{BASE}/{n}/by_date_{a}_{b}.json", "wb_subject", {"subject_id": n, "report": "by_date", "d1": a, "d2": b}))
    for s, skus in seg_cards().items():
        for sku in skus:
            for a, b in chunks("2025-08-01", D2):
                T.append((f"{BASE}/seg52/{sku}_{a}.json", "wb_sku", {"sku": sku, "report": "by_period", "d1": a, "d2": b}))
    return list({t[0]: t for t in T}.values())                  # карточка может быть в двух подтипах


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    T = [t for t in tasks() if not os.path.exists(t[0])]
    print("к скачиванию:", len(T))
    if a.dry_run or not T:
        return
    from src.strategy_collect import Client, fetch
    c, streak = Client(), 0
    try:
        for k, (p, tool, args) in enumerate(T, 1):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            try:
                json.dump(fetch(c, tool, args, timeout=200), open(p, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{k}/{len(T)}] ok {p[len(BASE) + 1:]}")
                streak = 0
            except Exception as e:                       # noqa: BLE001 — upstream Saleflow нестабилен
                print(f"[{k}/{len(T)}] fail {p[len(BASE) + 1:]}: {str(e)[:70]}")
                streak += 1
                if "закрылся" in str(e):
                    c = Client()
                if streak >= 4:
                    print("4 сбоя подряд — стоп")
                    break
    finally:
        c.close()


if __name__ == "__main__":
    main()
