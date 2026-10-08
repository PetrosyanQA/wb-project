"""Сезонный отбор ниш WB (ТЗ «Предметы | реальная выручка | скоринг 7/7»).

Источник — помесячные снимки Saleflow `wb_subjects_list` (окно 30 дней до `date`),
сохранённые в data/raw/saleflow/<run>/season/<YYYY-MM>/page_*.json.
Реальная выручка = revenue (сумма заказов) × purchase_after_return / 100
(= поле revenue_purchase_after_return).

    python -m src.season_niches prefilter --run 2026-10-05 --start 2025-12 --base 2025-11
    python -m src.season_niches growth    --run 2026-10-05 --start 2025-12 --base 2025-11
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

MIN_REAL = 10_000_000
MIN_GROWTH = 20.0
FASHION_MIN_BUYOUT = 65.0

DROP_CATS = {
    # ТЗ, шаг 2
    "Красота": "FMCG", "Здоровье": "FMCG", "Бытовая химия": "FMCG", "Продукты": "FMCG",
    "Детское питание": "FMCG", "Спортивное питание и косметика": "FMCG",
    "Бытовая техника": "электроника", "Крупная бытовая техника": "электроника",
    "Техника для кухни": "электроника",
    "Садовая техника": "мотор/аккумулятор", "Электроинструмент и оборудование": "мотор/аккумулятор",
    "Телевизоры и аудиотехника": "электроника", "Ноутбуки и компьютеры": "электроника",
    "Сетевое оборудование": "электроника",
    "Электротранспорт": "аккумулятор", "Аккумуляторы для ТС": "аккумулятор",
    "Смартфоны и гаджеты": "электроника", "Игровые консоли и игры": "электроника",
    "Умный дом и безопасность": "электроника", "Фото и Видеотехника": "электроника",
    "Освещение": "розетка/провод", "Электрика": "розетка/провод",
    "Масла и технические жидкости": "авто-специфика",
    "Ювелирные украшения": "КИЗ / маркировка",
    # аналоги по смыслу ТЗ (в выгрузке WB названы иначе) — [допущение]
    "Климатическая техника": "электроника (аналог)",
    "Техника для красоты и здоровья": "электроника (аналог)",
    "Автоэлектроника": "электроника (аналог)",
    "Оргтехника": "электроника (аналог)",
    "Периферия и аксессуары": "электроника (аналог)",
    "Ветаптека": "FMCG (аналог: лекарства)",
    "Автохимия и автокосметика": "FMCG (аналог: химия)",
    "Товары для курения": "акциз / вейпы (аналог)",
    "Транспортные средства": "мотор (аналог)",
}

FASHION = {"Одежда", "Обувь", "Спортивная одежда", "Спортивная обувь", "Белье",
           "Головные уборы", "Аксессуары для волос", "Одежда для малышей",
           "Аксессуары для малышей", "Белье для малышей"}

KEYWORDS = {
    "мотор/электро": r"электрическ|электро|аккумулятор|генератор|насос|компрессор",
    "транспорт": r"самокаты|велосипеды|ролики|роликовые кроссовки",
    "мото": r"мотошлем|мотобот|запчасти для мототехник",
    "дети (серт.)": r"коляск|автокресл|электро-качел",
    "химия": r"средства защиты растен|средства от блох",
    "стройка (серт.)": r"лестницы строительн",
    "запчасти БТ": r"запчасти для кондиционер|запчасти для холодильник",
}
# велозапчасти не трогаем (ТЗ): «Велосипедные …» содержат «велосипед», но не «велосипеды»


def load_month(run: str, month: str) -> dict[int, dict]:
    out = {}
    for f in glob.glob(f"data/raw/saleflow/{run}/season/{month}/*.json"):
        for r in json.load(open(f, encoding="utf-8"))["data"]:
            out[r["id"]] = r
    return out


def real(r: dict | None) -> float | None:
    if r is None:
        return None
    return r["revenue"] * r["purchase_after_return"] / 100


def split(name: str) -> tuple[str, str]:
    cat, _, subj = name.partition(" / ")
    return cat, subj


def prefilter(run: str, start: str) -> tuple[list[int], dict]:
    rows = load_month(run, start)
    log = {"loaded": len(rows), "step1_real": 0, "cats": {}, "fashion_drop": 0, "kw": {}}
    keep = []
    for sid, r in rows.items():
        if real(r) < MIN_REAL:
            continue
        log["step1_real"] += 1
        cat, subj = split(r["name"])
        if cat in DROP_CATS:
            log["cats"][DROP_CATS[cat]] = log["cats"].get(DROP_CATS[cat], 0) + 1
            continue
        if cat in FASHION and r["purchase_after_return"] < FASHION_MIN_BUYOUT:
            log["fashion_drop"] += 1
            continue
        hit = next((g for g, rx in KEYWORDS.items() if re.search(rx, subj.lower())), None)
        if hit:
            log["kw"][hit] = log["kw"].get(hit, 0) + 1
            continue
        keep.append(sid)
    return keep, log


# ── шаг 5: принципиальная классификация (файл data/processed/season_classification_*.txt) ──
EXPL = {
    # документы
    "el": "Электропитание/аккумулятор/вилка → обязательная сертификация",
    "motor": "Мотор/насос → обязательная сертификация",
    "pyro": "Пиротехника → обязательная сертификация",
    "weapon": "Оружие (пневматика) → сертификация, ограничения оборота",
    "tire": "Шины → обязательная сертификация ТР ТС 018",
    "chz": "Бельё постельное/столовое/туалетное/кухонное → Честный знак обязателен",
    "perfume": "Ароматизаторы для дома: химия + Честный знак (парфюмерия)",
    "food": "Контакт с пищей/водой → декларация ТР ТС 005",
    "water": "Контакт с питьевой водой → декларация/СГР",
    "kids": "Детский товар/игрушка → ТР ТС 008/007, декларация или сертификат",
    "kidsmix": "Игрушка; часть моделей с батарейкой → ТР ТС 008, проверить модель",
    "baby": "Для детей до 3 лет → ТР ТС 007, декларация/сертификат",
    "school": "Школьно-письменные принадлежности → ТР ТС 007",
    "elY": "Электрика без мотора (LED, низковольтное) → декларация ТР ТС 004/020",
    "elmix": "Смесь пассивных и электронных моделей → декларация для электронных",
    "watch": "Кварцевые часы на батарейке → вероятно декларация, проверить",
    "cut": "Режущие/колющие части → декларация, риск «холодное оружие»",
    "chem": "Химия/косметика/составы → декларация (ТР ТС 009 или ГОСТ)",
    "furn": "Мебель → декларация ТР ТС 025",
    "build": "Стройматериал/состав → декларация, пожарные требования",
    "lp": "Одежда/кожгалантерея/аксессуар из текстиля → ТР ТС 017 декларация",
    "lpchz": "Бельё/чулочно-носочные/одежда → ТР ТС 017 + вероятен Честный знак",
    "auto18": "Автокомпонент → ТР ТС 018 (сертификат)",
    "autokit": "Набор может включать огнетушитель/аптечку → сертификаты на состав",
    "helmet": "Защитная экипировка → часто декларация",
    "body": "Контакт с телом/гигиена → декларация",
    "incense": "Горючие ароматические изделия; обязательного ТР не найдено — проверить",
    "giftbox": "Зависит от наполнения: пустая коробка — отказное, еда/косметика — декларация",
    "text": "Текстиль без пищевого контакта → по ТЗ отказное (ТР ТС 017 может потребовать декларацию)",
    "dec": "Декор/сувенир без электрики и пищевого контакта → отказное письмо",
    "plast": "Пластик/металл бытовой, без пищи и питания → отказное письмо",
    "book": "Печатная продукция → отказное письмо",
    "sport": "Спортинвентарь без мотора → вероятно отказное",
    "fish": "Рыболовные снасти без питания → отказное",
    "pet": "Зоотовар без химии и пищи → отказное",
    "auto": "Автоаксессуар (не запчасть, без питания) → отказное",
    "acc": "Аксессуар/бижутерия без драгметаллов → отказное",
    "tool": "Ручной инструмент без лезвий и питания → отказное",
    "stat": "Канцелярия не для школы → отказное",
    "craft": "Материалы для творчества без химии → отказное",
    "music": "Акустический инструмент без электрики → отказное",
    "optic": "Оптика без питания → вероятно отказное",
    "adult": "Товар 18+ без электроники и химии → отказное",
    # габариты (по упаковке)
    "small": "Мелкий предмет: пакет/коробка ≤ 30 см, < 1 кг",
    "box": "Коробка до 60–80 см, до 10 кг",
    "soft": "Мягкий/складной: едет в пакете или чехле ≤ 60–90 см",
    "long": "Длинная упаковка 120–200 см",
    "big": "Упаковка > 200 см или > 25 кг",
    "furn": "Мебель в коробке 100–150 см, 15–30 кг",
    "chair": "Кресло в коробке ~70×65×35 см, 15–20 кг",
    "heavy": "Компактный, но тяжёлый (5–25 кг)",
    "var": "Сильно зависит от модели: от МГТ до СГТ",
    # ассортимент
    "design": "Выбор глазами: десятки принтов/дизайнов/цветов",
    "design2": "Много форм, материалов и дизайнов (≥ 10)",
    "func": "Вариации ограничены функцией: 5–15 типов",
    "brand": "Выбирают по характеристикам/бренду, визуал вторичен",
    "spec": "Commodity: выбирают по размеру/спецификации",
}
CONF = {"H": "Выс", "M": "Сред", "L": "Низ"}
DOC = {"G": "🟢", "Y": "🟡", "R": "🔴"}
DIM = {"M": "МГТ", "S": "СГТ", "K": "КГТ"}


def load_class(path: str) -> dict[int, dict]:
    out = {}
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        c = {"doc": p[1], "doc_c": p[2], "doc_k": p[3]}
        if len(p) >= 10:
            c.update(dim=p[4], dim_c=p[5], dim_k=p[6], asr=p[7], asr_c=p[8], asr_k=p[9],
                     avail=p[10] if len(p) > 10 else "G")
        out[int(p[0])] = c
    return out


def season(vals: list[float], labels: list[str], thr: float = 0.30) -> dict:
    """Непрерывный отрезок вокруг пика, где выручка ≥ thr × пик."""
    if not vals or max(vals) <= 0:
        return {"len": 0, "start": None, "end": None, "peak": None, "sum": 0.0}
    p = max(range(len(vals)), key=lambda i: vals[i])
    lim = vals[p] * thr
    a = b = p
    while a - 1 >= 0 and vals[a - 1] >= lim:
        a -= 1
    while b + 1 < len(vals) and vals[b + 1] >= lim:
        b += 1
    return {"len": b - a + 1, "start": labels[a], "end": labels[b], "peak": labels[p],
            "sum": sum(vals[a:b + 1])}


MONTHS_RU = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн", 7: "июл",
             8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"}


def mlabel(m: str) -> str:
    y, mm = m.split("-")
    return f"{MONTHS_RU[int(mm)]} {y[2:]}"


def build(run: str, start: str, base: str, months: list[str], season_last: str,
          target: float, class_path: str, out_xlsx: str) -> dict:
    data = {m: load_month(run, m) for m in months}
    g = json.load(open(f"data/raw/saleflow/{run}/season/growth_ids.json", encoding="utf-8"))
    cls = load_class(class_path)
    win = months[months.index(start): months.index(season_last) + 1]
    rows, removed = [], []
    for sid in g["ids"] + g["missing_base"]:
        r0 = data[start][sid]
        cat, subj = split(r0["name"])
        buy = r0["purchase_after_return"]
        rv = {m: real(data[m].get(sid)) for m in months}
        rb = rv[base]
        growth = (rv[start] - rb) / rb * 100 if rb else None
        s = season([rv[m] or 0 for m in win], [mlabel(m) for m in win])
        c = cls[sid]
        row = {"id": sid, "subj": subj, "cat": cat, "fashion": cat in FASHION, "growth": growth,
               "rev": rv, "season": s, "buyout": buy,
               "price": r0.get("median_price_final_with_sells") or r0.get("median_price_final"),
               **c}
        reason = None
        if c["doc"] == "R":
            reason = "🔴 Документы: " + EXPL[c["doc_k"]]
        elif c.get("avail") == "R":
            reason = "🔴 Доступность"
        elif c.get("dim") == "K":
            reason = "КГТ: " + EXPL[c["dim_k"]]
        if reason:
            row["reason"] = reason
            removed.append(row)
            continue
        share = target / s["sum"] * 100 if s["sum"] else None
        row["share"] = share
        n_win = len(win)
        g_len = 6 if n_win >= 6 else n_win
        row["len_flag"] = "G" if s["len"] >= g_len else ("Y" if s["len"] >= max(g_len - 2, 1) and s["len"] >= 4 else "R")
        row["share_flag"] = "G" if share is not None and share <= 5 else ("Y" if share is not None and share <= 10 else "R")
        row["buy_flag"] = "G" if buy >= 80 else ("Y" if buy >= 60 else "R")
        crit = {"Док": c["doc"] == "G", "Дост": c["avail"] == "G", "Габ": c["dim"] == "M",
                "Асс": c["asr"] == "G", "Сез": row["len_flag"] == "G", "Доля": row["share_flag"] == "G",
                "Вык": row["buy_flag"] == "G"}
        row["score"] = sum(crit.values())
        row["miss"] = [k for k, v in crit.items() if not v]
        rows.append(row)
    rows.sort(key=lambda x: (-x["score"], -(x["growth"] if x["growth"] is not None else 1e9)))
    write_xlsx(rows, removed, months, win, season_last, start, base, target, out_xlsx)
    return {"rows": rows, "removed": removed, "win": win}


def write_xlsx(rows, removed, months, win, season_last, start, base, target, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    GREEN, YEL, RED, BLUE = "C6EFCE", "FFEB9C", "FFC7CE", "DDEBF7"
    fill = {c: PatternFill("solid", fgColor=c) for c in (GREEN, YEL, RED, BLUE)}
    flag_fill = {"G": fill[GREEN], "Y": fill[YEL], "R": fill[RED]}
    conf_fill = {"H": fill[GREEN], "M": fill[YEL], "L": fill[RED]}
    emo = {"G": "🟢", "Y": "🟡", "R": "🔴"}

    wb = Workbook()
    ws = wb.active
    ws.title = "Ниши"
    mcols = [mlabel(m) + (" ⚠️неполн." if m > season_last else "") + ", млн ₽" for m in months]
    head = (["Ниша", "Категория", "Прирост %"] + mcols +
            ["Выр.СЕЗОН, млн ₽", "Сезон период", "Сезон мес.", "Пиковый мес.",
             "Выкуп % (текущий, Saleflow)", "Доля от цели %",
             "Документы", "Док.уверен.", "Док.пояснение", "Доступность",
             "Габариты", "Габ.уверен.", "Габ.пояснение",
             "Ассортимент", "Асс.уверен.", "Асс.пояснение",
             "Длина сезона", "Размер ниши", "% выкупа", "СКОР",
             "Не зелёные", "Мед. цена продаж (дек), ₽", "Коридор 1 400–2 600 ₽", "Карго без ГТД", "subject_id"])
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        s = r["season"]
        vals = ([("👗 " if r["fashion"] else "") + r["subj"], r["cat"],
                 round(r["growth"], 1) if r["growth"] is not None else "нов."] +
                [round(r["rev"][m] / 1e6, 1) if r["rev"][m] is not None else None for m in months] +
                [round(s["sum"] / 1e6, 1), f'{s["start"]}→{s["end"]}', s["len"], s["peak"],
                 r["buyout"], round(r["share"], 2) if r["share"] is not None else None,
                 emo[r["doc"]], CONF[r["doc_c"]], EXPL[r["doc_k"]], emo[r["avail"]],
                 DIM[r["dim"]], CONF[r["dim_c"]], EXPL[r["dim_k"]],
                 emo[r["asr"]], CONF[r["asr_c"]], EXPL[r["asr_k"]],
                 emo[r["len_flag"]], emo[r["share_flag"]], emo[r["buy_flag"]], f'{r["score"]}/7',
                 " ".join(f"[-{k}]" for k in r["miss"]), r["price"],
                 "✅" if r["price"] and 1400 <= r["price"] <= 2600 else "—",
                 "⚠️ нужна декларация" if r["doc"] == "Y" else "ок", r["id"]])
        ws.append(vals)
        i = ws.max_row
        col = {h: k + 1 for k, h in enumerate(head)}
        ws.cell(i, col["Выр.СЕЗОН, млн ₽"]).fill = fill[BLUE]
        L = r["season"]["len"]
        ws.cell(i, col["Сезон мес."]).fill = flag_fill[r["len_flag"]]
        ws.cell(i, col["Выкуп % (текущий, Saleflow)"]).fill = flag_fill[r["buy_flag"]]
        ws.cell(i, col["Доля от цели %"]).fill = flag_fill[r["share_flag"]]
        for k, ck in (("Документы", "doc"), ("Ассортимент", "asr"), ("Доступность", "avail")):
            ws.cell(i, col[k]).fill = flag_fill[r[ck]]
        ws.cell(i, col["Габариты"]).fill = fill[GREEN] if r["dim"] == "M" else fill[YEL]
        for k, ck in (("Док.уверен.", "doc_c"), ("Габ.уверен.", "dim_c"), ("Асс.уверен.", "asr_c")):
            ws.cell(i, col[k]).fill = conf_fill[r[ck]]
        for k in ("Длина сезона", "Размер ниши", "% выкупа"):
            pass
        for k in ("Док.пояснение", "Габ.пояснение", "Асс.пояснение"):
            ws.cell(i, col[k]).font = Font(size=8)
            ws.cell(i, col[k]).alignment = Alignment(wrap_text=True, vertical="top")
        sc = ws.cell(i, col["СКОР"])
        sc.font = Font(bold=True)
        sc.fill = fill[GREEN] if r["score"] >= 6 else (fill[YEL] if r["score"] == 5 else PatternFill())
    widths = {"Ниша": 30, "Категория": 22, "Док.пояснение": 34, "Габ.пояснение": 28, "Асс.пояснение": 28,
              "Сезон период": 14, "Не зелёные": 22}
    for k, h in enumerate(head, 1):
        ws.column_dimensions[get_column_letter(k)].width = widths.get(h, 11)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{ws.max_row}"
    ws.freeze_panes = "B2"

    # удалённые на шаге 6
    wr = wb.create_sheet("Удалённые (шаг 6)")
    wr.append(["Ниша", "Категория", "Прирост %", f"Выручка {mlabel(start)}, млн ₽", "Причина", "Уверенность", "subject_id"])
    for c in wr[1]:
        c.font = Font(bold=True)
    for r in sorted(removed, key=lambda x: x["reason"]):
        conf = CONF[r["doc_c"]] if r["doc"] == "R" else CONF.get(r.get("dim_c", "M"))
        wr.append([r["subj"], r["cat"], round(r["growth"], 1) if r["growth"] is not None else "нов.",
                   round(r["rev"][start] / 1e6, 1), r["reason"], conf, r["id"]])
    for k, w in enumerate([30, 24, 10, 14, 60, 12, 10], 1):
        wr.column_dimensions[get_column_letter(k)].width = w
    wr.auto_filter.ref = f"A1:G{wr.max_row}"
    wr.freeze_panes = "B2"

    gl = wb.create_sheet("Глоссарий")
    G = glossary(win, season_last, start, base, target)
    for line in G:
        gl.append([line])
        if line.startswith(("⚙️", "🔬", "📋", "🏆", "📊", "🚫", "⚠️")):
            gl.cell(gl.max_row, 1).font = Font(bold=True, size=12)
    gl.column_dimensions["A"].width = 140
    for row in gl.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)


def glossary(win, season_last, start, base, target) -> list[str]:
    cats = sorted(set(DROP_CATS.items()), key=lambda x: x[1])
    return [
        "⚙️ Параметры анализа",
        f"Месяц старта: {mlabel(start)}; базовый месяц: {mlabel(base)}. Прирост % = (Реальная_старт − Реальная_база) / Реальная_база × 100.",
        f"Цель по выручке за сезон: {target:,.0f} ₽ (пользователь не назвал цель — принято значение по умолчанию; меняется ключом --target).".replace(",", " "),
        "Реальная выручка = Сумма заказов × % выкупа с учётом возвратов / 100 (Saleflow: revenue × purchase_after_return = revenue_purchase_after_return).",
        "Источник: Saleflow wb_subjects_list, снимок за 30 дней до последнего дня месяца (≈ календарный месяц; сверено с wb_subject trends: ножи туристические, дек 25 — 247 vs 253 млн ₽).",
        "Фильтр шага 1: реальная выручка в месяце старта ≥ 10 000 000 ₽ и прирост ≥ 20%. Предметы без данных за базовый месяц помечены «нов.».",
        f"Окно сезона: {win[0]} … {win[-1]} ({len(win)} мес.). Сезон = непрерывный отрезок вокруг пикового месяца, где реальная выручка ≥ 30% от пика.",
        "Доля от цели = Цель / Выручка сезона × 100%. Ориентир: ≤ 5% комфортно, 5–10% реально, > 10% сложно.",
        "⚠️ Ограничения данных",
        "% выкупа в Saleflow — одно текущее значение на предмет, не помесячное (проверено: у всех 730 предметов одинаков во всех 12 снимках). Поэтому вместо 12 колонок выкупа — одна.",
        f"Месяцы после {season_last} неполные в Saleflow (сентябрь 26: ~49 млрд ₽ заказов против 81–91 млрд в июле–августе) — показаны с пометкой ⚠️ и не входят в расчёт сезона.",
        "Saleflow с 2025-09 считает заказы по новой методике; в окне октябрь 25 – сентябрь 26 методика одна, сравнение месяцев между собой корректно. Ошибка оценок продаж ±10–20%.",
        "Отбор по выручке старта сделан по revenue_estimated > 10 млн ₽; предметы, у которых реальная выручка ≥ 10 млн при оценке < 10 млн, могли не попасть (пограничные).",
        "🔬 Метод классификации v2",
        "Проход 1 (жёсткие красные, уверенность Выс): мотор/аккумулятор/вилка, пиротехника, оружие, шины, Честный знак (бельё постельное/столовое/кухонное/туалетное), КГТ (каркасные бассейны, батуты, комплекты мебели и т.п.) → удаляются, см. лист «Удалённые (шаг 6)».",
        "Проход 2 (принципиальная оценка): для остальных ниш Claude рассуждает по сути товара и ставит 🟢/🟡 по документам, МГТ/СГТ по упаковке, 🟢/🟡/🔴 по ассортименту, с уверенностью (Выс/Сред/Низ) и пояснением.",
        "Уверенность: Выс — товар однозначно попадает под принцип; Сред — пограничный, скорее попадает; Низ — нужна ручная проверка.",
        "📋 Принципы оценки",
        "Документы 🟢 (отказное): нет питания/мотора, нет контакта с пищей/водой, не химия/косметика, не для детей до 3 лет, без режущих частей, не контактирует с телом (кроме одежды/аксессуаров).",
        "Документы 🟡 (декларация): контакт с пищей (ТР ТС 005), электрика без мотора (004/020), детские товары (007/008), режущие части, химия/составы, мебель (025), стройматериалы, одежда/кожгалантерея (017).",
        "⚠️ Для вашей схемы (карго без ГТД) любая 🟡 = риск: колонка «Карго без ГТД» помечает такие ниши. ТЗ относит текстиль к отказному; по ТР ТС 017 часть текстиля требует декларации — у таких ниш уверенность «Сред/Низ».",
        "Габариты оцениваются по упаковке для отправки: МГТ — до 25 кг, сторона ≤ 120 см, сумма ≤ 200 см; СГТ — сторона 120–200 см, сумма 200–280 см; КГТ — > 25 кг или сторона > 200 см или сумма > 280 см (удаляется).",
        "Ассортимент: 🟢 ≥ 10 осмысленных вариаций (выбор глазами: принты, дизайн), 🟡 5–15 типов (ограничено функцией), 🔴 commodity 2–5 вариантов (выбор по спецификации).",
        "Доступность: при старте в декабре всё, что производится в Китае круглый год, — 🟢; садовые/рассадные товары — 🟡 (сезонный спрос и поставки с февраля).",
        "🏆 Скоринг 7/7 (+1 балл за каждый зелёный)",
        "Документы 🟢 · Доступность 🟢 · Габариты МГТ · Ассортимент 🟢 · Длина сезона ≥ 6 мес · Доля от цели ≤ 5% · Выкуп ≥ 80%.",
        "Длина сезона: 🟢 ≥ 6 мес, 🟡 4–5 мес, 🔴 ≤ 3 мес. Размер ниши: 🟢 ≤ 5%, 🟡 5–10%, 🔴 > 10%. Выкуп: 🟢 ≥ 80%, 🟡 60–80%, 🔴 < 60%.",
        "🔴 по ассортименту, сезону, размеру ниши и выкупу НЕ удаляет нишу — это маркер.",
        "📊 Интерпретация скора",
        "7/7 — идеальная ниша по всем критериям. 6/7 — отличная, один нюанс (см. колонку «Не зелёные»). 5/7 — хорошая, два компромисса. 4/7 и ниже — вход только с явным преимуществом.",
        "Скор не учитывает конкуренцию (top-10 / top-1), цену закупки и юнит-экономику — это следующий шаг для отобранных ниш.",
        "🚫 Удалённые категории (шаг 2) и ключевые слова (шаг 3)",
        *[f"{c} — {why}" for c, why in cats],
        "Fashion (Одежда, Обувь, Спортивная одежда/обувь, Белье, Головные уборы, Аксессуары для волос, Одежда/Аксессуары/Белье для малышей): выкуп < 65% → удалено, ≥ 65% → 👗.",
        "Ключевые слова: " + "; ".join(f"{k}: {v.replace('|', ', ')}" for k, v in KEYWORDS.items()) + ". Велозапчасти не удалялись.",
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prefilter", "growth", "build"])
    ap.add_argument("--run", default="2026-10-05")
    ap.add_argument("--start", default="2025-12")
    ap.add_argument("--base", default="2025-11")
    ap.add_argument("--first", default="2025-10")
    ap.add_argument("--last", default="2026-09")
    ap.add_argument("--season-last", default="2026-08")
    ap.add_argument("--target", type=float, default=5_000_000)
    ap.add_argument("--class-file", default="data/processed/season_classification_2026-10-05.txt")
    ap.add_argument("--out", default="reports/niches_season_dec_2026-10-05.xlsx")
    a = ap.parse_args()
    if a.cmd == "build":
        ms, y, m = [], int(a.first[:4]), int(a.first[5:])
        while f"{y}-{m:02d}" <= a.last:
            ms.append(f"{y}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        res = build(a.run, a.start, a.base, ms, a.season_last, a.target, a.class_file, a.out)
        summary(res, a.target)
        return
    keep, log = prefilter(a.run, a.start)
    out_dir = f"data/raw/saleflow/{a.run}/season"
    if a.cmd == "prefilter":
        json.dump({"ids": keep, "log": log}, open(f"{out_dir}/prefilter_ids.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(json.dumps(log, ensure_ascii=False, indent=1))
        print("осталось:", len(keep))
        return
    start, base = load_month(a.run, a.start), load_month(a.run, a.base)
    grow, missing = [], []
    for sid in keep:
        rs, rb = real(start[sid]), real(base.get(sid))
        if rb is None:
            missing.append(sid)
            continue
        g = (rs - rb) / rb * 100 if rb else float("inf")
        if g >= MIN_GROWTH:
            grow.append(sid)
    json.dump({"ids": grow, "missing_base": missing},
              open(f"{out_dir}/growth_ids.json", "w", encoding="utf-8"), indent=1)
    print(f"после фильтров шагов 2–3: {len(keep)}; прирост ≥ {MIN_GROWTH}%: {len(grow)}; нет базы: {len(missing)}")


def summary(res: dict, target: float) -> None:
    rows, removed = res["rows"], res["removed"]
    import collections
    dist = collections.Counter(r["score"] for r in rows)
    print("== распределение СКОР:", dict(sorted(dist.items(), reverse=True)), "| удалено шаг 6:", len(removed))
    rc = collections.Counter(r["reason"].split(":")[0] for r in removed)
    print("   причины удаления:", dict(rc))
    for sc in (7, 6):
        sel = [r for r in rows if r["score"] == sc]
        print(f"\n== {sc}/7: {len(sel)}")
        for r in sel:
            s = r["season"]
            print(f'{("👗" if r["fashion"] else "")}{r["subj"]} | {r["cat"]} | прирост {r["growth"] if r["growth"] is None else round(r["growth"])}% '
                  f'| сезон {s["start"]}→{s["end"]} {s["len"]} мес, {s["sum"]/1e6:.0f} млн | пик {s["peak"]} | доля {r["share"]:.2f}% '
                  f'| выкуп {r["buyout"]} | док {r["doc"]}/{r["doc_c"]} габ {r["dim"]}/{r["dim_c"]} асс {r["asr"]}/{r["asr_c"]} '
                  f'| цена {r["price"]} | {" ".join("-"+k for k in r["miss"])}')
    sel = sorted([r for r in rows if r["score"] == 5], key=lambda x: -(x["growth"] or 0))[:20]
    print("\n== 5/7 топ-20 по приросту")
    for r in sel:
        print(f'{("👗" if r["fashion"] else "")}{r["subj"]} | {r["cat"]} | {round(r["growth"])}% | сезон {r["season"]["len"]} мес | '
              f'доля {r["share"]:.2f}% | выкуп {r["buyout"]} | цена {r["price"]} | {" ".join("-"+k for k in r["miss"])}')
    for key in ("doc_c", "dim_c", "asr_c"):
        print(key, dict(collections.Counter(CONF[r[key]] for r in rows)))
    print("пиковые месяцы:", dict(collections.Counter(r["season"]["peak"] for r in rows).most_common()))
    print("длина сезона:", dict(sorted(collections.Counter(r["season"]["len"] for r in rows).items())))
    print("fashion прошли:", [r["subj"] for r in rows if r["fashion"]])
    safe = [r for r in rows if r["season"]["len"] >= 6 and r["buyout"] >= 80]
    print("длинный сезон + выкуп ≥ 80%:", len(safe))
    low = [r["subj"] for r in rows if "L" in (r["doc_c"], r["dim_c"], r["asr_c"])]
    print("низкая уверенность:", low)
    ok = [r for r in rows if r["doc"] == "G" and r["price"] and 1400 <= r["price"] <= 2600]
    print("док 🟢 и цена 1400–2600:", [(r["subj"], r["score"], r["price"]) for r in ok])


if __name__ == "__main__":
    main()
