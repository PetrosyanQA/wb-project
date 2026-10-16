"""Поиск ниши v6 (2026-10-16): БЕЗ карго-запретов (магниты, батарейки/электроника, жидкости разрешены),
Честный знак остаётся (+ need_kiz карточки), юридические запреты остаются (медизделия — регистрация, оружие, табак, еда).
Использует конвейер src.niche_v5 (те же этапы и кэш), подменяя списки запретов и пути вывода.

    python -m src.niche_v6 universe | collect [--max N] | score | cards [--top N] | final
    python -m src.niche_v6 preview        # 0 запросов: что «открылось» после снятия карго-фильтров (по выгрузке предметов)
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from src import niche_v5 as V

sys.stdout.reconfigure(encoding="utf-8")
V.ALLOW_ELECTRO = True
V.BANDS = V.BANDS + [(4000, 6000)]
V.UNIVERSE = "data/processed/niche_v6_universe.json"
V.STAGE1 = "data/processed/niche_v6_stage1.json"
V.FINAL = "data/processed/niche_v6_final.json"
V.BAN_ROOTS = {
    # Честный знак (корень целиком)
    "Одежда", "Обувь", "Белье", "Белье для малышей", "Одежда для малышей", "Детская одежда", "Детская обувь", "Спортивная одежда",
    "Спортивная обувь", "Шины и диски", "Спецодежда и СИЗы", "Игрушки", "Бытовая химия", "Автохимия и автокосметика",
    "Масла и технические жидкости", "Товары для курения", "Продукты", "Детское питание", "Спортивное питание и косметика",
    "Зоокорма", "Корма для животных",
    # юридические: регистрация / оружие / пробирный надзор / не наш товар
    "Здоровье", "Аптека", "Ветаптека", "Медицинские изделия", "Ювелирные украшения", "Транспортные средства", "Цифровые товары",
    "Книги", "Книжная продукция и диски",
    # габарит/подбор — экономика всё равно отсекает, экономим квоту
    "Мебель", "Мебель корпусная и мебель для хранения", "Мебель мягкая", "Мебель для сна", "Мебель садовая", "Мебель на заказ",
    "Мебель офисная и торговое оборудование", "Строительные материалы", "Отделочные материалы", "Сантехника", "Автозапчасти",
    "Запчасти для легковых автомобилей", "Запчасти для грузовых автомобилей", "Крупная бытовая техника",
}
V.BAN_NAME = re.compile(
    # Честный знак
    r"одежд|обув|бель[её]|носк|колготк|полотенц|простын|постельн|пододеяльн|наволоч|скатерт|ремни|ремень|перчат|жилеты спас|шины|велосипед|"
    r"духи|парфюм|туалетная вода|дезодор|помад|тушь|тени для|пудр|румян|консилер|тональн|крем|шампун|бальзам|скраб|сыворот|тоник|лосьон|"
    r"гель для|маски косметич|лак для ногт|косметич|фотоаппарат|объектив|"
    # еда / табак / медицина / оружие
    r"корм|лакомств|витамин|бад\b|лекарств|медицинск|ортопед|бандаж|тонометр|глюкометр|"
    r"чай|кофе|конфет|шоколад|сахар|продукт|напит|вода питьев|сигарет|кальян|вейп|табак|никотин|"
    r"оружи|пневмат|арбалет|патрон|пиротех", re.I)


def preview() -> None:
    """Что добавилось по сравнению с v5 (карго-фильтры сняты) — по выгрузке предметов, 0 запросов."""
    v5 = {u["id"] for u in json.load(open("data/processed/niche_v5_universe.json", encoding="utf-8"))}
    U = json.load(open(V.UNIVERSE, encoding="utf-8"))
    new = [u for u in U if u["id"] not in v5]
    for u in new:
        r = next((s for s in V.subjects() if s["id"] == u["id"]), {})
        u["rev_per_card"] = round(r.get("revenue", 0) / max(r.get("items_with_sells") or 1, 1))
        u["new_items_pct"] = round((r.get("items_new") or 0) / max(r.get("items") or 1, 1) * 100, 1)
    fit = [u for u in new if 900 <= (u["price_med"] or 0) <= 6000 and (u["buyout"] or 0) >= 60]
    fit.sort(key=lambda u: -u["rev_per_card"] * (u["buyout"] or 0) / 100)
    print(f"новых ниш после снятия карго-фильтров: {len(new)}; с медианой 900–6000 ₽ и выкупом ≥ 60 %: {len(fit)}")
    for u in fit[:60]:
        print(f"  {u['id']:5} {u['name'][:58]:58} | {u['rev_mln']:7} млн | медиана {u['price_med']} ₽ | выкуп {u['buyout']} | "
              f"продавцов {u['sellers_ws']} | выручка/карточку {u['rev_per_card']:,} ₽ | ком AM {u['com']} / РФ {u['rf_com']}")
    json.dump(fit, open("data/processed/niche_v6_preview.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def prioritize() -> None:
    """Порядок сбора: сначала «открывшиеся» ниши из preview (900–6000 ₽, выкуп ≥ 60 %), потом остальные не-габаритные."""
    import re as _re
    from src.all_niches import BULKY
    U = json.load(open(V.UNIVERSE, encoding="utf-8"))
    fit = {u["id"] for u in json.load(open("data/processed/niche_v6_preview.json", encoding="utf-8"))}
    big = _re.compile(r"ковр|матрас|кроват|шкаф|стол|кресл|диван|бассейн|батут|качел|палатк|лодк|самокат|велосипед|холодильн|стиральн|"
                      r"плит[аы]|духов|водонагрев|кондиционер|телевизор|мойк|культиватор|генератор|компрессор|бетоно", _re.I)
    U.sort(key=lambda u: (u["id"] not in fit, bool(BULKY.search(u["name"]) or big.search(u["name"])), -(u["rev_mln"] or 0)))
    json.dump(U, open(V.UNIVERSE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("приоритет записан; первые:", [u["name"].split(" / ")[-1] for u in U[:10]])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["universe", "collect", "score", "cards", "final", "preview", "prioritize"])
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "preview":
        preview()
    elif a.cmd == "prioritize":
        prioritize()
    elif a.cmd == "collect":
        V.collect(a.max)
    elif a.cmd == "cards":
        V.cards(a.top)
    else:
        {"universe": V.universe, "score": V.score, "final": V.final}[a.cmd]()


if __name__ == "__main__":
    main()
