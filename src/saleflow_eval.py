"""Офлайн-оценка ниши по сохранённым JSON-ответам Saleflow (воронка из CLAUDE.md).

Сеть не нужна: скрипт читает файлы, которые Claude сохранил из инструментов Saleflow,
считает метрики шагов воронки и складывает входы + результаты в data/raw/saleflow/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .fields import fnum, median, num, parse_date, pick
from .scoring import load_config as load_scoring_config
from .unit_econ import load_config as load_ue_config, unit_economics

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "saleflow"

DEFAULT_STRATEGY: dict[str, Any] = {
    "subject_revenue_min_rub": 30_000_000,
    "subject_revenue_max_rub": 250_000_000,
    "price_min_rub": 800,
    "price_max_rub": 2500,
    "top1_max_pct": 20,
    "concentration_level_pct": 40,
    "min_sellers_to_level": 5,
    "logistics_share_max_pct": 20,
    "volume_max_l": 2.0,
    "cost_ceiling_min_share": 0.25,
    "default_commission_pct": 22,
    "fresh_days": 365,
    "min_fresh_in_top20": 2,
    "max_median_comments_top20": 1000,
    "outlier_price_mult": 5,
    "min_days_with_sales": 3,
    "min_dominant_subject_pct": 80,
    "yoy_min_pct": -5,
    "rolling12_min_pct": -10,
    "flat_season_amplitude_pct": 15,
    "min_full_peaks": 3,
    "min_points_per_month": 3,
    "forecast_tail_days": 7,
    "complaints_window_days": 365,
    "complaint_min_share_pct": 10,
    "complaint_min_leaders": 2,
    "complaint_min_negatives": 30,
    "regulatory": {"block_keywords": [], "declaration_keywords": [], "declaration_extra_rub": 10_000},
    "complaint_themes": {},
}

PASS, FAIL, THIN, MISSING = "PASS", "FAIL", "THIN", "MISSING"
ICON = {PASS: "🟢", FAIL: "🔴", THIN: "🟡", MISSING: "⚪️"}


# ───────────────────────────────────────────────────────────── config / io
def load_strategy(cfg: dict | None = None) -> dict:
    cfg = cfg if cfg is not None else load_scoring_config()
    strategy = json.loads(json.dumps(DEFAULT_STRATEGY))
    for key, value in (cfg.get("strategy") or {}).items():
        if isinstance(value, dict) and isinstance(strategy.get(key), dict):
            strategy[key].update(value)
        else:
            strategy[key] = value
    return strategy


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows_of(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "comments", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def write_outputs(outdir: Path, name: str, result: dict, md: str,
                  inputs: list[Path | str] = ()) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for src in inputs:
        src = Path(src)
        dst = outdir / src.name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
    (outdir / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    (outdir / f"{name}.md").write_text(md, encoding="utf-8")


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


# ───────────────────────────────────────────────────── step 2: concentration
def seller_key(row: dict, i: int) -> str:
    """Имя продавца; в отчёте sellers оно лежит в `name`. Пустые не сливаем в одного."""
    for value in (pick(row, "seller"), row.get("name"), row.get("supplier_id"),
                  row.get("seller_id"), row.get("inn"), row.get("id")):
        if value not in (None, ""):
            return str(value)
    return f"row{i}"


def concentration(rows: list[dict], total_revenue: float | None, s: dict) -> dict:
    revenue: dict[str, float] = defaultdict(float)
    for i, row in enumerate(rows):
        value = fnum(row, "revenue")
        if value > 0:
            revenue[seller_key(row, i)] += value
    ranked = sorted(revenue.items(), key=lambda kv: kv[1], reverse=True)
    row_total = sum(revenue.values())
    # Строки с нулевой выручкой в выдаче = список продавцов полный; 200 ненулевых = обрезан.
    truncated = len(ranked) >= 200
    if total_revenue and total_revenue >= row_total:
        denom, source = float(total_revenue), "external (--total-revenue)"
    else:
        denom = row_total
        source = f"сумма {len(ranked)} продавцов с выручкой"
        if truncated:
            source += " (выдача обрезана → доли завышены, оценка строгая)"
    if not denom:
        return {"step": 2, "verdict": MISSING, "reason": "нет выручки в строках"}

    level = s["concentration_level_pct"]
    cum, n_to_level, top = 0.0, None, []
    for idx, (name, value) in enumerate(ranked, 1):
        cum += value
        share_cum = cum / denom * 100
        if n_to_level is None and share_cum >= level:
            n_to_level = idx
        if idx <= 10:
            top.append({"rank": idx, "seller": name, "revenue": round(value),
                        "share_pct": round(value / denom * 100, 1), "cum_pct": round(share_cum, 1)})
    top1 = ranked[0][1] / denom * 100
    top3 = sum(v for _, v in ranked[:3]) / denom * 100
    reasons, notes = [], []
    # wb_categories_search иногда подставляет выручку родителя; сумма по продавцам — реальный размер.
    if denom < s["subject_revenue_min_rub"]:
        notes.append(f"выручка пути за период {denom:,.0f} ₽ — это срез одной витрины, а не весь предмет; "
                     "размер ниши проверяется в `trends` (весь предмет, 12 мес)")
    if top1 > s["top1_max_pct"]:
        reasons.append(f"топ-1 = {top1:.1f}% > {s['top1_max_pct']}%")
    if n_to_level is not None and n_to_level < s["min_sellers_to_level"]:
        reasons.append(f"{level}% набирают {n_to_level} продавца(ов) < {s['min_sellers_to_level']}")
    return {
        "step": 2, "verdict": FAIL if reasons else PASS, "reasons": reasons, "notes": notes,
        "top1_pct": round(top1, 1), "top3_pct": round(top3, 1), "n_to_level": n_to_level,
        "level_pct": level, "sellers": len(ranked), "denominator_rub": round(denom),
        "denominator_source": source, "top": top,
    }


def md_concentration(r: dict) -> str:
    if r["verdict"] == MISSING:
        return f"## Шаг 2 — концентрация\n\n{ICON[MISSING]} {r['reason']}\n"
    lines = [f"## Шаг 2 — концентрация продавцов {ICON[r['verdict']]} {r['verdict']}", "",
             f"- топ-1: **{r['top1_pct']}%**, топ-3: {r['top3_pct']}%, "
             f"{r['level_pct']}% набирают: **{r['n_to_level'] or 'не набирают'}** продавцов "
             f"(всего {r['sellers']})",
             f"- знаменатель: {r['denominator_rub']:,} ₽ — {r['denominator_source']}"]
    lines += [f"- ❌ {x}" for x in r["reasons"]] + [f"- ⚠️ {x}" for x in r.get("notes", [])]
    lines += ["", "| # | Продавец | Выручка ₽ | Доля | Накопл. |", "|---|---|---:|---:|---:|"]
    lines += [f"| {t['rank']} | {t['seller']} | {t['revenue']:,} | {t['share_pct']}% | {t['cum_pct']}% |"
              for t in r["top"]]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────── step 3: items + econ
def volume_l(row: dict) -> float | None:
    dims = [num(row.get(k)) for k in ("package_length", "package_width", "package_height")]
    if all(d > 0 for d in dims):
        return dims[0] * dims[1] * dims[2] / 1000.0
    return None


def clean_items(items: list[dict], subject_id: int | None, s: dict) -> tuple[list[dict], list[dict]]:
    if subject_id is None:
        ids = Counter(i.get("subject_id") for i in items if i.get("subject_id") is not None)
        subject_id = ids.most_common(1)[0][0] if ids else None
    prices = [fnum(i, "price") for i in items if fnum(i, "price") > 0]
    med = median(prices)
    kept, dropped = [], []
    for item in items:
        reason = None
        if subject_id is not None and item.get("subject_id") not in (None, subject_id):
            reason = f"чужой subject_id {item.get('subject_id')}"
        elif med and fnum(item, "price") > s["outlier_price_mult"] * med:
            reason = f"цена {fnum(item, 'price'):,.0f} > {s['outlier_price_mult']}× медианы"
        elif "days_with_sales" in item and num(item["days_with_sales"]) < s["min_days_with_sales"]:
            reason = f"продажи только {num(item['days_with_sales']):.0f} дн."
        if reason:
            dropped.append({"id": pick(item, "id"), "name": pick(item, "name"), "reason": reason})
        else:
            kept.append(item)
    return kept, dropped


def items_metrics(items: list[dict], today: date, s: dict) -> dict:
    ranked = sorted(items, key=lambda i: fnum(i, "revenue"), reverse=True)
    top20 = ranked[:20]
    prices = [fnum(i, "price") for i in items if fnum(i, "price") > 0 and fnum(i, "revenue") > 0]
    volumes = [v for v in (volume_l(i) for i in items) if v]
    fresh = [i for i in top20
             if (d := parse_date(pick(i, "start_date"))) and (today - d).days <= s["fresh_days"]]
    leaders = [{"id": pick(i, "id"), "seller": pick(i, "seller"), "brand": pick(i, "brand"),
                "price": round(fnum(i, "price")), "revenue": round(fnum(i, "revenue")),
                "comments": round(fnum(i, "comments")), "volume_l": volume_l(i)} for i in ranked[:5]]
    return {
        "median_price": round(median(prices)) if prices else None,
        "median_volume_l": round(median(volumes), 2) if volumes else None,
        "volume_known": len(volumes),
        "fresh_in_top20": len(fresh),
        "median_comments_top20": round(median([fnum(i, "comments") for i in top20])) if top20 else None,
        "leaders": leaders,
    }


def max_cost(price: float, vol: float, ue_cfg: dict, commission_pct: float,
             min_margin: float, min_roi: float) -> float:
    """Максимальная себестоимость, при которой маржа и ROI ещё проходят цели."""
    def ok(cost: float) -> bool:
        e = unit_economics(price, cost, vol, ue_cfg, with_breakeven=False, commission_pct=commission_pct)
        return e["net_margin_pct"] >= min_margin and e["roi_on_goods_pct"] >= min_roi
    if not ok(0.0):
        return 0.0
    lo, hi = 0.0, price
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def napkin_econ(price: float, vol: float, commission_pct: float, ue_cfg: dict, s: dict) -> dict:
    e = unit_economics(price, price * 0.3, vol, ue_cfg, with_breakeven=False,
                       commission_pct=commission_pct)
    logistics = e["logistics_with_returns"] + e["storage"] + e["acceptance"]
    share = logistics / price * 100
    targets = ue_cfg["targets"]
    ceiling = max_cost(price, vol, ue_cfg, commission_pct,
                       targets["min_net_margin_pct"], targets["min_roi_on_cost_pct"])
    reasons = []
    if share > s["logistics_share_max_pct"]:
        reasons.append(f"логистика+возвраты+хранение {share:.1f}% цены > {s['logistics_share_max_pct']}%")
    if vol > s["volume_max_l"]:
        reasons.append(f"объём {vol:.2f} л > {s['volume_max_l']} л")
    if ceiling < s["cost_ceiling_min_share"] * price:
        reasons.append(f"потолок себестоимости {ceiling:,.0f} ₽ < "
                       f"{s['cost_ceiling_min_share'] * 100:.0f}% цены ({s['cost_ceiling_min_share'] * price:,.0f} ₽)")
    return {
        "price": round(price), "volume_l": round(vol, 2), "commission_pct": commission_pct,
        "logistics_rub": round(logistics), "logistics_share_pct": round(share, 1),
        "commission_rub": e["commission"], "ads_rub": e["ads"],
        "max_cost_rub": round(ceiling), "max_cost_share_pct": round(ceiling / price * 100, 1),
        "targets": {"min_net_margin_pct": targets["min_net_margin_pct"],
                    "min_roi_on_cost_pct": targets["min_roi_on_cost_pct"]},
        "tariffs_source": ue_cfg.get("_tariffs_source", "config/unit_economics.yaml (дефолты)"),
        "verdict": FAIL if reasons else PASS, "reasons": reasons,
    }


def items_step(items: list[dict], subject_id: int | None, today: date, s: dict) -> dict:
    kept, dropped = clean_items(items, subject_id, s)
    m = items_metrics(kept, today, s)
    reasons = []
    subjects = Counter(i.get("subject") or i.get("subject_id") for i in items)
    if subjects and subject_id is None:
        name, count = subjects.most_common(1)[0]
        share = count / len(items) * 100
        if share < s["min_dominant_subject_pct"]:
            reasons.append(f"смешанная витрина: «{name}» только {share:.0f}% выдачи — это не одна ниша")
    if m["median_price"] is None:
        reasons.append("нет цен")
    elif not (s["price_min_rub"] <= m["median_price"] <= s["price_max_rub"]):
        reasons.append(f"медианная цена {m['median_price']:,} ₽ вне {s['price_min_rub']}–{s['price_max_rub']} ₽")
    if m["fresh_in_top20"] < s["min_fresh_in_top20"]:
        reasons.append(f"в топ-20 только {m['fresh_in_top20']} карточек моложе {s['fresh_days']} дн.")
    notes = []
    if (m["median_comments_top20"] or 0) > s["max_median_comments_top20"]:
        text = f"медиана отзывов топ-20 {m['median_comments_top20']:,} > {s['max_median_comments_top20']}"
        # Склейка карточек: новые карточки наследуют отзывы, так что много свежих в топе = вход возможен.
        if m["fresh_in_top20"] >= 2 * s["min_fresh_in_top20"]:
            notes.append(text + f" — но {m['fresh_in_top20']} свежих карточек в топ-20, отзывы, вероятно, "
                                "унаследованы склейкой")
        else:
            reasons.append(text)
    return {"step": 3, "kept": len(kept), "dropped": dropped, **m,
            "verdict": FAIL if reasons else PASS, "reasons": reasons, "notes": notes}


def md_items(r: dict, econ: dict | None) -> str:
    verdicts = [r["verdict"]] + ([econ["verdict"]] if econ else [])
    total = FAIL if FAIL in verdicts else PASS
    lines = [f"## Шаг 3 — экономика и вход новичка {ICON[total]} {total}", "",
             f"- после чистки: {r['kept']} строк, отброшено {len(r['dropped'])}",
             f"- медианная цена: **{r['median_price'] or '—'} ₽**, медианный объём упаковки: "
             f"{r['median_volume_l'] or '—'} л (известен у {r['volume_known']})",
             f"- карточек моложе 365 дн. в топ-20: {r['fresh_in_top20']}, "
             f"медиана отзывов топ-20: {r['median_comments_top20']}"]
    lines += [f"- ❌ {x}" for x in r["reasons"]] + [f"- ⚠️ {x}" for x in r.get("notes", [])]
    if econ:
        lines += ["", md_econ(econ, header=False)]
    if r["dropped"]:
        lines += ["", "Отброшено:"] + [f"- {d['id']} {str(d['name'])[:40]} — {d['reason']}"
                                       for d in r["dropped"][:15]]
    return "\n".join(lines) + "\n"


def md_econ(e: dict, header: bool = True) -> str:
    lines = [f"## Экономика на салфетке {ICON[e['verdict']]} {e['verdict']}", ""] if header else []
    lines += [f"- цена {e['price']:,} ₽, объём {e['volume_l']} л, комиссия {e['commission_pct']}%",
              f"- логистика+возвраты+хранение: {e['logistics_rub']:,} ₽ = **{e['logistics_share_pct']}%** цены",
              f"- потолок себестоимости (маржа ≥ {e['targets']['min_net_margin_pct']}%, "
              f"ROI ≥ {e['targets']['min_roi_on_cost_pct']}%): **{e['max_cost_rub']:,} ₽** "
              f"({e['max_cost_share_pct']}% цены)",
              f"- тарифы: {e['tariffs_source']}"]
    lines += [f"- ❌ {x}" for x in e["reasons"]]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────── step 4: YoY
def peak_month(season_rows: list[dict]) -> tuple[int | None, float]:
    best_month, best = None, float("-inf")
    for row in season_rows:
        month = int(str(row.get("date", "00"))[:2] or 0)
        value = num(row.get("season_revenue"))
        if 1 <= month <= 12 and value > best:
            best_month, best = month, value
    return best_month, (best if best != float("-inf") else 0.0)


def _clean_trend(trend_rows: list[dict], today: date, s: dict) -> tuple[list[tuple[date, float]], int]:
    cutoff = today - timedelta(days=s["forecast_tail_days"])
    series = sorted((d, num(r.get("trend_revenue"))) for r in trend_rows
                    if (d := parse_date(r.get("date"))) and d <= cutoff)
    dropped = 0
    while len(series) >= 2 and series[-1][1] == series[-2][1]:
        series.pop()
        dropped += 1
    return series, dropped


def _month_end(year: int, month: int) -> date:
    return (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))


def yoy_peak(trend_rows: list[dict], month: int | None, today: date, s: dict) -> dict:
    series, ffill = _clean_trend(trend_rows, today, s)
    if len(series) < 60:
        return {"step": 4, "verdict": MISSING, "reason": f"мало точек тренда ({len(series)})"}
    last = series[-1][0]

    def avg(a: date, b: date) -> float | None:
        vals = [v for d, v in series if a < d <= b]
        return sum(vals) / len(vals) if len(vals) >= 40 else None

    cur12, prev12 = avg(last - timedelta(days=365), last), avg(last - timedelta(days=730), last - timedelta(days=365))
    rolling = (cur12 - prev12) / prev12 * 100 if cur12 and prev12 else None

    peaks: list[dict] = []
    if month:
        by_year: dict[int, list[float]] = defaultdict(list)
        for d, v in series:
            if d.month == month:
                by_year[d.year].append(v)
        for year in sorted(by_year):
            if len(by_year[year]) >= s["min_points_per_month"] and _month_end(year, month) <= last:
                peaks.append({"year": year, "avg": round(sum(by_year[year]) / len(by_year[year])),
                              "points": len(by_year[year])})
    for prev, cur in zip(peaks, peaks[1:]):
        cur["yoy_pct"] = round((cur["avg"] - prev["avg"]) / prev["avg"] * 100, 1) if prev["avg"] else None

    yoy_last = peaks[-1].get("yoy_pct") if len(peaks) >= 2 else None
    yoy_prev = peaks[-2].get("yoy_pct") if len(peaks) >= 3 else None
    reasons, notes = [], []
    if month and yoy_last is not None and yoy_last < s["yoy_min_pct"]:
        reasons.append(f"пиковый месяц год к году {yoy_last}% < {s['yoy_min_pct']}%")
    if rolling is not None and rolling < s["rolling12_min_pct"]:
        reasons.append(f"последние 12 мес {rolling:.1f}% к предыдущим < {s['rolling12_min_pct']}%")
    if yoy_last is not None and yoy_prev is not None and yoy_last < 0 and yoy_prev < 0:
        notes.append("два года падения на пике подряд")
    if month and len(peaks) < s["min_full_peaks"]:
        notes.append(f"полных пиков только {len(peaks)} — мало истории")
    if month is None:
        notes.append("сезонность плоская — судим по 12 мес")
    if rolling is None and (not month or yoy_last is None):
        return {"step": 4, "verdict": MISSING, "reason": "не хватает истории для сравнения",
                "peaks": peaks, "notes": notes}
    verdict = FAIL if reasons else (THIN if month and len(peaks) < s["min_full_peaks"] else PASS)
    return {"step": 4, "verdict": verdict, "reasons": reasons, "notes": notes,
            "peak_month": month, "peaks": peaks, "yoy_last_pct": yoy_last, "yoy_prev_pct": yoy_prev,
            "rolling12_pct": round(rolling, 1) if rolling is not None else None,
            "series_from": str(series[0][0]), "series_to": str(last), "forward_filled_dropped": ffill}


def load_monthly(path: Path | str) -> list[dict]:
    """Ряд wb_subject/wb_category_stats report=trends: JSON (label_date/date) или CSV (month)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        import csv
        raw = list(csv.DictReader(path.open(encoding="utf-8")))
    else:
        raw = rows_of(load_json(path))
    out = []
    for r in raw:
        month = str(r.get("month") or r.get("label_date") or r.get("date") or "")[:7]
        if len(month) != 7:
            continue
        est = r.get("revenue_est", r.get("revenue_estimated"))
        out.append({"month": month, "revenue": num(r.get("revenue")),
                    "revenue_est": num(est) if est not in (None, "", 0, "0") else None,
                    "sales": num(r.get("sales")),
                    "sales_est": num(r.get("sales_est", r.get("sales_estimated"))) or None})
    return sorted(out, key=lambda x: x["month"])


