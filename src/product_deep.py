"""Глубокий разбор конкретного товара (шаги 7–8 /vybor-tovara): конкуренты сегмента → карточки WB → отзывы → жалобы.

    python -m src.product_deep 8986 --include "тоут|шоппер|y2k" --price 2400 3600 --themes bag
    python -m src.product_deep 249 --include "подтягив|турник" --price 800 1300 --themes band

0 запросов Saleflow: карточки — публичный CDN WB (src.wb_cdn_card), отзывы — feedbacks1/2.wb.ru (кэш data/raw/wb_feedbacks/).
Конкуренты: топ-15 сегмента по продажам (июль 2026) + все новички с 08.2025 (до 30 карточек), копии брендов исключены.
Жалобы: отзывы с оценкой ≤ 3 → темы по словарю (общие + по типу товара). Тема ≥ 12 % негатива = исправимая жалоба-кандидат.
Итог: reports/product_deep_<id>_<дата>.md + data/processed/product_deep_<id>_<дата>.json.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
FB_DIR = str(ROOT / "data" / "raw" / "wb_feedbacks")

THEMES = {
    "common": {
        "брак / дефект": r"брак|дефект|бракован|испорч",
        "запах": r"запах|воня|пахн",
        "не как на фото / цвет": r"не как на фото|не соответств|цвет друг|другой цвет|на фото|оттенок|темнее|светлее",
        "размер меньше / больше": r"меньше чем|маленьк|больше чем|размер не|мелк|огромн",
        "качество / дёшево": r"качеств|дешев|дёшев|китай|ширпотреб|не стоит своих",
        "пришло повреждённым / грязным": r"порван.{0,15}упаков|грязн|пятн|поцарап|мят|повреж",
        "не пришло / не тот товар": r"не тот|пришл.{0,10}друг|не пришл|пуст|комплект не",
    },
    "bag": {
        "ручки / ремень рвутся": r"ручк.{0,25}(оторв|отпал|порв|тресн|отклеил|слаб)|ремен.{0,20}(оторв|порв|слаб)|лямк",
        "швы / нитки": r"шов|швы|нитк|строчк|расползл|разош",
        "кожзам трескается / облазит": r"тресн|трескает|облез|облаз|шелуш|слезает|потерт|потёрт|катышк",
        "молния / застёжка": r"молни|замок|застеж|застёж|кнопк|магнит",
        "не держит форму / тонкая": r"форм|тонк|мягк.{0,10}слишком|бесформ|висит|мнёт|мнет",
        "нет карманов / подклада": r"карман|подклад|отделени",
        "мала для А4 / ноутбука": r"а4|a4|ноутбук|не влез|не помещ|вместим",
    },
    "band": {
        "порвалась": r"порвал|лопнул|разорвал|трещин|надрыв",
        "запах резины": r"запах|воня",
        "слабая / сильная нагрузка": r"слаб|туг|сильн|не та нагрузк|нагрузк",
    },
    "brush": {
        "линяют / лезет ворс": r"лез|линя|выпада|сыпл|ворсинк|волоск|облыс",
        "колючие / жёсткие": r"колю|колет|жестк|жёстк|царап|грубы",
        "ручка / ферула отваливается": r"отвал|отклеи|шата|болта|ручк|ферул",
        "плохо набирают / растушёвывают": r"не набира|плохо набира|растуш|разводы|полос",
        "запах / краска на ворсе": r"запах|воня|краск|окраш",
        "мало / не тот комплект, чехол": r"чехол|косметичк|не все|не хватает|меньше кист",
    },
    "wallet": {
        "не натуральная кожа / кожзам": r"кожза|не натурал|не кожа|искусствен|пластик|клеёнк|клеенк|дерматин",
        "облезает / трескается / потёрлось": r"облез|облаз|тресн|шелуш|потер|потёр|стерл|слезает|краска",
        "швы / нитки": r"шов|швы|нитк|строчк|расползл|разош|торчат",
        "молния / кнопка / застёжка": r"молни|замок|кнопк|застеж|застёж|магнит",
        "карты не влезают / мало отделений": r"карт.{0,20}(не влез|туго|выпада|не помещ)|мало (отделен|карман|мест)|купюр.{0,15}не влез|тесн",
        "тонкий / мягкий / дешёвый вид": r"тонк|мягк|хлипк|дешев|дешёв|несолид",
    },
    "knife": {
        "ржавеют / пятна": r"ржав|ржа\b|коррози|пятн|темне|окисл",
        "тупые / быстро тупятся": r"туп|не реж|плохо реж|заточк|точить",
        "гнутся / хлипкие / тонкие": r"гнут|гнёт|гнет|хлипк|тонк|лёгк|легк|болта",
        "ручка: скользит / облезла / отпала": r"ручк|рукоят",
        "подставка: шатается / ножи выпадают": r"подставк|выпада|шата|кривое дно|решетк|решётк",
        "сколы / зазубрины на лезвии": r"скол|зазубр|щербин|выщерб",
        "ножницы / точилка / овощечистка": r"ножниц|точилк|овощечист|ножеточ",
    },
}


def products(sid):
    from src.niche_deep import products as P
    return P(sid)


def pick(sid, include, price, top=15, cap=30):
    from src.niche_deep import BRANDS
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0
    seg = [r for r in products(sid) if r.get("sales") and (not include or re.search(include, r["name"], re.I))
           and price[0] <= P(r) < price[1] and not BRANDS.search(r["name"])]
    seg.sort(key=lambda r: -r["sales"])
    out = seg[:top] + [r for r in seg[top:] if (r.get("sku_first_date") or "") >= "2025-08"]
    return out[:cap], seg


def opt(card, *keys):
    for o in card.get("options") or []:
        if any(k in (o.get("name") or "").lower() for k in keys):
            return o.get("value")
    for g in card.get("grouped_options") or []:
        for o in g.get("options") or []:
            if any(k in (o.get("name") or "").lower() for k in keys):
                return o.get("value")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sid", type=int)
    ap.add_argument("--include")
    ap.add_argument("--price", type=int, nargs=2, default=[0, 10 ** 6])
    ap.add_argument("--themes", default="common")
    a = ap.parse_args()
    from src.niche_monitor import feedbacks
    from src.wb_cdn_card import fetch
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0
    comp, seg = pick(a.sid, a.include, a.price)
    themes = {**THEMES["common"], **THEMES.get(a.themes, {})}
    rx = {k: re.compile(v, re.I) for k, v in themes.items()}
    rows, neg_all, quotes = [], [], collections.defaultdict(list)
    for r in comp:
        card = fetch(r["id"]) or {}
        imt = card.get("imt_id") or r.get("itemid")
        F = feedbacks(imt, FB_DIR) if imt else []
        vals = [f.get("productValuation") for f in F if f.get("productValuation")]
        neg = [f for f in F if (f.get("productValuation") or 5) <= 3]
        for f in neg:
            t = " ".join(str(f.get(k) or "") for k in ("text", "cons", "pros")).strip()
            hits = [k for k, x in rx.items() if x.search(t)]
            neg_all.append(hits)
            for k in hits:
                if len(quotes[k]) < 4 and 20 <= len(t) <= 220:
                    quotes[k].append(f"«{t[:200]}» ({r['id']})")
        rows.append(dict(id=r["id"], price=round(P(r)), sales=r["sales"], start=(r.get("sku_first_date") or "")[:7],
                         seller=r.get("seller"), name=r["name"][:60], fb=len(F), rating=round(st.mean(vals), 2) if vals else None,
                         neg=round(len(neg) / len(F) * 100, 1) if F else None, pics=r.get("picscount"), video=r.get("hasvideo"),
                         material=opt(card, "материал", "состав"), size=opt(card, "размер", "ширина", "высота", "длина"),
                         weight=opt(card, "вес"), country=r.get("country")))
    n_neg = len(neg_all)
    tc = collections.Counter(k for h in neg_all for k in h)
    mats = collections.Counter(str(x["material"] or "—").split(";")[0].strip().lower()[:30] for x in rows)
    L = [f"# Глубокий разбор: ниша {a.sid}, «{a.include or 'все'}», {a.price[0]}–{a.price[1]} ₽ — {dt.date.today()}", "",
         f"Сегмент (июль 2026, без копий брендов): {len(seg)} карточек, {sum(r['sales'] for r in seg):,} шт/мес, "
         f"продавцов {len({r.get('seller') for r in seg})}. В разборе {len(rows)} карточек (топ-15 + новички с 08.2025).".replace(",", " "),
         "", "## Конкуренты", "",
         "| SKU | Цена | Продаж/мес | Старт | Продавец | Отзывов | Рейтинг | Негатив ≤3 | Фото | Видео | Материал |",
         "|---|---:|---:|---|---|---:|---:|---:|---:|---|---|"]
    for x in rows:
        L.append(f"| [{x['id']}](https://www.wildberries.ru/catalog/{x['id']}/detail.aspx) {x['name'][:28]} | {x['price']} ₽ | {x['sales']} | "
                 f"{x['start']} | {str(x['seller'])[:16]} | {x['fb']} | {x['rating'] or '—'} | {x['neg'] if x['neg'] is not None else '—'} % | "
                 f"{x['pics']} | {'да' if x['video'] else 'нет'} | {str(x['material'] or '—')[:30]} |")
    L += ["", "Материалы в карточках: " + ", ".join(f"{k} — {v}" for k, v in mats.most_common(8)), "",
          f"## Жалобы (отзывы с оценкой ≤ 3: {n_neg} шт по {len(rows)} карточкам)", "",
          "| Тема | Отзывов | Доля негатива |", "|---|---:|---:|"]
    for k, v in tc.most_common():
        L.append(f"| {k} | {v} | {round(v / n_neg * 100) if n_neg else 0} %{' ✅ кандидат' if n_neg and v / n_neg >= 0.12 else ''} |")
    L += ["", f"Без темы: {sum(1 for h in neg_all if not h)} отзывов — читать вручную.", "", "### Примеры"]
    for k, _ in tc.most_common(5):
        L += [f"**{k}**"] + [f"- {q}" for q in quotes[k]]
    text = "\n".join(L)
    out = ROOT / "reports" / f"product_deep_{a.sid}_{dt.date.today()}.md"
    out.write_text(text, encoding="utf-8")
    json.dump(dict(rows=rows, themes=dict(tc), n_neg=n_neg), open(ROOT / "data" / "processed" / f"product_deep_{a.sid}_{dt.date.today()}.json", "w", encoding="utf-8"),
              ensure_ascii=False, default=str)
    print(text)
    print(f"\n→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
