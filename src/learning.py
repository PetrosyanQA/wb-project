"""Самообучение проекта (2026-11-02): уроки, прогнозы против факта, ежедневный бесплатный сбор. 0 платных запросов.

    python -m src.learning lesson "текст урока" --where "/analiz 1.2"     # записать урок → learning/LESSONS.md
    python -m src.learning predict --key spp_437 --value 18 --unit % --product "кисти 437" --source evirma --check 2026-12-15
    python -m src.learning fact --key spp_437 --value 12 --source "живая карточка"   # факт → ошибка прогноза
    python -m src.learning review            # открытые прогнозы, просроченные проверки, средняя ошибка по видам
    python -m src.learning daily [--tg]      # СПП Evirma по нишам наблюдения + архив дневных продаж конкурентов
                                             # + когорта новичков против прогноза → «что узнали сегодня»

Зачем: анализ становится умнее только если (1) каждая ошибка превращается в правило (LESSONS.md),
(2) каждое решение записывает проверяемый прогноз, а потом сверяется с фактом (predictions.csv → поправочные коэффициенты),
(3) каждый день копится история без затрат лимитов (СПП, продажи конкурентов, судьба новичков).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
L = ROOT / "learning"
LESSONS, PRED, SPP_H, COHORT = L / "LESSONS.md", L / "predictions.csv", L / "spp_history.csv", L / "cohort_437.csv"
ARCH = ROOT / "data" / "processed" / "learning" / "bp_archive"
WATCH = {437: "Кисти косметические", 804: "Наборы для поделок", 835: "Корректоры осанки", 9020: "Трикотажные изделия"}
NEWCOMER_FROM = "2026-01-01"
PCOLS = ["id", "date", "product", "key", "value", "unit", "source", "check_after", "fact", "fact_date", "fact_source", "error_pct"]
TODAY = dt.date.today()


def _rows(p: Path) -> list[dict]:
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def _write(p: Path, rows: list[dict], cols: list[str]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)


def lesson(text: str, where: str) -> None:
    with open(LESSONS, "a", encoding="utf-8") as f:
        f.write(f"| {TODAY} | {text} | {where} |\n")
    print(f"урок записан → {LESSONS.relative_to(ROOT)}")


def predict(a) -> None:
    rows = _rows(PRED)
    rows.append({"id": len(rows) + 1, "date": TODAY, "product": a.product, "key": a.key, "value": a.value, "unit": a.unit,
                 "source": a.source, "check_after": a.check or "", "fact": "", "fact_date": "", "fact_source": "", "error_pct": ""})
    _write(PRED, rows, PCOLS)
    print(f"прогноз #{len(rows)}: {a.key} = {a.value} {a.unit} (проверить после {a.check or '—'})")


def fact(key: str, value: float, source: str) -> None:
    rows, hit = _rows(PRED), 0
    for r in rows:
        if r["key"] == key and not r["fact"]:
            v = float(r["value"])
            r.update(fact=value, fact_date=TODAY, fact_source=source,
                     error_pct=round((float(value) - v) / v * 100, 1) if v else "")
            hit += 1
            print(f"#{r['id']} {key}: прогноз {v} → факт {value} ({r['error_pct']:+} %)")
    if not hit:
        print(f"нет открытого прогноза {key} — сначала predict")
    _write(PRED, rows, PCOLS)


def review() -> list[str]:
    rows = _rows(PRED)
    open_, due, done = [r for r in rows if not r["fact"]], [], [r for r in rows if r["fact"] and r["error_pct"] != ""]
    due = [r for r in open_ if r["check_after"] and r["check_after"] <= str(TODAY)]
    out = [f"Прогнозов: {len(rows)}, открыто {len(open_)}, проверено {len(done)}, пора проверить {len(due)}"]
    out += [f"  ⏰ #{r['id']} {r['product']}: {r['key']} = {r['value']} {r['unit']} (с {r['check_after']})" for r in due]
    by = {}
    for r in done:
        by.setdefault(r["key"].split("_")[0], []).append(float(r["error_pct"]))
    for k, v in by.items():                                  # поправочный коэффициент: на сколько мы систематически ошибаемся
        out.append(f"  📏 {k}: средняя ошибка {st.mean(v):+.1f} % по {len(v)} проверкам → множитель для будущих прогнозов ×{1 + st.mean(v) / 100:.2f}")
    return out


HALF_LIFE_DAYS = 180       # старые факты теряют вес: через полгода — вдвое


def calibration_factor(kind: str, min_observations: int = 5) -> dict:
    """Поправка к прогнозам вида kind (spp, buyout, newcomer, cost, drr, margin…) по проверенным фактам.
    < min_observations фактов → множитель 1.0 (мало данных); один выброс не двигает модель (взвешенная медиана
    отношений факт/прогноз); вес факта падает вдвое каждые HALF_LIFE_DAYS дней."""
    pts = []
    for r in _rows(PRED):
        if r["fact"] and r["key"].split("_")[0] == kind and float(r["value"] or 0):
            age = (TODAY - dt.date.fromisoformat(str(r["fact_date"])[:10])).days
            pts.append((float(r["fact"]) / float(r["value"]), 0.5 ** (age / HALF_LIFE_DAYS)))
    n = len(pts)
    if n < min_observations:
        return {"kind": kind, "factor": 1.0, "n": n, "confidence": "LOW", "note": f"мало фактов ({n} < {min_observations}) — без поправки"}
    pts.sort()
    half, acc, med = sum(w for _, w in pts) / 2, 0.0, pts[-1][0]
    for ratio, w in pts:                                     # взвешенная медиана — устойчива к одному выбросу
        acc += w
        if acc >= half:
            med = ratio
            break
    return {"kind": kind, "factor": round(med, 3), "n": n, "confidence": "HIGH" if n >= 15 else "MEDIUM", "note": "взвешенная медиана факт/прогноз"}


def adjust(kind: str, raw: float) -> str:
    """Готовая строка для отчёта: сырой прогноз → поправка learning → скорректированный."""
    c = calibration_factor(kind)
    return (f"Сырой прогноз: {raw:g} | поправка learning: ×{c['factor']} | скорректированный: {raw * c['factor']:.4g} | "
            f"наблюдений: {c['n']} | уверенность: {c['confidence']} ({c['note']})")


def spp_daily() -> list[str]:
    from src.evirma import ranges, spp_at
    hist, out = _rows(SPP_H), []
    try:
        rg = ranges(list(WATCH))
    except Exception as e:                                    # noqa: BLE001
        return [f"СПП Evirma: нет ответа ({str(e)[:60]})"]
    for sid, r in rg.items():
        for price in (1400, 1700, 2300, 3000):              # фиксированные цены продавца — видно, как гуляет полоса
            s = spp_at(r, price, "fbs")
            prev = next((h["spp"] for h in reversed(hist) if h["subject"] == str(sid) and h["price"] == str(price)), None)
            hist.append({"date": TODAY, "subject": sid, "price": price, "spp": s})
            if prev not in (None, "", str(s)) and s is not None and abs(float(prev) - s) >= 3:
                out.append(f"СПП {WATCH.get(sid, sid)} при {price} ₽: {prev} → {s} %")
    _write(SPP_H, hist, ["date", "subject", "price", "spp"])
    return out or ["СПП по нишам наблюдения без резких изменений"]


def cohort_daily() -> list[str]:
    """Архив дневных продаж 40 конкурентов кистей (их собирает утренний отчёт) + новички против нашего прогноза."""
    bp_f = ROOT / "data" / "processed" / "watch_437" / "report_bp.json"
    if not bp_f.exists():
        return ["когорта 437: нет данных утреннего отчёта"]
    bp = json.load(open(bp_f, encoding="utf-8"))
    last = max((d["data"] for v in bp.values() for d in v), default="")
    ARCH.mkdir(parents=True, exist_ok=True)
    (ARCH / f"437_{last}.json").write_text(json.dumps(bp, ensure_ascii=False), encoding="utf-8")
    from src.datastore import products
    start = {}
    for month in ("2026-07", "2026-10"):                          # дата старта карточки: июль + октябрь (октябрь перекрывает)
        start.update({r["id"]: str(r.get("sku_first_date") or "")[:10] for r in (products(437, month)[0] or []) if r.get("sku_first_date")})
    rows = _rows(COHORT)
    seen = {(r["date"], r["sku"]) for r in rows}
    new_sales = []
    for sku, days in bp.items():
        s0 = start.get(int(sku), "")
        if not s0 or s0 < NEWCOMER_FROM:
            continue                                          # новичок = карточка с начала 2026 года
        week = [d for d in days if d["data"] > str(dt.date.fromisoformat(last) - dt.timedelta(days=7))]
        per_day = round(sum(d.get("sales") or 0 for d in week) / max(1, len(week)), 2)
        price = (week[-1].get("final_price") if week else None)
        new_sales.append(per_day)
        if (last, sku) not in seen:
            rows.append({"date": last, "sku": sku, "start": s0, "sales_per_day_7d": per_day, "price": price,
                         "reviews": week[-1].get("comments") if week else "", "in_ads": week[-1].get("in_ads") if week else ""})
    _write(COHORT, rows, ["date", "sku", "start", "sales_per_day_7d", "price", "reviews", "in_ads"])
    if not new_sales:
        return [f"когорта 437 ({last}): новичков (с {NEWCOMER_FROM[:7]}) в наблюдении нет"]
    pred = next((float(r["value"]) for r in _rows(PRED) if r["key"] == "newcomer_p50_437" and not r["fact"]), None)
    med = st.median(new_sales) * 30
    msg = f"когорта 437 ({last}): {len(new_sales)} новичков в наблюдении (выжившие из топа — оценка сверху), медиана {med:.0f} шт/мес"
    if pred:
        msg += f" против прогноза {pred:.0f} ({(med - pred) / pred * 100:+.0f} %)"
    return [msg]


def daily(tg: bool) -> None:
    out = [f"🧠 ЧТО УЗНАЛИ СЕГОДНЯ ({TODAY})"] + spp_daily() + cohort_daily() + review()
    print("\n".join(out))
    if tg:
        from src.tg import send
        send("\n".join(out), html_mode=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("lesson"); p.add_argument("text"); p.add_argument("--where", default="—")
    p = sp.add_parser("predict")
    for k in ("key", "value", "product", "source"):
        p.add_argument(f"--{k}", required=True)
    p.add_argument("--unit", default=""); p.add_argument("--check")
    p = sp.add_parser("fact"); p.add_argument("--key", required=True); p.add_argument("--value", type=float, required=True)
    p.add_argument("--source", required=True)
    sp.add_parser("review")
    p = sp.add_parser("adjust"); p.add_argument("kind"); p.add_argument("raw", type=float)
    p = sp.add_parser("daily"); p.add_argument("--tg", action="store_true")
    a = ap.parse_args()
    if a.cmd == "lesson":
        lesson(a.text, a.where)
    elif a.cmd == "predict":
        predict(a)
    elif a.cmd == "fact":
        fact(a.key, a.value, a.source)
    elif a.cmd == "review":
        print("\n".join(review()))
    elif a.cmd == "adjust":
        print(adjust(a.kind, a.raw))
    else:
        daily(a.tg)


if __name__ == "__main__":
    main()