def trends_yoy(monthly: list[dict], peak: int | None, s: dict) -> dict:
    """Год к году по ФАКТИЧЕСКОМУ помесячному ряду. С сент. 2025 у выручки два режима:
    raw (как раньше) и est (скорректированная, ниже). Верхняя граница = raw/raw, нижняя = est/raw."""
    notes: list[str] = []
    m = {r["month"]: dict(r) for r in monthly}
    months = sorted(m)
    if len(months) >= 2 and m[months[-1]]["sales"] < 0.35 * m[months[-2]]["sales"] \
            and not m[months[-1]]["sales_est"]:
        notes.append(f"{months[-1]} выглядит неполным — исключён")
        del m[months[-1]]
        months = months[:-1]
    if len(months) < 24:
        return {"step": 4, "verdict": MISSING, "reason": f"мало месяцев ({len(months)})", "notes": notes}

    def prev(ym: str) -> str:
        return f"{int(ym[:4]) - 1}-{ym[5:]}"

    def yoy(ym: str) -> dict | None:
        p = prev(ym)
        if p not in m or ym not in m or not m[p]["revenue"]:
            return None
        cur = m[ym]
        hi = (cur["revenue"] / m[p]["revenue"] - 1) * 100
        lo = ((cur["revenue_est"] or cur["revenue"]) / m[p]["revenue"] - 1) * 100
        return {"month": ym, "hi_pct": round(hi, 1), "lo_pct": round(min(lo, hi), 1)}

    # сезонность по полным календарным годам
    shares: dict[int, list[float]] = defaultdict(list)
    for year in sorted({int(x[:4]) for x in months}):
        keys = [f"{year}-{mm:02d}" for mm in range(1, 13)]
        if all(k in m for k in keys):
            total = sum(m[k]["revenue"] for k in keys)
            for k in keys:
                shares[int(k[5:])].append(m[k]["revenue"] / total)
    seasonal = {}
    if shares:
        avg_share = {mm: sum(v) / len(v) for mm, v in shares.items()}
        pk = max(avg_share, key=avg_share.get)
        tr = min(avg_share, key=avg_share.get)
        top3 = sorted(avg_share.values(), reverse=True)[:3]
        seasonal = {"peak_month_auto": pk, "peak_share_pct": round(avg_share[pk] * 100, 1),
                    "trough_month": tr, "peak_to_trough": round(avg_share[pk] / avg_share[tr], 1),
                    "top3_months_share_pct": round(sum(top3) * 100, 1),
                    "amplitude_pct": round((avg_share[pk] * 12 - 1) * 100)}
        if peak is None and seasonal["amplitude_pct"] >= s["flat_season_amplitude_pct"]:
            peak = pk
    elif peak is None:
        notes.append("нет полного календарного года — пик не определён")

    peak_rows = []
    if peak:
        for ym in months:
            if int(ym[5:]) == peak and (y := yoy(ym)):
                peak_rows.append(y)
    last12 = months[-12:]
    prev12 = months[-24:-12]
    roll = None
    if len(last12) == 12 and all(prev(k) in m for k in last12):
        base = sum(m[prev(k)]["revenue"] for k in last12)
        hi = (sum(m[k]["revenue"] for k in last12) / base - 1) * 100
        lo = (sum((m[k]["revenue_est"] or m[k]["revenue"]) for k in last12) / base - 1) * 100
        roll = {"from": last12[0], "to": last12[-1], "hi_pct": round(hi, 1), "lo_pct": round(min(lo, hi), 1)}
    recent = [y for y in (yoy(k) for k in months[-6:]) if y]

    def judge(hi: float | None, lo: float | None, floor: float) -> str:
        if hi is None:
            return MISSING
        if lo >= floor:
            return PASS
        return FAIL if hi < floor else THIN

    peak_v = judge(peak_rows[-1]["hi_pct"], peak_rows[-1]["lo_pct"], s["yoy_min_pct"]) if peak_rows else MISSING
    roll_v = judge(roll["hi_pct"], roll["lo_pct"], s["rolling12_min_pct"]) if roll else MISSING
    verdicts = [v for v in (peak_v, roll_v) if v != MISSING]
    verdict = (FAIL if FAIL in verdicts else THIN if THIN in verdicts else PASS) if verdicts else MISSING
    reasons = []
    avg12 = sum((m[k]["revenue_est"] or m[k]["revenue"]) for k in last12) / max(len(last12), 1)
    size = {"avg_monthly_revenue_12m": round(avg12), "min": s["subject_revenue_min_rub"]}
    if avg12 < s["subject_revenue_min_rub"]:
        reasons.append(f"предмет слишком мал: в среднем {avg12:,.0f} ₽/мес за 12 мес < {s['subject_revenue_min_rub']:,} ₽")
        verdicts.append(FAIL)
        verdict = FAIL
    if peak_v == FAIL:
        reasons.append(f"пиковый месяц {peak_rows[-1]['month']}: {peak_rows[-1]['hi_pct']:+.0f}% даже по верхней оценке < {s['yoy_min_pct']}%")
    if roll_v == FAIL:
        reasons.append(f"12 мес к 12 мес: {roll['hi_pct']:+.0f}% даже по верхней оценке < {s['rolling12_min_pct']}%")
    if peak_v == THIN or roll_v == THIN:
        notes.append("результат зависит от режима данных (raw/est с сент. 2025) — вердикт «неоднозначно»")
    if recent and all(y["lo_pct"] < 0 for y in recent[-4:]):
        notes.append("последние 4 месяца по нижней оценке в минусе — рост вне сезона остановился")
    if any(m[k]["revenue_est"] for k in months):
        notes.append("с сент. 2025 два режима выручки: верхняя оценка raw/raw, нижняя est/raw")
    return {"step": 4, "verdict": verdict, "reasons": reasons, "notes": notes, "peak_month": peak,
            "peak_verdict": peak_v, "rolling_verdict": roll_v, "peak_yoy": peak_rows, "rolling12": roll,
            "recent_yoy": recent, "seasonal": seasonal, "months": f"{months[0]}…{months[-1]}", "size": size}


