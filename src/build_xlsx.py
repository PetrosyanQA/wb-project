"""Сводная Excel-таблица по нишам из data/raw/saleflow/<date>/<niche>/*.json (ничего не пересчитывает)."""
import json, sys, os, glob
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-03"
ROOT = os.path.join("data", "raw", "saleflow", DATE)
NAMES = {"termos": "Термос", "nozhi-kuhonnye": "Ножи кухонные", "manikyurnye-nabory": "Маникюрные наборы",
         "nabory-podelok": "Наборы для творчества", "tablichki": "Таблички", "klatchi": "Клатчи",
         "bizhuteriya-komplekty": "Бижутерия: комплекты", "tochilka": "Точилки", "derzhatel-vannoy": "Держатель для ванной",
         "organizer-kosmetika": "Органайзер косметики", "makeup_set": "Набор косметики", "stolovye-pribory": "Столовые приборы", "chehly-planshet": "Чехлы для планшетов",
         "vakuumatory": "Вакуумные упаковщики", "koshelki": "Кошельки", "nozhi-turist": "Ножи туристические",
         "chasy-naruchnye": "Часы наручные", "kombinezony-zhivotnye": "Комбинезоны для животных", "sumki-sport": "Сумки спортивные"}
ALIAS = {"manikyurnye-nabory": ["manikyur-nabory"]}

def load(niche, f):
    for n in [niche] + ALIAS.get(niche, []):
        p = os.path.join(ROOT, n, f)
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return None

