"""Ежедневная проверка в облаке (GitHub Actions) — работает без компьютера пользователя.

    python -m src.cloud_daily            # отчёт → Telegram (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID из окружения/секретов)
    python -m src.cloud_daily --no-send  # только печать

Что проверяет (без Saleflow, только публичные/свои API):
  • Evirma: СПП FBS для нашей ниши и запасной — в какую полосу попадает наша цена продавца, сдвинулась ли граница;
  • сигнал, если наша цена ниже границы полосы 31 % или СПП на нашей цене < порога (правило из decision_249_band_set);
  • (позже) WB Seller API — заказы, остаток, реклама, когда в секретах появится WB_TOKEN_* и карточка.
Параметры — config/cloud.yaml. Состояние между запусками — cloud_state/last.json (workflow коммитит его обратно).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests
import yaml

from src import evirma as E

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "cloud_state" / "last.json"


def send(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    try:
        return requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": chat, "text": text[:4000]}, timeout=20).ok
    except requests.RequestException:
        return False


def border(bands: list[dict]) -> int | None:
    """Нижняя граница полосы FBS с самой высокой типичной СПП (там, где мы хотим стоять)."""
    best = max(bands, key=lambda b: b["spp"] or 0, default=None)
    return best["price_from"] if best and len(bands) > 1 else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "cloud.yaml").read_text(encoding="utf-8"))
    prev = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    items = cfg["products"]
    rg = E.ranges([p["subject_id"] for p in items], retries=3)
    L, alerts, state = [f"📊 WB ежедневная проверка — {dt.date.today():%d.%m.%Y}"], [], {}
    for p in items:
        r = rg.get(p["subject_id"])
        if not r:
            alerts.append(f"⚠️ {p['name']}: Evirma не ответила")
            continue
        fbs = r["fbs"]
        spp = E.spp_at(r, p["seller_price"], "fbs")
        b = border(fbs) if p.get("target_spp") else None
        buyer = round(p["seller_price"] * (1 - (spp or 0) / 100))
        bands = "; ".join(f"{x['price_from']}–{x['price_to'] or '∞'} ₽ → {x['spp']:g} %" for x in fbs)
        L.append(f"\n{p['name']} ({p['subject_id']}): цена продавца {p['seller_price']} ₽ → СПП {spp} % → покупатель ≈ {buyer} ₽\n  полосы FBS: {bands}")
        state[str(p["subject_id"])] = {"spp": spp, "border": b, "bands": fbs}
        old = prev.get(str(p["subject_id"]), {})
        if b is not None and old.get("border") is not None and b != old["border"]:
            alerts.append(f"🔀 {p['name']}: граница верхней полосы СПП сдвинулась {old['border']} → {b} ₽")
        if p.get("target_spp") and b is not None and p["seller_price"] < b:
            alerts.append(f"🚨 {p['name']}: наша цена {p['seller_price']} ₽ НИЖЕ границы {b} ₽ — СПП упадёт до {spp} %. "
                          f"Правило: цена = граница + 4 % ≈ {round(b * 1.04)} ₽")
        if old.get("spp") is not None and spp is not None and old["spp"] - spp >= 5:
            alerts.append(f"📉 {p['name']}: СПП на нашей цене упала {old['spp']:g} → {spp:g} % за сутки (покупатель ≈ {buyer} ₽)")
        if p.get("min_spp") and (spp or 0) <= p["min_spp"]:
            alerts.append(f"🚨 {p['name']}: СПП на нашей цене {spp} % ≤ порога {p['min_spp']} % — {p.get('fallback', 'пересмотр')}")
    L.append("\n" + ("\n".join(alerts) if alerts else "✅ Сигналов нет: цена в нужной полосе СПП."))
    text = "\n".join(L)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"date": dt.date.today().isoformat(), **state}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    if not a.no_send:
        print("Telegram:", "отправлено" if send(text) else "не настроен (нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")


if __name__ == "__main__":
    main()