def md_trends(r: dict) -> str:
    if r["verdict"] == MISSING:
        return f"## Шаг 4 — спрос год к году (факт) {ICON[MISSING]}\n\n{r.get('reason', 'нет данных')}\n"
    sea = r.get("seasonal") or {}
    lines = [f"## Шаг 4 — спрос год к году (фактический ряд) {ICON[r['verdict']]} {r['verdict']}", "",
             f"- ряд: {r['months']}; пиковый месяц: **{r['peak_month'] or 'нет'}**; "
             f"размер предмета: {r['size']['avg_monthly_revenue_12m']:,} ₽/мес в среднем за 12 мес"]
    if sea:
        lines.append(f"- сезонность: пик {sea['peak_month_auto']} мес = {sea['peak_share_pct']}% года, "
                     f"пик/дно ×{sea['peak_to_trough']}, 3 лучших месяца = {sea['top3_months_share_pct']}%")
    if r["peak_yoy"]:
        lines += ["", "| Пиковый месяц | год к году, верх (raw) | год к году, низ (est) |", "|---|---:|---:|"]
        lines += [f"| {y['month']} | {y['hi_pct']:+.0f}% | {y['lo_pct']:+.0f}% |" for y in r["peak_yoy"]]
    if r["rolling12"]:
        ro = r["rolling12"]
        lines += ["", f"- 12 мес ({ro['from']}…{ro['to']}) к предыдущим 12: **{ro['hi_pct']:+.0f}%** (верх) / "
                      f"**{ro['lo_pct']:+.0f}%** (низ)"]
    if r["recent_yoy"]:
        lines.append("- последние месяцы (низ/верх): " +
                     ", ".join(f"{y['month'][2:]} {y['lo_pct']:+.0f}/{y['hi_pct']:+.0f}%" for y in r["recent_yoy"]))
    lines += [f"- ❌ {x}" for x in r["reasons"]] + [f"- ⚠️ {x}" for x in r["notes"]]
    return "\n".join(lines) + "\n"


