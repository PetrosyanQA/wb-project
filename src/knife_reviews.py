"""Цвета и жалобы ТОЛЬКО по нашему точному типу набора ножей (не по всему топу ниши). 0 запросов Saleflow.

    python -m src.knife_reviews                 # кэш WB CDN + WB feedbacks (догружает недостающее публично)
    python -m src.knife_reviews --cache-only    # только то, что уже скачано

Наш тип: набор на подставке, ≥ 5 ножей, металлическая/цельнолитая ручка, + ножницы или точилка, цена 2 500–6 500 ₽.
Отзывы берутся только с nmId самой карточки (у склейки бывают чужие варианты), за 12 мес. до 2026-10-23.
Вывод: data/processed/knives_type_reviews_2026-10-23.json и текст в stdout.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics as st
import sys
from pathlib import Path

from src import wb_cdn_card as W
from src.niche_monitor import feedbacks

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "saleflow" / "2026-10-23" / "knives" / "products500_2026-07.json"
FB = str(ROOT / "data" / "raw" / "wb_feedbacks")
SINCE = "2025-10-23"

THEMES = {
    "ржавеют / пятна": r"ржав|пятн|окисл|корроз|налет|налёт",
    "тупые / быстро тупятся": r"туп|не реж|плохо реж|не острые|неострые",
    "сломался / брак / скол": r"слома|отлом|треснул|трещин|погну|брак|скол|зазубр|отвалил",
    "подставка плохая": r"подставк\w*[^.!?]{0,40}(плох|крив|шата|трещ|мал|не влез|не встав|хлипк|дешев|деше|падает|легк)|(плох|крив|хлипк)\w*[^.!?]{0,20}подставк",
    "ножницы / точилка плохие": r"ножниц|точилк|мусат",
    "лёгкий / тонкий металл": r"тонк|хлипк|гнут|гнёт|лёгк\w* как|легк\w* как|несерьезн|игрушеч",
    "ручка неудобная / болтается": r"ручк\w*[^.!?]{0,30}(скольз|неудоб|болта|шата|отход|люфт)|рукоят",
    "упаковка / б/у / не для подарка": r"упаков|коробк|помят|б/у|бывш|использован|царап|подар",
    "не соответствует фото / некомплект": r"не соответ|не тот|не хватает|некомплект|другой цвет|отлича|не как на фото",
    "облезает покрытие / запах": r"облез|покрыти|краск|слезает|запах|пахн",
}


def our_type(r: dict, o: dict) -> bool:
    txt = (r["name"] + " " + " ".join(o.values())).lower()
    m = re.search(r"(\d+)\s*(шт|пред)", o.get("Количество предметов в упаковке", "") + " " + r["name"].lower())
    n = int(m.group(1)) if m else 0
    knives = len(re.findall(r"нож(?!ниц)", o.get("Комплектация", "").lower())) or max(0, n - 2)
    handle = o.get("Материал ручки", "").lower() + " " + r["name"].lower()
    return ("подставк" in txt and knives >= 5 and bool(re.search(r"метал|нерж|сталь|цельнолит", handle))
            and bool(re.search(r"ножниц|точилк|мусат", txt)) and 2500 <= r["final_price"] <= 6500)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-only", action="store_true")
    a = ap.parse_args()
    rows = json.load(open(SRC, encoding="utf-8"))["data"]
    cand = [r for r in rows if re.search("набор|ножи кухонные", r["name"], re.I)
            and re.search("подставк|ножниц|точилк|цельнолит", r["name"], re.I) and 1500 <= r["final_price"] <= 6500]
    cards, miss = [], 0
    for r in cand:
        if a.cache_only and not os.path.exists(f"{W.DIR}/{r['id']}.json"):
            miss += 1; continue
        c = W.fetch(r["id"]) or {}
        o = {x["name"]: x["value"] for x in c.get("options", [])}
        imt = c.get("imt_id")
        if a.cache_only and (not imt or not os.path.exists(f"{FB}/{imt}.json")):
            fb = None
        else:
            fb = [f for f in (feedbacks(imt, FB) if imt else []) if f.get("nmId") == r["id"]]
        cards.append({"sku": r["id"], "name": r["name"], "price": r["final_price"], "sales": r["sales"], "revenue": r["revenue"],
                      "seller": r.get("seller"), "color": (o.get("Цвет") or r.get("color") or "—").lower(), "opts": o,
                      "ours": our_type(r, o), "fb": fb})
    ours = [c for c in cards if c["ours"]]
    print(f"Кандидатов {len(cand)}, карточек прочитано {len(cards)} (без кэша {miss}); НАШ ТИП: {len(ours)} карточек, "
          f"{sum(c['sales'] for c in ours)} продаж/мес, {sum(c['revenue'] for c in ours) / 1e6:.1f} млн ₽ (июль 2026)")

    def main_color(c: str) -> str:
        for k in ("черн", "бел", "сер", "золот", "дерев", "коричн", "бежев", "красн", "зелен", "син", "мрамор", "радуж", "серебр", "сталь"):
            if k in c:
                return {"черн": "чёрный", "бел": "белый", "сер": "серый", "золот": "золотой", "дерев": "дерево", "коричн": "коричневый",
                        "бежев": "бежевый", "красн": "красный", "зелен": "зелёный", "син": "синий", "мрамор": "мрамор",
                        "радуж": "радужный", "серебр": "серебристый/сталь", "сталь": "серебристый/сталь"}[k]
        return "прочий"

    out = {"ours": [], "colors": {}, "themes": {}, "themes_by_color": {}}
    for label, grp in (("НАШ ТИП", ours), ("все наборы 1 500–6 500 ₽ с подставкой/ножницами", cards)):
        g = collections.defaultdict(list)
        for c in grp:
            g[main_color(c["color"])].append(c)
        print(f"\nЦвета — {label}: цвет | карточек | продаж/мес | доля продаж | медиана продаж на карточку | мед. цена")
        tot = sum(c["sales"] for c in grp) or 1
        for k, v in sorted(g.items(), key=lambda kv: -sum(c["sales"] for c in kv[1])):
            print(f"  {k} | {len(v)} | {sum(c['sales'] for c in v)} | {100 * sum(c['sales'] for c in v) / tot:.0f} % | "
                  f"{st.median(c['sales'] for c in v):.0f} | {st.median(c['price'] for c in v):.0f}")
            if label == "НАШ ТИП":
                out["colors"][k] = {"cards": len(v), "sales": sum(c["sales"] for c in v)}
    # жалобы
    with_fb = [c for c in ours if c["fb"] is not None]
    allf = [(c, f) for c in with_fb for f in c["fb"] if (f.get("createdDate") or "")[:10] >= SINCE]
    neg = [(c, f) for c, f in allf if (f.get("productValuation") or 5) <= 3]
    print(f"\nОтзывы НАШЕГО ТИПА за 12 мес: {len(with_fb)} карточек с отзывами, {len(allf)} отзывов, негатив (1–3★) {len(neg)} "
          f"= {100 * len(neg) / max(1, len(allf)):.1f} %")
    txt = lambda f: " ".join(str(f.get(k) or "") for k in ("text", "pros", "cons")).lower()
    neg_t = [(c, f) for c, f in neg if txt(f).strip()]
    print(f"негативных с текстом {len(neg_t)}. Тема | доля негатива с текстом | шт")
    for name, rx in THEMES.items():
        n = sum(1 for _, f in neg_t if re.search(rx, txt(f)))
        out["themes"][name] = n
        print(f"  {name} | {100 * n / max(1, len(neg_t)):.0f} % | {n}")
    print("\nНегатив по цвету карточки: цвет | отзывов | негатив % | топ-жалоба")
    by = collections.defaultdict(list)
    for c, f in allf:
        by[main_color(c["color"])].append((c, f))
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        ng = [(c, f) for c, f in v if (f.get("productValuation") or 5) <= 3 and txt(f).strip()]
        nn = sum(1 for _, f in v if (f.get("productValuation") or 5) <= 3)
        top = max(THEMES, key=lambda t: sum(1 for _, f in ng if re.search(THEMES[t], txt(f)))) if ng else "—"
        out["themes_by_color"][k] = {"reviews": len(v), "neg": nn, "top": top}
        print(f"  {k} | {len(v)} | {100 * nn / len(v):.1f} % | {top}")
    print("\nКарточки нашего типа: SKU | продавец | цена | продаж/мес | цвет | отзывов 12 мес | негатив %")
    for c in sorted(ours, key=lambda c: -c["sales"]):
        f12 = [f for f in (c["fb"] or []) if (f.get("createdDate") or "")[:10] >= SINCE]
        nn = sum(1 for f in f12 if (f.get("productValuation") or 5) <= 3)
        out["ours"].append({k: c[k] for k in ("sku", "seller", "price", "sales", "color")} | {"reviews12": len(f12), "neg": nn})
        print(f"  {c['sku']} | {(c['seller'] or '')[:22]} | {c['price']} | {c['sales']} | {c['color'][:22]} | "
              f"{len(f12) if c['fb'] is not None else '—'} | {100 * nn / len(f12):.1f} %" if f12 else
              f"  {c['sku']} | {(c['seller'] or '')[:22]} | {c['price']} | {c['sales']} | {c['color'][:22]} | — | —")
    print("\nПримеры негатива (ржавчина/тупые/подставка):")
    for name in ("ржавеют / пятна", "тупые / быстро тупятся", "подставка плохая"):
        ex = [txt(f)[:140] for _, f in neg_t if re.search(THEMES[name], txt(f))][:2]
        for e in ex:
            print(f"  [{name}] {e}")
    json.dump(out, open(ROOT / "data" / "processed" / "knives_type_reviews_2026-10-23.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
