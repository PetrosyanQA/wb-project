"""ДНК всех стабильных ниш → фильтры пользователя → лучший товар (2026-10-05).

Фильтры («Текущие», выбор пользователя 2026-10-05):
  F1 документы 🟢 (data/processed/season_classification_2026-10-05.txt)
  F2 медианная упаковка ≤ 1 л (products500 package_*; иначе карточки лидеров cards/*_dims.json)
  F3 маржа ≥ targets.min_net_margin_pct и ROI ≥ targets.min_roi_on_cost_pct при медианной цене ниши ДО СПП,
     комиссия FBS кабинета (kgvpMarketplace, WB API), себестоимость = цена до СПП / 78 × 17 (правило ¥×78, ¥×17 ₽)
  F4 ≥ 150 продаж медианной карточки top-100 в месяц
  F5 доля top-1 продавца ≤ 25%
  F6 закрываемая жалоба ≥ 12% негатива лидеров (темы доставки/пересорта WB не считаются)

    python -m src.dna_rank        # → data/processed/dna_rank_2026-10-05.json, reports/dna_all_2026-10-05.xlsx
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import statistics as st

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from src.dna_dicts import get_cfg
from src.dna_reviews import reviews
from src.niche_dna import analyze, hypotheses
from src.unit_econ import load_config, unit_economics

RUN = "2026-10-05"
IDS = [777, 731, 1203, 879, 840, 1520, 941, 874, 2090, 2591, 2950, 955, 1843, 1835, 4954, 3716, 6214, 4143, 1860, 1856,
       1857, 296, 1853, 501]
YUAN_RUB, MARKUP = 17.0, 78.0                  # пользователь: себестоимость ≈ ¥ × 17 ₽, розница ≥ ¥ × 78
DRR, PACK = 15.0, 50.0                         # ДРР 15% [допущение], упаковка + фулфилмент 50 ₽ [допущение]
MIN_SALES, MAX_T1, MAX_VOL, MIN_COMPLAINT, MIN_NEG = 150, 25.0, 1.0, 12.0, 30
NON_PRODUCT = {"упаковка / доставка", "некомплект / не тот товар"}
CACHE_COMMISSION = "data/cache_wb/2f03a9a1132d6c553cfd5e3a901ef334c7691e1b.json"   # /api/v1/tariffs/commission
SCREEN = f"data/processed/dna_screen_{RUN}.json"
SEASON = f"data/processed/season_classification_{RUN}.txt"
NOTES = {955: "Август 2026 = 1–30.08 (31-е не загрузилось — Saleflow timeout).",
         501: "Октябрь 2025 не загрузился (Saleflow timeout, 4 попытки) — 11 месяцев, в сезонности октябрь = 0."}

CFG = load_config()
T_MARGIN = float(CFG["targets"]["min_net_margin_pct"])
T_ROI = float(CFG["targets"]["min_roi_on_cost_pct"])


def commissions() -> dict[int, float]:
    d = json.load(open(CACHE_COMMISSION, encoding="utf-8"))["data"]["report"]
    return {r["subjectID"]: float(r["kgvpMarketplace"]) for r in d}          # kgvpMarketplace = FBS («Маркетплейс»)


def docs() -> dict[int, str]:
    out = {}
    for line in open(SEASON, encoding="utf-8"):
        m = re.match(r"^(\d+)\s+([GYR])\b", line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def volume(sid: int) -> tuple[float | None, str]:
    d = f"data/raw/saleflow/{RUN}/dna/{sid}"
    rows = json.load(open(f"{d}/products500_2026-07.json", encoding="utf-8"))["data"]
    rev = lambda x: x.get("revenue_estimated") or x.get("revenue") or 0
    top = sorted(rows, key=lambda x: -rev(x))[:100]
    vv = [(x.get("package_length") or 0) * (x.get("package_width") or 0) * (x.get("package_height") or 0) / 1000 for x in top]
    vv = [v for v in vv if v > 0]
    if len(vv) >= 10:
        return round(st.median(vv), 2), f"медиана упаковки {len(vv)} карточек top-100 [факт]"
    facts = [json.load(open(f, encoding="utf-8")) for f in glob.glob(f"{d}/cards/*_dims.json")]
    facts = [f for f in facts if f.get("item_volume_l")]
    if facts:
        vals = ", ".join(f"{f['type']} {f['item_volume_l']} л" for f in facts)
        return round(st.median(f["item_volume_l"] for f in facts), 2), f"габариты изделия у лидеров: {vals} [оценка, без упаковки]"
    return None, "нет габаритов в данных"


def econ(price_s: float, spp: float, vol: float | None, buyout: float, com: float) -> dict:
    """Юнит-экономика при цене до СПП и при цене покупателя (консервативно); ¥ = цена до СПП / 78."""
    v = vol if vol is not None else 0.5
    cost = price_s / MARKUP * YUAN_RUB
    kw = dict(buyout_pct=buyout, ad_share_of_revenue_pct=DRR, commission_pct=com, packaging_rub=PACK)
    e = unit_economics(price_s, cost, v, CFG, **kw)
    eb = unit_economics(price_s * (1 - spp / 100), cost, v, CFG, with_breakeven=False, **kw)
    lo, hi = 0.0, price_s                      # максимальный ¥, при котором маржа ≥ 18% и ROI ≥ 60%
    for _ in range(50):
        mid = (lo + hi) / 2
        r = unit_economics(price_s, mid, v, CFG, with_breakeven=False, **kw)
        lo, hi = (mid, hi) if r["net_margin_pct"] >= T_MARGIN and r["roi_on_goods_pct"] >= T_ROI else (lo, mid)
    return {"price_s": round(price_s), "price_b": round(price_s * (1 - spp / 100)), "yuan78": round(price_s / MARKUP, 1),
            "cost": round(cost), "margin": e["net_margin_pct"], "roi": e["roi_on_goods_pct"], "profit": e["net_profit"],
            "margin_b": eb["net_margin_pct"], "yuan_max": round(lo / YUAN_RUB, 1), "vol_assumed": vol is None, "ue": e}


def complaint(sid: int) -> dict:
    R = reviews(RUN, sid)
    prod = [(t, v) for t, v in R["pooled"] if t not in NON_PRODUCT]
    top = prod[0] if prod else (None, {"share": 0, "count": 0, "quotes": []})
    return {"total_neg": R["total_neg"], "files": R["files"], "top": top[0], "share": round(top[1]["share"], 1),
            "count": top[1]["count"], "quotes": top[1].get("quotes", [])[:2],
            "themes": [(t, round(v["share"], 1)) for t, v in R["pooled"][:5]],
            "fixable": bool(top[0]) and top[1]["share"] >= MIN_COMPLAINT and R["total_neg"] >= MIN_NEG}


def rank() -> dict:
    screen = {s["id"]: s for s in json.load(open(SCREEN, encoding="utf-8"))}
    com, dc = commissions(), docs()
    niches, hyps = [], []
    for sid in IDS:
        s, cfg = screen[sid], get_cfg(sid)
        vol, vsrc = volume(sid)
        e = econ(s["seller_price"], s["spp"], vol, s["buyout"], com[sid])
        c = complaint(sid)
        R = analyze(RUN, sid)
        H = hypotheses(R)
        for h in H:
            he = econ(h["check"], R["spp"], vol, s["buyout"], com[sid])
            hyps.append({"sid": sid, "niche": cfg["niche"], "s": h["s"], "name": h["name"], "base": h["base"],
                         "fills": h["fills"], "fy": round(h["fy"]), "def_pct": round(h["def_pct"]), "type": h["type"],
                         "length": h["length"], "seo": h["seo"], "risk": h["risk"], **{k: v for k, v in he.items() if k != "ue"}})
        ok_h = [h for h in hyps if h["sid"] == sid and h["margin"] >= T_MARGIN and h["roi"] >= T_ROI]
        best = max(ok_h, key=lambda h: (h["fy"], h["def_pct"])) if ok_h else None
        f = {
            "F1 документы 🟢": dc.get(sid) == "G",
            "F2 ≤ 1 л": None if vol is None else vol <= MAX_VOL,
            "F3 маржа ≥ 18% и ROI ≥ 60%": e["margin"] >= T_MARGIN and e["roi"] >= T_ROI,
            "F4 ≥ 150 шт/карточку": s["med_s"] >= MIN_SALES,
            "F5 top-1 ≤ 25%": s["t1"] <= MAX_T1,
            "F6 жалоба ≥ 12%": c["fixable"],
        }
        fails = [k for k, v in f.items() if v is False]
        unknown = [k for k, v in f.items() if v is None]
        niches.append({"id": sid, "name": cfg["niche"], "docs": dc.get(sid), "vol": vol, "vol_src": vsrc, "com": com[sid],
                       "spp": round(s["spp"], 1), "buyout": s["buyout"], "med_s": round(s["med_s"]), "t1": round(s["t1"], 1),
                       "t10": round(s["t10"], 1), "sellers": s["sellers"], "cn": round(s["cn"]), "newsh": round(s["newsh"], 1),
                       "months": len(R["months"]), "missing": R["missing"], "note": NOTES.get(sid, ""),
                       "fy": round(R["total_fy"]), "meanings": len(R["meanings"]), "unk": round(sum(q["fy"] for q in R["queries"] if q["unk"]) / R["total_fy"] * 100, 1),
                       **{k: v for k, v in e.items() if k != "ue"}, "complaint": c, "filters": f, "fails": fails,
                       "unknown": unknown, "best": best,
                       "potential": round(e["profit"] * s["med_s"]) if e["profit"] > 0 else 0})
    niches.sort(key=lambda n: (len(n["fails"]), len(n["unknown"]), -n["potential"]))
    return {"run": RUN, "targets": {"margin": T_MARGIN, "roi": T_ROI, "sales": MIN_SALES, "t1": MAX_T1, "vol": MAX_VOL,
                                    "complaint": MIN_COMPLAINT, "min_neg": MIN_NEG},
            "assumptions": {"yuan_rub": YUAN_RUB, "markup": MARKUP, "drr": DRR, "pack": PACK},
            "niches": niches, "hyps": hyps}


def write_xlsx(D: dict, path: str) -> None:
    F = lambda c: PatternFill("solid", fgColor=c)
    B, wrap = Font(bold=True), Alignment(wrap_text=True, vertical="top")
    wb = Workbook()
    ws = wb.active
    ws.title = "🏁 Сводка"
    cols = ["Место", "Ниша", "id", "Вердикт", "Не прошла", "Док", "Объём, л", "Комиссия FBS %", "СПП %", "Цена покуп. ₽",
            "Цена до СПП ₽", "¥ при ×78", "Маржа до СПП %", "ROI %", "Маржа от цены покуп. %", "¥ max (18%/60%)",
            "Шт/карточку/мес", "Top-1 %", "Top-10 %", "Продавцов", "Китай %", "Жалоба №1", "Доля %", "Негатива",
            "Лучшая гипотеза (маржа ≥ 18%)", "Её цена до СПП ₽", "Её маржа %", "Спрос (год)", "Прибыль × шт/мес ₽"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), F("305496"), wrap
    for i, n in enumerate(D["niches"], 1):
        b = n["best"]
        verdict = "✅ проходит все" if not n["fails"] and not n["unknown"] else ("❔ не хватает данных" if not n["fails"] else "❌")
        ws.append([i, n["name"], n["id"], verdict, "; ".join(n["fails"] + [u + " (нет данных)" for u in n["unknown"]]),
                   n["docs"], n["vol"] if n["vol"] is not None else "—", n["com"], n["spp"], n["price_b"], n["price_s"],
                   n["yuan78"], n["margin"], n["roi"], n["margin_b"], n["yuan_max"], n["med_s"], n["t1"], n["t10"],
                   n["sellers"], n["cn"], n["complaint"]["top"] or "—", n["complaint"]["share"], n["complaint"]["total_neg"],
                   b["name"] if b else "—", b["price_s"] if b else "—", b["margin"] if b else "—", b["fy"] if b else "—",
                   n["potential"]])
        r = ws.max_row
        ws.cell(r, 4).fill = F("C6EFCE" if verdict.startswith("✅") else "FFEB9C" if verdict.startswith("❔") else "FFC7CE")
        for col, ok in ((13, n["margin"] >= T_MARGIN), (17, n["med_s"] >= MIN_SALES), (18, n["t1"] <= MAX_T1),
                        (23, n["complaint"]["fixable"])):
            ws.cell(r, col).font = Font(color="2E7D32" if ok else "C00000", bold=True)
        for col in (5, 22, 25):
            ws.cell(r, col).alignment = wrap
    ws.freeze_panes = "C2"
    for i, w in enumerate([6, 26, 6, 16, 40, 5, 8, 9, 7, 9, 9, 8, 9, 8, 10, 9, 10, 8, 8, 9, 8, 30, 7, 8, 44, 10, 9, 11, 12], 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w

    ws = wb.create_sheet("🎯 Гипотезы всех ниш")
    cols = ["Ниша", "Стратегия", "Товар", "Основа", "Начинки", "Спрос (год)", "Дефицит %", "Сезонность", "Цена до СПП ₽",
            "Цена покуп. ₽", "¥ при ×78", "Маржа %", "ROI %", "Маржа от цены покуп. %", "¥ max (18%/60%)", "Риски"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), F("305496"), wrap
    for h in sorted(D["hyps"], key=lambda h: (-(h["margin"] >= T_MARGIN), -h["fy"])):
        ws.append([h["niche"], h["s"], h["name"], h["base"], h["fills"], h["fy"], h["def_pct"], f"{h['type']}, {h['length']} мес",
                   h["price_s"], h["price_b"], h["yuan78"], h["margin"], h["roi"], h["margin_b"], h["yuan_max"], h["risk"]])
        ws.cell(ws.max_row, 12).font = Font(color="2E7D32" if h["margin"] >= T_MARGIN else "C00000", bold=True)
        for col in (3, 4, 5, 16):
            ws.cell(ws.max_row, col).alignment = wrap
    ws.freeze_panes = "D2"
    for i, w in enumerate([24, 18, 36, 34, 34, 11, 9, 14, 10, 10, 8, 8, 8, 10, 9, 60], 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w

    ws = wb.create_sheet("🗣 Жалобы")
    ws.append(["Ниша", "Файлов отзывов", "Негатива (≤3★ с текстом, 365 дн.)", "Темы (доля негатива)", "Цитаты главной темы"])
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), F("305496"), wrap
    for n in D["niches"]:
        c = n["complaint"]
        ws.append([n["name"], c["files"], c["total_neg"], "; ".join(f"{t} {s}%" for t, s in c["themes"]),
                   " | ".join(q[:160] for q in c["quotes"])])
        for col in (4, 5):
            ws.cell(ws.max_row, col).alignment = wrap
    for i, w in enumerate([26, 10, 14, 80, 90], 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w

    ws = wb.create_sheet("📖 Легенда")
    a, t = D["assumptions"], D["targets"]
    lines = [
        "📖 Как считали (2026-10-05)",
        "Данные: Saleflow — keywords 2025-09 … 2026-08 помесячно, products (500 карточек, июль 2026), отзывы 2–3 лидеров каждой ниши; "
        "комиссия FBS — WB API кабинета (/api/v1/tariffs/commission, поле kgvpMarketplace) [факт].",
        "Метрики ниши (цена, СПП, top-1, top-10, продавцы, шт/карточку, Китай %) — скрининг top-100 карточек июля 2026 после "
        "src.outliers.clean_items (data/processed/dna_screen_2026-10-05.json) [факт; ±10–20% — оценка MPStats/Saleflow].",
        f"Юнит-экономика — src/unit_econ.py: цена до СПП, себестоимость = цена / {a['markup']:.0f} × {a['yuan_rub']:.0f} ₽ "
        f"(правило пользователя: розница ≥ ¥ × 78, закупка ≈ ¥ × 17 ₽), ДРР {a['drr']:.0f}% и упаковка+фулфилмент {a['pack']:.0f} ₽ [допущение], "
        "выкуп — Saleflow по нише, логистика — config (тарифы WB API) [допущение для FBS Подмосковье].",
        "«Маржа от цены покупателя» — консервативный сценарий, если удержания считаются от цены после СПП (главный непроверенный риск).",
        f"¥ max — наибольшая закупочная цена, при которой маржа ≥ {t['margin']:.0f}% и ROI ≥ {t['roi']:.0f}%.",
        f"Фильтры: F1 документы 🟢; F2 ≤ {t['vol']} л; F3 маржа ≥ {t['margin']:.0f}% и ROI ≥ {t['roi']:.0f}% при медианной цене ниши; "
        f"F4 ≥ {t['sales']} продаж медианной карточки в месяц; F5 top-1 ≤ {t['t1']:.0f}%; "
        f"F6 закрываемая жалоба ≥ {t['complaint']:.0f}% при ≥ {t['min_neg']} негативных отзывах (темы «упаковка / доставка» и "
        "«некомплект / не тот товар» — проблемы WB, не товара).",
        "Лучшая гипотеза — из листа «Гипотезы» ДНК ниши: наибольший спрос среди гипотез с маржой ≥ 18% и ROI ≥ 60% при цене сегмента "
        "(медиана цены карточек с теми же смыслами), не «цена мечты».",
        "Прибыль × шт/мес — чистая прибыль на единицу при медианной цене × продажи медианной карточки: ориентир масштаба, не прогноз [оценка].",
        "⚠️ Исправление: в скрининге 2026-10-05 (утро) комиссия бралась из поля kgvpSupplier (это DBS «Витрина»). "
        "Для FBS верное поле — kgvpMarketplace; для «Держателей в авто» оба = 20%, для остальных ниш FBS выше на 2–8 п.п.",
    ]
    for n in D["niches"]:
        if n["note"]:
            lines.append(f"⚠️ {n['name']}: {n['note']}")
    for line in lines:
        ws.append([line])
        ws.cell(ws.max_row, 1).alignment = wrap
        if line[:2] in ("📖", "⚠️"):
            ws.cell(ws.max_row, 1).font = B
    ws.column_dimensions["A"].width = 160
    wb.save(path)


def main() -> None:
    D = rank()
    os.makedirs("data/processed", exist_ok=True)
    json.dump(D, open(f"data/processed/dna_rank_{RUN}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    write_xlsx(D, f"reports/dna_all_{RUN}.xlsx")
    print(f"saved reports/dna_all_{RUN}.xlsx")
    for i, n in enumerate(D["niches"], 1):
        b = n["best"]
        print(f"{i:2}. {n['name'][:28]:28} | {'✅' if not n['fails'] and not n['unknown'] else '❌' if n['fails'] else '❔'} "
              f"{', '.join(n['fails']) or '—'}{' | нет данных: ' + ', '.join(n['unknown']) if n['unknown'] else ''} | "
              f"маржа {n['margin']}% ROI {n['roi']}% | шт {n['med_s']} | top1 {n['t1']} | жалоба {n['complaint']['top']} "
              f"{n['complaint']['share']}% ({n['complaint']['total_neg']}) | лучшая: {b['name'] + ' ' + str(b['price_s']) + ' ₽ ' + str(b['margin']) + '%' if b else '—'}")


if __name__ == "__main__":
    main()