def md_yoy(r: dict) -> str:
    if r["verdict"] == MISSING:
        return f"## Шаг 4 — спрос год к году {ICON[MISSING]}\n\n{r['reason']}\n"
    lines = [f"## Шаг 4 — спрос год к году {ICON[r['verdict']]} {r['verdict']}", "",
             f"- пиковый месяц: **{r['peak_month'] or 'нет (плоская сезонность)'}**; "
             f"ряд {r['series_from']} … {r['series_to']} (отброшено хвоста прогноза: {r['forward_filled_dropped']})",
             f"- год к году на пике: **{_pct(r['yoy_last_pct'])}** (годом ранее: {_pct(r['yoy_prev_pct'])})",
             f"- последние 12 мес к предыдущим 12: **{_pct(r['rolling12_pct'])}**"]
    lines += [f"- ❌ {x}" for x in r["reasons"]] + [f"- ⚠️ {x}" for x in r["notes"]]
    if r["peaks"]:
        lines += ["", "| Год | Ср. trend_revenue в пик. месяце | Точек | Год к году |", "|---|---:|---:|---:|"]
        lines += [f"| {p['year']} | {p['avg']:,} | {p['points']} | {_pct(p.get('yoy_pct'))} |" for p in r["peaks"]]
    return "\n".join(lines) + "\n"


