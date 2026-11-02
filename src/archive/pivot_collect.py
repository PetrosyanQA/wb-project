"""Сбор для разворота «без магнитов» (2026-10-11): отзывы лидеров держателей с зажимом (777, без магнита) +
габариты/вес и отзывы лидеров мисок для животных (1126). Уже скачанное пропускается; 3 сбоя подряд → стоп.

    python -m src.pivot_collect --dry-run
    python -m src.pivot_collect
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
OUT = "data/raw/saleflow/2026-10-11/pivot"
CLAMP_777 = [208015625, 163375828, 189246305]               # зажим/присоска, без магнита: 8 098 / 6 122 / 5 114 шт в июле
BOWLS_1126 = [137053734, 772685316, 396806148, 781974428, 160003098]   # миски на подставке/керамика в полосе 2 000–2 300 ₽ до СПП


LEASH_729 = [517717379, 209201610, 111647586]            # поводки-рулетки: лидеры top-100 (март 2026)
FISHSET_2499 = [185738754, 49364175, 548025847]       # наборы для рыбалки: лидеры top-100 (декабрь 2025)


def tasks() -> list[tuple[str, str, dict]]:
    L = [(f"{OUT}/729/cards/{s}.json", "wb_card_content", {"sku": str(s)}) for s in LEASH_729]
    L += [(f"{OUT}/729/comments/{s}.json", "wb_sku", {"sku": s, "report": "comments"}) for s in LEASH_729]
    L += [(f"{OUT}/2499/cards/{s}.json", "wb_card_content", {"sku": str(s)}) for s in FISHSET_2499[:2]]
    L += [(f"{OUT}/2499/comments/{s}.json", "wb_sku", {"sku": s, "report": "comments"}) for s in FISHSET_2499[:3]]
    L += [(f"{OUT}/777/comments/{s}.json", "wb_sku", {"sku": s, "report": "comments"}) for s in CLAMP_777]
    # 1126 миски сняты 2026-10-11 (подставки 44 см, керамика — объём)

    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    T = [t for t in tasks() if not os.path.exists(t[0])]
    print(f"к скачиванию: {len(T)} (= запросов Saleflow)")
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
                    print(f"[{k}/{len(T)}] {tool} {args.get('sku')}: {str(e)[:160]} (попытка {attempt + 1})")
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
