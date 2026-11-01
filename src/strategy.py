"""Стратегия ниши под шаблон «Senior E-commerce Strategist» — общий код для пресетов 777 и 2486 (2026-10-07). 0 запросов.

    python -m src.strategy top100 --niche 2486     # → data/processed/top100_2486_2026-10-07.json + reports/top100_2486_2026-10-07.xlsx
    python -m src.strategy build  --niche 2486     # → data/processed/strategy_2486_2026-10-07.json + таблицы (markdown) в stdout
    python -m src.strategy check  --niche 777      # регрессия против data/processed/strategy777_2026-10-06.json

Обобщает src/strategy777.py и src/top100_777.py (их не трогаем: они воспроизводят отчёт 2026-10-06).
Методика одна для всех ниш:
  «30 дней» = июль 2026, «90 дней» = май–июль 2026 (в Saleflow 08–09.2026 неполные, проверено 2026-10-07);
  цена до СПП = products.final_price (= start_price × (1 − basic_sale)); цена покупателя = final_price_average = выручка/шт;
  в дневном by_period final_price = цена покупателя;
  сценарии спроса = P25/P50/P75 траекторий новых карточек top-100 (заказов/день, очищено от сезона).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import statistics as st
import sys

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from src.outliers import clean_items
from src.unit_econ import load_config, load_scheme, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-07"
R5, R6, R7 = "data/raw/saleflow/2026-10-05", "data/raw/saleflow/2026-10-06", "data/raw/saleflow/2026-10-07"
R11 = "data/raw/saleflow/2026-10-11"
R13 = "data/raw/saleflow/2026-10-13"
R14 = "data/raw/saleflow/2026-10-14"
R15 = "data/raw/saleflow/2026-10-15"
WINDOW = ("2026-04-01", "2026-07-31")          # надёжное окно дневных данных (08–09.2026 в Saleflow неполные)
COMMENTS_SINCE = "2025-10-06"                  # 365 дней отзывов (как в отчётах 2026-10-06)
COHORT = ("2025-10-01", "2026-06-30")          # новые карточки для траекторий входа
YEAR = [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]
YUAN_RUB, FX, CARGO_USD_KG, BASE_KG = 17.0, 83.48, 2.0, 0.5   # ¥ × 17 ₽ покрывает товар до 0.5 кг; сверх — $2/кг
FIXED = 10000                                  # фулфилмент Подмосковье, минимум ₽/мес [со слов пользователя]
DRR_BASE, PACK = 15.0, 15.0   # упаковка 15 ₽ [исправлено 2026-10-27, было 50]

# ── 777: словари из src/strategy777.py (без изменений) ──────────────────────────────────────────────────────────
SEG_777 = {487711855, 485786521, 740582525, 397439115, 264729116, 494403950, 390437007, 1146446018, 481858028,
           913853487, 848134054, 148983914}
COMPLAINTS_777 = {
    "магнит слабый / телефон падает": r"слаб\w* магнит|магнит\w* слаб|пада|пада[её]т|упал|пада|не держит телефон|телефон не держ|отва\w+ телефон|слетает",
    "присоска/основа отклеивается": r"присоск\w* (не|отва|отклеи|слет)|отклеи|отвал\w*(ся|ась)? (от|с) (панел|стекл|торпед)|не держится на|не прилип|не присас|отпада",
    "шарнир болтается / не держит угол": r"шарнир|болта|опуска|не держит угол|провис|клони|наклон",
    "не держит через чехол": r"чехл|чехол",
    "кольцо/пластина отклеивается": r"кольц\w* (отклеи|отва)|пластин\w* (отклеи|отва)|отклеил\w* кольц|отклеил\w* пластин",
    "жара/холод (лето, мороз)": r"жар|солнц|мороз|холод|зим|плав",
    "царапает/следы": r"царап|след",
    "брак/некомплект": r"брак|не (тот|та) |некомплект|не хватает|без кольц|пришл\w* (без|сломан)",
}
PAINS_777 = {"не падает / надёжно держит": r"не пада|надёжн|надежн|крепк|прочн|стабильн|держит",
             "на кочках / резкое торможение": r"кочк|торможен|манёвр|маневр|тряс|неровн",
             "360° / угол обзора": r"360|поворот|угол",
             "без следов / легко снять": r"без следов|не оставля|легко сн",
             "одной рукой / быстро": r"одной рук|быстро|мгновенн|секунд",
             "универсальный / любой телефон": r"любо\w+ (телефон|смартфон)|универсальн|iphone|samsung|android",
             "MagSafe": r"magsafe|магсейф",
             "жара/мороз": r"жар|мороз|температур",
             "подарок": r"подар"}

# ── 2486: словарь жалоб — тот же, что дал 16/12/12% в fresh/comments/_themes.txt (2026-10-06) ───────────────────
COMPLAINTS_2486 = {
    "ломается механизм/шестерни (быстро выходит из строя)": r"слома|развал|сыпл|хруст|вышл[аи] (из|со) стро|шестер|не крути|туго крути|ход тяж|заклин|не провор",
    "ручка: крепление/болты/люфт": r"ручк|рукоят|болтик|фиксатор",
    "подшипники: меньше заявленного/втулки": r"подшипник|потшибник|втулк",
    "укладка лески/зазор/дужка": r"леск|плет[её]н|зазор|укладыв|дужк|скоб",
    "хлипкий пластик/материал": r"хлипк|пластик|пластмас|слаб|мягк",
    "брак/некомплект при получении": r"брак|пришл[аио]? .*сломан|треснут|не тот|не та|нет болт|без ручк|не хватает",
}
PAINS_2486 = {"металл (шпуля / корпус / шестерни)": r"металл|алюмин|сталь|латун",
              "подшипники (число)": r"подшипник",
              "плавный / тихий ход": r"плавн|мягк\w* ход|бесшумн|тих\w* ход|без люфт",
              "фрикцион / тормоз, кг": r"фрикцион|тормоз",
              "запасная шпуля": r"запасн\w* шпул",
              "леска / шнур в комплекте": r"(леск|шнур|плет[её]н)\w*.{0,30}(в комплект|в подарок|намотан)|намотан",
              "ручка: складная / левая-правая / на резьбе": r"складн\w* ручк|ручк\w*.{0,20}(лев|прав|резьб|винт|вкруч|переставн)",
              "антиреверс / мгновенный стоп": r"антиреверс|обратн\w* ход|мгновенн\w* стоп|instant",
              "передаточное число / скорость": r"передаточн|\d[.,]\d\s*:\s*1|скорост",
              "лёгкая / вес": r"л[её]гк|\bвес",
              "подарок": r"подар",
              "морская / солёная вода": r"морск|сол[её]н",
              "гарантия": r"гаранти"}

# ── 729: поводки (рулетки). Словарь жалоб откалиброван по 45 случайным негативам лидеров (pivot/729, 2026-10-11) ────
COMPLAINTS_729 = {
    "заедает / не сматывается лента": r"заеда|застрева|заклин|не (сматыва|скручива|втягива|выдвига|заход)|плохо (сматыв|скручив|заход|втягив)|провиса|перекрут|закручива|глючит",
    "кнопка / стопор / фиксатор": r"кнопк|стопор|тормоз|фиксатор|фиксац|блокир|застопор|регулировк|остановк",
    "лента/трос порвались, собака сорвалась": r"порвал|оборвал|оторвал|перетер|перетёр|лопнул|сорвал|перегрыз",
    "быстро сломался (дни–месяцы)": r"слома|сломан|перестал\w* работ|развалил|треснул|через (недел|месяц|\d)|хватило|прослужил|прожил|продержал",
    "ручка неудобная / тяжёлый корпус": r"ручк|неудобн|не удобн|тяжел|тяжёл|в руке|громоздк",
    "карабин / замок": r"карабин|замоч|замок|защелк|защёлк",
    "хлипкий пластик / не удержит крупную": r"хлипк|пластик|ненад[её]жн|не удерж|крупн\w* собак|рывк|дерга",
    "длина/нагрузка не как заявлено": r"длин|короче|метр|кг\b|вес собак",
    "брак / некомплект / запах": r"брак|не (тот|та) |некомплект|не хватает|запах|воня",
}
PAINS_729 = {"нагрузка до N кг": r"до \d+ ?кг|нагрузк",
             "длина N м": r"\d+ ?м\b|метр",
             "лента (не трос)": r"лент",
             "трос": r"трос",
             "стальная пружина / механизм": r"пружин|механизм",
             "кнопка: одно нажатие / тормоз / фиксатор": r"кнопк|тормоз|фиксатор|блокир|стоп",
             "эргономичная / прорезиненная ручка": r"эргоном|прорезин|ручк",
             "карабин 360° / не перекручивается": r"360|вращ|перекру",
             "светоотражающий": r"светоотраж|отражат",
             "диспенсер для пакетов": r"пакет|диспенсер",
             "ударопрочный ABS": r"abs|ударопроч|прочн\w* пластик",
             "гарантия": r"гаранти",
             "подарок": r"подар"}


def num(s):
    m = re.search(r"\d+(?:[.,]\d+)?", str(s or ""))
    return float(m.group().replace(",", ".")) if m else None


def opt(card: dict, name: str):
    for o in card.get("options", []):
        if o["name"] == name:
            return o["value"]
    return None


def classify_777(name: str, card: dict) -> dict:
    """Копия top100_777.classify (флаги типа крепления)."""
    mount, compat = opt(card, "Тип крепления"), opt(card, "Совместимость")
    t = f"{name} {mount or ''} {compat or ''} {card.get('description', '')[:600]}".lower()
    n = f"{name} {mount or ''}".lower()
    return {"магнит": bool(re.search(r"магнит", n)), "MagSafe": bool(re.search(r"magsafe|магсейф", t)),
            "зарядка": bool(re.search(r"зарядк|беспроводн|qi", n)), "присоска/вакуум": bool(re.search(r"присоск|вакуум", n)),
            "воздуховод": bool(re.search(r"воздуховод|дефлектор|решетк|решётк", n)),
            "панель/торпедо": bool(re.search(r"панел|торпед|приборн", n)),
            "зажим/захват": bool(re.search(r"зажим|захват|клипс|автоматич", n)),
            "на руль/зеркало/подголовник": bool(re.search(r"руль|зеркал|подголов", n))}


def segment_777(row: dict) -> str:
    if row["id"] in SEG_777:
        return "магнит + вакуум (наш сегмент)"
    if row.get("зарядка"):
        return "с зарядкой"
    if row.get("присоска/вакуум"):
        return "присоска + зажим"
    if row.get("магнит"):
        return "магнит"
    if row.get("воздуховод"):
        return "воздуховод"
    return "прочие (зажим и др.)"


def classify_2486(name: str, card: dict) -> dict:
    kind = (opt(card, "Вид катушки") or "").lower()
    n = name.lower()
    t = f"{n} {(card.get('description') or '')[:1500].lower()} {(opt(card, 'Комплектация') or '').lower()}"
    size = num(opt(card, "Размер шпули"))
    if size is None:
        m = re.search(r"\b(\d{3,5})\b", n)
        size = float(m.group(1)) if m and 500 <= int(m.group(1)) <= 12000 else None
    return {"size": size, "bearings": num(opt(card, "Количество подшипников")), "ratio": opt(card, "Передаточное отношение"),
            "kind": kind or None, "weight_g": num(opt(card, "Вес товара без упаковки (г)")),
            "байтраннер": bool(re.search(r"байтран|baitrun|бэйтран", t)),
            "карп/фидер": bool(re.search(r"карп|фидер", n)),
            "мультипликатор": bool(re.search(r"мультипликатор|байткаст|baitcast", n + " " + kind)),
            "инерционная/зимняя": bool(re.search(r"(?<!без)инерцион|зимн|нахлыст|проводочн", n + " " + kind)),
            "ультралайт": bool(re.search(r"ультралайт|микроджиг|мормыш|\bul\b", n)) or (size is not None and size <= 1500),
            "металл": bool(re.search(r"металл\w* (шпул|корпус|шестер|ротор)|алюмини\w* шпул|шпул\w* (из )?(металл|алюмин)", t)),
            "запасная шпуля": bool(re.search(r"запасн\w* шпул|шпул\w* (\d|запас)|2 шпул", t)),
            "леска/шнур": bool(re.search(r"(леск|шнур|плет[её]н)", (opt(card, "Комплектация") or "").lower() + " " + n)),
            "набор 2+ шт": bool(re.search(r"\b2 (шт|катушк)|набор|комплект из 2|2 штуки", t[:400]))}


def segment_2486(row: dict) -> str:
    s = row.get("size")
    if row.get("мультипликатор"):
        return "мультипликатор / байткастинг"
    if row.get("инерционная/зимняя"):
        return "инерционная / зимняя"
    if row.get("байтраннер"):
        return "с байтраннером (фидер/карп)"
    if s is not None and s >= 5000:
        return "крупная 5000+ (фидер/карп/море)"
    if row.get("ультралайт"):
        return "ультралайт ≤ 1500"
    return "спиннинговая 2000–4000"


def classify_729(name: str, card: dict) -> dict:
    n = name.lower()
    t = f"{n} {(card.get('description') or '')[:1500].lower()} {(opt(card, 'Комплектация') or '').lower()}"
    L = num(opt(card, "Длина поводка")) or num(opt(card, "Длина"))
    if L is None:
        m = re.search(r"(\d+(?:[.,]\d)?)\s*(?:м\b|метр)", n)
        L = float(m.group(1).replace(",", ".")) if m else None
    if L is not None and L > 20:                             # «500 см» / «5000 мм»
        L = L / 100 if L <= 2000 else L / 1000
    kg = num(opt(card, "Максимальная нагрузка")) or num(opt(card, "Максимальная нагрузка (кг)"))
    if kg is None:
        m = re.search(r"до\s*(\d+)\s*кг", t)
        kg = float(m.group(1)) if m else None
    rou = bool(re.search(r"рулетк|автоматическ|выдвижн|самосматыв", n))
    return {"рулетка": rou, "length_m": L, "max_kg": kg,
            "лента": bool(re.search(r"лент", n)), "трос": bool(re.search(r"трос|шнур", n)),
            "LED": bool(re.search(r"\bled|фонар|подсветк|светодиод|usb|заряд", t[:600])),
            "крупные": bool(re.search(r"крупн|больш\w* (пород|собак)|до (40|50|60|70)\s*кг", t[:600])),
            "мелкие": bool(re.search(r"мелк|маленьк|миниатюр|кошек|для кош|до (5|8|10|12)\s*кг", t[:600])),
            "двойной": bool(re.search(r"двойн|для двух|на 2 собак", n)),
            "диспенсер": bool(re.search(r"пакет|диспенсер", n)),
            "светоотражающий": bool(re.search(r"светоотраж|отражат", t[:600]))}


def segment_729(row: dict) -> str:
    if not row.get("рулетка"):
        return "обычный поводок / другое"
    if row.get("LED"):
        return "рулетка с фонариком/LED (батарейки — исключено)"
    L = row.get("length_m")
    if L is None:
        return "рулетка, длина не указана"
    if L <= 3.5:
        return "рулетка ≤ 3 м (мелкие)"
    if L <= 5.5:
        return "рулетка 5 м"
    return "рулетка 8+ м"


# ── 2499: наборы для рыбалки. Жалобы откалиброваны по 25 негативам лидеров (pivot/2499, 2026-10-13) ───────────
COMPLAINTS_2499 = {
    "некомплект / не хватает предметов": r"не ?комплект|не полност\w* укомплект|не хватает|нет (\w+ ){0,2}(шумовк|богор|удочк|удилищ|фонар|поводк|ремн)|отсутству|недолож|не было",
    "не соответствует фото / описанию": r"не соответств|не совпада|другое|не то|на фото|картинк|другой фирм",
    "упаковка мятая, всё рассыпано": r"мят|рассыпа|рваная|порван\w* (короб|упаков)|упаковк|коробк\w* (вся|мят|порв)|выпал|как попало",
    "сломано / трещина при получении": r"слома|треснут|трещин|лопнул|сломан",
    "дёшево выглядит / стыдно дарить": r"стыдно|дешев|ужасн\w* качеств|качество ужас|не стоит|за такие деньги|мусор",
    "мелкие / не те снасти": r"мал[ыеа]|мелк|не подход|бесполезн",
    "подарок": r"подар",
}
PAINS_2499 = {"в подарок / подарочная упаковка": r"подар|упаковк|короб",
              "N предметов в наборе": r"\d+ ?(в|предмет)",
              "ящик / органайзер": r"ящик|бокс|органайзер|коробк",
              "для зимней рыбалки": r"зимн",
              "для летней / поплавочной": r"летн|поплав",
              "спиннинг / приманки": r"спиннинг|блесн|воблер|приманк",
              "мужчине / 23 февраля / папе": r"мужчин|папе|муж|23 феврал|отцу"}


def classify_2499(name: str, card: dict) -> dict:
    n = name.lower()
    m = re.search(r"(\d{2,3}) ?(в ?1|предмет)", n)
    return {"items_n": int(m.group(1)) if m else None,
            "подарочный": bool(re.search(r"подар", n)),
            "зимний": bool(re.search(r"зимн|жерлиц|балансир|мормыш", n)),
            "хапуга/каркас": bool(re.search(r"хапуг|каркас|клетк", n)),
            "ящик": bool(re.search(r"ящик|бокс", n)),
            "удочка в комплекте": bool(re.search(r"удочк|удилищ|спиннинг \d|\d[.,]?\d? ?м\b", n)),
            "приманки/блёсны": bool(re.search(r"блесн|воблер|приманк", n)),
            "электроника": bool(re.search(r"камер|эхолот|сигнализатор|фонар", n))}


def segment_2499(row: dict) -> str:
    if row.get("хапуга/каркас"):
        return "хапуга / каркас (габарит)"
    if row.get("электроника"):
        return "электроника (исключено)"
    if row.get("зимний"):
        return "зимний набор"
    if row.get("приманки/блёсны"):
        return "набор приманок / блёсен"
    if row.get("подарочный") or (row.get("items_n") or 0) >= 20:
        return "подарочный набор аксессуаров"
    if row.get("ящик"):
        return "ящик со снастями"
    return "прочие наборы"


# ── 7640: сумки спортивные (2026-10-14). Словарь жалоб — типовой для сумок, проверяется на отзывах лидеров ─────────
COMPLAINTS_7640 = {
    "молния ломается / расходится": r"молни|застежк|застёжк|бегунок|собачк",
    "шов / ручка / ремень оторвались": r"шов|швы|расп[оа]рол|оторвал|отвалил|ручк|ремен|лямк|карабин",
    "меньше, чем на фото / не влезает": r"меньше|маленьк|не влез|не помещ|размер|объем|объём",
    "ткань тонкая / дешёвая": r"тонк|хлипк|дешев|дёшев|ткань|материал|качество",
    "запах": r"запах|воня|пахнет",
    "не соответствует фото / цвет": r"не соответств|на фото|цвет|другой",
    "брак при получении": r"брак|дырк|пятн|грязн",
}
PAINS_7640 = {"отдел для обуви": r"обув", "отдел мокрое/сухое": r"мокр|влажн", "водоотталкивающая": r"водо",
              "объём N л": r"\d+ ?л\b|литр", "ручная кладь / размеры": r"ручн\w* клад|\d+ ?[хx×] ?\d+",
              "регулируемый ремень": r"ремен|через плечо", "карман для телефона/ключей": r"карман"}


def classify_7640(name: str, card: dict) -> dict:
    n = name.lower()
    m = re.search(r"(\d{2}) ?л\b", n)
    return {"liters": int(m.group(1)) if m else None, "дорожная": bool(re.search(r"дорожн|путешеств|ручная кладь|поездок", n)),
            "фитнес": bool(re.search(r"фитнес|тренир|зал", n)), "через плечо": bool(re.search(r"плеч", n)),
            "рюкзак": bool(re.search(r"рюкзак", n)), "поясная": bool(re.search(r"поясн|бананк", n)),
            "бассейн": bool(re.search(r"бассейн|пляж", n)), "обувной отдел": bool(re.search(r"обув", n))}


def segment_7640(row: dict) -> str:
    if row.get("рюкзак"):
        return "рюкзак"
    if row.get("поясная"):
        return "поясная"
    if row.get("бассейн"):
        return "для бассейна/пляжа"
    if row.get("дорожная"):
        return "спорт+дорожная"
    return "спортивная/фитнес"


# ── 52: кошельки (2026-10-15). Словарь жалоб — типовой для кошельков/кожгалантереи, проверяется на отзывах лидеров ───
COMPLAINTS_52 = {
    "не натуральная кожа / дешёвый материал": r"не (натуральн|кож)|кожзам|экокож\w* (а не|вместо)|дерматин|клеёнк|клеенк|пластик|дешев|дёшев",
    "запах": r"запах|воня|пахнет",
    "кнопка / молния сломалась": r"кнопк|молни|застежк|застёжк|замок|магнит",
    "нитки / швы / краска облезла": r"нитк|шов|швы|облез|облуп|стерл|потерт|потёрт|отклеил|расклеил",
    "маленький / карты не влезают": r"маленьк|не влез|не помещ|тесн|карт\w* (не|выпада)|купюр\w* (не|мнут)",
    "не как на фото / цвет": r"не соответств|на фото|цвет|другой",
    "брак / упаковка": r"брак|упаковк|короб|мят",
}
PAINS_52 = {"натуральная кожа": r"натуральн\w* кож", "RFID-защита": r"rfid|защит\w* от (считыв|сканир)",
            "отделения для карт N": r"\d+ ?(карт|отдел)", "монетница на молнии": r"монет", "подарочная упаковка": r"подар",
            "компактный / тонкий": r"компакт|тонк|маленьк", "на кнопке / на молнии": r"кнопк|молни"}


def classify_52(name: str, card: dict) -> dict:
    n = name.lower()
    return {"натуральная кожа": bool(re.search(r"натуральн|кожан|кожи\b", n)) and not re.search(r"эко", n),
            "эко-кожа": bool(re.search(r"эко|искусств|pu\b", n)),
            "картхолдер": bool(re.search(r"картхолдер|визитниц|для карт", n)),
            "обложка паспорт": bool(re.search(r"паспорт|обложк|автодокумент", n)),
            "портмоне/большой": bool(re.search(r"портмоне|больш|клатч|длинн", n)),
            "маленький": bool(re.search(r"маленьк|мини|компакт", n)),
            "женский": bool(re.search(r"женск", n)), "мужской": bool(re.search(r"мужск", n)),
            "подарок": bool(re.search(r"подар", n))}


def segment_52(row: dict) -> str:
    if row.get("обложка паспорт"):
        return "обложка / для документов"
    if row.get("картхолдер"):
        return "картхолдер"
    if row.get("маленький"):
        return "маленький кошелёк"
    if row.get("портмоне/большой"):
        return "портмоне / большой"
    return "кошелёк (прочее)"


PRESETS = {
    777: {
        "name": "Держатели в авто",
        "trends": f"{R7}/strategy777/trends_month.json",
        "products500": f"{R5}/dna/777/products500_2026-07.json",
        "products_30d": f"{R6}/strategy777/products_30d.json",
        "top100_products": f"{R5}/dna/777/top100/top100_products_2026-07.json",
        "top100_json": "data/processed/top100_777_2026-10-05.json",          # src/top100_777.py
        "cards": f"{R5}/dna/777/top100/cards",
        "daily": [f"{R7}/strategy777/daily_long", f"{R5}/dna/777/top100/daily"],
        "price_seg": {"2026-07": f"{R6}/strategy777/price_seg_2026-07.json", "30d": f"{R6}/strategy777/price_seg_30d.json"},
        "kw_year": [f"{R5}/dna/777/keywords_{m}.json" for m in YEAR],
        "kw_30d": f"{R6}/strategy777/keywords_30d.json",
        "kw_peak": (f"{R7}/strategy777/keywords/keywords_2024-12.json", f"{R5}/dna/777/keywords_2025-12.json"),
        "gap_source": None, "gap_min_freq": 1500,                              # None = 30 дней (как 2026-10-06)
        "gap_re": r"магнит|присоск|вакуум|magsafe|магсейф|мagsafe|на панел|торпед|на стекл",
        "core_re": r"держател|подставк\w* для телефона|магнит\w* для телефона|присоск|magsafe|магсейф|крепление для телефона",
        "sku_keywords": f"{R6}/strategy777/sku_*_keywords.json",
        "comments": [f"{R5}/dna/777/comments/*.json", f"{R6}/strategy777/sku_*_comments.json"],
        "sellers": f"{R7}/strategy777/sellers_2026-07.json",
        "complaints": COMPLAINTS_777, "pains": PAINS_777, "classify": classify_777, "segment": segment_777,
        "type_keys": ("магнит", "MagSafe", "присоска/вакуум", "зажим/захват", "воздуховод", "зарядка"),
        "our_segment": "магнит + вакуум (наш сегмент)",
        "winner": 494403950, "winner_file": f"{R5}/dna/777/winners/494403950_by_period.json",
        "product": {"name": "вакуумно-магнитный держатель, совместимый с MagSafe", "price": 1590, "yuan": 18, "vol": 0.4,
                    "kg": 0.15, "buyout": 84.6, "commission": 20.0, "buyer_price": 1000},
        "launch": "2026-12", "first_batch": 300,
    },
    2486: {
        "name": "Катушки рыболовные",
        "trends": f"{R7}/strategy2486/trends_month.json",
        "products500": f"{R7}/strategy2486/products500_2026-07.json",
        "products_30d": f"{R7}/strategy2486/products_30d.json",
        "top100_products": f"{R7}/strategy2486/top100/top100_products_2026-07.json",
        "top100_json": f"data/processed/top100_2486_{RUN}.json",
        "cards": f"{R7}/strategy2486/top100/cards",
        "daily": [f"{R7}/strategy2486/top100/daily"],
        "price_seg": {"2026-07": f"{R7}/strategy2486/price_seg_2026-07.json", "30d": f"{R7}/strategy2486/price_seg_30d.json"},
        "kw_year": [f"{R7}/strategy2486/keywords/keywords_{m}.json" for m in YEAR],
        "kw_30d": f"{R7}/strategy2486/keywords_30d.json",
        "kw_peak": (f"{R7}/strategy2486/keywords/keywords_2025-06.json", f"{R7}/strategy2486/keywords/keywords_2026-06.json"),
        "gap_source": f"{R7}/strategy2486/keywords/keywords_2026-06.json",    # пик сезона: продаём весной–летом
        "gap_min_freq": 1500, "gap_min_results": 300,
        "gap_re": r"безынерцион|спиннинг|3000|2000|4000|2500|металл|ультралайт|микроджиг|мормыш|шпул|недорог|для удочки|поплав|универсал",
        "core_re": r"катушк",
        "sku_keywords": f"{R7}/strategy2486/sku_*_keywords.json",
        "comments": [f"{R7}/strategy2486/comments/*.json"],
        "sellers": f"{R7}/strategy2486/sellers_2026-07.json",
        "complaints": COMPLAINTS_2486, "pains": PAINS_2486, "classify": classify_2486, "segment": segment_2486,
        "type_keys": ("металл", "запасная шпуля", "леска/шнур", "набор 2+ шт"),
        "our_segment": "спиннинговая 2000–4000",
        "winner": None, "winner_file": None,                                   # берём лучшую новую карточку из top-100
        # вариант A (2026-10-07): полоса 1 428–1 609 ₽ — №1 по выручке на продающую карточку; ¥ — допущение до КП
        "product": {"name": "катушка безынерционная 3000: металлическая шпуля, 5+1 реальных подшипников, металлическая ручка "
                            "на резьбе, запасная шпуля", "price": 1590, "yuan": 20, "vol": 1.8, "kg": 0.45, "buyout": 79.0,
                    "commission": 21.0, "buyer_price": 1345},
        "launch": "2027-03", "first_batch": 250,                              # 300 шт съедают весь бюджет при той же прибыли
    },
    729: {
        "name": "Поводки (рулетки)", "run": "2026-10-11",
        "trends": f"{R11}/strategy729/trends_month.json",
        "products500": f"{R11}/strategy729/products500_2026-07.json",
        "products_30d": f"{R11}/strategy729/products_30d.json",
        "top100_products": f"{R11}/strategy729/top100/top100_products_2026-07.json",
        "top100_json": "data/processed/top100_729_2026-10-11.json",
        "cards": f"{R11}/strategy729/top100/cards",
        "daily": [f"{R11}/strategy729/top100/daily"],
        "price_seg": {"2026-07": f"{R11}/strategy729/price_seg_2026-07.json", "30d": f"{R11}/strategy729/price_seg_30d.json"},
        "kw_year": [f"{R11}/strategy729/keywords/keywords_{m}.json" for m in YEAR],
        "kw_30d": f"{R11}/strategy729/keywords_30d.json",
        "kw_peak": (f"{R11}/strategy729/keywords/keywords_2025-04.json", f"{R11}/strategy729/keywords/keywords_2026-04.json"),
        "gap_source": f"{R11}/strategy729/keywords/keywords_2026-04.json",    # пик сезона: март–май
        "gap_min_freq": 1500, "gap_min_results": 300,
        "gap_re": r"рулетк|автоматическ|5 м|8 м|3 м|10 м|крупн|мелк|средн|лент|трос|для собак|прочн|кг",
        "core_re": r"поводок|рулетк",
        "sku_keywords": f"{R11}/strategy729/sku_*_keywords.json",
        "comments": [f"{R11}/pivot/729/comments/*.json", f"{R11}/strategy729/comments/*.json"],
        "sellers": f"{R11}/strategy729/sellers_2026-07.json",
        "complaints": COMPLAINTS_729, "pains": PAINS_729, "classify": classify_729, "segment": segment_729,
        "type_keys": ("лента", "трос", "крупные", "мелкие", "диспенсер"),
        "our_segment": "рулетка 5 м",
        "winner": None, "winner_file": None,
        # уточняется после build (медиана сегмента); ¥ — допущение до КП
        "product": {"name": "поводок-рулетка 5 м, лента, до 25 кг, стальная пружина, кнопка тормоз+фиксатор одним пальцем, "
                            "эргономичная прорезиненная ручка, карабин 360°", "price": 990, "yuan": 11, "vol": 0.9, "kg": 0.3,
                    "buyout": 85.0, "commission": 20.0, "buyer_price": 700},
        "launch": "2027-02", "first_batch": 400,
    },
    2499: {
        "name": "Наборы для рыбалки", "run": "2026-10-13",
        "trends": f"{R13}/strategy2499/trends_month.json",
        "products500": f"{R13}/strategy2499/products500_2026-07.json",
        "products_30d": f"{R13}/strategy2499/products_30d.json",
        "top100_products": f"{R13}/strategy2499/top100/top100_products_2026-07.json",
        "top100_json": "data/processed/top100_2499_2026-10-13.json",
        "cards": f"{R13}/strategy2499/top100/cards",
        "daily": [f"{R13}/strategy2499/top100/daily"],
        "price_seg": {"2026-07": f"{R13}/strategy2499/price_seg_2026-07.json", "30d": f"{R13}/strategy2499/price_seg_30d.json"},
        "kw_year": [f"{R13}/strategy2499/keywords/keywords_{m}.json" for m in YEAR],
        "kw_30d": f"{R13}/strategy2499/keywords_30d.json",
        "kw_peak": (f"{R13}/strategy2499/keywords/keywords_2025-07.json", f"{R13}/strategy2499/keywords/keywords_2026-07.json"),
        "gap_source": f"{R13}/strategy2499/keywords/keywords_2025-12.json",   # новогодний пик подарков
        "gap_min_freq": 1000, "gap_min_results": 100,
        "gap_re": r"подар|набор|мужчин|рыбак|зимн|летн|снаст|ящик|бокс",
        "core_re": r"набор|рыбал|снаст",
        "sku_keywords": f"{R13}/strategy2499/sku_*_keywords.json",
        "comments": [f"{R11}/pivot/2499/comments/*.json", f"{R13}/strategy2499/comments/*.json"],
        "sellers": f"{R13}/strategy2499/sellers_2026-07.json",
        "complaints": COMPLAINTS_2499, "pains": PAINS_2499, "classify": classify_2499, "segment": segment_2499,
        "type_keys": ("подарочный", "ящик", "удочка в комплекте", "зимний"),
        "our_segment": "подарочный набор аксессуаров",
        "winner": None, "winner_file": None,
        "product": {"name": "подарочный набор аксессуаров рыбака в кейсе", "price": 2290, "yuan": 28, "vol": 1.0, "kg": 0.5,
                    "buyout": 70.0, "commission": 21.0, "buyer_price": 2060},     # уточняется после build; ¥ — допущение
        "launch": "2026-12", "first_batch": 200,
    },
    7640: {
        "name": "Сумки спортивные", "run": "2026-10-14",
        "trends": f"{R14}/strategy7640/trends_month.json",
        "products500": f"{R14}/strategy7640/products500_2026-07.json",
        "products_30d": f"{R14}/strategy7640/products_30d.json",
        "top100_products": f"{R14}/strategy7640/top100/top100_products_2026-07.json",
        "top100_json": "data/processed/top100_7640_2026-10-14.json",
        "cards": f"{R14}/strategy7640/top100/cards",
        "daily": [f"{R14}/strategy7640/top100/daily"],
        "price_seg": {"2026-07": f"{R14}/strategy7640/price_seg_2026-07.json", "30d": f"{R14}/strategy7640/price_seg_30d.json"},
        "kw_year": [f"{R14}/strategy7640/keywords/keywords_{m}.json" for m in YEAR],
        "kw_30d": f"{R14}/strategy7640/keywords_30d.json",
        "kw_peak": (f"{R14}/strategy7640/keywords/keywords_2025-07.json", f"{R14}/strategy7640/keywords/keywords_2026-07.json"),
        "gap_source": None, "gap_min_freq": 1500,
        "gap_re": r"сумк|дорожн|спортивн|фитнес|ручная кладь|через плечо|обув",
        "core_re": r"сумк",
        "sku_keywords": f"{R14}/strategy7640/sku_*_keywords.json",
        "comments": [f"{R14}/strategy7640/comments/*.json"],
        "sellers": f"{R14}/strategy7640/sellers_2026-07.json",
        "complaints": COMPLAINTS_7640, "pains": PAINS_7640, "classify": classify_7640, "segment": segment_7640,
        "type_keys": ("дорожная", "фитнес", "через плечо", "обувной отдел"),
        "our_segment": "спорт+дорожная",
        "winner": None, "winner_file": None,
        "product": {"name": "сумка спортивная дорожная", "price": 1590, "yuan": 15, "vol": 1.0, "kg": 0.5,
                    "buyout": 70.0, "commission": 21.0, "buyer_price": 1370},     # уточняется после build; ¥ — допущение
        "launch": "2027-01", "first_batch": 250,
    },
    52: {
        "name": "Кошельки", "run": "2026-10-15",
        "trends": f"{R15}/strategy52/trends_month.json",
        "products500": f"{R15}/strategy52/products500_2026-07.json",
        "products_30d": f"{R15}/strategy52/products_30d.json",
        "top100_products": f"{R15}/strategy52/top100/top100_products_2026-07.json",
        "top100_json": "data/processed/top100_52_2026-10-15.json",
        "cards": f"{R15}/strategy52/top100/cards",
        "daily": [f"{R15}/strategy52/top100/daily"],
        "price_seg": {"2026-07": f"{R15}/strategy52/price_seg_2026-07.json", "30d": f"{R15}/strategy52/price_seg_30d.json"},
        "kw_year": [f"{R15}/strategy52/keywords/keywords_{m}.json" for m in YEAR],
        "kw_30d": f"{R15}/strategy52/keywords_30d.json",
        "kw_peak": (f"{R15}/strategy52/keywords/keywords_2025-12.json", f"{R15}/strategy52/keywords/keywords_2025-12.json"),
        "gap_source": None, "gap_min_freq": 1500,
        "gap_re": r"кошел|портмоне|картхолдер|обложк|кожа|мужск|женск|подар",
        "core_re": r"кошел|портмоне|картхолдер|бумажник",
        "sku_keywords": f"{R15}/strategy52/sku_*_keywords.json",
        "comments": [f"{R15}/strategy52/comments/*.json"],
        "sellers": f"{R15}/strategy52/sellers_2026-07.json",
        "complaints": COMPLAINTS_52, "pains": PAINS_52, "classify": classify_52, "segment": segment_52,
        "type_keys": ("натуральная кожа", "эко-кожа", "женский", "мужской", "подарок"),
        "our_segment": "маленький кошелёк",
        "winner": None, "winner_file": None,
        "product": {"name": "кошелёк", "price": 1290, "yuan": 10, "vol": 0.5, "kg": 0.25,
                    "buyout": 71.0, "commission": 28.0, "buyer_price": 1160},     # ¥ — допущение
        "launch": "2027-01", "first_batch": 300,
    },
}


def load(p):
    return json.load(open(p, encoding="utf-8"))


def rows_of(d):
    return d.get("data", d) if isinstance(d, dict) else d


def filters_cfg() -> dict:
    return yaml.safe_load(open("config/filters.yaml", encoding="utf-8"))


def daily_of(P: dict, sku: int) -> list[dict]:
    for d in P["daily"]:
        f = f"{d}/{sku}.json"
        if os.path.exists(f):
            return sorted(rows_of(load(f)), key=lambda r: r["data"])
    return []


# ── top-100: характеристики карточек + дневные продажи (обобщённый top100_777) ─────────────────────────────────────
def build_top100(niche: int) -> list[dict]:
    P = PRESETS[niche]
    top = sorted(rows_of(load(P["top100_products"])), key=lambda p: -(p.get("revenue") or 0))[:100]
    rows = []
    for rank, p in enumerate(top, 1):
        f = f"{P['cards']}/{p['id']}.json"
        card = load(f) if os.path.exists(f) else {}
        daily = daily_of(P, p["id"])
        win = [r for r in daily if WINDOW[0] <= r["data"] <= WINDOW[1]]
        by_m = collections.defaultdict(list)
        for r in win:
            by_m[r["data"][:7]].append(r)
        msales = {m: sum(r["sales"] or 0 for r in L) for m, L in sorted(by_m.items())}
        ds = [r["sales"] or 0 for r in win]
        mean = st.mean(ds) if ds else 0
        apr, jul = msales.get("2026-04", 0), msales.get("2026-07", 0)
        prices = [r["final_price"] for r in win if r.get("final_price")]
        h, w, dd = (num(opt(card, k)) for k in ("Высота предмета", "Ширина предмета", "Глубина предмета"))
        flags = P["classify"](p["name"], card)
        row = {"rank": rank, "id": p["id"], "name": p["name"], "seller": p.get("seller"), "brand": p.get("brand"),
               "supplier_id": p.get("supplier_id"), "price_jul": p["final_price"], "buyer_price": p.get("final_price_average"),
               "start_price": p.get("start_price"), "basic_sale": p.get("basic_sale"), "spp_avg": p.get("spp_avg"),
               "sales_jul_products": p.get("sales"), "revenue_jul": p.get("revenue"), "buyout": p.get("purchase_after_return"),
               "rating": p.get("rating"), "comments": p.get("comments"), "start": p.get("sku_first_date"),
               "fbs": bool(p.get("is_fbs")), "pics": card.get("media", {}).get("photo_count") or p.get("picscount"),
               "video": bool(card.get("media", {}).get("has_video") if card else p.get("hasvideo")),
               "rich": bool(card.get("has_rich")), "desc_len": len(card.get("description") or ""),
               "item_l": round(h * w * dd / 1000, 2) if h and w and dd else None,
               "kit": opt(card, "Комплектация") or card.get("contents"), "country": opt(card, "Страна производства"),
               **flags, "m_sales": msales, "daily_mean": round(mean, 1),
               "zero_days": sum(1 for x in ds if x == 0), "max_day": max(ds) if ds else 0,
               "growth_jul_apr": round(jul / apr, 2) if apr else None,
               "ads_pct": round(sum(1 for r in win if r.get("in_ads")) / len(win) * 100) if win else None,
               "promo_pct": round(sum(1 for r in win if r.get("in_action")) / len(win) * 100) if win else None,
               "oos_days": sum(1 for r in win if not r.get("balance")),
               "price_min": min(prices) if prices else None, "price_med": st.median(prices) if prices else None,
               "price_max": max(prices) if prices else None,
               "pos_med": st.median([r["search_position_avg"] for r in win if r.get("search_position_avg")] or [0]) or None,
               "reviews_gain": (win[-1]["comments"] - win[0]["comments"]) if win else None,
               "has_card": bool(card), "has_daily": bool(daily)}
        row["segment"] = P["segment"](row)
        rows.append(row)
    return rows


def write_top100(niche: int) -> None:
    rows = build_top100(niche)
    out = PRESETS[niche]["top100_json"]
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    wb = Workbook()
    ws = wb.active
    ws.title = "Топ-100"
    cols = ["#", "Артикул", "Название", "Продавец", "Сегмент", "Цена до СПП ₽", "Цена покуп. ₽", "Продажи апр", "май", "июн", "июл",
            "Ср. в день (апр–июл)", "Рост июл/апр", "Реклама % дней", "Акции % дней", "Дней без остатка", "Поз. в поиске",
            "Рейтинг", "Отзывы", "Старт", "Размер", "Подшипники", "Вес, г", "Товар, л", "Комплектация", "Фото", "Видео", "FBS"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496"), Alignment(wrap_text=True)
    for r in rows:
        m = r["m_sales"]
        ws.append([r["rank"], r["id"], r["name"], r["seller"], r["segment"], r["price_jul"], r["buyer_price"], m.get("2026-04"),
                   m.get("2026-05"), m.get("2026-06"), m.get("2026-07"), r["daily_mean"], r["growth_jul_apr"], r["ads_pct"],
                   r["promo_pct"], r["oos_days"], r["pos_med"], r["rating"], r["comments"], r["start"], r.get("size"),
                   r.get("bearings"), r.get("weight_g"), r.get("item_l"), str(r.get("kit") or "")[:120], r["pics"],
                   "да" if r["video"] else "нет", "FBS" if r["fbs"] else "FBO"])
    ws.freeze_panes = "D2"
    for i, w in enumerate([4, 11, 40, 22, 22, 9, 9, 8, 8, 8, 8, 9, 8, 8, 8, 8, 8, 7, 8, 11, 7, 7, 7, 7, 40, 6, 6, 6], 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    xl = f"reports/top100_{niche}_{PRESETS[niche].get('run', RUN)}.xlsx"
    wb.save(xl)
    print(f"saved {out}, {xl}; карточек с контентом {sum(r['has_card'] for r in rows)}, с дневкой {sum(r['has_daily'] for r in rows)}")


# ── разделы стратегии ───────────────────────────────────────────────────────────────────────────────────────────────
def trends(P: dict) -> dict:
    return {r["label_date"]: r for r in rows_of(load(P["trends"]))}


def overview(P: dict) -> dict:
    t = trends(P)
    jul, may_jul = t["2026-07"], [t[m] for m in ("2026-05", "2026-06", "2026-07")]
    months = [m for m in sorted(t) if "2024-09" <= m <= "2026-07"]
    by_m = collections.defaultdict(list)
    for m in months:
        by_m[m[5:]].append(t[m]["sales"])
    mean_all = st.mean(t[m]["sales"] for m in months)
    season = {mm: round(st.mean(v) / mean_all * 100) for mm, v in sorted(by_m.items())}
    peak = max(season, key=season.get)
    trough = min(season, key=season.get)
    cur = max(m for m in months if m[5:] == peak)                       # последний полный пиковый месяц
    prev = f"{int(cur[:4]) - 1}-{peak}"
    y12 = [m for m in sorted(t) if "2025-08" <= m <= "2026-07"]
    y12p = [m for m in sorted(t) if "2024-08" <= m <= "2025-07"]
    pct = lambda a, b: round((a / b - 1) * 100, 1) if b else None
    return {
        "rev_30d": jul["revenue"], "sales_30d": jul["sales"], "rev_90d": sum(r["revenue"] for r in may_jul),
        "sales_90d": sum(r["sales"] for r in may_jul), "sellers_total": jul["sellers"],
        "sellers_with_sells": jul["sellers_with_sells"], "items": jul["items"], "items_with_sells": jul["items_with_sells"],
        "aov": jul["average_order_value"],
        "rev_12m": sum(t[m]["revenue"] for m in y12), "sales_12m": sum(t[m]["sales"] for m in y12),
        "sales_12m_prev": sum(t[m]["sales"] for m in y12p), "yoy_12m_sales": pct(sum(t[m]["sales"] for m in y12),
                                                                                  sum(t[m]["sales"] for m in y12p)),
        "peak_month": peak, "trough_month": trough, "peak_cur": cur, "peak_prev": prev,
        "trough_to_peak_pct": round(season[trough] / season[peak] * 100),
        "yoy_peak_sales": pct(t[cur]["sales"], t[prev]["sales"]), "yoy_peak_rev": pct(t[cur]["revenue"], t[prev]["revenue"]),
        "yoy_jul_sales": pct(t["2026-07"]["sales"], t["2025-07"]["sales"]),
        "yoy_h1_sales": pct(sum(t[f"2026-0{i}"]["sales"] for i in range(1, 8)), sum(t[f"2025-0{i}"]["sales"] for i in range(1, 8))),
        "yoy_jul_sellers_ws": pct(t["2026-07"]["sellers_with_sells"], t["2025-07"]["sellers_with_sells"]),
        "yoy_jul_items_ws": pct(t["2026-07"]["items_with_sells"], t["2025-07"]["items_with_sells"]),
        "method_break": {m: [t[m]["sales"], t[m].get("sales_estimated"), t[m]["items_with_sells"], t[m]["sellers_with_sells"]]
                         for m in ("2025-08", "2025-09", "2025-10") if m in t},
        "season_index": season,
        "series": {m: [t[m]["sales"], round(t[m]["revenue"] / 1e6, 1), t[m]["items_with_sells"], t[m]["sellers_with_sells"],
                       t[m].get("sales_estimated")] for m in sorted(t) if m >= "2024-09"},
    }


def top100_rows(P: dict) -> list[dict]:
    return sorted(load(P["top100_json"]), key=lambda c: -c["revenue_jul"])


def type_of(P: dict, c: dict) -> str:
    flags = "+".join(k for k in P["type_keys"] if c.get(k))
    return flags if "segment" not in c or P is PRESETS[777] else f"{c['segment']}{' · ' + flags if flags else ''}"


def top20(P: dict) -> list[dict]:
    T = top100_rows(P)
    src = {p["id"]: p for p in rows_of(load(P["top100_products"]))}
    src.update({p["id"]: p for p in rows_of(load(P["products500"]))})
    out = []
    for i, c in enumerate(T[:20], 1):
        p = src.get(c["id"], {})
        out.append({"n": i, "id": c["id"], "name": c["name"], "brand": c["brand"], "seller": c["seller"], "type": type_of(P, c),
                    "revenue": c["revenue_jul"], "sales": c["sales_jul_products"], "price": c["price_jul"],
                    "old_price": p.get("start_price"), "discount": p.get("basic_sale"), "spp": p.get("spp_avg"),
                    "buyer_price": round(c["revenue_jul"] / max(c["sales_jul_products"], 1)),
                    "rating": c["rating"], "comments": c["comments"], "pics": c["pics"], "video": c["video"], "rich": c["rich"],
                    "pos_med": c.get("pos_med"), "ads_pct": c.get("ads_pct"), "oos_days": c.get("oos_days"),
                    "start": c["start"], "growth": c.get("growth_jul_apr")})
    return out


def keywords(P: dict) -> dict:
    """Год (2025-09…2026-08) по месяцам + 30 дней. wb_count = частота, count = товаров в выдаче WB."""
    year = collections.defaultdict(lambda: {"freq": 0, "months": 0, "count": [], "items": []})
    for f in P["kw_year"]:
        if not os.path.exists(f):
            continue
        for q in load(f)["queries"]:
            y = year[q["word"]]
            y["freq"] += q.get("wb_count") or 0
            y["months"] += 1
            y["count"].append(q.get("count") or 0)
            y["items"].append(q.get("items_count") or 0)
            y["cluster"] = q.get("query_cluster")
    last = {q["word"]: q for q in load(P["kw_30d"])["queries"]}
    peak = {q["word"]: q for q in load(P["gap_source"])["queries"]} if P.get("gap_source") else {}
    rows = []
    for w, y in year.items():
        items = st.median(y["items"])
        if items < 20 or y["months"] < 6:
            continue                                            # чужие запросы (мало карточек ниши в выдаче)
        l = last.get(w, {})
        cnt = l.get("count") or st.median(y["count"])
        freq_m = l.get("wb_count") or round(y["freq"] / y["months"])
        r = {"q": w, "cluster": y.get("cluster"), "freq_year": y["freq"], "freq_30d": freq_m, "results": cnt,
             "items_niche": round(items), "deficit": round(freq_m / max(cnt, 1), 2)}
        if peak:
            pk = peak.get(w, {})
            r.update({"freq_peak": pk.get("wb_count"), "results_peak": pk.get("count"),
                      "deficit_peak": round((pk.get("wb_count") or 0) / max(pk.get("count") or 0, 1), 2) if pk else None})
        rows.append(r)
    rows.sort(key=lambda r: -r["freq_year"])
    seg_re = re.compile(P["gap_re"], re.I)
    if P.get("gap_source"):
        gap = [r for r in rows if (r.get("freq_peak") or 0) >= P["gap_min_freq"] and seg_re.search(r["q"])
               and (r.get("results_peak") or 0) >= P.get("gap_min_results", 0)]   # «count» < 300 — WB отдаёт витрину категории
        gap.sort(key=lambda r: -(r.get("deficit_peak") or 0))
    else:
        gap = sorted([r for r in rows if r["freq_30d"] >= P["gap_min_freq"] and seg_re.search(r["q"])], key=lambda r: -r["deficit"])
    return {"top50": rows[:50], "gap": gap[:20], "n_rel": len(rows)}


def positions(P: dict) -> dict:
    out = {}
    for f in glob.glob(P["sku_keywords"]):
        sku = int(re.search(r"sku_(\d+)_", f.replace("\\", "/")).group(1))
        words = load(f)["data"]["words"]
        out[sku] = {w["query"]: {"pos": w.get("avg_position"), "org": w.get("avg_organic_position"),
                                 "ad": w.get("avg_ad_position"), "freq": w.get("wb_count"), "found": w.get("total_found")}
                    for w in words}
    return out


def prices(P: dict, clean: bool = True) -> dict:
    P5 = [p for p in rows_of(load(P["products500"])) if p.get("final_price")]
    rep = None
    if clean:
        P5, rep = clean_items(P5, filters_cfg(), expected_subject=P5[0].get("subject_id"))
    fp = [p["final_price"] for p in P5]
    bp = [p["revenue"] / p["sales"] for p in P5 if p.get("sales")]
    segs = {}
    for tag, f in P["price_seg"].items():
        ps = load(f)
        ps = rows_of(ps)
        tot = sum(r["revenue"] for r in ps)
        segs[tag] = [{"range": r["range"], "items": r["items"], "iws": r["items_with_sells"], "sales": r["sales"],
                      "rev": r["revenue"], "share": round(r["revenue"] / tot * 100, 1),
                      "rev_per_iws": round(r["revenue"] / max(r["items_with_sells"], 1)),
                      "comp_index": round(r["items"] / max(r["revenue"] / 1e6, 0.01))} for r in ps]
    out = {"before_spp": {"min": min(fp), "med": st.median(fp), "mean": round(st.mean(fp)), "max": max(fp)},
           "buyer": {"min": round(min(bp)), "med": round(st.median(bp)), "mean": round(st.mean(bp)), "max": round(max(bp))},
           "segments": segs}
    if rep:
        out["clean"] = {k: rep[k] for k in ("kept", "dropped", "dropped_pct", "reasons", "suspicious")}
    return out


def content(P: dict) -> dict:
    T = top100_rows(P)[:20]
    cards = []
    for c in T:
        f = f"{P['cards']}/{c['id']}.json"
        if os.path.exists(f):
            cards.append(load(f))
    words, pains = collections.Counter(), collections.Counter()
    for c in cards:
        for w in re.findall(r"[а-яёa-z0-9°]+", c["imt_name"].lower()):
            if len(w) > 2:
                words[w] += 1
        d = (c.get("description") or "").lower()
        for k, rx in P["pains"].items():
            if re.search(rx, d):
                pains[k] += 1
    tops = top100_rows(P)
    return {"n": len(cards), "title_words": words.most_common(25), "pains": pains.most_common(),
            "pics_med_top20": st.median(c["pics"] or 0 for c in T), "video_top20": sum(bool(c["video"]) for c in T),
            "rich_top20": sum(bool(c["rich"]) for c in T), "pics_med_top100": st.median(c["pics"] or 0 for c in tops),
            "video_top100": sum(bool(c["video"]) for c in tops), "rich_top100": sum(bool(c["rich"]) for c in tops),
            "titles": [c["imt_name"] for c in cards]}


def complaints(P: dict) -> dict:
    files = {}
    for g in P["comments"]:
        for f in glob.glob(g):
            files[int(re.findall(r"(\d{6,})", os.path.basename(f))[0])] = f
    per, pooled, total = {}, collections.Counter(), 0
    quotes = collections.defaultdict(list)
    for sku, f in files.items():
        c = load(f)["comments"]
        neg = [x for x in c if x["valuation"] <= 3 and (x.get("text") or "").strip() and x["date"] >= COMMENTS_SINCE]
        total += len(neg)
        hit = collections.Counter()
        for x in neg:
            t = x["text"].lower()
            for k, rx in P["complaints"].items():
                if re.search(rx, t):
                    hit[k] += 1
                    if len(quotes[k]) < 3 and len(x["text"]) > 25:
                        quotes[k].append(x["text"][:140].replace("\n", " "))
        pooled.update(hit)
        per[sku] = {"reviews": len(c), "neg365": len(neg), "neg_pct": round(len(neg) / max(len(c), 1) * 100, 1),
                    "top": hit.most_common(3)}
    return {"per_sku": per, "total_neg": total,
            "themes": [(k, v, round(v / max(total, 1) * 100)) for k, v in pooled.most_common()], "quotes": dict(quotes)}


def winner_series(P: dict) -> tuple[int | None, list[dict]]:
    if P.get("winner_file"):
        return P["winner"], sorted(load(P["winner_file"]), key=lambda r: r["data"])
    T = [c for c in top100_rows(P) if COHORT[0] <= (c.get("start") or "") <= COHORT[1]]
    for c in T:                                         # лучшая новая карточка по выручке июля с дневкой
        d = daily_of(P, c["id"])
        if d:
            return c["id"], d
    return None, []


def barriers(P: dict) -> dict:
    T = top100_rows(P)
    top10 = T[:10]
    seg = [c for c in T if (c.get("segment") or segment_777(c)) == P["our_segment"]]
    new = [c for c in T if (c["start"] or "") >= "2025-10-01"]
    wid, w = winner_series(P)
    first = next((r["data"] for r in w if (r.get("sales") or 0) > 0), None)
    hit10 = next((r["data"] for r in w if first and r["data"] >= first and (r.get("sales") or 0) >= 10), None)
    hit30 = next((r["data"] for r in w if first and r["data"] >= first and (r.get("sales") or 0) >= 30), None)
    com_at = {r["data"]: r.get("comments") for r in w}
    return {"reviews_top10_med": st.median(c["comments"] for c in top10),
            "reviews_seg_med": st.median(c["comments"] for c in seg) if seg else None,
            "reviews_top100_min": min(c["comments"] for c in T),
            "new_cards_in_top100": len(new), "new_cards_share": round(sum(c["revenue_jul"] for c in new) /
                                                                       sum(c["revenue_jul"] for c in T) * 100, 1),
            "ads_med_top100": st.median(c.get("ads_pct") or 0 for c in T),
            "winner": {"id": wid, "first_sale": first, "day10": hit10, "day30": hit30,
                       "reviews_at_10": com_at.get(hit10), "reviews_at_30": com_at.get(hit30), "series_len": len(w)}}


def cost_rub(yuan: float, kg: float, vol: float | None = None) -> tuple[float, float]:
    """→ (себестоимость 1 шт до ФФ ₽, часть «не от ¥»). С объёмом и секцией cargo в схеме — модель карго YUANEXIM (src.cargo):
    ¥ × курс + коробка карго / шт; иначе старая модель ¥ × 17 (+ $2/кг сверх 0,5 кг)."""
    c = econ_config().get("cargo") if vol is not None else None
    if c:
        from src.cargo import per_unit
        u = per_unit(yuan, kg, vol, c=c)
        return u["landed_rub"], u["cargo_rub"]
    extra = max(0.0, kg - BASE_KG) * CARGO_USD_KG * FX
    return yuan * YUAN_RUB + extra, extra


def rub_per_yuan() -> float:
    c = econ_config().get("cargo")
    return c["cny_to_rub"] * (1 + c.get("agent_pct", 0) / 100) if c else YUAN_RUB


def econ_config() -> dict:
    """Текущая схема бизнеса (ИП Армения, FBS «Свой склад РФ», налог 10 %, ДРР от заказов) — config/scheme_am_fbs.yaml.
    До 2026-10-15 здесь был load_config() = СЦ Ереван (tariffs_auto) — старые отчёты считались по нему."""
    return load_scheme("am_fbs")


def econ(P: dict, prod: dict) -> dict:
    """prod: price, yuan, vol, kg, buyout, commission, buyer_price [+ orders_day — заказов/день P50: тогда ФФ
    (fixed_month_rub) делится на ожидаемые продажи и входит в маржу и в max ¥]."""
    cfg = econ_config()
    t = cfg["targets"]
    fixed_m = cfg.get("fixed_month_rub", FIXED)
    price, yuan, vol = prod["price"], prod["yuan"], prod["vol"]
    cost, extra = cost_rub(yuan, prod.get("kg", 0.3), vol)
    sold_m = (prod.get("orders_day") or 0) * 30 * prod["buyout"] / 100
    ff = round(fixed_m / sold_m, 1) if sold_m else 0.0
    kw = dict(buyout_pct=prod["buyout"], commission_pct=prod["commission"], ad_share_of_revenue_pct=DRR_BASE, packaging_rub=PACK)
    out = {}
    rows = [("старт ДРР 25%", price, 25.0, 0.0), ("база ДРР 15%", price, 15.0, 0.0), ("зрелость ДРР 10%", price, 10.0, 0.0),
            ("цена −15%", round(price * 0.85), 15.0, 0.0),
            (f"СПП-сценарий (от цены покупателя {prod['buyer_price']} ₽)", prod["buyer_price"], 15.0, 0.0)]
    if ff:
        rows.append((f"база ДРР 15% + ФФ {ff:.0f} ₽/шт (при {prod['orders_day']} заказов/день)", price, 15.0, ff))
    for tag, pr, drr, fx in rows:
        e = unit_economics(pr, cost, vol, cfg, **{**kw, "ad_share_of_revenue_pct": drr, "fixed_per_unit_rub": fx})
        out[tag] = {**{k: e[k] for k in ("price", "commission", "acquiring", "logistics_with_returns", "storage", "goods_cost_full",
                                         "ads", "tax", "fixed_per_unit", "net_profit", "net_margin_pct", "roi_on_goods_pct",
                                         "breakeven_price")},
                    "yuan": yuan}

    def max_cost(fx: float) -> float:
        lo, hi = 0.0, float(price)
        for _ in range(50):
            mid = (lo + hi) / 2
            e = unit_economics(price, mid + extra, vol, cfg, with_breakeven=False, **{**kw, "fixed_per_unit_rub": fx})
            ok = e["net_margin_pct"] >= t["min_net_margin_pct"] and e["roi_on_goods_pct"] >= t["min_roi_on_cost_pct"]
            lo, hi = (mid, hi) if ok else (lo, mid)
        return lo

    lo, lo_ff = max_cost(0.0), max_cost(ff)
    out["max_cost_rub"] = round(lo)
    out["max_yuan"] = round(lo / rub_per_yuan(), 1)                 # без ФФ (как в отчётах до 2026-10-15)
    out["max_yuan_with_ff"] = round(lo_ff / rub_per_yuan(), 1) if ff else None
    out["ff_per_unit"] = ff
    out["cargo_extra_rub"] = round(extra)
    out["fixed_month_rub"] = fixed_m
    out["breakeven_units_month"] = round(fixed_m / out["база ДРР 15%"]["net_profit"]) if out["база ДРР 15%"]["net_profit"] > 0 else None
    out["tariffs_source"] = cfg.get("_tariffs_source")
    return out


# ── новые общие секции (2026-10-07) ─────────────────────────────────────────────────────────────────────────────────
def concentration(P: dict) -> dict:
    t = trends(P)["2026-07"]
    S = sorted(rows_of(load(P["sellers"])), key=lambda r: -(r.get("revenue") or 0))
    share = lambda xs, key, tot: round(sum(x.get(key) or 0 for x in xs) / tot * 100, 1) if tot else None
    T = top100_rows(P)
    tot100 = sum(c["revenue_jul"] for c in T)
    by_s = collections.Counter()
    for c in T:
        by_s[c["seller"]] += c["revenue_jul"]
    sh = sorted((v / tot100 * 100 for v in by_s.values()), reverse=True)
    top3_sellers = [c["seller"] for c in T[:3]]
    return {"niche_rev_jul": t["revenue"], "sellers_rows": len(S),
            "top1_seller": S[0].get("name") if S else None,
            "top1_niche_pct": share(S[:1], "revenue", t["revenue"]), "top10_niche_pct": share(S[:10], "revenue", t["revenue"]),
            "top1_niche_pct_est": share(S[:1], "revenue_estimated", t.get("revenue_estimated")),
            "top10_niche_pct_est": share(S[:10], "revenue_estimated", t.get("revenue_estimated")),
            "top100_sellers": len(by_s), "top1_top100_pct": round(sh[0], 1), "top10_top100_pct": round(sum(sh[:10]), 1),
            "top3_cards_one_seller": len(set(top3_sellers)) == 1, "top3_sellers": top3_sellers,
            "top_sellers": [(x.get("name"), x.get("revenue"), x.get("items_with_sells")) for x in S[:10]]}


def yoy_check(P: dict) -> dict:
    """Спрос в поиске (wb_count) в пиковый месяц год к году — вторая сторона к YoY продаж (методика Saleflow сменилась 2025-09)."""
    prev_f, cur_f = P["kw_peak"]
    if not (os.path.exists(prev_f) and os.path.exists(cur_f)):
        return {"error": "нет файлов keywords пикового месяца"}
    core = re.compile(P["core_re"], re.I)
    a = {q["word"]: q.get("wb_count") or 0 for q in load(prev_f)["queries"] if core.search(q["word"])}
    b = {q["word"]: q.get("wb_count") or 0 for q in load(cur_f)["queries"] if core.search(q["word"])}
    both = set(a) & set(b)
    top = sorted(both, key=lambda w: -(a[w] + b[w]))[:30]
    pct = lambda x, y: round((x / y - 1) * 100, 1) if y else None
    t = trends(P)
    m_prev, m_cur = re.search(r"(\d{4}-\d{2})\.json$", prev_f).group(1), re.search(r"(\d{4}-\d{2})\.json$", cur_f).group(1)
    return {"months": [m_prev, m_cur], "queries_prev": len(a), "queries_cur": len(b), "matched": len(both),
            "sum_prev_all": sum(a.values()), "sum_cur_all": sum(b.values()), "yoy_all_pct": pct(sum(b.values()), sum(a.values())),
            "sum_prev_matched": sum(a[w] for w in both), "sum_cur_matched": sum(b[w] for w in both),
            "yoy_matched_pct": pct(sum(b[w] for w in both), sum(a[w] for w in both)),
            "top_queries": [(w, a[w], b[w], pct(b[w], a[w])) for w in top[:15]],
            "sales_yoy_pct": pct(t[m_cur]["sales"], t[m_prev]["sales"]),
            "sales_est_cur": t[m_cur].get("sales_estimated"), "sales_prev": t[m_prev]["sales"]}


def entry_curves(P: dict, season: dict) -> dict:
    """Новые карточки top-100 (старт COHORT): заказов/день по 30-дневным месяцам от первой продажи, делённые на индекс
    сезона календарного месяца. Только до 2026-07-31 (дальше Saleflow неполный). Ошибка выжившего: это победители."""
    T = [c for c in top100_rows(P) if COHORT[0] <= (c.get("start") or "") <= COHORT[1]]
    curves, used = {}, []
    import datetime as dt
    for c in T:
        d = [r for r in daily_of(P, c["id"]) if r["data"] <= WINDOW[1]]
        first = next((r["data"] for r in d if (r.get("sales") or 0) > 0), None)
        if not d or not first or first < c["start"][:10] or d[0]["data"] > c["start"][:10]:
            continue                                     # дневка не покрывает старт карточки
        f0 = dt.date.fromisoformat(first)
        by_day = {r["data"]: r.get("sales") or 0 for r in d}
        cur = []
        for k in range(12):
            a, b = f0 + dt.timedelta(days=30 * k), f0 + dt.timedelta(days=30 * k + 29)
            if b.isoformat() > WINDOW[1]:
                break
            mid = (a + dt.timedelta(days=15)).strftime("%m")
            s = sum(by_day.get((a + dt.timedelta(days=i)).isoformat(), 0) for i in range(30)) / 30
            cur.append(round(s / (season[mid] / 100), 2))
        if cur:
            curves[c["id"]] = cur
            used.append({"id": c["id"], "start": c["start"][:10], "first_sale": first, "months": len(cur), "curve": cur,
                         "segment": c.get("segment")})
    pct = {}
    for k in range(12):
        vals = sorted(v[k] for v in curves.values() if len(v) > k)
        if len(vals) >= 5:
            q = lambda p: round(vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))], 1)
            pct[k + 1] = {"n": len(vals), "p25": q(0.25), "p50": q(0.5), "p75": q(0.75)}
    return {"cohort": len(T), "with_daily": len(curves), "percentiles": pct, "cards": used}


def newcomer_levels(P: dict, season: dict, curves: dict, band: tuple[float, float] | None = None) -> dict:
    """Уровень спроса новичка без ошибки выжившего top-100: новые карточки (старт 2025-10 … 2026-04) в products500 июля
    в ценовой полосе товара (цена до СПП −18 … +13%), заказов/день, делённые на индекс сезона июля.
    Форма разгона — из P50 траекторий top-100 (монотонно, не выше 1)."""
    R = sorted(rows_of(load(P["products500"])), key=lambda p: -(p.get("revenue") or 0))
    new = [p for p in R if "2025-10-01" <= (p.get("sku_first_date") or "") <= "2026-04-30"
           and (band is None or band[0] <= (p.get("final_price") or 0) < band[1])]
    k = season["07"] / 100
    d = sorted((p.get("sales") or 0) / 31 / k for p in new)
    q = lambda p: round(d[min(len(d) - 1, int(round(p * (len(d) - 1))))], 1) if d else None
    pc = curves["percentiles"]
    p50 = [pc[i]["p50"] if i in pc else None for i in range(1, 7)]
    known = [v for v in p50[3:6] if v is not None]
    plateau = st.mean(known) if known else None
    shape, best = [], 0.0
    for v in p50:
        if v is not None and plateau:
            best = max(best, min(1.0, v / plateau))
        shape.append(round(best or 1.0, 2))
    return {"band": [round(x) for x in band] if band else None, "n_new_top500": len(new),
            "rank500_per_day": round((R[-1].get("sales") or 0) / 31, 1),
            "p25": q(0.25), "p50": q(0.5), "p75": q(0.75), "winners_plateau_p50": round(plateau, 1) if plateau else None,
            "shape": shape + [1.0] * 6, "season_jul": season["07"]}


def price_basis(P: dict) -> dict:
    """Проверка смысла полей цены на top-100 июля."""
    R = [p for p in rows_of(load(P["top100_products"])) if p.get("sales") and p.get("final_price")]
    dev = [abs((p.get("final_price_average") or 0) - p["revenue"] / p["sales"]) / (p["revenue"] / p["sales"]) for p in R]
    seller = [p["final_price"] / (p["start_price"] * (1 - p["basic_sale"] / 100)) for p in R
              if p.get("start_price") and p.get("basic_sale") is not None and p["basic_sale"] < 100]
    spp_real = [1 - (p["revenue"] / p["sales"]) / p["final_price"] for p in R]
    return {"n": len(R), "avg_vs_rev_per_unit_dev_med_pct": round(st.median(dev) * 100, 2),
            "final_vs_start_x_discount_med": round(st.median(seller), 3),
            "spp_realized_med_pct": round(st.median(spp_real) * 100, 1),
            "spp_avg_reported_med_pct": st.median(p.get("spp_avg") or 0 for p in R),
            "seller_price_med": st.median(p["final_price"] for p in R),
            "buyer_price_med": round(st.median(p["revenue"] / p["sales"] for p in R))}


def segments(P: dict) -> list[dict]:
    T = top100_rows(P)
    tot = sum(c["revenue_jul"] for c in T)
    g = collections.defaultdict(list)
    for c in T:
        g[c.get("segment") or segment_777(c)].append(c)
    out = []
    for s, L in g.items():
        out.append({"segment": s, "n": len(L), "rev": sum(c["revenue_jul"] for c in L),
                    "share": round(sum(c["revenue_jul"] for c in L) / tot * 100, 1),
                    "rev_per_card": round(sum(c["revenue_jul"] for c in L) / len(L)),
                    "price_med": st.median(c["price_jul"] for c in L),
                    "buyer_med": round(st.median(c["revenue_jul"] / max(c["sales_jul_products"], 1) for c in L)),
                    "sales_med": st.median(c["sales_jul_products"] or 0 for c in L),
                    "new": sum(1 for c in L if (c["start"] or "") >= "2025-10-01"),
                    "rating_med": st.median(c["rating"] or 0 for c in L),
                    "buyout_med": st.median(c.get("buyout") or 0 for c in L) if L[0].get("buyout") is not None else None})
    return sorted(out, key=lambda r: -r["rev"])


def build(niche: int, clean: bool = True, product: dict | None = None) -> dict:
    P = PRESETS[niche]
    ov = overview(P)
    D = {"niche": niche, "name": P["name"], "run": P.get("run", RUN), "overview": ov, "top20": top20(P), "keywords": keywords(P),
         "positions": positions(P), "prices": prices(P, clean), "content": content(P), "complaints": complaints(P),
         "barriers": barriers(P), "concentration": concentration(P), "yoy_check": yoy_check(P),
         "entry_curves": entry_curves(P, ov["season_index"]), "price_basis": price_basis(P), "segments": segments(P)}
    prod = product or P.get("product")
    band = (prod["price"] * 0.82, prod["price"] * 1.13) if prod else None
    D["newcomer_levels"] = newcomer_levels(P, ov["season_index"], D["entry_curves"], band)
    D["newcomer_levels_all"] = newcomer_levels(P, ov["season_index"], D["entry_curves"])
    if prod:
        D["product"] = prod
        D["econ"] = econ(P, prod)
    return D


# ── регрессия 777 против отчёта 2026-10-06 ───────────────────────────────────────────────────────────────────────────
def check(niche: int) -> None:
    global econ_config
    old = load("data/processed/strategy777_2026-10-06.json")
    cur, econ_config = econ_config, load_config         # отчёт 2026-10-06 считался по старой схеме (СЦ Ереван, налог 6 %)
    try:
        new = json.loads(json.dumps(build(niche, clean=False), ensure_ascii=False, default=str))
    finally:
        econ_config = cur
    o, n = old["overview"], new["overview"]
    pairs = [(o[k], n[k]) for k in ("rev_30d", "sales_30d", "rev_90d", "sales_90d", "sellers_total", "sellers_with_sells",
                                    "items", "items_with_sells", "aov", "yoy_jul_sales", "yoy_h1_sales", "season_index")]
    pairs += [(o["yoy_peak_dec_sales"], n["yoy_peak_sales"]), (o["yoy_peak_dec_rev"], n["yoy_peak_rev"])]
    rename = lambda r: {("items_niche" if kk == "items_777" else kk): v for kk, v in r.items()}
    for k in ("top20", "keywords", "positions", "content", "complaints", "barriers", "econ"):
        a, b = old[k], new[k]
        if k == "keywords":
            a = {kk: [rename(r) for r in v] if isinstance(v, list) else v for kk, v in a.items()}
        if k == "positions":                             # «found» (товаров в выдаче) — новое поле
            b = {s: {q: {kk: v for kk, v in w.items() if kk != "found"} for q, w in ws.items()} for s, ws in b.items()}
        if k == "barriers":
            b = {**{kk: v for kk, v in b.items() if kk != "winner"},
                 "winner_494403950": {kk: v for kk, v in b["winner"].items() if kk != "id"}}
        if k == "econ":                                  # ярлык СПП-сценария отличается пробелом в «1 000» — сверяем по порядку
            new_keys = ("cargo_extra_rub", "max_yuan_with_ff", "ff_per_unit")      # поля, добавленные после 2026-10-06
            a = list(a.values())
            b = [{x: y for x, y in v.items() if x not in ("acquiring", "fixed_per_unit")} if isinstance(v, dict) else v
                 for kk, v in b.items() if kk not in new_keys]
        pairs.append((a, b))
    a, b = old["prices"], new["prices"]
    pairs.append(({kk: a[kk] for kk in ("before_spp", "buyer", "segments")}, {kk: b[kk] for kk in ("before_spp", "buyer", "segments")}))
    bad = [(i, x, y) for i, (x, y) in enumerate(pairs) if json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)
           != json.dumps(y, sort_keys=True, ensure_ascii=False, default=str)]
    print(f"проверено блоков: {len(pairs)}; расхождений: {len(bad)}")
    for i, x, y in bad:
        xs, ys = json.dumps(x, ensure_ascii=False, default=str), json.dumps(y, ensure_ascii=False, default=str)
        j = next((q for q in range(min(len(xs), len(ys))) if xs[q] != ys[q]), min(len(xs), len(ys)))
        print(f"  блок {i}: было …{xs[max(0, j - 80):j + 120]}\n           стало …{ys[max(0, j - 80):j + 120]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["top100", "build", "check"])
    ap.add_argument("--niche", type=int, required=True)
    ap.add_argument("--no-clean", action="store_true")
    ap.add_argument("--price", type=float)
    ap.add_argument("--yuan", type=float)
    ap.add_argument("--vol", type=float)
    ap.add_argument("--kg", type=float)
    ap.add_argument("--buyout", type=float)
    ap.add_argument("--commission", type=float)
    ap.add_argument("--buyer-price", type=float)
    ap.add_argument("--product-name")
    a = ap.parse_args()
    if a.cmd == "top100":
        write_top100(a.niche)
        return
    if a.cmd == "check":
        check(a.niche)
        return
    prod = None
    if a.price:
        prod = {"name": a.product_name, "price": a.price, "yuan": a.yuan, "vol": a.vol, "kg": a.kg, "buyout": a.buyout,
                "commission": a.commission, "buyer_price": a.buyer_price}
    D = build(a.niche, clean=not a.no_clean, product=prod)
    out = f"data/processed/strategy_{a.niche}_{PRESETS[a.niche].get('run', RUN)}.json"
    json.dump(D, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