# ────────────────────────────────────────────────────────── step 5: complaints
def complaints(files: list[Path], s: dict, today: date) -> dict:
    themes: dict[str, list[str]] = s["complaint_themes"]
    since = today - timedelta(days=s["complaints_window_days"])
    per_sku = []
    for path in files:
        rows = rows_of(load_json(path))
        negatives = [r for r in rows
                     if num(r.get("valuation"), 5) <= 3 and str(r.get("text") or "").strip()
                     and (d := parse_date(r.get("date"))) and d >= since]
        found = {}
        for theme, stems in themes.items():
            hits = [r for r in negatives if any(st in str(r["text"]).lower() for st in stems)]
            if hits:
                found[theme] = {"count": len(hits),
                                "share_pct": round(len(hits) / len(negatives) * 100, 1),
                                "quotes": [str(h["text"]).replace("\n", " ")[:200] for h in hits[:5]]}
        per_sku.append({"file": Path(path).name, "comments": len(rows), "negatives": len(negatives),
                        "enough": len(negatives) >= s["complaint_min_negatives"], "themes": found})

    enough = [p for p in per_sku if p["enough"]]
    common = {}
    for theme in themes:
        leaders = [p["file"] for p in enough
                   if p["themes"].get(theme, {}).get("share_pct", 0) >= s["complaint_min_share_pct"]]
        if len(leaders) >= s["complaint_min_leaders"]:
            common[theme] = leaders
    if len(enough) < s["complaint_min_leaders"]:
        verdict = THIN
    else:
        verdict = PASS if common else FAIL
    return {"step": 5, "verdict": verdict, "common_themes": common, "per_sku": per_sku,
            "window_from": str(since)}