def g(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d: return None
        d = d[k]
    return d

rows = []
for tp in sorted(glob.glob(os.path.join(ROOT, "*", "trends.json"))):
    niche = os.path.basename(os.path.dirname(tp))
    if niche in sum(ALIAS.values(), []): continue
    tr, se, it, ec, cm, rg = (load(niche, f) for f in ("trends.json", "sellers.json", "items.json", "econ.json", "comments.json", "reg.json"))
    pk = g(tr, "peak_yoy") or []
    last = pk[-1] if pk else {}
    r12 = g(tr, "rolling12") or {}
    themes = g(cm, "common_themes")
    rows.append({
        "Ниша": NAMES.get(niche, niche), "slug": niche,
        "0 Регуляторика": g(rg, "verdict"),
        "2 Концентрация": g(se, "verdict"), "Top-1, %": g(se, "top1_pct"), "Top-3, %": g(se, "top3_pct"),
        "Продавцов до 40%": g(se, "n_to_level"), "Продавцов всего": g(se, "sellers"),
        "Медиана цены, ₽": g(it, "median_price"), "Объём, л": g(it, "median_volume_l"),
        "Свежих в топ-20": g(it, "fresh_in_top20"), "Медиана отзывов топ-20": g(it, "median_comments_top20"),
        "Комиссия, %": g(ec, "commission_pct"), "Логистика, % цены": g(ec, "logistics_share_pct"),
        "Потолок себестоимости, ₽": g(ec, "max_cost_rub"), "Потолок, % цены": g(ec, "max_cost_share_pct"),
        "6 Экономика": g(ec, "verdict"),
        "4 Тренд": g(tr, "verdict"), "Пик-месяц": g(tr, "peak_month"),
        "Пик YoY низ, %": last.get("lo_pct"), "Пик YoY верх, %": last.get("hi_pct"),
        "12м vs 12м низ, %": r12.get("lo_pct"), "12м vs 12м верх, %": r12.get("hi_pct"),
        "Выручка, ₽/мес (12м)": g(tr, "size", "avg_monthly_revenue_12m"),
        "Пик/дно сезонности": g(tr, "seasonal", "peak_to_trough"), "Доля пик-месяца года, %": g(tr, "seasonal", "peak_share_pct"),
        "5 Жалобы": g(cm, "verdict"), "Тема жалоб": ", ".join(themes) if themes else None,
    })
if not rows: sys.exit("нет trends.json")
rows.sort(key=lambda r: ({"PASS": 0, "THIN": 1}.get(r["4 Тренд"], 2), -(r["Выручка, ₽/мес (12м)"] or 0)))

wb = Workbook(); ws = wb.active; ws.title = "Сводка"
cols = [c for c in rows[0] if c != "slug"]
ws.append(cols)
for r in rows: ws.append([r[c] if r[c] is not None else "—" for c in cols])
fills = {"PASS": "C6EFCE", "THIN": "FFEB9C", "FAIL": "FFC7CE"}
hdr = PatternFill("solid", fgColor="1F3864")
for c in ws[1]:
    c.fill = hdr; c.font = Font(bold=True, color="FFFFFF"); c.alignment = Alignment(wrap_text=True, vertical="center")
ws.row_dimensions[1].height = 45
for row in ws.iter_rows(min_row=2):
    for c in row:
        if c.value in fills: c.fill = PatternFill("solid", fgColor=fills[c.value])
        if isinstance(c.value, (int, float)) and abs(c.value) >= 1000: c.number_format = "#,##0"
for i, c in enumerate(cols, 1):
    ws.column_dimensions[get_column_letter(i)].width = 24 if i == 1 else 13
ws.freeze_panes = "B2"

n = wb.create_sheet("Примечания")
for line in [
    f"Источник: data/raw/saleflow/{DATE}/<ниша>/*.json (Saleflow → saleflow_eval). Прочерк «—» = шаг не выполнялся.",
    "Пик YoY / 12м: «низ» = est/raw, «верх» = raw/raw (два режима данных с 2025-09). PASS только если проходит низ.",
    "Потолок себестоимости — верхняя граница при марже ≥18% и ROI ≥60%, НЕ цена поставщика.",
    "Логистика — дефолты config/unit_economics.yaml; комиссия — реальная из wb_seller commission, где она передавалась.",
    "Ошибка данных MPSTATS ±10–20%. Выручка — по предмету (subject), среднее за последние 12 мес.",
    "Таблички: ряд шумный (средний чек 520→2990 ₽), PASS ненадёжен. Клатчи: THIN из-за расхождения режимов.",
    "Наборы для творчества: ×8.7 пик/дно — почти всё в декабре; к сезону 2026 вряд ли успеем.",
]: n.append([line])
n.column_dimensions["A"].width = 130
rk_path = os.path.join(ROOT, "ranking.json")  # пишет python -m src.niche_rank
if os.path.exists(rk_path):
    rk = wb.create_sheet("Рейтинг", 0)
    head = ["#", "Ниша", "Итог с реальностью", "Балл рынка", "Пик YoY низ, %", "12м низ, %", "Отзывы топ-20", "Свежих в топ-20",
            "Top-1, %", "Потолок, % цены", "Логистика, % цены", "Жалоба, % негатива", "Пик/дно", "Штрафы реальности"]
    rk.append(head)
    for i, r in enumerate(json.load(open(rk_path, encoding="utf-8")), 1):
        rk.append([i, NAMES.get(r["niche"], r["niche"]), r.get("real_score", r["score"]), r["score"], r["peak_lo"], r["r12_lo"],
                   r["comments_top20"], r["fresh_top20"], r["top1"], r["ceiling_pct"], r["logistics_pct"],
                   round(r["complaint_pct"], 1), r["season"], "; ".join(r.get("real_why", [])) or "—"])
    for c in rk[1]:
        c.fill = hdr; c.font = Font(bold=True, color="FFFFFF"); c.alignment = Alignment(wrap_text=True)
    rk.column_dimensions["B"].width = 24
    rk.append([]); rk.append(["Допуск: шаги 2–5 PASS. Балл 0–100 нормирован по допущенным нишам; экономика по медианной цене. Скрипт: python -m src.niche_rank"])
out = os.path.join("reports", f"niches_comparison_{DATE}.xlsx"); wb.save(out); print(out, len(rows))
for r in rows: print(r["Ниша"], r["4 Тренд"], r["2 Концентрация"], r["6 Экономика"], r["5 Жалобы"])
