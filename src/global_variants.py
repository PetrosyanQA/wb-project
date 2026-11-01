"""Варианты товара, которые продаются за рубежом, но которых нет (или мало) на WB (01.11.2026).

    python -m src.global_variants fetch          # поиск Amazon по каждой нише (Bright Data, 1 запрос на нишу, кэш)
    python -m src.global_variants gaps           # признаки вариантов: доля на Amazon (по отзывам) против доли на WB (топ-500 ниши)

Ниши — из отбора v7 (спрос на WB доказан, экономика проходит). Признак варианта (комплект, чехол, подставка, Type-C, подсветка,
«2 в 1», подогрев…) ищется в названиях Amazon и в названиях/описаниях карточек WB. Пробел = на Amazon у признака ≥ 15 % отзывов
ниши и ≥ 1 000 отзывов, а на WB он есть у < 5 % карточек топ-500. Магниты помечаются (нам нельзя).
→ data/processed/global_variants_<дата>.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
DAY = dt.date.today().isoformat()
OUT = f"data/processed/global_variants_{DAY}.json"
RAW = f"data/raw/brightdata/{DAY}"
P500 = "data/raw/saleflow/2026-11-01/p500"
from src.datastore import PRODUCT_DIRS  # noqa: E402
OLD = PRODUCT_DIRS["2026-07"]

NICHES = [  # (id ниши WB, название, запрос Amazon)
    (9020, "Корректор осанки / пояс для спины", "posture corrector"),
    (3851, "Походный душ", "portable camping shower"),
    (2012, "Автопылесос", "cordless car vacuum"),
    (942, "Домики для животных", "cat house bed"),
    (1545, "Чехол для гладильной доски", "ironing board cover"),
    (1370, "Москитная сетка", "window screen mosquito net"),
    (811, "Ножи кухонные", "kitchen knife set"),
    (1717, "Триммер женский", "bikini trimmer women"),
    (1142, "Петличный микрофон", "wireless lavalier microphone"),
    (7048, "Опоры для растений", "plant support stakes"),
    (5595, "Матрас для автомобиля", "car air mattress"),
    (804, "Наборы для поделок", "craft kit for girls"),
    (824, "Разделочные доски", "cutting board set"),
    (8551, "Комплекты украшений", "jewelry set for women"),
    (503, "Решётки для гриля", "grill basket"),
    (2294, "Отвёртки", "precision screwdriver set"),
    (2999, "Куртки для собак", "dog winter coat"),
    (511, "Термосы", "vacuum insulated thermos"),
    (6370, "Автоинструменты (дымогенератор и др.)", "car smoke machine leak detector"),
    (462, "Насос спортивный / электронасос", "electric air pump portable"),
    (620, "Бритва электрическая", "electric shaver for men"),
    (437, "Кисти для макияжа (контроль)", "makeup brush set"),
]

FEAT = {  # признак: (regex Amazon, regex WB)
    "чехол/кейс/сумка": (r"\bcase\b|carrying|storage bag|pouch|travel bag", r"чехол|кейс|сумк|футляр|пенал|мешоч"),
    "подставка/держатель/док": (r"\bstand\b|holder|dock|base\b|mount", r"подставк|держател|док-станц|крепл"),
    "аккумулятор / Type-C": (r"rechargeable|usb-?c|type-?c|cordless", r"аккумулят|type-?c|usb|беспровод"),
    "подсветка / LED": (r"\bled\b|light\b|lamp", r"подсветк|\bled\b|свет"),
    "приложение / смарт": (r"\bapp\b|smart|bluetooth", r"приложен|смарт|bluetooth|блютуз"),
    "водонепроницаемый": (r"waterproof|ipx\d", r"водонепрониц|влагозащ|ipx"),
    "складной / компактный": (r"foldable|collapsible|portable|compact", r"складн|портатив|компакт"),
    "подарочная коробка": (r"gift box|gift set|gifts? for", r"подароч"),
    "сменные / запасные": (r"refill|replacement|extra blades|spare", r"сменн|запасн"),
    "подогрев / тепло": (r"heated|heating|warm(ing|er)", r"подогрев|нагрев|тепл"),
    "массаж": (r"massag", r"массаж"),
    "дисплей / цифровой": (r"digital|display|lcd", r"дисплей|цифров|экран"),
    "нержавеющая сталь": (r"stainless", r"нержав"),
    "силикон": (r"silicone", r"силикон"),
    "бамбук / дерево": (r"bamboo|wood(en)?|acacia|walnut", r"бамбук|дерев|акаци|орех"),
    "именной / гравировка": (r"personali[sz]ed|custom|engrav", r"именн|гравир|персонал"),
    "N в 1 (многофункц.)": (r"\b\d\s?-?in-?\s?1\b", r"\d\s?в\s?1"),
    "регулируемый": (r"adjustable", r"регулир"),
    "набор/комплект (несколько предметов)": (r"\bset\b|\bkit\b|bundle|\d+\s?(pcs|pack|piece)", r"набор|комплект|\d+\s?шт"),
    "магнит (нам нельзя)": (r"magnet", r"магнит"),
}


def fetch_all() -> None:
    from src.brightdata_client import BudgetStop, fetch
    for sid, nm, q in NICHES:
        slug = re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")[:40]
        try:
            fetch(f"https://www.amazon.com/s?k={requests.utils.quote(q)}", f"amz_s_{slug}")
            print(f"{sid} {q}: ok")
        except BudgetStop:
            raise
        except BaseException as e:                                           # noqa: BLE001 — fetch может вызвать SystemExit
            print(f"{sid} {q}: ошибка {str(e)[:120]}")


def parse(q: str) -> list[dict]:
    slug = re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")[:40]
    p = next((f"data/raw/brightdata/{d}/amz_s_{slug}.html" for d in sorted(os.listdir("data/raw/brightdata"), reverse=True)
              if os.path.exists(f"data/raw/brightdata/{d}/amz_s_{slug}.html")), None)
    if not p:
        return []
    html = open(p, encoding="utf-8", errors="ignore").read()
    out = {}
    for b in html.split('data-component-type="s-search-result"')[1:]:
        g = lambda rx: (re.findall(rx, b) or [None])[0]                       # noqa: E731
        asin = g(r'data-asin="(\w+)"')
        t = g(r'<h2[^>]*aria-label="([^"]+)"') or g(r'<span class="a-size-[^"]*a-text-normal"[^>]*>([^<]+)<') or ""
        rv = (g(r'aria-label="([\d,]+) ratings?"') or "0").replace(",", "")
        bm = (g(r'([\d.,]+K?)\+? bought in past month') or "0").replace(",", "")
        bm = float(bm[:-1]) * 1000 if bm.endswith("K") else float(bm or 0)
        if asin and asin not in out:
            out[asin] = {"asin": asin, "title": re.sub(r"^Sponsored Ad - ", "", t), "price": g(r'a-offscreen">\$?([\d.,]+)<'),
                         "reviews": int(rv or 0), "bought": bm, "img": g(r'class="s-image"[^>]+src="([^"]+)"')}
    return list(out.values())


def wb_rows(sid: int) -> list[dict]:
    for p in [f"{P500}/{sid}.json"] + [f"{d}/{sid}.json" for d in OLD]:
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            return [r for r in ((d.get("data") if isinstance(d, dict) else d) or []) if r.get("sales")]
    return []


def wb_text(r: dict) -> str:
    c = f"data/raw/wb_cdn/{r['id']}.json"
    desc = ""
    if os.path.exists(c):
        j = json.load(open(c, encoding="utf-8"))
        desc = (j.get("description") or "") + " " + " ".join(str(o.get("value")) for o in j.get("options") or [])
    return (r["name"] + " " + desc).lower()


def gaps() -> None:
    res = []
    for sid, nm, q in NICHES:
        am = parse(q)
        wb = wb_rows(sid)
        if not am or not wb:
            print(f"{sid} {nm}: нет данных (Amazon {len(am)}, WB {len(wb)})")
            continue
        tot_rv = sum(a["reviews"] for a in am) or 1
        wtx = [wb_text(r) for r in wb]
        wb_sales = sum(r["sales"] for r in wb) or 1
        feats = []
        for f, (ra, rw) in FEAT.items():
            A = [a for a in am if re.search(ra, a["title"], re.I)]
            a_rv = sum(a["reviews"] for a in A)
            W = [r for r, t in zip(wb, wtx) if re.search(rw, t)]
            w_share = len(W) / len(wb) * 100
            w_sales = sum(r["sales"] for r in W) / wb_sales * 100
            feats.append(dict(feat=f, am_items=len(A), am_rv=a_rv, am_share=round(a_rv / tot_rv * 100), am_bought=sum(a["bought"] for a in A),
                              wb_cards=len(W), wb_share=round(w_share, 1), wb_sales_share=round(w_sales, 1),
                              gap=a_rv >= 1000 and a_rv / tot_rv >= 0.15 and w_share < 5,
                              weak=a_rv >= 1000 and a_rv / tot_rv >= 0.15 and 5 <= w_share < 15,
                              examples=[f"{a['title'][:80]} — ${a['price']}, {a['reviews']} отз., {int(a['bought'])}+/мес" for a in sorted(A, key=lambda a: -a["reviews"])[:3]]))
        res.append(dict(sid=sid, niche=nm, query=q, amazon_items=len(am), wb_cards=len(wb), feats=feats))
        print(f"\n== {sid} {nm} | Amazon {len(am)} товаров, WB {len(wb)} карточек")
        for x in sorted(feats, key=lambda x: (-x["gap"], -x["weak"], -x["am_share"])):
            if x["gap"] or x["weak"]:
                print(f"   {'🟢 ПРОБЕЛ' if x['gap'] else '🟡 слабо'} {x['feat']}: Amazon {x['am_share']}% отзывов ({x['am_rv']}), "
                      f"{int(x['am_bought'])}+/мес | WB {x['wb_cards']} карт. ({x['wb_share']}%)")
                for e in x["examples"][:2]:
                    print("        ", e)
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    {"fetch": fetch_all, "gaps": gaps}[sys.argv[1] if len(sys.argv) > 1 else "gaps"]()