def md_complaints(r: dict) -> str:
    lines = [f"## Шаг 5 — чем отличиться {ICON[r['verdict']]} {r['verdict']}", "",
             f"- окно: отзывы с {r['window_from']}, негатив = оценка ≤ 3 с текстом",
             f"- общие темы у ≥ 2 лидеров: **{', '.join(r['common_themes']) or 'нет'}**"]
    for p in r["per_sku"]:
        flag = "" if p["enough"] else " (мало негатива — не учитывается)"
        lines += ["", f"### {p['file']} — {p['negatives']} негативных из {p['comments']}{flag}"]
        for theme, t in sorted(p["themes"].items(), key=lambda kv: kv[1]["count"], reverse=True):
            lines.append(f"- **{theme}**: {t['count']} ({t['share_pct']}%)")
            lines += [f"  - «{q}»" for q in t["quotes"][:3]]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────── step 0 + summary
def _keyword_hits(leaf: str, keywords: list[str], allow: list[str]) -> list[str]:
    """Однословная основа — по началу слова («носк» не ловит «переноска»), фраза — подстрокой."""
    words = [w for w in "".join(ch if ch.isalnum() or ch == "-" else " " for ch in leaf).split()
             if not any(w.startswith(a) for a in allow)]
    return [k for k in keywords
            if (k in leaf if " " in k else any(w.startswith(k) for w in words))]


