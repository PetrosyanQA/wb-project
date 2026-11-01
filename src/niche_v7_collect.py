"""Докачка карточек ниш за октябрь-2026 (wb_subject products, fbs=1, 500 строк = 1 запрос) для отбора v7.

    python -m src.niche_v7_collect --max 440        # очередь data/processed/_v7_queue.json; скачанное не повторяет
Порядок: ниши, прошедшие этап 2 на июле (пересчёт на свежих данных) → ниши без карточек (одежда/обувь/бельё с размерной
сеткой — в конце). Пауза между запросами; при 429 — ожидание и повтор; стоп, если лимит Saleflow < 40.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from src.niche_v7 import P500
from src.saleflow_stdio import Client

SIZED = ("Одежда", "Обувь", "Белье", "Спортивная одежда", "Спортивная обувь", "Детская одежда", "Белье для малышей")


def queue() -> list[int]:
    q = json.load(open("data/processed/_v7_queue.json"))
    names = {r["id"]: r["name"] for r in json.load(open("data/processed/niche_v7_screen_2026-11-01.json", encoding="utf-8"))["rows"]}
    sized = lambda i: names.get(i, "").split(" / ")[0] in SIZED                      # noqa: E731
    miss = [i for i in q["miss"] if not sized(i)] + [i for i in q["miss"] if sized(i)]
    return q["ok"] + miss


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=440)
    a = ap.parse_args()
    os.makedirs(P500, exist_ok=True)
    todo = [i for i in queue() if not os.path.exists(f"{P500}/{i}.json")][:a.max]
    print(f"в очереди {len(todo)}", flush=True)
    c = Client()
    done = fails = 0
    try:
        for k, sid in enumerate(todo):
            if k % 50 == 0:
                lim = c.call("account_limits", {})
                rem = (lim.get("remaining") if isinstance(lim, dict) else None)
                if rem is None and isinstance(lim, str) and "Остаток:" in lim:
                    rem = int(lim.split("Остаток:")[1].split()[0])
                print(f"лимит: {rem}", flush=True)
                if rem is not None and rem < 40:
                    print("стоп: лимит < 40")
                    break
            for attempt in range(4):
                try:
                    res = c.call("wb_subject", {"subject_id": sid, "report": "products", "d1": "2026-10-01",
                                                "d2": "2026-10-31", "limit": 500, "fbs": 1})
                    json.dump(res, open(f"{P500}/{sid}.json", "w", encoding="utf-8"), ensure_ascii=False)
                    done += 1
                    print(f"{k + 1}/{len(todo)} {sid}: {len(res.get('data', []))} строк", flush=True)
                    break
                except Exception as e:                                               # noqa: BLE001
                    msg = str(e)[:150]
                    print(f"{sid}: ошибка ({attempt + 1}) {msg}", flush=True)
                    time.sleep(60 if "429" in msg else 15)
                    if "429" in msg or "SSE" in msg:
                        c.close()
                        c = Client()
            else:
                fails += 1
                if fails >= 8:
                    print("стоп: 8 ниш подряд с ошибкой")
                    break
                continue
            fails = 0
            time.sleep(2)
    finally:
        c.close()
    print(f"готово: {done}")


if __name__ == "__main__":
    main()
