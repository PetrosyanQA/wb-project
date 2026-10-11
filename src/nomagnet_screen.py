"""Скрин ниш без «чувствительного груза» (敏感货): магниты, аккумуляторы/электроника, жидкости/порошки (2026-10-11). 0 запросов.

    python -m src.nomagnet_screen                 # → data/processed/nomagnet_screen_2026-10-11.json + таблица
    python -m src.nomagnet_screen --only magnet   # если карго/поставщик подтвердит, что запрещены только магниты

Почему: поставщики/карго не могут отправлять товары с магнитами (нужны новые разрешения после изменений правил;
сообщение пользователя 2026-10-11). Вакуумно-магнитный держатель 777 выбыл.
Метод: для каждой ниши из прошлых скринов (newcomer_screen 07.10 — единая модель новичка; fresh stageB 06.10 с
исправленной ценой; ДНК 24 ниш 05.10) берём сохранённый top-100 (src.datastore) и считаем долю выручки карточек,
в названии которых есть признаки чувствительного груза. Ниша «чистая», если доля ≤ CLEAN_MAX, и при этом сам
продукт-кандидат можно выбрать без магнита (доля < 100%).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from src.datastore import latest, rows

sys.stdout.reconfigure(encoding="utf-8")
OUT = "data/processed/nomagnet_screen_2026-10-11.json"
SENSITIVE = {
    "magnet": r"магнит|magsafe|магсейф|неодим",
    "battery": r"аккумулят|батаре|заряд|usb|type-c|led\b|светодиод|подсветк|электр|беспровод|bluetooth|пульт|мотор|вибро|датчик|gps",
    "liquid": r"жидк|спрей|масл|лосьон|гель\b|краск|клей\b|аэрозол|парфюм|духи|порош",
}
CLEAN_MAX = 20.0      # % выручки top-100 с признаками чувствительного груза


def top100(niche: int) -> list[dict]:
    for kind in ("products500", "products", "top100"):
        p = latest(niche, kind)
        if p:
            R = [r for r in rows(p) if isinstance(r, dict) and r.get("name")]
            if len(R) >= 30:
                return sorted(R, key=lambda r: -(r.get("revenue") or 0))[:100]
    return []


def shares(R: list[dict], kinds: list[str]) -> dict:
    tot = sum(r.get("revenue") or 0 for r in R) or 1
    out = {}
    for k in kinds:
        out[k] = round(sum(r.get("revenue") or 0 for r in R if re.search(SENSITIVE[k], r["name"].lower())) / tot * 100, 1)
    rx = "|".join(SENSITIVE[k] for k in kinds)
    out["any"] = round(sum(r.get("revenue") or 0 for r in R if re.search(rx, r["name"].lower())) / tot * 100, 1)
    return out


def candidates() -> dict[int, dict]:
    C = {}
    for r in json.load(open("data/processed/newcomer_screen_2026-10-07.json", encoding="utf-8")):
        C[r["id"]] = {"name": r["name"], "src": "newcomer_07.10", "price": r.get("price"), "yuan": r.get("yuan"),
                      "p50_day": r.get("p50"), "profit12_p50": r.get("profit12_p50"), "payback": r.get("payback_p50"),
                      "launch": r.get("launch"), "fails": [k for k, v in r["gates"].items() if v is False]}
    for f in ("data/processed/fresh_stageB_2026-10-06_2kg_pricefix.json", "data/processed/fresh_stageB_2026-10-06_pricefix.json"):
        if os.path.exists(f):
            for r in json.load(open(f, encoding="utf-8")):
                C.setdefault(r["id"], {"name": r["name"], "src": "stageB_06.10", "price": r.get("price_s"), "yuan": r.get("yuan78"),
                                       "margin": r.get("margin"), "roi": r.get("roi"), "fails": r.get("fails", [])})
    return C


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(SENSITIVE), action="append")
    a = ap.parse_args()
    kinds = a.only or list(SENSITIVE)
    res = []
    for n, c in candidates().items():
        R = top100(n)
        s = shares(R, kinds) if R else None
        clean = s is not None and s["any"] <= CLEAN_MAX
        res.append({"id": n, **c, "top100_n": len(R), "sensitive_pct": s, "clean": clean})
    res.sort(key=lambda r: (not r["clean"], -(r.get("profit12_p50") or -1e9), -(r.get("margin") or 0)))
    json.dump({"kinds": kinds, "clean_max_pct": CLEAN_MAX, "rows": res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"фильтр: {kinds}, чистая ниша = ≤ {CLEAN_MAX}% выручки top-100 с признаками\n")
    print("ниша | источник | чувств.% (магнит/аккум./жидк.) | цена | ¥ | шт/день P50 | прибыль 12 мес P50 | окуп. | провалы")
    for r in res:
        s = r["sensitive_pct"] or {}
        print(f"{'✅' if r['clean'] else '❌'} {r['id']} {r['name'][:42]} | {r['src']} | {s.get('any')} ({s.get('magnet')}/{s.get('battery')}/{s.get('liquid')}) | "
              f"{r.get('price')} | {r.get('yuan')} | {r.get('p50_day', '—')} | {r.get('profit12_p50', '—')} | {r.get('payback', '—')} | {r.get('fails')}")
    print("→", OUT)


if __name__ == "__main__":
    main()