def regulatory_check(path: str, s: dict) -> dict:
    low = path.replace("\\", "/").rstrip("/").split("/")[-1].strip().lower()
    reg = s["regulatory"]
    allow = reg.get("allow_keywords", [])
    block = _keyword_hits(low, reg.get("block_keywords", []), allow)
    decl = _keyword_hits(low, reg.get("declaration_keywords", []), allow)
    if block:
        return {"step": 0, "verdict": FAIL, "reasons": [f"«Честный знак»: {', '.join(block)}"], "path": path}
    notes = ([f"нужна декларация соответствия (+{reg.get('declaration_extra_rub', 0):,} ₽): {', '.join(decl)}"]
             if decl else [])
    return {"step": 0, "verdict": PASS, "reasons": [], "notes": notes, "path": path,
            "manual_check": "сверить с честныйзнак.рф — список меняется"}


STEP_FILES = [(0, "reg", "Регуляторика"), (2, "sellers", "Концентрация продавцов"),
              (3, "items", "Экономика и вход"), (3, "econ", "Экономика на салфетке"),
              (4, "yoy", "Спрос год к году"), (5, "comments", "Чем отличиться")]


def summary(outdir: Path, niche: str) -> tuple[dict, str]:
    rows, overall = [], PASS
    for step, name, title in STEP_FILES:
        f = outdir / f"{name}.json"
        if name == "yoy" and (outdir / "trends.json").exists():
            f = outdir / "trends.json"      # фактический ряд важнее модельного forecast/trend
        if not f.exists():
            rows.append((step, title, MISSING, "не запускалось"))
            continue
        r = load_json(f)
        verdict = r.get("verdict", MISSING)
        detail = "; ".join(r.get("reasons") or r.get("notes") or [r.get("reason", "")]) or "ок"
        rows.append((step, title, verdict, detail))
        if verdict == FAIL:
            overall = FAIL
        elif verdict in (THIN, MISSING) and overall == PASS:
            overall = THIN
    if any(v == MISSING for _, _, v, _ in rows) and overall == PASS:
        overall = THIN
    lines = [f"# Воронка: {niche} — {ICON[overall]} {overall}", "",
             "| Шаг | Проверка | Итог | Детали |", "|---|---|---|---|"]
    lines += [f"| {st} | {t} | {ICON[v]} {v} | {d} |" for st, t, v, d in rows]
    lines += ["", "Шаг 6 (полная юнит-экономика) — только с себестоимостью от поставщика: "
                  "`python -m src.unit_econ --price <медиана> --cost <поставщик> --volume <л> --commission <WB>`."]
    return {"niche": niche, "verdict": overall, "steps": rows}, "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────── selftest
def selftest() -> None:
    s = load_strategy({"strategy": {"complaint_themes": {"тепло": ["держит тепл"]}}})
    today = date(2026, 10, 3)

    rows = [{"name": None, "id": i, "revenue": 10} for i in range(10)]
    c = concentration(rows, None, s)
    assert c["sellers"] == 10 and c["top1_pct"] == 10.0, c
    rows = [{"name": "A", "revenue": 50}, {"name": "B", "revenue": 30}] + \
           [{"name": f"x{i}", "revenue": 1} for i in range(20)]
    assert concentration(rows, None, s)["verdict"] == FAIL

    items = [{"id": 1, "subject_id": 5, "final_price": 1000, "revenue": 9, "days_with_sales": 15},
             {"id": 2, "subject_id": 5, "final_price": 50000, "revenue": 99, "days_with_sales": 1},
             {"id": 3, "subject_id": 7, "final_price": 900, "revenue": 5, "days_with_sales": 15},
             {"id": 4, "subject_id": 5, "final_price": 1100, "revenue": 8, "days_with_sales": 15}]
    kept, dropped = clean_items(items, None, s)
    assert [i["id"] for i in kept] == [1, 4] and len(dropped) == 2, (kept, dropped)

    start = date(2022, 1, 3)
    trend = [{"date": str(start + timedelta(weeks=w)), "trend_revenue": 100 + w} for w in range(230)]
    trend += [{"date": str(start + timedelta(weeks=w)), "trend_revenue": 999} for w in range(230, 250)]
    r = yoy_peak(trend, 12, today, s)
    assert r["forward_filled_dropped"] >= 1 and r["verdict"] in (PASS, THIN), r
    assert yoy_peak(trend, None, today, s)["notes"], "flat season note"
    assert yoy_peak(trend[:40], 12, today, s)["verdict"] == MISSING

    synth = []
    for y in range(2022, 2027):
        for mm in range(1, 13):
            if (y, mm) > (2026, 8):
                break
            base = 20e6 * (1.3 ** (y - 2022)) * (2.0 if mm in (12, 2) else 1.0)
            synth.append({"month": f"{y}-{mm:02d}", "revenue": base, "sales": base / 10,
                          "revenue_est": base * 0.8 if (y, mm) >= (2025, 9) else None, "sales_est": None})
    synth.append({"month": "2026-09", "revenue": 5, "sales": 1, "revenue_est": None, "sales_est": None})
    tr = trends_yoy(synth, None, s)
    assert tr["peak_month"] in (2, 12) and tr["verdict"] == PASS, tr
    assert any("неполным" in n for n in tr["notes"]), tr["notes"]
    falling = [dict(r, revenue=r["revenue"] * (0.5 if r["month"] >= "2025-09" else 1), revenue_est=None) for r in synth[:-1]]
    assert trends_yoy(falling, None, s)["verdict"] == FAIL

    reg = load_strategy({"strategy": {"regulatory": {"block_keywords": ["носк", "корм", "туалетная вода"],
                                                      "allow_keywords": ["кормушк"]}}})
    assert regulatory_check("Зоотовары/Транспортировка/Переноска для животных", reg)["verdict"] == PASS
    assert regulatory_check("Одежда/Носки", reg)["verdict"] == FAIL
    assert regulatory_check("Сад/Кормушка для птиц", reg)["verdict"] == PASS
    assert regulatory_check("Зоотовары/Корм сухой", reg)["verdict"] == FAIL
    assert regulatory_check("Красота/Туалетная вода", reg)["verdict"] == FAIL

    ue = load_ue_config()
    assert max_cost(1500, 0.5, ue, 20, 18, 60) > max_cost(1500, 3.0, ue, 20, 18, 60) >= 0
    print("selftest OK")


