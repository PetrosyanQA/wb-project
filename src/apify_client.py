"""Apify (международные тренды: Amazon, TikTok, Google Trends) — клиент с кэшем и потолком расходов (2026-10-12).

    python -m src.apify_client me                     # аккаунт, план, расход за месяц (0 $)
    python -m src.apify_client leash [--dry-run]      # первый скан: поводок-рулетка на Amazon / TikTok / Google Trends

Токен — только из .env (APIFY_TOKEN), никогда не печатается. Ответы → data/raw/apify/<дата>/<имя>.json;
повторный запуск с тем же именем в тот же день = 0 $ (кэш). Каждый запуск ограничен maxTotalChargeUsd (PAY_PER_EVENT).
Бесплатный план Apify — $5/мес. Не используем useCaptchaSolver и не обходим защиту сайтов.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
API = "https://api.apify.com/v2/"
OUT = f"data/raw/apify/{dt.date.today().isoformat()}"


def token() -> str:
    for line in open(".env", encoding="utf-8-sig"):
        if line.startswith("APIFY_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("нет APIFY_TOKEN в .env")


def call(path: str, body: dict | None = None, params: dict | None = None, timeout: int = 330):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def me() -> dict:
    d = call("users/me")["data"]
    u = call("users/me/usage/monthly")["data"]
    return {"user": d.get("username"), "plan": (d.get("plan") or {}).get("id"),
            "credits_usd": (d.get("plan") or {}).get("monthlyUsageCreditsUsd"),
            "used_usd": round(u.get("totalUsageCreditsUsdAfterVolumeDiscount") or u.get("totalUsageCreditsUsdBeforeVolumeDiscount") or 0, 3)}


RESERVE_USD = 0.5      # правило пользователя: стоп, когда до конца месячного лимита остаётся < $0,5


def run(name: str, actor: str, inp: dict, max_usd: float, timeout_s: int = 300) -> list:
    """Синхронный запуск актора → элементы датасета. Кэш по имени на сегодня.
    [аудит 2026-11-01] Проверка остатка — в каждом запуске (было только в main), пустые ответы не кэшируются."""
    path = f"{OUT}/{name}.json"
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    m = me()
    left = (m.get("credits_usd") or 5.0) - (m.get("used_usd") or 0)
    if left - max_usd < RESERVE_USD:
        raise SystemExit(f"Apify: остаток ${left:.2f}, запуск до ${max_usd:.2f} оставит < ${RESERVE_USD} — СТОП, скажите пользователю")
    items = call(f"acts/{actor}/run-sync-get-dataset-items", inp,
                 {"timeout": timeout_s, "maxTotalChargeUsd": max_usd, "memory": 1024}, timeout=timeout_s + 30)
    if items:                                                   # пустой/ошибочный ответ не кэшируем — иначе повтор вернёт пустоту
        os.makedirs(OUT, exist_ok=True)
        json.dump(items, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return items


LEASH = [  # (имя, актор, вход, потолок $)
    ("amazon_retractable_leash", "junglee~amazon-crawler",
     {"categoryOrProductUrls": [{"url": "https://www.amazon.com/s?k=retractable+dog+leash"}], "maxItemsPerStartUrl": 60,
      "scrapeProductDetails": False, "maxOffers": 0, "scrapeSellers": False, "useCaptchaSolver": False}, 0.40),
    ("tiktok_retractable_leash", "clockworks~tiktok-scraper",
     {"searchQueries": ["retractable dog leash"], "resultsPerPage": 40, "searchSection": "/video",
      "shouldDownloadVideos": False, "shouldDownloadCovers": False}, 0.50),   # минимум Apify — $0.50 на запуск
    ("gtrends_leash", "apify~google-trends-scraper",
     {"searchTerms": ["retractable dog leash", "поводок рулетка"], "timeRange": "today 5-y", "maxItems": 10}, 0.50),
]


TRENDS = [  # 01.11.2026: корректор осанки и кисти для макияжа — уникальные модели и тренды (потолок ≈ $4)
    ("amazon_posture", "junglee~amazon-crawler",
     {"categoryOrProductUrls": [{"url": "https://www.amazon.com/s?k=posture+corrector"}], "maxItemsPerStartUrl": 60,
      "scrapeProductDetails": False, "maxOffers": 0, "scrapeSellers": False, "useCaptchaSolver": False}, 0.40),
    ("amazon_brushes", "junglee~amazon-crawler",
     {"categoryOrProductUrls": [{"url": "https://www.amazon.com/s?k=makeup+brush+set"}], "maxItemsPerStartUrl": 60,
      "scrapeProductDetails": False, "maxOffers": 0, "scrapeSellers": False, "useCaptchaSolver": False}, 0.40),
    ("tiktok_posture", "clockworks~tiktok-scraper",
     {"searchQueries": ["posture corrector"], "resultsPerPage": 40, "searchSection": "/video",
      "shouldDownloadVideos": False, "shouldDownloadCovers": False}, 0.50),
    ("tiktok_brushes", "clockworks~tiktok-scraper",
     {"searchQueries": ["makeup brush set"], "resultsPerPage": 40, "searchSection": "/video",
      "shouldDownloadVideos": False, "shouldDownloadCovers": False}, 0.50),
    ("instagram_tags", "apify~instagram-hashtag-scraper",
     {"hashtags": ["posturecorrector", "makeupbrushes"], "resultsLimit": 30}, 0.50),
    ("gtrends_both", "apify~google-trends-scraper",
     {"searchTerms": ["posture corrector", "makeup brush set", "корректор осанки", "кисти для макияжа"], "timeRange": "today 5-y",
      "geo": "", "maxItems": 10}, 0.50),
    ("pinterest_both", "epctex~pinterest-scraper",
     {"search": ["posture corrector", "makeup brush set aesthetic"], "maxItems": 40}, 0.50),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["me", "leash", "trends"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "me":
        print(me())
        return
    jobs = TRENDS if a.cmd == "trends" else LEASH
    print("до:", me())
    print(f"потолок скана: ${sum(x[3] for x in jobs):.2f}")
    if a.dry_run:
        return
    for name, actor, inp, cap in jobs:
        try:
            items = run(name, actor, inp, cap)                  # остаток проверяется внутри run()
            print(f"{name}: {len(items)} шт → {OUT}/{name}.json")
        except Exception as e:                                  # noqa: BLE001 — один актор не должен валить скан
            print(f"{name}: ошибка {str(e)[:160]}")
    print("после:", me())


if __name__ == "__main__":
    main()
