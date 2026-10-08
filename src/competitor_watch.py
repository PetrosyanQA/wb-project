"""Еженедельная слежка за 5 главными конкурентами 777: цена, реклама, акции, позиция, отзывы, (продажи/остаток — если данные целые).

    python -m src.fresh_collect --watch     # 5 запросов Saleflow: by_period за 21 день
    python -m src.competitor_watch          # 0 запросов → reports/weekly/competitors_<дата>.md

Сравнивает последние 7 дней с предыдущими 14. Сигналы:
  цена покупателя −/+ ≥ 7% · реклама выключена (≥ 4 дней из 7 без рекламы) · вошёл/вышел из акции ·
  позиция в поиске хуже/лучше на 25% · дефектура (остаток 0 ≥ 3 дней) — ТОЛЬКО если продажи/остатки за период целые.
⚠️ Проверка качества: Saleflow с августа 2026 отдаёт остаток 0 при продажах и нулевые продажи в свежих днях
(проверено 2026-10-08). Если в окне > 30% дней «продажи при остатке 0» или все продажи = 0 — продажи и остатки не используем.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
OUT_DIR = "reports/weekly"
NAMES = {487711855: "вакуум+магнит (ИП Хива Ш)", 485786521: "MagSafe-премиум (ИП Андреев)", 494403950: "вакуум (ИП Бракар)",
         566117039: "зажим+вакуум, демпинг (ИП Мусаев)", 148983914: "HYRO (№1 по выручке)"}


def med(xs):
    xs = [x for x in xs if x]
    return st.median(xs) if xs else None


def analyse(rows: list[dict]) -> dict:
    R = sorted([r for r in rows if isinstance(r, dict) and r.get("data")], key=lambda r: r["data"])
    last, prev = R[-7:], R[-21:-7]
    window = R[-21:]                                     # качество проверяем ТОЛЬКО в окне анализа, не по всей истории
    sale_days = [r for r in window if (r.get("sales") or 0) > 0]
    broken = (not sale_days) or sum(1 for r in sale_days if not r.get("balance")) / len(sale_days) > 0.3
    out = {"period": f"{window[0]['data']} … {window[-1]['data']}" if window else "—", "data_ok": not broken, "signals": []}
    p1, p0 = med([r.get("final_price") for r in last]), med([r.get("final_price") for r in prev])
    out["price"] = p1
    if p1 and p0 and abs(p1 / p0 - 1) >= 0.07:
        out["signals"].append(f"цена покупателя {p0:.0f} → {p1:.0f} ₽ ({(p1 / p0 - 1) * 100:+.0f}%)")
    ads1 = sum(1 for r in last if r.get("in_ads"))
    ads0 = sum(1 for r in prev if r.get("in_ads")) / max(len(prev), 1) * 7
    out["ads_days"] = ads1
    if ads1 <= 3 and ads0 >= 5:
        out["signals"].append(f"🎯 реклама почти выключена ({ads1}/7 дней) — окно, чтобы поднять ставки")
    pr1, pr0 = sum(1 for r in last if r.get("in_action")), sum(1 for r in prev if r.get("in_action")) / max(len(prev), 1) * 7
    if pr1 >= 4 and pr0 < 2:
        out["signals"].append("вошёл в акцию")
    if pr1 < 2 and pr0 >= 4:
        out["signals"].append("вышел из акции")
    q1, q0 = med([r.get("search_position_avg") for r in last]), med([r.get("search_position_avg") for r in prev])
    out["pos"] = q1
    if q1 and q0:
        if q1 >= 1.25 * q0:
            out["signals"].append(f"позиция хуже: {q0:.0f} → {q1:.0f}")
        elif q1 <= 0.8 * q0:
            out["signals"].append(f"позиция лучше: {q0:.0f} → {q1:.0f}")
    out["reviews"] = R[-1].get("comments") if R else None
    if not broken:
        oos = sum(1 for r in last if not r.get("balance"))
        if oos >= 3:
            out["signals"].append(f"🎯 дефектура {oos}/7 дней — забирать его трафик (реклама на его запросы)")
        out["sales_7d"] = round(st.mean([r.get("sales") or 0 for r in last]), 1)
    return out


def main() -> None:
    files = sorted(glob.glob("data/raw/saleflow/*/fresh777/watch/*_by_period.json"))
    today = dt.date.today()
    if files:
        latest_dir = os.path.dirname(files[-1])
        series = {int(os.path.basename(f).split("_")[0]): json.load(open(f, encoding="utf-8"))
                  for f in sorted(glob.glob(f"{latest_dir}/*_by_period.json"))}
        src = f"Saleflow by_period, `{latest_dir}`"
    else:                                                    # запасной путь: самые длинные уже сохранённые ряды
        from src.datastore import daily
        series = {sku: daily(sku) for sku in NAMES}
        series = {k: v for k, v in series.items() if v}
        if not series:
            raise SystemExit("нет данных — сначала: python -m src.fresh_collect --watch (5 запросов Saleflow)")
        src = "сохранённые ряды из каталога (fresh_collect --watch не сработал)"
    L = [f"# Конкуренты 777 — {today}", "", f"Источник: {src}.", "",
         "| Артикул | Кто | Период | Цена покупателя | Реклама, дней из 7 | Позиция | Отзывы | Продажи/день | Сигналы |",
         "|---|---|---|---:|---:|---:|---:|---:|---|"]
    broken_any = False
    for sku, rows in series.items():
        a = analyse(rows)
        broken_any |= not a["data_ok"]
        L.append(f"| {sku} | {NAMES.get(sku, '')} | {a['period']} | {a['price'] or '—'} | {a['ads_days']} | {a['pos'] or '—'} | {a['reviews'] or '—'} | "
                 f"{a.get('sales_7d', '— (данные неполные)')} | {'; '.join(a['signals']) or '—'} |")
    if broken_any:
        L += ["", "⚠️ Продажи и остатки Saleflow за этот период неполные (остаток 0 при продажах) — сигналы по дефектуре отключены."]
    os.makedirs(OUT_DIR, exist_ok=True)
    out = f"{OUT_DIR}/competitors_{today}.md"
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("→", out)


if __name__ == "__main__":
    main()
