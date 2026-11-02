"""Новые ниши против 777 (2026-10-06): те же 6 фильтров, что прошёл «Держатели в авто», схема FBS Подмосковье.

    python -m src.fresh_screen stage0 [--top 40]     # 0 запросов: выгрузка 2 291 предмета → очередь для top-100
    python -m src.fresh_screen stageB                # разбор сохранённых products (top-100) → короткий список
    python -m src.fresh_screen stage0|stageB --max-kg 3   # габарит до 3 кг: крупное разрешено, карго сверх 0.5 кг — в себестоимость

Этап 0 — мягкий: средняя цена ниши (revenue / sales, цена покупателя) у 777 = 535 ₽, а медиана top-100 до СПП = 1 112 ₽,
поэтому цена и экономика здесь только отсекают безнадёжное, жёсткая проверка — на top-100 (этап B).
Уже разобранные 24 ниши DNA + 6 ниш gates_fbs + 559 исключаются. Комиссия FBS — кабинет WB (kgvpMarketplace) [факт].
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics as st
import sys

from src.dna_rank import (IDS as DNA_IDS, econ, commissions, T_MARGIN, T_ROI, MIN_SALES, MAX_T1, MAX_VOL,
                          CFG, DRR, PACK, YUAN_RUB, MARKUP)
from src.unit_econ import unit_economics
from src.outliers import clean_items
from src.saleflow_eval import load_strategy, regulatory_check
from src.subject_screen import build_exclude

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-06"
DUMP = "data/raw/saleflow/2026-10-04/subjects_*/page_*.json"
SEASON = "data/processed/season_classification_2026-10-05.txt"
RAW = f"data/raw/saleflow/{RUN}/fresh"
QUEUE = f"data/processed/fresh_queue_{RUN}{{}}.json"
OUT = f"data/processed/fresh_stageB_{RUN}{{}}.json"
DONE = set(DNA_IDS) | {847, 1292, 7660, 27, 3472, 3333, 559}      # разобраны полностью 2026-10-05
SPP0 = 35.0                  # типичная СПП для пересчёта цены покупателя в цену до СПП [допущение; у 777 — 37.6%]
AOV_MIN, AOV_MAX = 450, 2600 # цена покупателя по нише; 777 = 535 ₽ должен пройти
MIN_NICHE_SALES = 15000      # top-100 × 150 шт — меньше физически не даст медианной карточке 150 продаж
MIN_SELLERS = 50
# FBS без ГТД: любая обязательная декларация/сертификат = нельзя; > 1 л не возим [допущение по названию предмета]
FRESH_EXCLUDE = re.compile(
    r"техника|камер|накопител|карты памяти|мыш|клавиатур|утюг|увлажнител|воздуходув|компрессор|паров|кабел|"   # электрика (ТР ТС 004/020)
    r"масл|антифриз|жидкост|герметик|клей|спре|средств|бактери|салфет|пенк|воск|кондиционер|"                 # химия/косметика
    r"контейнер|кувшин|фильтр|для вакуумат|посуд|бутыл|термос|"                                                  # контакт с пищей/водой (ТР ТС 005)
    r"ткан|пряж|текстил|"                                                                                        # текстиль (ТР ТС 017)
    r"нож|оружи|"                                                                                                # холодное оружие
    r"теплоизол|покрыти|бумаг|пеленк|"                                                                           # рулоны / дешёвое тяжёлое
    r"стройматериал|строительные материалы|отделочные материалы|"
    r"^красота /", re.I)
BIG_EXCLUDE = re.compile(r"швабр|ведр|лотк|корзин|коробк|тренажер|гантел|удилищ|домик|лежак", re.I)  # > 1 л — только при лимите 0.5 кг
FX = 83.48                   # ₽/$ (config/filters.yaml, ЦБ 03.10.2026)
CARGO_USD_KG = 2.0           # карго Китай → Москва без ГТД [со слов пользователя]
BASE_KG = 0.5                # правило ¥ × 17 ₽ уже покрывает лёгкий товар до 0.5 кг [допущение]
KG_PER_L = 0.2               # объёмный вес карго: 200 кг/м³ [допущение]
BATCH, BUDGET_GOODS_USD = 200, 1700   # партия ≥ 200 шт; товар + карго ≤ 85% от $2 000 (остальное — образцы, ФФ, реклама) [допущение]
MAX_KG = 0.5                 # перезаписывается --max-kg
EXTRA_RAW: list[str] = []     # --extra-raw: доп. папки с products_<sid>_2026-07.json (докачка 2026-10-07)
LEGACY_PRICE = False         # --legacy-price: формула 2026-10-06 (final_price / (1 − СПП) — двойной учёт СПП, ошибка)
# ложные срабатывания фильтра по названию («носк» в «Переноски», «клей» в «наклейки», «корм» в «Кормушки» …) — сертификат не нужен [проверено вручную 2026-10-06]
NAME_FALSE_POSITIVE = {2159, 2783, 7048, 968, 930, 388, 726, 1599, 2267, 586, 1272, 1543, 1121, 625, 1597, 1545}


def suffix() -> str:
    return "" if MAX_KG <= 0.5 else f"_{MAX_KG:g}kg"


def econ_kg(price_s: float, spp: float, vol: float | None, buyout: float, com: float, kg: float) -> dict:
    """dna_rank.econ + карго за вес сверх BASE_KG (оплачиваемый вес = max(вес, объём × KG_PER_L))."""
    v = vol if vol is not None else 0.5
    extra = max(0.0, kg - BASE_KG) * CARGO_USD_KG * FX
    cost = price_s / MARKUP * YUAN_RUB + extra
    kw = dict(buyout_pct=buyout, ad_share_of_revenue_pct=DRR, commission_pct=com, packaging_rub=PACK)
    e = unit_economics(price_s, cost, v, CFG, **kw)
    eb = unit_economics(price_s * (1 - spp / 100), cost, v, CFG, with_breakeven=False, **kw)
    lo, hi = 0.0, price_s
    for _ in range(50):
        mid = (lo + hi) / 2
        r = unit_economics(price_s, mid + extra, v, CFG, with_breakeven=False, **kw)
        lo, hi = (mid, hi) if r["net_margin_pct"] >= T_MARGIN and r["roi_on_goods_pct"] >= T_ROI else (lo, mid)
    return {"price_s": round(price_s), "price_b": round(price_s * (1 - spp / 100)), "yuan78": round(price_s / MARKUP, 1),
            "cost": round(cost), "cargo_extra": round(extra), "margin": e["net_margin_pct"], "roi": e["roi_on_goods_pct"],
            "profit": e["net_profit"], "margin_b": eb["net_margin_pct"], "yuan_max": round(lo / YUAN_RUB, 1),
            "batch_usd": round(BATCH * cost / FX), "ue": e}


def dump() -> dict[int, dict]:
    rows = {}
    for f in glob.glob(DUMP):
        for x in json.load(open(f, encoding="utf-8"))["data"]:
            rows[x["id"]] = x
    return rows


def docs() -> dict[int, str]:
    out = {}
    for line in open(SEASON, encoding="utf-8"):
        m = re.match(r"^(\d+)\s+([GYR])\b", line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def stage0(top: int) -> None:
    rows, dc, com, strat = dump(), docs(), commissions(), load_strategy()
    excl = build_exclude({"gadget", "decor"})
    drop = {k: 0 for k in ("уже разобрана", "док 🔴/🟡", "ЧЗ/категория", "сезон", "продавцы", "оборот", "цена", "нет комиссии", "экономика")}
    out = []
    for sid, x in rows.items():
        name = x["name"]
        sales = x.get("sales_estimated") or x.get("sales") or 0
        aov = (x.get("revenue_estimated") or x.get("revenue") or 0) / sales if sales else 0
        if sid in DONE:
            drop["уже разобрана"] += 1; continue
        if dc.get(sid) in ("R", "Y"):
            drop["док 🔴/🟡"] += 1; continue
        big = BIG_EXCLUDE.search(name) and MAX_KG <= 0.5
        if sid not in NAME_FALSE_POSITIVE and (regulatory_check(name, strat)["verdict"] == "FAIL" or excl.search(name)
                                               or FRESH_EXCLUDE.search(name) or big):
            drop["ЧЗ/категория"] += 1; continue
        if (x.get("seasonality_level") or 0) > 2:
            drop["сезон"] += 1; continue
        if (x.get("sellers") or 0) <= MIN_SELLERS:
            drop["продавцы"] += 1; continue
        if sales < MIN_NICHE_SALES:
            drop["оборот"] += 1; continue
        if not AOV_MIN <= aov <= AOV_MAX:
            drop["цена"] += 1; continue
        if sid not in com:
            drop["нет комиссии"] += 1; continue
        price_s = aov / (1 - SPP0 / 100)
        buyout = x.get("purchase_after_return") or 75
        e = econ(price_s, SPP0, None, buyout, com[sid])          # объём неизвестен → 0.5 л [допущение]
        if e["margin"] < T_MARGIN - 6:                             # запас 6 п.п.: у top-100 цена выше средней по нише
            drop["экономика"] += 1; continue
        val = x.get("comment_valuation_average") or 5
        out.append({"id": sid, "name": name, "docs": dc.get(sid, "?"), "aov_b": round(aov), "price_s_est": round(price_s),
                    "sales": sales, "sellers": x["sellers"], "season": x.get("seasonality_level"), "buyout": buyout,
                    "com": com[sid], "margin_est": e["margin"], "rating": val,
                    "fresh_pct": round(100 * (x.get("items_new") or 0) / max(x.get("items") or 1, 1), 1),
                    # очередь: масштаб × маржа × недовольство (место для исправимой жалобы)
                    "score": round(sales ** 0.5 * max(e["margin"], 1) * (1 + max(0, 4.8 - val)), 1)})
    out.sort(key=lambda r: -r["score"])
    print(f"предметов: {len(rows)} | отсеяно: {drop} | осталось: {len(out)}")
    print("| # | id | Предмет | док | цена покуп. ₽ | шт/мес ниши | продавцов | FBS % | маржа оц. % | оценка отзывов |")
    print("|---|---|---|---|---:|---:|---:|---:|---:|---:|")
    for i, r in enumerate(out, 1):
        mark = "→" if i <= top else " "
        print(f"|{mark}{i} | {r['id']} | {r['name']} | {r['docs']} | {r['aov_b']} | {r['sales']} | {r['sellers']} | "
              f"{r['com']} | {r['margin_est']} | {r['rating']} |")
    os.makedirs("data/processed", exist_ok=True)
    json.dump({"run": RUN, "max_kg": MAX_KG, "drop": drop, "all": out, "queue": out[:top]},
              open(QUEUE.format(suffix()), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nочередь top-{top} → {QUEUE.format(suffix())}")


def collect(src_dir: str) -> None:
    """Сохранённые MCP-ответы (tool-results) → RAW/products_<sid>_2026-07.json по преобладающему subject_id."""
    import collections, shutil
    os.makedirs(RAW, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(src_dir, "mcp-saleflow_universal-wb_subject-*.txt"))):
        d = json.load(open(f, encoding="utf-8"))
        c = collections.Counter(p.get("subject_id") for p in d.get("data", []))
        if not c:
            continue
        sid = c.most_common(1)[0][0]
        dst = f"{RAW}/products_{sid}_2026-07.json"
        shutil.copyfile(f, dst)
        print(f"{os.path.basename(f)} → {dst} ({len(d['data'])} строк)")


def top100(sid: int) -> dict | None:
    f = next((x for x in [f"{d}/products_{sid}_2026-07.json" for d in [RAW, *EXTRA_RAW]] if os.path.exists(x)), None)
    if f is None:
        return None
    d = json.load(open(f, encoding="utf-8"))
    rows = d.get("data", d) if isinstance(d, dict) else d
    rev = lambda p: p.get("revenue_estimated") or p.get("revenue") or 0
    rows = sorted(rows, key=lambda p: -rev(p))[:100]
    kept, rep = clean_items(rows, expected_subject=sid)
    return {"rows": kept, "n": len(rows), "dropped": rep["dropped"], "reasons": rep["reasons"]}


def stageB() -> None:
    Q = json.load(open(QUEUE.format(suffix()), encoding="utf-8"))["all"]   # очередь отбиралась вручную: берём всё, что скачано
    com = commissions()
    res = []
    for q in Q:
        t = top100(q["id"])
        if t is None:
            continue
        P = t["rows"]
        if LEGACY_PRICE:
            spp = st.median([p.get("spp_avg") or 0 for p in P])
            price_s = st.median([p["final_price"] / (1 - (p.get("spp_avg") or 0) / 100) for p in P if p.get("final_price")])
        else:   # final_price уже = цена до СПП (= start_price × (1 − basic_sale)); СПП — реализованная: 1 − выручка/шт / до СПП
            spp = st.median([(1 - p["revenue"] / p["sales"] / p["final_price"]) * 100 for p in P if p.get("sales") and p.get("final_price")])
            price_s = st.median([p["final_price"] for p in P if p.get("final_price")])
        sales = st.median([p.get("sales_estimated") or p.get("sales") or 0 for p in P])
        vols = [(p.get("package_length") or 0) * (p.get("package_width") or 0) * (p.get("package_height") or 0) / 1000 for p in P]
        vols = [v for v in vols if v > 0]
        vol = round(st.median(vols), 2) if len(vols) >= 10 else None
        rev = lambda p: p.get("revenue_estimated") or p.get("revenue") or 0
        tot = sum(rev(p) for p in P) or 1
        by_seller: dict = {}
        for p in P:
            by_seller[p.get("supplier_id") or p.get("seller")] = by_seller.get(p.get("supplier_id") or p.get("seller"), 0) + rev(p)
        shares = sorted((v / tot * 100 for v in by_seller.values()), reverse=True)
        new = [p for p in P if (p.get("sku_first_date") or "") >= "2025-07-01"]
        kg = None if vol is None else vol * KG_PER_L
        if MAX_KG <= 0.5:
            e = econ(price_s, spp, vol, q["buyout"], com[q["id"]])
            f2 = ("F2 ≤ 1 л", None if vol is None else vol <= MAX_VOL)
        else:
            e = econ_kg(price_s, spp, vol, q["buyout"], com[q["id"]], kg if kg is not None else BASE_KG)
            f2 = (f"F2 ≤ {MAX_KG:g} кг (объёмный)", None if kg is None else kg <= MAX_KG)
        f = {f2[0]: f2[1],
             "F3 маржа ≥ 18% и ROI ≥ 60%": e["margin"] >= T_MARGIN and e["roi"] >= T_ROI,
             "F4 ≥ 150 шт/карточку": sales >= MIN_SALES,
             "F5 top-1 ≤ 25%": shares[0] <= MAX_T1}
        if MAX_KG > 0.5:
            f[f"F7 партия {BATCH} шт ≤ ${BUDGET_GOODS_USD}"] = e["batch_usd"] <= BUDGET_GOODS_USD
        res.append({**q, "n": t["n"], "dropped": t["dropped"], "spp": round(spp, 1), "price_s": round(price_s),
                    "price_b": round(price_s * (1 - spp / 100)), "med_s": round(sales), "vol": vol,
                    "kg": None if kg is None else round(kg, 2), "t1": round(shares[0], 1),
                    "t10": round(sum(shares[:10]), 1), "sellers_top100": len(by_seller), "new_cards": len(new),
                    "new_rev_pct": round(sum(rev(p) for p in new) / tot * 100, 1),
                    **{k: v for k, v in e.items() if k != "ue"}, "filters": f,
                    "fails": [k for k, v in f.items() if v is False], "unknown": [k for k, v in f.items() if v is None],
                    "potential": round(e["profit"] * sales) if e["profit"] > 0 else 0})
    res.sort(key=lambda r: (len(r["fails"]), -r["potential"]))
    out = OUT.format(suffix() + ("" if LEGACY_PRICE else "_pricefix"))
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"→ {out}")
    print("| id | Ниша | чистка | цена до СПП ₽ | покуп. ₽ | шт/карт | л | кг (объёмн.) | карго+ ₽ | партия $ | top-1 % | top-10 % "
          "| маржа % | ROI % | от покуп. % | ¥max | прибыль×шт ₽ | не прошла |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in res:
        print(f"| {r['id']} | {r['name'][:40]} | {r['n']}/{r['dropped']} | {r['price_s']} | {r['price_b']} | {r['med_s']} | "
              f"{r['vol'] if r['vol'] is not None else '—'} | {r['kg'] if r['kg'] is not None else '—'} | "
              f"{r.get('cargo_extra', 0)} | {r.get('batch_usd', '—')} | {r['t1']} | {r['t10']} | {r['margin']} | {r['roi']} | "
              f"{r['margin_b']} | {r['yuan_max']} | {r['potential']} | {', '.join(r['fails']) or '✅'} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["stage0", "collect", "stageB"])
    ap.add_argument("--src", default="")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--max-kg", type=float, default=0.5)
    ap.add_argument("--legacy-price", action="store_true")
    ap.add_argument("--extra-raw", nargs="*", default=[])
    a = ap.parse_args()
    global MAX_KG, LEGACY_PRICE, EXTRA_RAW
    MAX_KG, LEGACY_PRICE, EXTRA_RAW = a.max_kg, a.legacy_price, a.extra_raw
    if a.stage == "stage0":
        stage0(a.top)
    elif a.stage == "collect":
        collect(a.src)
    else:
        stageB()


if __name__ == "__main__":
    main()
