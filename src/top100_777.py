"""Топ-100 «Держателей в авто» (777): характеристики карточек WB + ежедневные продажи (Saleflow by_period).

    python -m src.top100_777     # → data/processed/top100_777_2026-10-05.json, reports/top100_777_2026-10-05.xlsx
"""
from __future__ import annotations

import collections
import json
import os
import re
import statistics as st

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

B = "data/raw/saleflow/2026-10-05/dna/777/top100"
OUT = "data/processed/top100_777_2026-10-05.json"
APR_JUL = ("2026-04-01", "2026-07-31")      # надёжное окно; август–сентябрь в Saleflow неполные


def num(s):
    m = re.search(r"[\d.,]+", str(s or ""))
    return float(m.group().replace(",", ".")) if m else None


def opt(card, name):
    for o in card.get("options", []):
        if o["name"] == name:
            return o["value"]
    return None


def classify(name: str, mount: str, compat: str, card: dict) -> dict:
    t = f"{name} {mount or ''} {compat or ''} {card.get('description', '')[:600]}".lower()
    n = f"{name} {mount or ''}".lower()
    return {
        "магнит": bool(re.search(r"магнит", n)),
        "MagSafe": bool(re.search(r"magsafe|магсейф", t)),
        "зарядка": bool(re.search(r"зарядк|беспроводн|qi", n)),
        "присоска/вакуум": bool(re.search(r"присоск|вакуум", n)),
        "воздуховод": bool(re.search(r"воздуховод|дефлектор|решетк|решётк", n)),
        "панель/торпедо": bool(re.search(r"панел|торпед|приборн", n)),
        "зажим/захват": bool(re.search(r"зажим|захват|клипс|автоматич", n)),
        "на руль/зеркало/подголовник": bool(re.search(r"руль|зеркал|подголов", n)),
    }


def main() -> None:
    top = json.load(open(f"{B}/top100_products_2026-07.json", encoding="utf-8"))
    rows = []
    for rank, p in enumerate(top, 1):
        card = json.load(open(f"{B}/cards/{p['id']}.json", encoding="utf-8"))
        daily = sorted(json.load(open(f"{B}/daily/{p['id']}.json", encoding="utf-8")), key=lambda r: r["data"])
        win = [r for r in daily if APR_JUL[0] <= r["data"] <= APR_JUL[1]]
        by_m = collections.defaultdict(list)
        for r in win:
            by_m[r["data"][:7]].append(r)
        msales = {m: sum(r["sales"] or 0 for r in L) for m, L in sorted(by_m.items())}
        ds = [r["sales"] or 0 for r in win]
        mean = st.mean(ds) if ds else 0
        L, W, H = (num(opt(card, n)) for n in ("Длина упаковки", "Ширина упаковки", "Высота упаковки"))
        vol = round(L * W * H / 1000, 2) if L and W and H else None
        wt = num(opt(card, "Вес с упаковкой (кг)"))
        mount, compat = opt(card, "Тип крепления"), opt(card, "Совместимость")
        apr, jul = msales.get("2026-04", 0), msales.get("2026-07", 0)
        prices = [r["final_price"] for r in win if r.get("final_price")]
        rows.append({
            "rank": rank, "id": p["id"], "name": p["name"], "seller": p.get("seller"), "brand": p.get("brand"),
            "price_jul": p["final_price"], "sales_jul_products": p.get("sales"), "revenue_jul": p.get("revenue"),
            "rating": p.get("rating"), "comments": p.get("comments"), "start": p.get("sku_first_date"),
            "fbs": bool(p.get("is_fbs")), "pics": card.get("media", {}).get("photo_count"), "video": bool(card.get("media", {}).get("has_video")),
            "rich": bool(card.get("has_rich")), "desc_len": len(card.get("description") or ""),
            "mount": mount, "material": opt(card, "Материал изделия"), "compat": compat, "color": opt(card, "Цвет"),
            "kit": opt(card, "Комплектация"), "country": opt(card, "Страна производства"), "warranty": opt(card, "Гарантийный срок"),
            "weight_kg": wt, "pack_l": vol, "pack_cm": f"{L}×{W}×{H}" if vol else None,
            **classify(p["name"], mount, compat, card),
            "m_sales": msales, "daily_mean": round(mean, 1),
            "daily_cv": round(st.pstdev(ds) / mean, 2) if mean else None,
            "zero_days": sum(1 for x in ds if x == 0), "max_day": max(ds) if ds else 0,
            "growth_jul_apr": round(jul / apr, 2) if apr else None,
            "ads_pct": round(sum(1 for r in win if r.get("in_ads")) / len(win) * 100) if win else None,
            "promo_pct": round(sum(1 for r in win if r.get("in_action")) / len(win) * 100) if win else None,
            "oos_days": sum(1 for r in win if not r.get("balance")),
            "price_min": min(prices) if prices else None, "price_med": st.median(prices) if prices else None, "price_max": max(prices) if prices else None,
            "pos_med": st.median([r["search_position_avg"] for r in win if r.get("search_position_avg")] or [0]) or None,
            "reviews_gain": (win[-1]["comments"] - win[0]["comments"]) if win else None,
        })
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    wb = Workbook(); ws = wb.active; ws.title = "Топ-100"
    cols = ["#", "Артикул", "Название", "Продавец", "Цена июль ₽", "Продажи апр", "май", "июн", "июл", "Ср. в день (апр–июл)", "Рост июл/апр",
            "Реклама % дней", "Акции % дней", "Дней без остатка", "Цена мин–макс ₽", "Поз. в поиске", "Рейтинг", "Отзывы", "+отзывов за 4 мес",
            "Старт", "Тип крепления", "Материал", "Совместимость", "Цвет", "Вес, кг", "Упаковка, см", "Упаковка, л", "Комплектация", "Фото", "Видео", "FBS"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496"), Alignment(wrap_text=True)
    for r in rows:
        m = r["m_sales"]
        ws.append([r["rank"], r["id"], r["name"], r["seller"], r["price_jul"], m.get("2026-04"), m.get("2026-05"), m.get("2026-06"), m.get("2026-07"),
                   r["daily_mean"], r["growth_jul_apr"], r["ads_pct"], r["promo_pct"], r["oos_days"],
                   f"{r['price_min']}–{r['price_max']}", r["pos_med"], r["rating"], r["comments"], r["reviews_gain"], r["start"], r["mount"],
                   r["material"], r["compat"], r["color"], r["weight_kg"], r["pack_cm"], r["pack_l"], r["kit"], r["pics"],
                   "да" if r["video"] else "нет", "FBS" if r["fbs"] else "FBO"])
    ws.freeze_panes = "D2"
    for i, w in enumerate([4, 11, 40, 22, 9, 8, 8, 8, 8, 9, 8, 8, 8, 8, 12, 8, 7, 8, 9, 11, 24, 26, 24, 14, 7, 12, 8, 40, 6, 6, 6], 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    wb.save("reports/top100_777_2026-10-05.xlsx")
    print("saved", OUT, "reports/top100_777_2026-10-05.xlsx")


if __name__ == "__main__":
    main()
