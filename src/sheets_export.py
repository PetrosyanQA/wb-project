"""Строки для Google Sheets «WB 249 мониторинг» из журналов мониторинга (0 запросов).

    python -m src.sheets_export --niche 249            # только НОВОЕ с прошлой выгрузки → data/processed/monitor_249/sheets_rows.json
    python -m src.sheets_export --niche 249 --all      # всё заново (первичное заполнение)
    python -m src.sheets_export --niche 249 --commit   # отметить, что строки из sheets_rows.json записаны в таблицу

Писать в таблицу умеет только Claude (коннектор Google Sheets, append_values): скрипт готовит строки по вкладкам,
Claude дописывает их и вызывает --commit. ID таблицы — config/notify.yaml → sheets_id.
Вкладки: «Ниша по дням» (итоги дня), «Конкуренты» (топ-20 дня по продажам + конкуренты из launch.yaml),
«Выдача» (competitor_pulse, места ≤ 30), «СПП» (Evirma).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
TOP = 20


def num(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def rows_csv(p: Path) -> list[dict]:
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def build(niche: int, since: dict) -> dict[str, list[list]]:
    base = ROOT / "data" / "processed"
    watch = set((yaml.safe_load((ROOT / "config" / "launch.yaml").read_text(encoding="utf-8")) or {}).get("competitors") or [])
    by_day = defaultdict(list)
    for r in rows_csv(base / f"monitor_{niche}" / "daily.csv"):
        if r["date"] > since.get("daily", ""):
            by_day[r["date"]].append(r)
    out = {"Ниша по дням": [], "Конкуренты": [], "Выдача": [], "СПП": []}
    for d in sorted(by_day):
        R = by_day[d]
        prices = [num(r["price"]) for r in R if num(r["price"])]
        ads = [r for r in R if r["ads"] not in ("", None)]
        out["Ниша по дням"].append([
            d, len(R), round(sum(num(r["sales"]) or 0 for r in R), 1),
            sum(1 for r in R if r["sales_src"].startswith("факт")),
            int(sum(num(r["rev_new"]) or 0 for r in R)), int(sum(num(r["rev_neg"]) or 0 for r in R)),
            int(sum(num(r["rev_rip"]) or 0 for r in R)),
            round(st.median(prices)) if prices else None,
            round(sum(1 for r in ads if r["ads"] in ("1", "True", "true")) / len(ads), 3) if ads else None,
            '=IF(INDIRECT("E"&ROW())=0;0;INDIRECT("F"&ROW())/INDIRECT("E"&ROW()))'])   # % негатива; «;» — русская локаль таблицы
        top = sorted(R, key=lambda r: -(num(r["sales"]) or 0))[:TOP]
        keep = {r["sku"] for r in top} | {r["sku"] for r in R if int(r["sku"]) in watch}
        for r in sorted((r for r in R if r["sku"] in keep), key=lambda r: -(num(r["sales"]) or 0)):
            out["Конкуренты"].append([
                d, "'" + r["sku"], r["name"][:50], num(r["sales"]), r["sales_src"], num(r["price"]),
                {"1": "да", "True": "да", "0": "нет", "False": "нет"}.get(r["ads"], ""), int(num(r["rev_new"]) or 0),
                int(num(r["rev_neg"]) or 0), int(num(r["rev_rip"]) or 0), num(r["rating"]), num(r["balance"]),
                num(r["search_pos"]), "да" if int(r["sku"]) in watch else ""])
    for r in rows_csv(base / f"pulse_{niche}" / "history.csv"):
        if r["ts"] > since.get("pulse", "") and int(r["pos"]) <= 30:
            out["Выдача"].append([r["ts"].replace("T", " "), "'" + r["sku"], int(r["pos"]), num(r["price"]),
                                  "да" if r["ads"] == "1" else "нет", num(r["balance"]), "FBS" if r["fbs"] == "1" else "FBO"])
    for r in rows_csv(base / f"monitor_{niche}" / "spp.csv"):
        if r["date"] > since.get("spp", "") and r["subject"] == str(niche):
            out["СПП"].append([r["date"], num(r["fbo_spp"]), r["fbs_bands"]])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, default=249)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    d = ROOT / "data" / "processed" / f"monitor_{a.niche}"
    state_p, rows_p = d / "sheets_state.json", d / "sheets_rows.json"
    state = json.load(open(state_p, encoding="utf-8")) if state_p.exists() and not a.all else {}
    if a.commit:
        rows = json.load(open(rows_p, encoding="utf-8"))
        for key, tab in (("daily", "Ниша по дням"), ("pulse", "Выдача"), ("spp", "СПП")):
            if rows[tab]:
                state[key] = max(str(r[0]).replace(" ", "T") for r in rows[tab])
        json.dump(state, open(state_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("отмечено:", state); return
    rows = build(a.niche, state)
    json.dump(rows, open(rows_p, "w", encoding="utf-8"), ensure_ascii=False)
    print({k: len(v) for k, v in rows.items()}, "→", rows_p.relative_to(ROOT))


if __name__ == "__main__":
    main()
