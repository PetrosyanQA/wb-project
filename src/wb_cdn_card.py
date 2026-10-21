"""Карточка товара WB из публичного CDN (basket-NN.wbbasket.ru/…/info/ru/card.json) — 0 запросов Saleflow/MPStats (2026-10-16).

    python -m src.wb_cdn_card 901782010 1008302213 …     # → data/raw/wb_cdn/<sku>.json (кэш: уже скачанное не качаем)

Формат совместим с niche_v5.card_dims (options[{name, value}], imt_name). Корзина ищется перебором basket-01…40, как в
photo-editor/wb-fetch-photos.sh (40 потоков, первый ответ); найденный номер сохраняется в поле _basket.
"""
from __future__ import annotations

import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
DIR = "data/raw/wb_cdn"
UA = {"User-Agent": "Mozilla/5.0"}


def url(sku: int, n: int) -> str:
    return f"https://basket-{n:02d}.wbbasket.ru/vol{sku // 100000}/part{sku // 1000}/{sku}/info/ru/card.json"


def fetch(sku: int) -> dict | None:
    p = f"{DIR}/{sku}.json"
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def get(n):
        try:
            r = requests.get(url(sku, n), headers=UA, timeout=8)
            return (n, r.json()) if r.status_code == 200 and r.text.startswith("{") else None
        except (requests.RequestException, ValueError):
            return None

    hit = None
    ex = ThreadPoolExecutor(80)                        # все корзины разом (новые SKU > 1 млрд — basket-41+), берём первый ответ (по порядку ждали таймаутов)
    for f in as_completed([ex.submit(get, n) for n in range(1, 81)]):
        if f.result():
            hit = f.result()
            break
    ex.shutdown(wait=False, cancel_futures=True)
    if hit:
        n, d = hit
        d["_basket"] = n
        os.makedirs(DIR, exist_ok=True)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        return d
    return None


def main() -> None:
    from src.niche_v5 import card_dims
    for s in sys.argv[1:]:
        d = fetch(int(s))
        print(s, card_dims(d) if d else "не найдено", flush=True)


if __name__ == "__main__":
    main()
