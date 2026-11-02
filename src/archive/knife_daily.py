"""Ежедневный отчёт по нише «Ножи кухонные» (наш тип — премиум-набор на подставке) → файл + Telegram.

    python -m src.knife_daily            # 3 запроса Saleflow (живая выдача) + 1 Evirma; ~1–2 мин
    python -m src.knife_daily --no-send  # без Telegram
    python -m src.knife_daily --from-files a.json b.json c.json   # выдача уже сохранена (MCP wb_check_rates, по порядку queries)

Что считает (по сравнению со вчерашним снимком):
  • рынок: медиана цены топ-30 по каждому запросу, доля рекламы, сколько карточек ≥ 3 000 ₽, лидеры по продавцам;
  • конкуренты из config/knives.yaml → watch: цена (изменение ≥ 3 %), реклама вкл/выкл, остаток FBS, место в выдаче;
  • новые карточки в топ-30, выпавшие из топ-30;
  • СПП конкурентов (Evirma) на нашу цену.
Файлы: data/processed/knives_daily/history.csv (все снимки), last.json; отчёт reports/monitor/knives/<дата>.md.
Telegram — тем же ботом, что пульс 249 (src.competitor_pulse.telegram). Токен не печатается.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

import yaml

from src.competitor_pulse import telegram

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime.now()
BASE = ROOT / "data" / "processed" / "knives_daily"


def _rows(d: dict) -> list[dict]:
    return [{"id": x["id"], "pos": x["position_general"], "price": x.get("final_price"), "ads": bool(x.get("promoted")),
                   "bal": x.get("balance"), "brand": x.get("brand") or "", "seller": x.get("seller") or "", "name": (x.get("name") or "")[:45],
                   "comments": x.get("comments")} for x in d.get("data") or []]


def _load(path: str) -> dict:
    t = open(path, encoding="utf-8").read()
    t = t[t.index("{"): t.rindex("}") + 1]                              # MCP-ответ может быть обёрнут текстом
    d = json.loads(t)
    if "content" in d:                                                  # обёртка MCP content[].text
        return _load_text(d["content"][0]["text"])
    return d


def _load_text(t: str) -> dict:
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def snapshot(queries: list[str], files: list[str] | None = None) -> dict[str, list[dict]]:
    out = {}
    if files:
        for q, f in zip(queries, files):
            out[q] = _rows(_load(f))
        return out
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch
    raw = ROOT / "data" / "raw" / "knives_daily" / NOW.strftime("%Y-%m-%d")
    raw.mkdir(parents=True, exist_ok=True)
    c = Client()
    for i, q in enumerate(queries):
        try:
            d = fetch(c, "wb_check_rates", {"query": q, "region": "Москва", "limit": 100})
        except Exception as e:                                          # noqa: BLE001
            print("выдача не получена:", q, str(e)[:80]); c = Client(); continue
        json.dump(d, open(raw / f"{NOW:%H%M}_{i}.json", "w", encoding="utf-8"), ensure_ascii=False)
        out[q] = _rows(d)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--from-files", nargs="+")
    a = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "knives.yaml").read_text(encoding="utf-8"))
    BASE.mkdir(parents=True, exist_ok=True)
    prev = json.load(open(BASE / "last.json", encoding="utf-8")) if (BASE / "last.json").exists() else {}
    cur = snapshot(cfg["queries"], a.from_files)
    if not cur:
        print("нет данных выдачи"); return
    L = [f"🔪 Ножи (811) — {NOW:%d.%m %H:%M}"]
    # 1. рынок по запросам
    for q, rows in cur.items():
        t30 = [r for r in rows if r["pos"] <= 30]
        if not t30:
            continue
        sellers = collections.Counter(r["seller"] for r in t30).most_common(2)
        L.append(f"\n«{q}»: медиана {st.median(r['price'] for r in t30 if r['price']):.0f} ₽, в рекламе {sum(r['ads'] for r in t30)}/{len(t30)}, "
                 f"≥3 000 ₽: {sum(1 for r in t30 if (r['price'] or 0) >= 3000)}; лидеры: " + ", ".join(f"{s[:14]}×{n}" for s, n in sellers))
        p_ids = {r["id"] for r in prev.get(q, []) if r["pos"] <= 30}
        if p_ids:
            new = [r for r in t30 if r["id"] not in p_ids]
            gone = len(p_ids - {r["id"] for r in t30})
            if new:
                L.append("  🆕 в топ-30: " + "; ".join(f"{r['id']} {r['price']} ₽ (место {r['pos']})" for r in new[:5]))
            if gone:
                L.append(f"  ⬇️ выпали из топ-30: {gone}")
    # 2. конкуренты из watch
    best = {}
    for q, rows in cur.items():
        for r in rows:
            if r["id"] not in best or r["pos"] < best[r["id"]]["pos"]:
                best[r["id"]] = r
    pbest = {}
    for q, rows in prev.items():
        for r in rows:
            if r["id"] not in pbest or r["pos"] < pbest[r["id"]]["pos"]:
                pbest[r["id"]] = r
    sig = []
    for sku in cfg["watch"]:
        b, a0 = best.get(sku), pbest.get(str(sku)) or pbest.get(sku)
        if not b:
            continue
        if a0:
            if a0.get("price") and b.get("price") and abs(b["price"] / a0["price"] - 1) >= 0.03:
                sig.append(f"💸 {sku}: {a0['price']} → {b['price']} ₽")
            if a0.get("ads") != b.get("ads"):
                sig.append(f"{'📣 включил' if b['ads'] else '📴 выключил'} рекламу {sku}")
            if (a0.get("bal") or 0) > 5 and b.get("bal") is not None and b["bal"] <= 5:
                sig.append(f"📦 {sku}: остаток {a0['bal']} → {b['bal']}")
            if abs(b["pos"] - a0["pos"]) >= 10:
                sig.append(f"{'⬆️' if b['pos'] < a0['pos'] else '⬇️'} {sku}: место {a0['pos']} → {b['pos']}")
    L.append("\nКонкуренты: " + (" | ".join(sig[:12]) if sig else "без изменений" if prev else "первый снимок"))
    seen = [best[s] for s in cfg["watch"] if s in best]
    if seen:
        L.append("Цены конкурентов: " + ", ".join(f"{r['id']}={r['price']}" for r in sorted(seen, key=lambda r: r["pos"])[:8]))
    # 3. СПП
    try:
        from src import evirma as E
        rg = E.ranges([cfg["subject_id"]], retries=1).get(cfg["subject_id"])
        if rg:
            seller_price = cfg["target_buyer_price"] / (1 - (E.spp_at(rg, cfg["target_buyer_price"] / 0.69, "fbs") or 31) / 100)
            L.append(f"СПП FBS: " + "; ".join(f"{b['price_from']}–{b['price_to'] or '∞'} → {b['spp']:g} %" for b in rg["fbs"])
                     + f". Наша цена продавца для {cfg['target_buyer_price']} ₽ ≈ {seller_price:.0f} ₽")
    except Exception:                                                   # noqa: BLE001
        pass
    text = "\n".join(L)
    # файлы
    new_file = not (BASE / "history.csv").exists()
    with open(BASE / "history.csv", "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "query", "sku", "pos", "price", "ads", "balance", "seller"])
        for q, rows in cur.items():
            for r in rows:
                if r["pos"] <= 50 or r["id"] in cfg["watch"]:
                    w.writerow([NOW.isoformat(timespec="minutes"), q, r["id"], r["pos"], r["price"], int(r["ads"]), r["bal"], r["seller"]])
    json.dump(cur, open(BASE / "last.json", "w", encoding="utf-8"), ensure_ascii=False)
    rep = ROOT / "reports" / "monitor" / "knives" / f"{NOW:%Y-%m-%d}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(text + "\n", encoding="utf-8")
    print(text)
    if not a.no_send:
        print("Telegram:", "отправлено" if telegram(text) else "не настроен")


if __name__ == "__main__":
    main()
