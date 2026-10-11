"""Проход по ВСЕМ предметам WB (7 587 на 2026-10-11) → годовая ниша + сезонная пара (H1 / H2). Saleflow wb_subjects_list.

    python -m src.all_niches list [--dry-run]       # все предметы, последний снимок: ~16 запросов (500 строк/запрос)
    python -m src.all_niches prefilter              # 0 запросов: жёсткие фильтры → data/processed/all_niches_prefilter_2026-10-11.json
    python -m src.all_niches monthly [--dry-run]    # 12 помесячных снимков 2024-09 … 2025-08 только по выжившим (фильтр id)
    python -m src.all_niches season                 # 0 запросов: пик, длина сезона, H1/H2, стабильность

Почему 2024-09 … 2025-08 для сезонности: в этом году методика Saleflow однородна (с 2025-09 выручка пересчитана,
а 2026-08/09 неполные — проверено 2026-10-08). Размер ниши сейчас — из последнего снимка.
Ограничения пользователя: FBS из Подмосковья, карго без ГТД → никакой обязательной сертификации/маркировки;
≤ 1 л, ≤ 0,5 кг; без магнитов, аккумуляторов/электроники, жидкостей (2026-10-11).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics as st
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-11"
RAW = f"data/raw/saleflow/{RUN}/all"
PRE = f"data/processed/all_niches_prefilter_{RUN}.json"
SEASON_OUT = f"data/processed/all_niches_season_{RUN}.json"
MONTHS = [f"2024-{m:02d}" for m in (9, 10, 11, 12)] + [f"2025-{m:02d}" for m in range(1, 9)]
# 2025-09 исключён: в этом месяце Saleflow сменил методику (выручка подскочила у большинства ниш — ложный «пик сентября»)
PAGE = 500

# ── жёсткие фильтры ──────────────────────────────────────────────────────────────────────────────
MIN_REAL_REV = 15_000_000      # ₽/мес реальной выручки (revenue × выкуп) — меньше не прокормит новичка
MIN_SELLERS_WITH_SALES = 50
PRICE_MIN, PRICE_MAX = 450, 3000   # медианная цена покупателя продающих карточек; < 450 ₽ не проходит ¥×78
DROP_ROOTS = {  # корневые категории: сертификация/маркировка/электроника/химия/еда/одежда (ТР ТС 017)
    "Красота", "Здоровье", "Бытовая химия", "Продукты", "Детское питание", "Спортивное питание и косметика",
    "Бытовая техника", "Крупная бытовая техника", "Техника для кухни", "Садовая техника", "Электроинструмент и оборудование",
    "Телевизоры и аудиотехника", "Ноутбуки и компьютеры", "Сетевое оборудование", "Электротранспорт", "Аккумуляторы для ТС",
    "Смартфоны и гаджеты", "Игровые консоли и игры", "Умный дом и безопасность", "Фото и Видеотехника", "Освещение",
    "Электрика", "Масла и технические жидкости", "Ювелирные украшения", "Климатическая техника",
    "Техника для красоты и здоровья", "Автоэлектроника", "Оргтехника", "Периферия и аксессуары", "Ветаптека",
    "Автохимия и автокосметика", "Товары для курения", "Транспортные средства", "Одежда", "Обувь", "Спортивная одежда",
    "Спортивная обувь", "Белье", "Одежда для малышей", "Белье для малышей", "Детская одежда", "Детская обувь",
    "Книги", "Цифровые товары", "Медицинские изделия", "Аптека", "Зоокорма", "Корма для животных", "Шины и диски",
    "Запчасти для легковых автомобилей", "Запчасти для грузовых автомобилей", "Мебель", "Строительные материалы",
    # уточнение 2026-10-11 по реальным корням выгрузки
    "Книжная продукция и диски", "Товары для взрослых", "Спецодежда и СИЗы", "Автозапчасти", "Отделочные материалы",
    "Сантехника", "Мототовары", "Головные уборы", "Игрушки", "Товары для малышей", "Аксессуары для малышей",
}
DROP_NAME = re.compile(
    r"магнит|аккумулят|батаре|заряд|электр|светодиод|led|гирлянд|лампа|фонар|наушник|колонк|камер|датчик|"
    r"жидк|спрей|масл|клей|краск|гель|крем|шампун|духи|парфюм|средств|аэрозол|чистящ|"
    r"нож|оружи|пневмат|арбалет|"                       # холодное/пневматика
    r"детские сиденья|автокресл|коляск|соски|пустыш|бутылочк|прорезыват|"   # детское — сертификация
    r"посуд|кастрюл|сковород|тарелк|кружк|стакан|бокал|контейнер|бутыл|термос|ланч|"   # контакт с пищей (ТР ТС 005)
    r"матрас|подушк|одеял|постельн|полотенц|текстил|ткан|пряж|"   # текстиль
    r"мебел|диван|кресл|стол|стул|шкаф|кроват|"           # габарит
    r"шины|диски колес|аккумулятор|"
    r"корм|лакомств|наполнител|пеленк|витамин|паст[аы] для|подгузник|удобрен|грунт|торф|субстрат|мульч|рассад|растени|"
    r"семен|газон|бактери|прикормк|туалетная бумага|салфетк|фольга|пакет|пленк|обои|эмал|лак[и ]|пен[аы] |герметик|"
    r"антисептик|бумага|чеков|сверл|диск|круг[и ]|цепи для пил|компрессор|пылесос|автосканер|домкрат|ламп|фар[ыа]|"
    r"насос|свечи|фильтр|картридж|шланг|бассейн|мангал|тент|качел|туалет|душ|умывальн|елки|тренажер|гантел|штанг|"
    r"груш[аи] боксер|удилищ|весл|жилет|круги для плав|бинокл|обогрев|печ[иь]|ведр|таз|швабр|корзин|клетк|переноск|"
    r"домик|лежак|коврики автомоб|звукоизоляц|брызговик|колпак|емкост|бочк|лопат|топор|культиватор|опрыскивател|"
    r"сумки-тележк|чемодан|рюкзак|шторы|тюль|жалюзи|карниз|сидень|респиратор|карты таро|парик|ковр|"
    r"машинки для стрижк|умные устройств|светильник|отпугивател|паяльник|лосьон|капли|часы наручн|фонтан|аквариум|вольер|"
    r"эпоксидн|гримы|воски для свеч|глина", re.I)


BULKY = re.compile(r"бордюр|забор|клумб|сетк|арк[иа]|теплиц|сушилк|лестниц|ящик|дорожк|плитк|зонт|скиммер|"
                   r"коробки картон|мольберт|подставки для цвет|лотк|кашпо|горш|вешалк|органайзеры в багаж|подлокотн|"
                   r"наборы инструмент|наборы автомоб|кусторез|сучкорез|елки", re.I)    # явно > 1 л / > 0,5 кг


def fetch_pages(tasks: list[tuple[str, dict]]) -> None:
    from src.strategy_collect import Client, fetch, quota
    T = [t for t in tasks if not os.path.exists(t[0])]
    print(f"к скачиванию: {len(T)} (= запросов Saleflow)")
    if not T:
        return
    c = Client()
    streak = 0
    try:
        print("квота до:", quota(c))
        for k, (path, args) in enumerate(T, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            for attempt in range(2):
                try:
                    json.dump(fetch(c, "wb_subjects_list", args), open(path, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"[{k}/{len(T)}] → {path}")
                    streak = 0
                    break
                except Exception as e:                      # noqa: BLE001 — upstream Saleflow нестабилен
                    print(f"[{k}/{len(T)}] {path}: {str(e)[:160]} (попытка {attempt + 1})")
                    if "закрылся" in str(e):
                        c = Client()
                    if attempt == 0:
                        time.sleep(30)
            else:
                streak += 1
                if streak >= 3:
                    print("3 сбоя подряд — стоп")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()


def list_tasks(total: int = 7587) -> list[tuple[str, dict]]:
    return [(f"{RAW}/latest/page_{s}.json", {"start_row": s, "limit": PAGE, "sort": "revenue", "sort_dir": "desc"})
            for s in range(0, total, PAGE)]


def load(pattern: str) -> dict[int, dict]:
    out = {}
    for f in glob.glob(pattern):
        d = json.load(open(f, encoding="utf-8"))
        for r in (d.get("data", []) if isinstance(d, dict) else d):
            out[r["id"]] = r
    return out


def real_rev(r: dict) -> float:
    return (r.get("revenue_estimated") or r.get("revenue") or 0) * (r.get("purchase_after_return") or 0) / 100


def prefilter() -> None:
    A = load(f"{RAW}/jul2026/page_*.json") | load(f"{RAW}/jul2026_rev15m/page_*.json")   # снимок на 2026-07-31: «последний» снимок Saleflow неполный (777: 38 vs 114 млн)
    log = {"всего": len(A)}
    keep = []
    steps = [
        ("реальная выручка < 15 млн ₽/мес", lambda r: real_rev(r) >= MIN_REAL_REV),
        ("корневая категория: сертификация/электроника/химия/одежда/габарит", lambda r: r["name"].split(" / ")[0] not in DROP_ROOTS),
        ("название: магнит/аккумулятор/жидкость/посуда/текстиль/мебель/детское", lambda r: not DROP_NAME.search(r["name"])),
        (f"медианная цена покупателя вне {PRICE_MIN}–{PRICE_MAX} ₽", lambda r: PRICE_MIN <= (r.get("median_price_final_with_sells") or 0) <= PRICE_MAX),
        (f"продавцов с продажами < {MIN_SELLERS_WITH_SALES}", lambda r: (r.get("sellers_with_sells") or 0) >= MIN_SELLERS_WITH_SALES),
    ]
    rows = list(A.values())
    for label, ok in steps:
        before = len(rows)
        rows = [r for r in rows if ok(r)]
        log[label] = before - len(rows)
    for r in rows:
        keep.append({"id": r["id"], "name": r["name"], "real_rev_mln": round(real_rev(r) / 1e6, 1),
                     "median_price": r.get("median_price_final_with_sells"), "sellers_ws": r.get("sellers_with_sells"),
                     "items_ws": r.get("items_with_sells"), "buyout": r.get("purchase_after_return"),
                     "com_fbs_rf": r.get("commision_fbs"), "rating_ws": r.get("comment_valuation_with_sells"),
                     "seasonality_level": r.get("seasonality_level"), "turnover": r.get("turnover_in_days")})
    keep.sort(key=lambda x: -x["real_rev_mln"])
    roots = {r["name"].split(" / ")[0] for r in A.values()}
    out = {"run": RUN, "subjects_total": len(A), "root_categories_total": len(roots), "log": log, "keep": keep}
    json.dump(out, open(PRE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"предметов: {len(A)}, корневых категорий: {len(roots)}")
    for k, v in log.items():
        print(f"  {k}: {v}")
    print(f"осталось: {len(keep)} → {PRE}")


def monthly_tasks() -> list[tuple[str, dict]]:
    ids = [k["id"] for k in json.load(open(PRE, encoding="utf-8"))["keep"]]
    chunks = [ids[i:i + PAGE] for i in range(0, len(ids), PAGE)]
    T = []
    for m in MONTHS:
        y, mm = map(int, m.split("-"))
        last = {2: 28}.get(mm, 30 if mm in (4, 6, 9, 11) else 31)
        for j, ch in enumerate(chunks):
            T.append((f"{RAW}/monthly/{m}/ids_{j}.json",
                      {"date": f"{m}-{last:02d}", "limit": PAGE, "start_row": 0,
                       "filter_model": {"id": {"filterType": "set", "values": [str(i) for i in ch]}}}))
    return T


def season() -> None:
    from src.season_niches import season as window
    pre = {k["id"]: k for k in json.load(open(PRE, encoding="utf-8"))["keep"]}
    M = {m: load(f"{RAW}/monthly/{m}/*.json") for m in MONTHS}
    res = []
    for sid, k in pre.items():
        vals = [(M[m].get(sid) or {}).get("revenue") or 0 for m in MONTHS]
        if sum(1 for v in vals if v > 0) < 10:
            continue
        mean = st.mean(vals)
        idx = [round(v / mean * 100) for v in vals]
        w = window(vals, MONTHS, 0.5)
        peak_m = int(w["peak"][5:])
        half = "H1 (фев–июл)" if 2 <= peak_m <= 7 else "H2 (авг–янв)"
        cv = st.pstdev(vals) / mean if mean else None
        res.append({**k, "index": dict(zip([m[5:] for m in MONTHS], idx)), "peak_month": peak_m, "half": half,
                    "season_len_50": w["len"], "trough_pct": round(min(vals) / max(vals) * 100), "cv": round(cv, 2),
                    "type": "круглый год" if min(vals) / max(vals) >= 0.6 else ("сезон" if w["len"] <= 6 else "умеренно сезонная")})
    J = load(f"{RAW}/jul2026/page_*.json") | load(f"{RAW}/jul2026_rev15m/page_*.json")
    for r in res:
        j, idx = J[r["id"]], r["index"]
        real = real_rev(j)
        pk = max(idx.values())
        r["peak_real_mln"] = round(real * pk / max(idx["07"], 1) / 1e6, 1)     # июль-2026 × форма сезона
        r["per_item_peak"] = round(real * pk / max(idx["07"], 1) / max(j.get("items_with_sells") or 1, 1))
        r["bulky_name"] = bool(BULKY.search(r["name"]))
    json.dump(res, open(SEASON_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("типы:", Counter(r["type"] for r in res), "| половина пика:", Counter(r["half"] for r in res if r["type"] != "круглый год"))
    print("→", SEASON_OUT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["list", "prefilter", "monthly", "season", "collect", "finalists"])
    ap.add_argument("--src", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.step == "list":
        T = list_tasks()
        print(f"страниц: {len(T)}")
        if not a.dry_run:
            fetch_pages(T)
    elif a.step == "prefilter":
        prefilter()
    elif a.step == "monthly":
        T = monthly_tasks()
        print(f"запросов: {len(T)}")
        if not a.dry_run:
            fetch_pages(T)
    elif a.step == "season":
        season()
    elif a.step == "collect":
        collect_finalists(a.src)
    else:
        finalists()



# ── финалисты: top-100 в месяц пика → экономика, концентрация, объём, чувствительный груз (0 запросов) ──────────
FIN = f"{RAW}/finalists"
FIN_OUT = f"data/processed/all_niches_finalists_{RUN}.json"


def collect_finalists(src_dir: str) -> None:
    """MCP-ответы wb_subject products из tool-results → finalists/products_<sid>.json (по преобладающему subject_id)."""
    import collections, shutil
    os.makedirs(FIN, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(src_dir, "mcp-saleflow_universal-wb_subject-*.txt"))):
        if os.path.getmtime(f) < time.time() - 6 * 3600:
            continue
        d = json.load(open(f, encoding="utf-8"))
        c = collections.Counter(p.get("subject_id") for p in d.get("data", []))
        if c:
            shutil.copyfile(f, f"{FIN}/products_{c.most_common(1)[0][0]}.json")


def finalists() -> None:
    from src.dna_rank import commissions, econ, T_MARGIN, T_ROI
    from src.nomagnet_screen import SENSITIVE
    from src.outliers import clean_items
    S = {s["id"]: s for s in json.load(open(SEASON_OUT, encoding="utf-8"))}
    com = commissions()
    rx_sens = "|".join(SENSITIVE.values())
    res = []
    for f in glob.glob(f"{FIN}/products_*.json"):
        sid = int(re.search(r"products_(\d+)", f).group(1))
        s = S.get(sid)
        if not s:
            continue
        rows = json.load(open(f, encoding="utf-8"))["data"]
        rev = lambda p: p.get("revenue_estimated") or p.get("revenue") or 0
        rows = sorted(rows, key=lambda p: -rev(p))[:100]
        P, rep = clean_items(rows, expected_subject=sid)
        price_s = st.median([p["final_price"] for p in P if p.get("final_price")])
        spp = st.median([(1 - p["revenue"] / p["sales"] / p["final_price"]) * 100 for p in P if p.get("sales") and p.get("final_price")])
        sales_peak = st.median([p.get("sales_estimated") or p.get("sales") or 0 for p in P])
        idx = s["index"]
        sales_year_avg = sales_peak * st.mean(idx.values()) / max(idx.values())      # шт/карточку в среднем месяце года
        vols = [(p.get("package_length") or 0) * (p.get("package_width") or 0) * (p.get("package_height") or 0) / 1000 for p in P]
        vols = [v for v in vols if v > 0]
        vol = round(st.median(vols), 2) if len(vols) >= 10 else None
        tot = sum(rev(p) for p in P) or 1
        by = {}
        for p in P:
            by[p.get("supplier_id") or p.get("seller")] = by.get(p.get("supplier_id") or p.get("seller"), 0) + rev(p)
        shares = sorted((v / tot * 100 for v in by.values()), reverse=True)
        sens = sum(rev(p) for p in P if re.search(rx_sens, (p.get("name") or "").lower())) / tot * 100
        new = [p for p in P if (p.get("sku_first_date") or "") >= "2025-06-01"]
        e = econ(price_s, spp, vol, s.get("buyout") or 80, com.get(sid, 20.0))
        fails = []
        if vol is not None and vol > 1.0:
            fails.append(f"объём {vol} л > 1")
        if not (e["margin"] >= T_MARGIN and e["roi"] >= T_ROI):
            fails.append(f"маржа {e['margin']}% / ROI {e['roi']}%")
        if sales_year_avg < 150:
            fails.append(f"{round(sales_year_avg)} шт/карт/мес в среднем < 150")
        if shares[0] > 25:
            fails.append(f"top-1 {round(shares[0])}%")
        if sens > 20:
            fails.append(f"чувств. груз {round(sens)}%")
        res.append({"id": sid, "name": s["name"], "type": s["type"], "half": s["half"], "peak_month": s["peak_month"],
                    "season_len_50": s["season_len_50"], "trough_pct": s["trough_pct"], "index": idx,
                    "dropped": rep["dropped"], "price_s": round(price_s), "spp": round(spp, 1), "price_b": round(price_s * (1 - spp / 100)),
                    "sales_peak_med": round(sales_peak), "sales_year_avg": round(sales_year_avg), "vol": vol,
                    "t1": round(shares[0], 1), "t10": round(sum(shares[:10]), 1), "sellers_top100": len(by),
                    "sens_pct": round(sens, 1), "new_rev_pct": round(sum(rev(p) for p in new) / tot * 100, 1),
                    "commission": com.get(sid), "margin": e["margin"], "roi": e["roi"], "margin_b": e["margin_b"],
                    "profit": e["profit"], "yuan": e["yuan78"], "yuan_max": e["yuan_max"],
                    "profit_year_per_card": round(e["profit"] * sales_year_avg * 12) if e["profit"] > 0 else 0, "fails": fails})
    res.sort(key=lambda r: (len(r["fails"]), -r["profit_year_per_card"]))
    json.dump(res, open(FIN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("| id | Ниша | тип | пик | цена до СПП / покуп. | шт/карт пик / ср.мес | л | top-1 | маржа / ROI / от покуп. | ¥ | прибыль/год на медиан. карточку | не прошла |")
    for r in res:
        print(f"| {r['id']} | {r['name'][:38]} | {r['type'][:10]} {r['half'][:2]} | м{r['peak_month']:02d} | {r['price_s']} / {r['price_b']} | "
              f"{r['sales_peak_med']} / {r['sales_year_avg']} | {r['vol']} | {r['t1']} | {r['margin']} / {r['roi']} / {r['margin_b']} | "
              f"{r['yuan']} | {r['profit_year_per_card']} | {'; '.join(r['fails']) or '✅'} |")
    print("→", FIN_OUT)


if __name__ == "__main__":
    main()
