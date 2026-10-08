"""Excel-сборка ДНК ниши (7 листов, стили — Приложение А промта).

    python -m src.niche_dna_xlsx --subject 777 --run 2026-10-05
    python -m src.niche_dna_xlsx --all          # все ниши из data/processed/dna_rank_<run>.json (сначала python -m src.dna_rank)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re

from src.niche_dna import MONTH_RU, analyze, fmt_check, hypotheses

GROUP_COLOR = {"КТО": "B4C6E7", "ЧТО": "C5E0B4", "МАТЕРИАЛ": "F8CBAD", "РАЗМЕР": "D5A6BD", "КОНСТРУКЦИЯ": "CDB4DB",
               "ЦВЕТ": "FFE699", "НАЗНАЧЕНИЕ": "A8D8EA", "СТИЛЬ": "FFD3B6", "КУДА": "B4C6E7", "ФУНКЦИЯ": "CDB4DB"}
SEASON_COLOR = {"Всесезон": "E2EFDA", "Весна-Лето": "FFF2CC", "Осень-Зима": "D6E4F0", "Сезонный": "F2F2F2"}
CHECK_COLOR = {"Низкий": "DDEBF7", "Средний": "E2EFDA", "Высокий": "FCE4D6"}
STRAT_COLOR = {"🛡️ Безопасный вход": "E2EFDA", "💰 Маржинальный": "FCE4D6", "🎯 Нишевый": "A8D8EA"}


def length_style(n: int) -> tuple[str, str]:
    if n >= 11:
        return "2E7D32", "Круглогодичный"
    if n >= 8:
        return "66BB6A", "Длинный сезон"
    if n >= 5:
        return "FFC107", "Средний"
    if n >= 3:
        return "FF9800", "Короткий"
    return "E53935", "Узкий"


def lerp(a: str, b: str, t: float) -> str:
    x = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    y = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(p + (q - p) * t):02X}" for p, q in zip(x, y))


def num(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def base_words(cfg: dict) -> str:
    """Человекочитаемый список базовых слов из regex словаря."""
    ws = re.findall(r"[а-яёa-z][а-яёa-z\-]+", cfg["base"].replace("\\w*", "…").replace("\\w", ""))
    return ", ".join(dict.fromkeys(ws))


def write_xlsx(R: dict, H: list[dict], screen: list[dict], sid: int, path: str, rank: dict | None = None) -> None:
    from openpyxl import Workbook
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    def F(c):
        return PatternFill("solid", fgColor=c)

    B = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    lo, hi, cfg = R["lo"], R["hi"], R["cfg"]

    def def_style(cell, v):
        if v >= 70:
            cell.fill, cell.font = F("2E7D32"), Font(bold=True, color="FFFFFF")
        elif v >= 30:
            cell.fill = F("A9D18E")
        elif v < 15:
            cell.fill, cell.font = F("F2F2F2"), Font(color="808080")

    def check_cell(cell, c):
        txt = fmt_check(c, lo, hi)
        cell.value = txt
        cell.fill = F(CHECK_COLOR[txt.split()[0]])

    def heat(ws, row, col0, vals):
        mx = max(vals) or 1
        for i, v in enumerate(vals):
            c = ws.cell(row, col0 + i, round(v))
            t = v / mx
            c.fill = F(lerp("F7FAF7", "2E7D32", t))
            if t > 0.75:
                c.font = Font(bold=True, color="FFFFFF")
            elif t < 0.2:
                c.font = Font(color="808080")

    def widths(ws, w):
        for i, x in enumerate(w, 1):
            ws.column_dimensions[get_column_letter(i)].width = x

    def header(ws, cols):
        ws.append(cols)
        for c in ws[ws.max_row]:
            c.font, c.alignment = B, wrap

    def band(ws, text, color, ncols, size=11):
        ws.append([text])
        r = ws.max_row
        for col in range(1, ncols + 1):
            ws.cell(r, col).fill = F(color)
        ws.cell(r, 1).font = Font(bold=True, size=size)

    gsum = collections.defaultdict(float)
    for v in R["meanings"].values():
        gsum[v["g"]] += v["fy"]
    gorder_demand = sorted(gsum, key=lambda g: -gsum[g])
    wb = Workbook()

    # 1 ── Обзор
    ws = wb.active
    ws.title = "📋 Обзор"
    ws.append([f"🧬 ДНК ниши: {cfg['niche']}"])
    ws["A1"].font = Font(bold=True, size=14)
    for k, v in [
        ("Ниша", f"{cfg['niche']} (subject_id {sid})"),
        ("Период данных", f"{R['months'][0]} … {R['months'][-1]} ({len(R['months'])} мес., Saleflow wb_subject keywords)"
                          + (f"; нет данных: {', '.join(R['missing'])}" if R.get("missing") else "")),
        ("СПП", f"{R['spp']:.1f}% — средневзвешенный spp_avg по 500 карточкам, июль 2026 [оценка]"),
        ("Общий спрос (частота, год)", num(R["total_fy"])),
        ("Смыслов / двоек / троек", f"{len(R['meanings'])} / {len(R['pairs'])} / {len(R['triples'])}"),
        ("Средний чек рынка (до СПП)", f"{num(R['market'])} ₽"),
        ("Пороги чека", f"Низкий < {lo} ₽ · Средний {lo}–{hi} ₽ · Высокий > {hi} ₽ (адаптированы по терцилям цен ниши)"),
        ("Запросов в анализе", f"{len(R['queries'])} из {R['n_raw']} уникальных"),
    ]:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = B
    ws.append([])
    band(ws, "ТОП-3 дефицитных смысла (частота ≥ 1% спроса)", "E2EFDA", 5, 12)
    header(ws, ["Смысл", "Группа", "Дефицит %", "Частота (год)", "Средний чек"])
    for v in sorted([v for v in R["meanings"].values() if v["fy"] >= 0.01 * R["total_fy"]], key=lambda v: -v["def_pct"])[:3]:
        ws.append([v["m"], v["g"], round(v["def_pct"]), round(v["fy"]), ""])
        def_style(ws.cell(ws.max_row, 3), v["def_pct"])
        check_cell(ws.cell(ws.max_row, 5), v["check"])
    ws.append([])
    band(ws, "ТОП-3 двойки (основы) по частоте", "E2EFDA", 5, 12)
    header(ws, ["Основа", "Частота (год)", "Дефицит %", "Средний чек", "Сезонность"])
    for p in R["pairs"][:3]:
        ws.append([" + ".join(p["c"]), round(p["fy"]), round(p["def_pct"]), "", p["type"]])
        def_style(ws.cell(ws.max_row, 3), p["def_pct"])
        check_cell(ws.cell(ws.max_row, 4), p["check"])
        ws.cell(ws.max_row, 5).fill = F(SEASON_COLOR.get(p["type"], "FFFFFF"))
    me = next((n for n in (rank or {}).get("niches", []) if n["id"] == sid), None)
    if me:
        ws.append([])
        band(ws, "💵 Экономика при медианной цене ниши (src/unit_econ.py)", "FCE4D6", 5, 12)
        for k, v in [
            ("Комиссия FBS кабинета", f"{me['com']}% — WB API /api/v1/tariffs/commission, kgvpMarketplace [факт]"),
            ("Медианная цена", f"{num(me['price_b'])} ₽ покупателя · {num(me['price_s'])} ₽ до СПП (СПП {me['spp']}%) [факт]"),
            ("Закупка по правилу ¥×78", f"¥ {me['yuan78']} → себестоимость {num(me['cost'])} ₽ (¥ × 17) [допущение]"),
            ("Чистая маржа / ROI", f"{me['margin']}% / {me['roi']}% до СПП · {me['margin_b']}% от цены покупателя [оценка]"),
            ("¥ max для 18% / 60%", f"¥ {me['yuan_max']}"),
            ("Вердикт по фильтрам", "✅ проходит все" if not me["fails"] and not me["unknown"] else
             "❌ " + "; ".join(me["fails"] + [u + " — нет данных" for u in me["unknown"]])),
        ]:
            ws.append([k, v])
            ws.cell(ws.max_row, 1).font = B
        ws.append([])
        c = me["complaint"]
        band(ws, f"🗣 Жалобы лидеров: {c['total_neg']} негативных отзывов (≤ 3★ с текстом, 365 дн.), {c['files']} карточки", "FFF2CC", 5, 12)
        header(ws, ["Тема", "Доля негатива %", "Закрываемая (≥ 12%)?"])
        for t, sh in c["themes"]:
            prod = t not in ("упаковка / доставка", "некомплект / не тот товар")
            ws.append([t, sh, "✅" if sh >= 12 and prod and c["total_neg"] >= 30 else ("— (проблема WB)" if not prod else "—")])
        for q in c["quotes"]:
            ws.append([f"«{q[:200]}»"])
            ws.cell(ws.max_row, 1).alignment = wrap
        ws.append([])
        band(ws, "📦 Габариты / вес", "DDEBF7", 5, 12)
        ws.append(["Объём", f"{me['vol']} л — {me['vol_src']}" if me["vol"] is not None else f"— ({me['vol_src']}; в экономике 0.5 л [допущение])"])
        ws.cell(ws.max_row, 1).font = B
    if rank:
        screen = [{"id": n["id"], "name": n["name"], "spp": n["spp"], "price": n["price_b"], "seller_price": n["price_s"],
                   "t1": n["t1"], "t10": n["t10"], "sellers": n["sellers"], "med_s": n["med_s"], "newsh": n["newsh"],
                   "cn": n["cn"], "margin": n["margin"], "rank": i} for i, n in enumerate(rank["niches"], 1)]
    if screen:
        ws.append([])
        band(ws, f"Почему эта ниша: {len(screen)} стабильных ниш 7/7 (июль 2026, top-100 карточек), место по фильтрам", "FFF2CC", 12, 12)
        header(ws, ["Ниша", "СПП %", "Мед. цена покупателя ₽", "Цена до СПП ₽", "Top-1 продавец %", "Top-10 %",
                    "Продавцов в top-100", "Мед. продаж карточки, шт/мес", "Выручка новинок (с окт 25) %", "Китай %",
                    "Маржа при мед. цене %", "Ранг"])
        for s in screen:
            ws.append([s["name"], round(s["spp"]), round(s["price"]), round(s["seller_price"]), round(s["t1"], 1),
                       round(s["t10"], 1), s["sellers"], round(s["med_s"]), round(s["newsh"], 1), round(s["cn"]),
                       s.get("margin", "—"), s.get("rank", "")])
            if s["id"] == sid:
                for c in ws[ws.max_row]:
                    c.fill, c.font = F("E2EFDA"), B
        ws.append(["Доли top-1/top-10 — внутри top-100 карточек (верхняя граница). Маржа — src/unit_econ.py при цене до СПП, "
                   "комиссия FBS кабинета, себестоимость = цена до СПП / 78 × 17 (правило ¥×78), ДРР 15%, упаковка 50 ₽ [оценка]. "
                   "Место — по числу проваленных фильтров (reports/dna_all_2026-10-05.xlsx)."])
    widths(ws, [34, 62, 14, 14, 12, 10, 12, 14, 14, 10, 12, 8])

    # 2 ── Спрос
    ws = wb.create_sheet("📊 Спрос")
    head = ["№", "Группа", "Смысл", "Частота (год)", "Дефицит % (год)", "Средний чек", "Сезонность", "Длина",
            "Лучший вход", "Пик месяцы"] + MONTH_RU
    header(ws, head)
    n = 0
    for g in gorder_demand:
        band(ws, f"▌ {g} — {num(gsum[g])}", GROUP_COLOR.get(g, "DDDDDD"), len(head))
        for v in sorted([v for v in R["meanings"].values() if v["g"] == g], key=lambda v: -v["fy"]):
            n += 1
            ws.append([n, g, v["m"], round(v["fy"]), round(v["def_pct"]), "", v["type"], "", v["entry"], v["peaks"]])
            r = ws.max_row
            def_style(ws.cell(r, 5), v["def_pct"])
            check_cell(ws.cell(r, 6), v["check"])
            ws.cell(r, 7).fill = F(SEASON_COLOR.get(v["type"], "FFFFFF"))
            col, lbl = length_style(v["length"])
            ws.cell(r, 8).value, ws.cell(r, 8).fill = f"{v['length']} · {lbl}", F(col)
            ws.cell(r, 9).fill, ws.cell(r, 9).font = F("1B5E20"), Font(bold=True, color="FFFFFF")
            heat(ws, r, 11, v["fm"])
    ws.freeze_panes = "D2"
    widths(ws, [5, 13, 28, 13, 11, 18, 12, 20, 11, 18] + [8] * 12)

    # 3 ── Двойки
    ws = wb.create_sheet("🍕 Двойки")
    header(ws, ["№", "Основа", "Частота (год)", "Артикулы (среднее)", "Дефицит %", "Средний чек",
                "Ценовое распределение (низ / сред / выс)", "Сезонность", "Не хватает групп"])
    for i, p in enumerate(R["pairs"], 1):
        miss = ", ".join(f"{g} ({R['grank'][g]})" for g in sorted(p["missing"], key=lambda g: R["grank"][g]))
        ws.append([i, " + ".join(p["c"]), round(p["fy"]), round(p["res"]), round(p["def_pct"]), "",
                   " / ".join(f"{x:.0f}%" for x in p["dist"]), p["type"], miss])
        r = ws.max_row
        def_style(ws.cell(r, 5), p["def_pct"])
        check_cell(ws.cell(r, 6), p["check"])
        if max(p["dist"]) > 50:
            ws.cell(r, 7).font = B
        ws.cell(r, 8).fill = F(SEASON_COLOR.get(p["type"], "FFFFFF"))
    ws.freeze_panes = "C2"
    widths(ws, [5, 46, 13, 13, 11, 18, 22, 12, 70])

    # 4 ── Тройки
    ws = wb.create_sheet("🍕 Тройки")
    header(ws, ["№", "Родитель → +элемент", "Частота (год)", "% от родителя", "Артикулы (среднее)", "Дефицит %",
                "Средний чек", "Не хватает"])
    for i, t in enumerate(R["triples"], 1):
        miss = ", ".join(f"{g} ({R['grank'][g]})" for g in sorted(t["missing"], key=lambda g: R["grank"][g]))
        ws.append([i, "", round(t["fy"]), round(t["pct_parent"], 1), round(t["res"]), round(t["def_pct"]), "", miss])
        r = ws.max_row
        ws.cell(r, 2).value = CellRichText(TextBlock(InlineFont(b=True), " + ".join(t["parent"])), f" → +{t['new']}")
        def_style(ws.cell(r, 6), t["def_pct"])
        check_cell(ws.cell(r, 7), t["check"])
    ws.freeze_panes = "C2"
    widths(ws, [5, 60, 13, 12, 13, 11, 18, 70])

    # 5 ── Начинки
    ws = wb.create_sheet("🧀 Начинки")
    head = ["№", "Группа", "Начинка", "Частота (год)", "Дефицит %", "Средний чек", "Δ чек", "Уник %", "Сочетается с", "SEO-ядро"]
    header(ws, head)
    n = 0
    for g in gorder_demand:
        band(ws, f"▌ {g}", GROUP_COLOR.get(g, "DDDDDD"), len(head))
        for v in sorted([v for v in R["meanings"].values() if v["g"] == g], key=lambda v: -v["fy"]):
            n += 1
            label = v["m"] + (f" ⛔ {cfg['blocked'][v['m']]}" if v["m"] in cfg["blocked"] else "")
            seo = "; ".join(f"{q} ({num(f)})" for q, f in v["seo"])
            ws.append([n, g, label, round(v["fy"]), round(v["def_pct"]), "", f"{v['dcheck']:+,.0f} ₽".replace(",", " "),
                       round(v["uniq"]), "; ".join(v["with"]), seo])
            r = ws.max_row
            def_style(ws.cell(r, 5), v["def_pct"])
            check_cell(ws.cell(r, 6), v["check"])
            d, u = v["dcheck"], v["uniq"]
            ws.cell(r, 7).font = (Font(bold=True, color="2E7D32") if d > 500 else Font(color="2E7D32") if d >= 0
                                  else Font(color="808080") if d >= -500 else Font(bold=True, color="C00000"))
            ws.cell(r, 8).font = (Font(bold=True, color="2E7D32") if u >= 80 else Font(color="808080") if u >= 50
                                  else Font(color="BFBFBF"))
            ws.cell(r, 10).alignment = wrap
    ws.freeze_panes = "D2"
    widths(ws, [5, 13, 34, 13, 10, 18, 11, 8, 48, 72])

    # 6 ── Гипотезы
    ws = wb.create_sheet("🎯 Гипотезы")
    head = ["№", "Стратегия", "Товар", "Основа", "Начинки", "Частота (год)", "Дефицит %", "Средний чек", "Сезонность",
            "SEO-ядро", "Риски", "Маржа % (до СПП)", "¥ max (18%/60%)"]
    hx = {(h["s"], h["name"]): h for h in (rank or {}).get("hyps", []) if h["sid"] == sid}
    header(ws, head)
    n = 0
    for s, col in STRAT_COLOR.items():
        band(ws, s, col, len(head), 12)
        for h in [h for h in H if h["s"] == s]:
            n += 1
            e = hx.get((h["s"], h["name"]), {})
            ws.append([n, s, h["name"], f"{h['base']} ({h['kind']})", h["fills"], round(h["fy"]), round(h["def_pct"]), "",
                       f"{h['type']}, {h['length']} мес", "; ".join(f"{q} ({num(f)})" for q, f in h["seo"]), h["risk"],
                       e.get("margin", "—"), e.get("yuan_max", "—")])
            if e:
                ws.cell(ws.max_row, 12).font = Font(bold=True, color="2E7D32" if e["margin"] >= 18 else "C00000")
            r = ws.max_row
            def_style(ws.cell(r, 7), h["def_pct"])
            check_cell(ws.cell(r, 8), h["check"])
            for c in (3, 4, 5, 10, 11):
                ws.cell(r, c).alignment = wrap
    widths(ws, [5, 18, 40, 40, 42, 13, 10, 18, 18, 60, 60, 11, 11])

    # 7 ── Легенда
    ws = wb.create_sheet("📖 Легенда")
    L = R["log"]
    unk = sum(q["fy"] for q in R["queries"] if q["unk"]) / R["total_fy"] * 100
    lines = [
        "📖 Метрики",
        "Частота (год) = сумма помесячной «Частоты WB» (Saleflow wb_count) за 12 мес.; «Частоты 365» в выгрузке нет.",
        "Результаты WB = Saleflow count (товаров в выдаче). Дефицит = Частота WB / Результаты WB (медиана по месяцам).",
        "Дефицит % = дефицит / 95-й перцентиль дефицита среди смыслов (двоек, троек) × 100, обрезано на 100 — защита от выбросов малых запросов.",
        f"Средний чек: выручки и продаж по запросу в выгрузке keywords нет. Чек запроса = медиана цены карточек предмета, "
        f"в названии которых есть все смыслы запроса (группы ЧТО / КОНСТРУКЦИЯ / ФУНКЦИЯ / МАТЕРИАЛ); 500 карточек за июль 2026; "
        f"цена до СПП = цена покупателя / (1 − {R['spp']:.1f}%). Если совпадений < 3 — убирается самый редкий смысл, в крайнем случае берётся медиана рынка.",
        "Δ чек = чек начинки − средний чек всех запросов. Уник % = доля запросов с этой начинкой, где она единственный смысл.",
        f"Сезонность: CV месячной частоты, порог {R['thr_cv']} (ниша {'резко' if R['sharp'] else 'не резко'} сезонная); "
        f"Мар–Авг vs Сен–Фев, коэффициент {R['k']}. Длина — месяцев > 30% пика; пик-месяцы — > 130% средней.",
        "Лучший вход: «Любой», если CV < порога и пик < 150% средней; иначе месяц начала подъёма перед пиком минус 2 месяца.",
        "Ценовое распределение двойки: доли её запросов в сегментах низ / сред / выс. «Не хватает»: непокрытые группы; ранг 1 — группа с наибольшей средней частотой начинок.",
        "🔧 Как пользоваться",
        "1) Выберите основу на листах «Двойки»/«Тройки». 2) Для каждой группы из «Не хватает» возьмите начинку на листе «Начинки»: "
        "по частоте (безопасно), по Δ чек (маржа) или по дефициту (ниша). 3) Название и SEO соберите из столбцов «SEO-ядро». 4) Сверьте с листом «Гипотезы».",
        "🧹 Очистка данных",
        f"Уникальных запросов за 12 мес.: {R['n_raw']}. Отсечено: " + "; ".join(f"{k} — {v}" for k, v in L.items())
        + f". В анализе: {len(R['queries'])}.",
        f"Базовые слова: {base_words(cfg)}; запросы только из базового слова исключены.",
        f"Запросы с нераспознанными словами дают {unk:.1f}% частоты (порог промта — 5%)"
        + ("." if unk <= 5 else " — длинный хвост редких слов, принят с оговоркой: доли смыслов занижены примерно на эту величину."),
        "⚠️ Ограничения",
        "Saleflow keywords отдаёт до 5 000 запросов в месяц, включая запросы, где карточки предмета лишь показываются; "
        "в анализ берутся запросы, по которым у предмета ≥ 20 карточек хотя бы в одном месяце.",
        "Месяцы Янв…Дек собраны из окна 2025-09 … 2026-08 (сентябрь–декабрь — 2025 год, январь–август — 2026)."
        + (f" Нет данных за {', '.join(R['missing'])} (Saleflow timeout) — в сезонности = 0." if R.get("missing") else "")
        + (f" {me['note']}" if me and me.get("note") else ""),
        ("⛔ " + "; ".join(f"«{m}» — {why}" for m, why in cfg["blocked"].items()) + ". Показаны в спросе, исключены из гипотез.")
        if cfg["blocked"] else "⛔ Запрещённых смыслов в словаре ниши нет.",
        "Спрос ≠ продажи: частота — интерес покупателей; дефицит по count приблизителен (±).",
    ]
    for line in lines:
        ws.append([line])
        if line[:2] in ("📖", "🔧", "🧹", "⚠️"):
            ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        ws.cell(ws.max_row, 1).alignment = wrap
    ws.column_dimensions["A"].width = 150
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", type=int, default=777)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--run", default="2026-10-05")
    ap.add_argument("--screen", default="data/processed/dna_screen_2026-10-05.json")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rf = f"data/processed/dna_rank_{a.run}.json"
    rank = json.load(open(rf, encoding="utf-8")) if os.path.exists(rf) else None
    screen = json.load(open(a.screen, encoding="utf-8")) if os.path.exists(a.screen) else []
    sids = [n["id"] for n in rank["niches"]] if a.all and rank else [a.subject]
    for sid in sids:
        R = analyze(a.run, sid)
        H = hypotheses(R)
        out = a.out if a.out and not a.all else f"reports/dna_{sid}_{a.run}.xlsx"
        write_xlsx(R, H, screen, sid, out, rank)
        print("saved", out)
    if a.all:
        return
    for h in H:
        print(f"{h['s']} | {h['name']} | {h['base']} | {h['fills']} | fy {h['fy']:.0f} | def {h['def_pct']:.0f} | "
              f"чек {h['check']:.0f} | {h['type']} {h['length']} | {h['risk']}")


if __name__ == "__main__":
    main()
