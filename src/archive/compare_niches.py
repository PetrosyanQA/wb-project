"""Сравнение двух ниш по одной методике (strategy_*.json + finplan_*.json от 2026-10-07). 0 запросов.

    python -m src.compare_niches 777 2486      # → data/processed/compare_777_2486_2026-10-07.json + markdown-таблицы в stdout

Гейты — 6 фильтров пользователя (DNA 2026-10-05 / fresh 2026-10-06): документы, ≤ 1 л, маржа ≥ 18% и ROI ≥ 60% при медиане
до СПП (¥ = цена / 78), ≥ 150 шт на карточку, top-1 ≤ 25%, исправимая жалоба ≥ 12%. Гейты не ослабляем — только показываем.
"""
from __future__ import annotations

import glob
import json
import statistics as st
import sys

from src.dna_rank import econ as econ78
from src.strategy import PRESETS, RUN, load, rows_of

sys.stdout.reconfigure(encoding="utf-8")
NON_PRODUCT = ("брак", "некомплект", "упаковка")


def docs(P: dict) -> dict:
    cards = [load(f) for f in glob.glob(f"{P['cards']}/*.json")]
    return {"cards": len(cards), "need_kiz": sum(1 for c in cards if c.get("need_kiz")),
            "with_certificate": sum(1 for c in cards if c.get("certificate"))}


def sales_med(P: dict) -> float:
    R = sorted(rows_of(load(P["top100_products"])), key=lambda p: -(p.get("revenue") or 0))[:100]
    return st.median((p.get("sales_estimated") or p.get("sales") or 0) for p in R)


def niche(n: int) -> dict:
    P = PRESETS[n]
    S = load(f"data/processed/strategy_{n}_{RUN}.json")
    F = load(f"data/processed/finplan_{n}_{RUN}.json")
    ov, pb, cc, pr = S["overview"], S["price_basis"], S["concentration"], S["product"]
    themes = [t for t in S["complaints"]["themes"] if not any(w in t[0] for w in NON_PRODUCT)]
    med_price = pb["seller_price_med"]
    buy = st.median([c.get("buyout") or 0 for c in load(P["top100_json"])]) or pr["buyout"]
    e78 = econ78(med_price, pb["spp_realized_med_pct"], pr["vol"], pr["buyout"], pr["commission"])
    d = docs(P)
    sm = sales_med(P)
    runs = dict(zip(("пессимистичный", "реалистичный", "оптимистичный", "СПП-сценарий"), F["runs"]))
    gates = {
        "Документы: нет ЧЗ (need_kiz) у top-100": d["need_kiz"] == 0,       # сертификаты в карточках — добровольные
        "≤ 1 л": pr["vol"] <= 1.0,
        "Маржа ≥ 18% и ROI ≥ 60% при медиане до СПП": e78["margin"] >= 18 and e78["roi"] >= 60,
        "≥ 150 шт на карточку (медиана top-100)": sm >= 150,
        "top-1 продавец ≤ 25% (top-100)": cc["top1_top100_pct"] <= 25,
        "Исправимая жалоба ≥ 12%": bool(themes) and themes[0][2] >= 12,
    }
    return {"n": n, "name": P["name"], "S": S, "F": F, "gates": gates, "docs": d, "sales_med": sm, "e78": e78,
            "top_theme": themes[0] if themes else None, "runs": runs, "med_price": med_price, "buyout_top100": buy}


def fmt(x, nd=0):
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "✅" if x else "❌"
    if isinstance(x, (int, float)):
        s = f"{x:,.{nd}f}".replace(",", " ")
        return s
    return str(x)


