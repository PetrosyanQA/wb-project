"""Внутри ниши: из чего она состоит и какой ТИП товара брать. 0 запросов (products500 Saleflow 07.2026 уже скачан).

    python -m src.niche_inside 811                      # типы товара по словам названий → таблица + отчёт
    python -m src.niche_inside 811 --type "топорик"     # один тип: ценовые сегменты, лидеры, новички, форматы
    python -m src.niche_inside 811 --min-share 2 --top 30

Тип = слово (основа) или пара слов из названий карточек ниши, которые покрывают ≥ min-share % продаж.
По каждому типу: карточек, продажи и доля, медиана цены, новички с 08.2025 и их продажи P25/P50, топ-6 и топ-1 продавцов,
выкуп, запрещённые признаки (батарейки, магнит, электрика, детское/игрушка) и прибыль при белом ввозе
(та же модель, что screen_white: цена продавца через СПП Evirma, комиссия FBS WB API, ¥ = 11 % цены [допущение]).
Осторожная прибыль/мес = прибыль/шт (ДРР 8 %) × P25 новичка (ошибка выжившего — см. скилл, шаг 4b).
Типы пересекаются (одна карточка может быть в нескольких) — это карта ниши, а не сумма.
Итог: reports/niche_inside_<id>_<дата>.md
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import re
import statistics as st
import sys
from pathlib import Path

from src.outliers import clean_items
from src.screen_white import BANDS, CNY, COM, REQ, econ, load, seller_for

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]

STOP = set("""для из и в на с со по от до без под над при к ко о об а но или не же как это все всё шт штук штуки предметов предмета
предмет набор наборы комплект комплекта подарок подарочный подарочная подарочные новый новая новинка 2025 2026 большой большая
маленький маленькая мини супер premium премиум качественный качественная универсальный универсальная оригинал прочный прочная""".split())
BANNED = {"батарейки / аккумулятор": r"батаре|аккумул|usb|заряд", "магнит": r"магнит|magsafe",
          "электрика": r"электр|led|светодиод|ультразвук|пульт|мотор|солнечн", "детское / игрушка (ЧЗ)": r"детск|для детей|игрушк|для девоч|для мальч"}


def stem(w: str) -> str:
    return w[:6] if len(w) > 6 else w


def words(name: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-zа-яё]+", (name or "").lower()) if len(t) > 2 and t not in STOP]
    return list(dict.fromkeys(stem(t) for t in toks))


def stats(seg: list[dict], sid: int, total: int) -> dict:
    sales = sum(r["sales"] for r in seg)
    newp = sorted(r["sales"] for r in seg if "2025-08-01" <= (r.get("sku_first_date") or "") <= "2026-06-15")
    by = collections.Counter()
    for r in seg:
        by[r.get("seller")] += r["sales"]
    buyer = st.median(r["price"] for r in seg)
    pur = [r["purchase"] for r in seg if r.get("purchase")]
    buyout = st.median(pur) if pur else 80
    vols = [r["package_length"] * r["package_width"] * r["package_height"] / 1000 for r in seg
            if r.get("package_length") and r.get("package_width") and r.get("package_height")]
    vol = st.median(vols) if len(vols) >= 3 else 2.0
    seller, spp = seller_for(sid, buyer)
    com = COM.get(sid)
    p8 = None
    if seller and com:
        y = buyer * 0.11 / CNY
        p8 = round(econ(seller, y, vol, max(0.1, 0.22 * vol), com, buyout, 8, 200)["net_profit"])
    names = " ".join(r["name"] or "" for r in seg).lower()
    ban = [k for k, rx in BANNED.items() if len(re.findall(rx, names)) >= max(2, len(seg) * 0.3)]
    p25 = newp[len(newp) // 4] if newp else 0
    return dict(cards=len(seg), sales=sales, share=round(sales / total * 100, 1), price=round(buyer),
                new=len(newp), p25=p25, p50=st.median(newp) if newp else 0,
                top6=round(sum(v for _, v in by.most_common(6)) / sales * 100) if sales else 100,
                top1=round(by.most_common(1)[0][1] / sales * 100) if sales else 100, sellers=len(by),
                buyout=buyout, vol=round(vol, 1), vol_assumed=len(vols) < 3, spp=spp, profit8=p8,
                month=round(p8 * p25) if p8 is not None else None, ban=ban)


def verdict(s: dict) -> str:
    if s["ban"]:
        return "❌ " + ", ".join(s["ban"])
    bad = []
    if s["top6"] > 60:
        bad.append(f"монополия топ-6 {s['top6']} %")
    if s["new"] < 5:
        bad.append("мало новичков")
    elif s["p25"] < 20:
        bad.append("новички слабые")
    if s["buyout"] < 70:
        bad.append(f"выкуп {s['buyout']:.0f} %")
    if s["profit8"] is not None and s["profit8"] <= 0:
        bad.append("убыток")
    return "✅" if not bad else "⚠️ " + "; ".join(bad)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sid", type=int)
    ap.add_argument("--type", help="regex типа товара: разбор одного типа по ценам")
    ap.add_argument("--min-share", type=float, default=2.0)
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    rows = load(a.sid)
    if not rows:
        sys.exit(f"нет products500 по нише {a.sid}: python -m src.niche_deep scan {a.sid} --products-only")
    for r in rows:
        r["price"] = r.get("final_price_average") or r.get("final_price")
    kept, rep = clean_items(rows, {"outliers": {"price_upper_ratio": 15, "price_lower_ratio": 0.05}}, expected_subject=a.sid)
    kept = [r for r in kept if (r.get("sales") or 0) > 0 and r.get("price")]
    total = sum(r["sales"] for r in kept)
    subj = REQ.get(a.sid, {}).get("subject", a.sid)
    L = [f"# Внутри ниши {a.sid} «{subj}» — {dt.date.today()}", "",
         f"Saleflow products500, июль 2026: {len(kept)} карточек с продажами, {total:,} шт/мес (очистка: −{rep['dropped_pct']} %).".replace(",", " "),
         "Осторожно/мес = прибыль/шт (ДРР 8 %, ¥ = 11 % цены [допущение]) × P25 новичка. Объём «2 л*» = габаритов нет, допущение.", ""]
    if a.type:
        rx = re.compile(a.type, re.I)
        seg = [r for r in kept if rx.search(r["name"] or "")]
        if not seg:
            sys.exit("нет карточек этого типа")
        s = stats(seg, a.sid, total)
        L += [f"## Тип «{a.type}»: {s['cards']} карточек, {s['sales']} шт/мес ({s['share']} % ниши), {verdict(s)}", "",
              "| Цена | Карточек | Продаж/мес | Новичков | P25 / P50 | Топ-6 | Выкуп | Прибыль/шт | Осторожно/мес | Вывод |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for lo, hi in BANDS:
            b = [r for r in seg if lo <= r["price"] < hi]
            if len(b) < 3:
                continue
            x = stats(b, a.sid, total)
            L.append(f"| {lo}–{hi} ₽ | {x['cards']} | {x['sales']} | {x['new']} | {x['p25']} / {x['p50']} | {x['top6']} % | {x['buyout']:.0f} % | "
                     f"{x['profit8'] if x['profit8'] is not None else '—'} ₽ | {x['month'] if x['month'] is not None else '—'} ₽ | {verdict(x)} |")
        L += ["", "### Топ-10 карточек типа", "| SKU | Цена | Продаж/мес | Старт | Продавец | Название |", "|---|---:|---:|---|---|---|"]
        for r in sorted(seg, key=lambda r: -r["sales"])[:10]:
            L.append(f"| [{r['id']}](https://www.wildberries.ru/catalog/{r['id']}/detail.aspx) | {round(r['price'])} ₽ | {r['sales']} | "
                     f"{(r.get('sku_first_date') or '')[:7]} | {r.get('seller')} | {(r['name'] or '')[:60]} |")
        out = ROOT / "reports" / f"niche_inside_{a.sid}_{re.sub(r'[^a-zа-яё0-9]+', '_', a.type.lower())[:20]}_{dt.date.today()}.md"
    else:
        idx = collections.defaultdict(list)
        for r in kept:
            ws = words(r["name"])
            for w in ws:
                idx[w].append(r)
            for w1, w2 in zip(ws, ws[1:]):
                idx[f"{w1} {w2}"].append(r)
        cand = [(k, v) for k, v in idx.items() if sum(r["sales"] for r in v) / total * 100 >= a.min_share and len(v) >= 5]
        res = []
        for k, v in cand:
            s = stats(v, a.sid, total)
            if s["share"] >= 90:                       # слово есть почти везде («нож», «кухонн») — не тип
                continue
            res.append((k, s))
        res.sort(key=lambda kv: (verdict(kv[1]) != "✅", -(kv[1]["month"] or -1e9)))   # сначала ✅, потом по прибыли
        L += ["## Типы товара в нише (по словам названий): сначала ✅, внутри — по осторожной прибыли/мес", "",
              "| Тип (основа слова) | Карточек | Продаж/мес | Доля | Медиана цены | Новичков | P25 / P50 | Топ-6 | Выкуп | Объём | Прибыль/шт | Осторожно/мес | Вывод |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for k, s in res[:a.top]:
            L.append(f"| {k} | {s['cards']} | {s['sales']} | {s['share']} % | {s['price']} ₽ | {s['new']} | {s['p25']} / {s['p50']} | {s['top6']} % | "
                     f"{s['buyout']:.0f} % | {s['vol']}{'*' if s['vol_assumed'] else ''} л | {s['profit8'] if s['profit8'] is not None else '—'} ₽ | "
                     f"{s['month'] if s['month'] is not None else '—'} ₽ | {verdict(s)} |")
        L += ["", "Дальше: лучший ✅ тип → `python -m src.niche_inside <id> --type \"<слова>\"` (цены внутри типа) → "
              "`niche_deep report <id> --include` / `risers` / `product_deep` / `spec_find` (шаги скилла `/vnutri-nishi`)."]
        out = ROOT / "reports" / f"niche_inside_{a.sid}_{dt.date.today()}.md"
    text = "\n".join(L)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
