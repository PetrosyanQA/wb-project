"""Как заходили победители: выборка новичков (победители + контроль) и сбор их дневных рядов (2026-10-08).

    python -m src.launch_collect select            # 0 запросов → data/processed/launch_sample_2026-10-08.json
    python -m src.launch_collect collect --dry-run # сколько запросов уйдёт
    python -m src.launch_collect collect           # wb_sku by_period, по одному; уже скачанное пропускается

Выборка из products500 июля 2026 (top-500 по выручке) каждой ниши:
  новичок  = sku_first_date 2025-06-01 … 2026-05-31;
  победитель = новичок в top-100 по выручке (до 12, не больше 3 карточек на продавца);
  контроль = новичок с рангом ≥ 250 и минимальными продажами (до 8).
⚠️ Карточки совсем без продаж в top-500 не попадают → контроль = «слабые новички», а не «нулевые».
Ряд by_period: d1 = старт − 14 дней (не раньше 2025-05-15), d2 = вчера. Готовые ряды (777 daily_long, 2486 top100/daily)
переиспользуются, если покрывают старт карточки.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-08"
D2 = "2026-10-07"
OUT = f"data/raw/saleflow/{RUN}/launch"
SAMPLE = f"data/processed/launch_sample_{RUN}.json"
NICHES = {
    777: ("Держатели в авто", "data/raw/saleflow/2026-10-05/dna/777/products500_2026-07.json"),
    2486: ("Катушки рыболовные", "data/raw/saleflow/2026-10-07/strategy2486/products500_2026-07.json"),
    249: ("Эспандеры", "data/raw/saleflow/2026-10-07/newcomer/249/products500_2026-07.json"),
    2264: ("Рамки для номеров", "data/raw/saleflow/2026-10-07/newcomer/2264/products500_2026-07.json"),
    1203: ("Ершики", "data/raw/saleflow/2026-10-05/dna/1203/products500_2026-07.json"),
    1520: ("Ключницы", "data/raw/saleflow/2026-10-05/dna/1520/products500_2026-07.json"),
    731: ("Игрушки для животных", "data/raw/saleflow/2026-10-05/dna/731/products500_2026-07.json"),
}
OLD_DAILY = ["data/raw/saleflow/2026-10-07/strategy777/daily_long/{}.json",
             "data/raw/saleflow/2026-10-07/strategy2486/top100/daily/{}.json"]
N_WIN, N_CTL, PER_SELLER = 12, 8, 3


def rows(path: str) -> list[dict]:
    d = json.load(open(path, encoding="utf-8"))
    r = d.get("data", d) if isinstance(d, dict) else d
    return sorted(r, key=lambda p: -(p.get("revenue") or 0))


def is_new(p: dict) -> bool:
    return "2025-06-01" <= (p.get("sku_first_date") or "") < "2026-06-01"


def select() -> dict:
    out = {}
    for n, (name, path) in NICHES.items():
        R = rows(path)
        win, per = [], collections.Counter()
        for p in R[:100]:
            if is_new(p) and per[p.get("seller")] < PER_SELLER and len(win) < N_WIN:
                win.append(p); per[p.get("seller")] += 1
        ctl = sorted([p for p in R[250:] if is_new(p)], key=lambda p: p.get("sales") or 0)[:N_CTL]
        rank = {p["id"]: i + 1 for i, p in enumerate(R)}
        out[n] = {"name": name, "win": [slim(p, rank) for p in win], "ctl": [slim(p, rank) for p in ctl]}
        print(f"{n} {name}: победителей {len(win)}, контроль {len(ctl)}")
    os.makedirs(os.path.dirname(SAMPLE), exist_ok=True)
    json.dump(out, open(SAMPLE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", SAMPLE)
    return out


def slim(p: dict, rank: dict) -> dict:
    return {k: p.get(k) for k in ("id", "name", "seller", "brand", "sku_first_date", "sales", "revenue", "final_price",
                                  "final_price_average", "rating", "comments", "is_fbs")} | {"rank": rank[p["id"]]}


def existing(sku: int, start: str) -> str | None:
    """Готовый ряд годится, если начинается не позже старта карточки."""
    for pat in OLD_DAILY:
        f = pat.format(sku)
        if os.path.exists(f):
            d = json.load(open(f, encoding="utf-8"))
            if d and min(r["data"] for r in d) <= start:
                return f
    return None


def series_path(niche: int, sku: int) -> str:
    return f"{OUT}/{niche}/{sku}.json"


def todo(sample: dict) -> list[tuple[str, dict]]:
    L = []
    for n, s in sample.items():
        for p in s["win"] + s["ctl"]:
            start = p["sku_first_date"][:10]
            if existing(p["id"], start) or os.path.exists(series_path(int(n), p["id"])):
                continue
            d1 = max((dt.date.fromisoformat(start) - dt.timedelta(days=14)).isoformat(), "2025-05-15")
            L.append((series_path(int(n), p["id"]), {"sku": p["id"], "report": "by_period", "d1": d1, "d2": D2}))
    return L


def collect(dry: bool) -> None:
    from src.strategy_collect import Client, fetch, quota
    sample = json.load(open(SAMPLE, encoding="utf-8")) if os.path.exists(SAMPLE) else select()
    T = todo(sample)
    print(f"by_period к скачиванию: {len(T)} (= запросов к квоте Saleflow)")
    if dry or not T:
        return
    c = Client()
    fails, streak = [], 0
    try:
        print("квота до:", quota(c))
        for k, (path, args) in enumerate(T, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            for attempt in range(2):
                try:
                    json.dump(fetch(c, "wb_sku", args), open(path, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"[{k}/{len(T)}] → {path}")
                    streak = 0
                    break
                except Exception as e:                      # noqa: BLE001 — upstream Saleflow нестабилен
                    print(f"[{k}/{len(T)}] {args['sku']}: {str(e)[:160]} (попытка {attempt + 1})")
                    if "закрылся" in str(e):
                        c = Client()
                    if attempt == 0:
                        time.sleep(30)
            else:
                fails.append(path)
                streak += 1
                if streak >= 3:
                    print("3 сбоя подряд — стоп, чтобы не жечь квоту")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()
    print(f"не скачано: {fails}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["select", "collect"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    select() if a.step == "select" else collect(a.dry_run)


if __name__ == "__main__":
    main()