def main() -> None:
    a, b = (niche(int(x)) for x in sys.argv[1:3])
    A, B = a["S"], b["S"]
    print(f"## Гейты\n| Гейт | {a['n']} | {b['n']} |\n|---|:---:|:---:|")
    for g in a["gates"]:
        print(f"| {g} | {fmt(a['gates'][g])} | {fmt(b['gates'][g])} |")
    print(f"\nмедиана до СПП: {a['med_price']} / {b['med_price']}; маржа/ROI при ней (¥ = цена/78): "
          f"{a['e78']['margin']}/{a['e78']['roi']} vs {b['e78']['margin']}/{b['e78']['roi']}; шт/карточку {a['sales_med']} / {b['sales_med']}; "
          f"жалоба №1 {a['top_theme']} / {b['top_theme']}; документы {a['docs']} / {b['docs']}")

    def row(label, f, nd=0):
        print(f"| {label} | {fmt(f(a), nd)} | {fmt(f(b), nd)} |")

    print(f"\n## Рынок\n| Показатель | {a['n']} | {b['n']} |\n|---|---:|---:|")
    row("Выручка 12 мес. (авг 2025 – июл 2026), млн ₽", lambda x: x["S"]["overview"]["rev_12m"] / 1e6, 1)
    row("Продажи 12 мес., тыс. шт", lambda x: x["S"]["overview"]["sales_12m"] / 1e3, 0)
    row("YoY 12 мес. (шт)", lambda x: x["S"]["overview"]["yoy_12m_sales"], 1)
    row("Выручка июль 2026, млн ₽", lambda x: x["S"]["overview"]["rev_30d"] / 1e6, 1)
    row("Продавцов с продажами, июль", lambda x: x["S"]["overview"]["sellers_with_sells"])
    row("SKU с продажами, июль", lambda x: x["S"]["overview"]["items_with_sells"])
    row("Пик / провал сезона (индекс)", lambda x: f"{x['S']['overview']['peak_month']} / {x['S']['overview']['trough_month']} "
                                                f"({x['S']['overview']['trough_to_peak_pct']}%)")
    row("YoY пикового месяца (шт)", lambda x: x["S"]["overview"]["yoy_peak_sales"], 1)
    row("YoY спроса в поиске в пиковый месяц", lambda x: x["S"]["yoy_check"].get("yoy_matched_pct"), 1)
    row("Продавцов с продажами июль YoY", lambda x: x["S"]["overview"]["yoy_jul_sellers_ws"], 1)
    row("top-1 / top-10 продавцов, % ниши", lambda x: f"{x['S']['concentration']['top1_niche_pct']} / {x['S']['concentration']['top10_niche_pct']}")
    row("top-1 / top-10 продавцов, % top-100", lambda x: f"{x['S']['concentration']['top1_top100_pct']} / {x['S']['concentration']['top10_top100_pct']}")
    row("Цена до СПП / покупателя, медиана top-100", lambda x: f"{x['S']['price_basis']['seller_price_med']} / {x['S']['price_basis']['buyer_price_med']}")
    row("Реализованная СПП, медиана", lambda x: x["S"]["price_basis"]["spp_realized_med_pct"], 1)
    row("Продажи медианной карточки top-100, шт/мес", lambda x: x["sales_med"])
    row("Новые карточки (с 2025-10) в top-100 / доля выручки %", lambda x: f"{x['S']['barriers']['new_cards_in_top100']} / {x['S']['barriers']['new_cards_share']}")
    row("Отзывы: медиана top-10 / минимум top-100", lambda x: f"{x['S']['barriers']['reviews_top10_med']} / {x['S']['barriers']['reviews_top100_min']}")
    row("Реклама, % дней (медиана top-100)", lambda x: x["S"]["barriers"]["ads_med_top100"])
    row("Жалоба №1 (доля негатива)", lambda x: f"{x['top_theme'][0]} {x['top_theme'][2]}%" if x["top_theme"] else None)

    print(f"\n## Траектории новых карточек (заказов/день без сезона, P25/P50/P75)\n| Мес. от 1-й продажи | {a['n']} | {b['n']} |\n|---|---|---|")
    for k in range(1, 7):
        f = lambda x: (lambda v: f"{v['p25']} / {v['p50']} / {v['p75']} (n={v['n']})" if v else "—")(
            x["S"]["entry_curves"]["percentiles"].get(str(k)))
        print(f"| {k} | {f(a)} | {f(b)} |")

    print(f"\n## Юнит-экономика выбранного товара (ДРР 15%)\n| | {a['n']} | {b['n']} |\n|---|---:|---:|")
    row("Товар", lambda x: x["S"]["product"].get("name"))
    row("Цена до СПП, ₽", lambda x: x["S"]["product"]["price"])
    row("¥ / потолок ¥", lambda x: f"{x['S']['product']['yuan']} / {x['S']['econ']['max_yuan']}")
    row("Объём, л / вес, кг", lambda x: f"{x['S']['product']['vol']} / {x['S']['product'].get('kg')}")
    for tag in ("база ДРР 15%", "цена −15%"):
        row(f"Прибыль/шт, ₽ — {tag}", lambda x, t=tag: x["S"]["econ"][t]["net_profit"])
        row(f"Маржа / ROI — {tag}", lambda x, t=tag: f"{x['S']['econ'][t]['net_margin_pct']}% / {x['S']['econ'][t]['roi_on_goods_pct']}%")
    row("СПП-сценарий: маржа", lambda x: next(v["net_margin_pct"] for k, v in x["S"]["econ"].items() if k.startswith("СПП")), 1)
    row("Безубыточность, шт/мес (ФФ 10 000 ₽)", lambda x: x["S"]["econ"]["breakeven_units_month"])

    print(f"\n## Финплан (12 мес.)\n| | {a['n']} | {b['n']} |\n|---|---:|---:|")
    row("Старт продаж", lambda x: x["F"]["start"])
    row("Партия 1, шт / вложения, ₽", lambda x: f"{x['F']['batch']} / {fmt(x['F']['runs'][0]['invest'])}")
    for nm in ("пессимистичный", "реалистичный", "оптимистичный"):
        row(f"{nm}: окупаемость, мес.", lambda x, n=nm: x["runs"][n]["payback"])
        row(f"{nm}: ROI 3/6/12 мес., %", lambda x, n=nm: "/".join(str(v) for v in x["runs"][n]["roi"].values()))
        row(f"{nm}: прибыль 12 мес., ₽", lambda x, n=nm: x["runs"][n]["rows"][-1]["cum_profit"])
    row("реалистичный: упущено из-за остатка, шт", lambda x: x["runs"]["реалистичный"]["lost_units"])
    row("СПП-сценарий: окупаемость, мес.", lambda x: x["F"]["runs"][3]["payback"])
    row("Чувствительность к месяцу старта (P50)", lambda x: "; ".join(f"{k}: окуп. {v['payback']}" for k, v in x["F"]["start_sensitivity"].items()))

    # последовательность: хватит ли денег первой ниши на партию второй к месяцу заказа
    inv_b = b["F"]["runs"][0]["invest"]
    m_order = 2                                                    # 777 стартует в декабре → январь = мес. 2
    print(f"\n## Последовательность «{a['n']} → {b['n']} на деньги {a['n']}» (заказ {b['n']} в январе = мес. {m_order} финплана {a['n']})")
    print(f"| Сценарий {a['n']} | Деньги к концу мес. {m_order}, ₽ | Деньги к концу мес. 3, ₽ | Нужно на запуск {b['n']}, ₽ | "
          f"Хватает в январе? | Первый месяц, когда хватает |\n|---|---:|---:|---:|:---:|---|")
    seq = {}
    names = a["F"]["month_names"]
    for nm, r in a["runs"].items():
        c2, c3 = r["rows"][m_order - 1]["cash_end"], r["rows"][2]["cash_end"]
        first = next((x["month"] for x in r["rows"] if x["cash_end"] >= inv_b), None)
        seq[nm] = {"cash_m2": c2, "cash_m3": c3, "need": inv_b, "ok": c2 >= inv_b, "first_month": first}
        print(f"| {nm} | {fmt(c2)} | {fmt(c3)} | {fmt(inv_b)} | {fmt(c2 >= inv_b)} | "
              f"{f'мес. {first} ({names[first - 1]})' if first else 'не в 12 мес.'} |")
    out = {"run": RUN, "a": a["n"], "b": b["n"], "gates": {a["n"]: a["gates"], b["n"]: b["gates"]},
           "e78": {a["n"]: a["e78"], b["n"]: b["e78"]}, "sales_med": {a["n"]: a["sales_med"], b["n"]: b["sales_med"]},
           "docs": {a["n"]: a["docs"], b["n"]: b["docs"]}, "sequencing": seq}
    path = f"data/processed/compare_{a['n']}_{b['n']}_{RUN}.json"
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
