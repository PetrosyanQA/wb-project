"""Пульс конкурентов каждые 2 часа: топ живой выдачи WB по главным запросам → сигналы (Telegram + файл).

    python -m src.competitor_pulse --niche 249          # 1 запрос Saleflow на запрос пресета (2 для 249)

Сигналы по топ-N выдачи (и по SKU из config/launch.yaml → competitors):
  💸 цена изменилась ≥ 10 %   📴 выключил рекламу   📦 закончился / почти закончился товар (FBS-остаток)
  🆕 новый SKU в топ-N        ⬆️⬇️ сдвиг места ≥ 10
История: data/processed/pulse_<niche>/history.csv; последний снимок: last.json; сигналы: reports/monitor/pulse/<дата>.md.
Telegram: токен бота — из настроек плагина (~/.claude/channels/telegram/.env), чат — `config/notify.yaml → telegram_chat_id`
(заполняется после привязки чата). Токен не печатается и не копируется в проект.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests
import yaml

from src.niche_monitor import PRESETS

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime.now()
TOP = 10


def telegram(text: str) -> bool:
    cfg = ROOT / "config" / "notify.yaml"
    chat = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("telegram_chat_id") if cfg.exists() else None
    env = Path.home() / ".claude" / "channels" / "telegram" / ".env"
    if not chat or not env.exists():
        return False
    token = next((l.split("=", 1)[1].strip() for l in env.read_text(encoding="utf-8").splitlines()
                  if l.startswith("TELEGRAM_BOT_TOKEN=")), "")
    if not token:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text[:4000]}, timeout=20)
        return r.ok
    except requests.RequestException:
        return False


def snapshot(niche: int) -> dict[int, dict]:
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch
    raw = ROOT / "data" / "raw" / "pulse" / str(niche) / NOW.strftime("%Y-%m-%d")
    raw.mkdir(parents=True, exist_ok=True)
    c, snap = Client(), {}
    for i, q in enumerate(PRESETS[niche]["queries"]):
        try:
            d = fetch(c, "wb_check_rates", {"query": q, "region": "Москва", "limit": 100})
        except Exception as e:                                           # noqa: BLE001
            print("выдача не получена:", q, str(e)[:80]); c = Client(); continue
        json.dump(d, open(raw / f"{NOW:%H%M}_{i}.json", "w", encoding="utf-8"), ensure_ascii=False)
        for x in d.get("data") or []:
            s = snap.setdefault(x["id"], {"name": x.get("name", "")[:40], "pos": x["position_general"], "price": x.get("final_price"),
                                          "ads": bool(x.get("promoted")), "balance": x.get("balance"), "fbs": x.get("is_fbs"), "q": i})
            if x["position_general"] < s["pos"]:
                s.update(pos=x["position_general"], q=i)
    return snap


def signals(prev: dict, cur: dict, watch: set[int]) -> list[str]:
    S = []
    top_now = {k for k, v in cur.items() if v["pos"] <= TOP}
    top_prev = {int(k) for k, v in prev.items() if v["pos"] <= TOP}
    for sku in sorted(top_now | (watch & set(cur)), key=lambda k: cur[k]["pos"]):
        a, b = prev.get(str(sku)), cur[sku]
        tag = f"{sku} «{b['name']}» (место {b['pos']})"
        if a is None:
            if prev and sku in top_now and sku not in top_prev:
                S.append(f"🆕 {tag}: новый в топ-{TOP}, {b['price']} ₽, реклама {'да' if b['ads'] else 'нет'}")
            continue
        if a.get("price") and b.get("price") and abs(b["price"] / a["price"] - 1) >= 0.10:
            S.append(f"💸 {tag}: цена {a['price']} → {b['price']} ₽")
        if a.get("ads") and not b.get("ads"):
            S.append(f"📴 {tag}: выключил рекламу")
        if (a.get("balance") or 0) > 5 and b.get("balance") is not None and b["balance"] <= 5:      # только переход через порог
            S.append(f"📦 {tag}: остаток {a['balance']} → {b['balance']} шт")
        if abs(b["pos"] - a["pos"]) >= 10 and min(a["pos"], b["pos"]) <= TOP:
            S.append(f"{'⬆️' if b['pos'] < a['pos'] else '⬇️'} {tag}: место {a['pos']} → {b['pos']}")
    for sku in top_prev - top_now - (watch & set(cur)):
        a = prev[str(sku)]
        S.append(f"⬇️ {sku} «{a['name']}»: выпал из топ-{TOP} (было место {a['pos']})")
    return S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, default=249)
    a = ap.parse_args()
    base = ROOT / "data" / "processed" / f"pulse_{a.niche}"
    base.mkdir(parents=True, exist_ok=True)
    launch = yaml.safe_load((ROOT / "config" / "launch.yaml").read_text(encoding="utf-8")) or {}
    watch = set(launch.get("competitors") or [])
    prev = json.load(open(base / "last.json", encoding="utf-8")) if (base / "last.json").exists() else {}
    cur = snapshot(a.niche)
    if not cur:
        print("нет данных выдачи — пропуск"); return
    S = signals(prev, cur, watch)
    hist, new = base / "history.csv", not (base / "history.csv").exists()
    with open(hist, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "sku", "pos", "price", "ads", "balance", "fbs"])
        for sku, v in cur.items():
            if v["pos"] <= 30 or sku in watch:
                w.writerow([NOW.isoformat(timespec="minutes"), sku, v["pos"], v["price"], int(v["ads"]), v["balance"], v["fbs"]])
    json.dump({str(k): v for k, v in cur.items()}, open(base / "last.json", "w", encoding="utf-8"), ensure_ascii=False)
    rep = ROOT / "reports" / "monitor" / "pulse" / f"{a.niche}_{NOW:%Y-%m-%d}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    block = f"\n## {NOW:%H:%M}\n" + ("\n".join(f"- {s}" for s in S) if S else "- без изменений") + "\n"
    if not rep.exists():
        block = f"# Пульс конкурентов {a.niche} — {NOW:%Y-%m-%d} (живая выдача, Москва, топ-{TOP})\n" + block
    with open(rep, "a", encoding="utf-8") as f:
        f.write(block)
    print(block)
    if S:
        sent = telegram(f"Ниша {a.niche}, {NOW:%d.%m %H:%M}\n" + "\n".join(S[:15]))
        print("Telegram:", "отправлено" if sent else "не настроен (config/notify.yaml → telegram_chat_id)")


if __name__ == "__main__":
    main()