# ──────────────────────────────────────────────────────────────────────── CLI
def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Оценка ниши по сохранённым ответам Saleflow")
    p.add_argument("--niche", help="короткое имя ниши (папка результатов)")
    p.add_argument("--today", help="YYYY-MM-DD (по умолчанию сегодня)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sellers"); sp.add_argument("file")
    sp.add_argument("--total-revenue", type=float, help="полная выручка категории за тот же период")
    sp = sub.add_parser("items"); sp.add_argument("file"); sp.add_argument("--subject-id", type=int)
    sp.add_argument("--commission", type=float, help="комиссия WB %% из wb_seller commission")
    sp = sub.add_parser("econ"); sp.add_argument("--price", type=float, required=True)
    sp.add_argument("--volume", type=float, required=True)
    sp.add_argument("--commission", type=float, help="комиссия WB %% из wb_seller commission")
    sp = sub.add_parser("yoy"); sp.add_argument("trend_file")
    sp.add_argument("--season-file"); sp.add_argument("--peak-month", type=int)
    sp = sub.add_parser("trends"); sp.add_argument("file", help="wb_subject report=trends (JSON или CSV month,revenue,...)")
    sp.add_argument("--peak-month", type=int)
    sp = sub.add_parser("comments"); sp.add_argument("files", nargs="+")
    sp = sub.add_parser("reg"); sp.add_argument("path", help="путь категории WB")
    sub.add_parser("summary")
    sub.add_parser("selftest")
    args = p.parse_args()

    if args.cmd == "selftest":
        selftest()
        return
    if not args.niche:
        p.error("--niche обязателен")
    today = parse_date(args.today) if args.today else date.today()
    s = load_strategy()
    outdir = RAW_DIR / str(today) / args.niche

    def commission_or_default(value: float | None) -> float:
        if value is None:
            print(f"⚠️ комиссия не передана — беру {s['default_commission_pct']}% (возьми реальную: "
                  f"python -m src.wb_seller commission --subject ...)")
            return float(s["default_commission_pct"])
        return value

    if args.cmd == "sellers":
        r = concentration(rows_of(load_json(args.file)), args.total_revenue, s)
        md, inputs = md_concentration(r), [args.file]
    elif args.cmd == "items":
        r = items_step(rows_of(load_json(args.file)), args.subject_id, today, s)
        econ = None
        if r["median_price"] and r["median_volume_l"]:
            econ = napkin_econ(r["median_price"], r["median_volume_l"],
                               commission_or_default(args.commission), load_ue_config(), s)
            write_outputs(outdir, "econ", econ, md_econ(econ))
        md, inputs = md_items(r, econ), [args.file]
    elif args.cmd == "econ":
        r = napkin_econ(args.price, args.volume, commission_or_default(args.commission), load_ue_config(), s)
        md, inputs = md_econ(r), []
    elif args.cmd == "yoy":
        month = args.peak_month
        amplitude = None
        if month is None and args.season_file:
            month, amplitude = peak_month(rows_of(load_json(args.season_file)))
            if amplitude < s["flat_season_amplitude_pct"]:
                month = None
        r = yoy_peak(rows_of(load_json(args.trend_file)), month, today, s)
        r["season_amplitude_pct"] = amplitude
        md, inputs = md_yoy(r), [args.trend_file] + ([args.season_file] if args.season_file else [])
    elif args.cmd == "trends":
        r = trends_yoy(load_monthly(args.file), args.peak_month, s)
        md, inputs = md_trends(r), [args.file]
    elif args.cmd == "comments":
        r = complaints([Path(f) for f in args.files], s, today)
        md, inputs = md_complaints(r), args.files
    elif args.cmd == "reg":
        r = regulatory_check(args.path, s)
        md = (f"## Шаг 0 — регуляторика {ICON[r['verdict']]} {r['verdict']}\n\n- {args.path}\n"
              + "".join(f"- ❌ {x}\n" for x in r["reasons"])
              + "".join(f"- ⚠️ {x}\n" for x in r.get("notes", []))
              + f"- {r.get('manual_check', '')}\n")
        inputs = []
    else:
        r, md = summary(outdir, args.niche)
        inputs = []

    write_outputs(outdir, args.cmd, r, md, inputs)
    print(md)
    print(f"[сохранено: {outdir}]")


if __name__ == "__main__":
    main()
