"""«ДНК победителей» ниши по сохранённым ответам Saleflow. Только чтение, 0 запросов.

    python -m src.winner_dna market --niche videonyani            # 12 мес. top-100 по месяцам
    python -m src.winner_dna seo    --niche videonyani --subject 902   # группы запросов × месяцы vs продажи
    python -m src.winner_dna launch --niche videonyani            # как заходил каждый победитель
    python -m src.winner_dna gaps   --niche videonyani            # пустые ценовые окна и признаки

Вход: data/raw/saleflow/<date>/<niche>/{monthly/products_YYYY-MM.json, seo/keywords_YYYY-MM.json,
winners/<sku>/by_period.json}, ряд предмета <date>/xborder/<subject>/subject<id>_trends_monthly.csv.
Методика старта — ~/.claude/skills/wb-winner-dna: ≥ 8 шт/день в первую неделю → рекламный старт;
≥ 50 отзывов за 21 день → выкуп + органика; иначе органика. Флаги рекламы WB — поля in_ads / search_words_in_ad.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import statistics as st
import sys
from collections import defaultdict
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
RAW = os.path.join("data", "raw", "saleflow")

MONITOR = re.compile(r"монитор|экран|дисплей|дюйм")
NO_WIFI = re.compile(r"без\s*(wi.?fi|вай.?фай|интернета)")
WIFI = re.compile(r"wi.?fi|вай.?фай|телефон|смартфон|приложен")

SEO_GROUPS = {
    "видеоняня (общий)": r"^видео\s?няня$|^видеоняня$",
    "видеоняня с монитором": r"няня.*монитор|монитор.*нян",
    "радионяня": r"радио\s?нян",
    "видеоняня + новорожд./малыш": r"нян.*(новорожд|малыш|ребен|детск)|(новорожд|малыш|ребен|детск).*нян",
    "видеоняня wifi/телефон": r"нян.*(wi.?fi|вай.?фай|телефон)|(wi.?fi|телефон).*нян",
    "камера wifi для дома": r"камера.*(wi.?fi|вай.?фай).*(дом|квартир)|камера видеонаблюдения для дома",
    "без wifi": r"без\s*(wi.?fi|вай.?фай|интернета)",
    "белый шум / сон": r"белый шум|для сна",
    "для новорожденных (общий)": r"^для новорожденных$|^товары для новорожденных$|^для новорожденных товары$",
}


def mtype(name: str) -> str:
    n = name.lower()
    wifi = bool(WIFI.search(NO_WIFI.sub("", n)))
    mon = bool(MONITOR.search(n))
    return ("монитор" if mon else "без монитора") + (" + Wi-Fi" if wifi else " без Wi-Fi")


def mtype_masturb(name: str) -> str:
    n = name.lower()
    if not re.search(r"автомат|электр", n):
        return "ручной"
    if re.search(r"фрикц|толч|поступат", n):
        return "авто: толчки"
    if re.search(r"вакуум|всасыв|посасыв|отсос", n):
        return "авто: вакуум"
    return "авто: вибрация/прочее"


# Правила ниши: тип карточки, «целевой» тип для доли выручки, группы SEO, ценовые полосы, признаки в названиях.
PRESETS = {
    "videonyani": dict(
        type_fn=mtype, target="монитор без Wi-Fi", target_label="«Монитор без Wi-Fi»",
        seo=SEO_GROUPS, core=r"нян|монитор|радион", new=r"нян|монитор|радион|малыш|новорожд",
        bands=[(0, 2000), (2000, 3000), (3000, 3500), (3500, 4000), (4000, 4500), (4500, 5000), (5000, 6000), (6000, 8000), (8000, 99999)],
        feats={"5 дюймов/большой экран": r"\b5\s*(\"|дюйм)|5,0|4[.,]3", "2 камеры": r"2\s*камер|две камер", "поворотная": r"поворот|360|355",
               "датчик дыхания": r"дыхан", "аккумулятор в камере": r"камер[аы]? с аккумулятор", "VOX/звук": r"vox|реагирует на звук|датчик звук",
               "белый шум": r"белый шум", "запись/карта памяти": r"запис|карт[аы] памяти|microsd", "дальность в названии": r"\d+\s*м\b|дальн",
               "подарок/выписка": r"подар|выписк"}),
    "masturb": dict(
        type_fn=mtype_masturb, target=None, target_label="Автоматические",
        seo={"мастурбатор (общий)": r"^(мужской )?мастурбатор( мужской| для мужчин)?$",
             "автоматический": r"автомат|электр",
             "вагина / резиновая вагина": r"вагин",
             "секс кукла": r"кукл",
             "секс игрушки для мужчин": r"игрушк.*муж|муж.*игрушк",
             "вакуум / минет / рот": r"вакуум|минет|\bрот\b|орал|отсос",
             "попа / анал": r"\bпоп[аы]\b|анал|жоп",
             "с вибрацией": r"вибрац|вибро",
             "карманный / стакан": r"карман|стакан|fleshlight|флешлайт|tenga|тенга|яйцо",
             "тренажёр / для тренировки": r"тренаж|тренир",
             "18+ общие": r"^18\+$|товары для взрослых|игрушки для взрослых"},
        core=r"мастурб|вагин|кукл", new=r"мастурб|вагин|кукл|мужч|автомат",
        bands=[(0, 1000), (1000, 1500), (1500, 2000), (2000, 2500), (2500, 3000), (3000, 3500), (3500, 4000), (4000, 5000), (5000, 7000), (7000, 99999)],
        feats={"автоматический": r"автомат", "вакуум/всасывание": r"вакуум|всасыв|посасыв", "вибрация": r"вибрац",
               "фрикции/толчки": r"фрикц|толч", "вращение": r"вращ", "нагрев": r"нагрев|подогрев", "голос/стоны": r"голос|стон",
               "приложение": r"приложен", "пульт": r"пульт", "реалистичный": r"реалист", "2 в 1 / 3 в 1": r"[23]\s*в\s*1",
               "водозащита": r"водонепрониц|ipx", "карманный/компактный": r"карман|компакт|мини"}),
}


def preset(niche: str) -> dict:
    return PRESETS.get(niche, PRESETS["videonyani"])


def load_months(niche: str, d: str) -> dict[str, list[dict]]:
    out = {}
    for f in sorted(glob.glob(os.path.join(RAW, d, niche, "monthly", "products_*.json"))):
        rows = json.load(open(f, encoding="utf-8"))["data"]
        rows.sort(key=lambda x: -x["revenue"])
        for i, x in enumerate(rows, 1):
            x["rank"] = i
        out[os.path.basename(f)[9:16]] = rows
    return out


def is_target(P: dict, name: str) -> bool:
    t = P["type_fn"](name)
    return t == P["target"] if P["target"] else t.startswith("авто")


def market(niche: str, d: str) -> dict:
    P = preset(niche)
    months = load_months(niche, d)
    prev: set = set()
    res = {}
    print(f"| Месяц | Выручка top-100 | Продаж, шт | Мед. цена | Top-1 | Top-10 | Новых в top-100 | из них < 365 дн | {P['target_label']}, доля выручки |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m, rows in months.items():
        tot = sum(x["revenue"] for x in rows) or 1
        units = sum(x.get("sales") or 0 for x in rows)
        new = [x for x in rows if x["id"] not in prev] if prev else []
        mon = sum(x["revenue"] for x in rows if is_target(P, x["name"]))
        r = dict(revenue=round(tot), units=units, median_price=st.median(x["final_price"] for x in rows),
                 top1_pct=round(100 * rows[0]["revenue"] / tot, 1), top10_pct=round(100 * sum(x["revenue"] for x in rows[:10]) / tot, 1),
                 new=len(new), new_young=sum(1 for x in new if (x.get("days_in_site") or 9999) < 365),
                 monitor_nowifi_pct=round(100 * mon / tot, 1))
        res[m] = r
        print(f"| {m} | {r['revenue']/1e6:.1f} M ₽ | {units:,} | {r['median_price']:,.0f} ₽ | {r['top1_pct']}% | {r['top10_pct']}% | "
              f"{r['new'] if prev else '—'} | {r['new_young'] if prev else '—'} | {r['monitor_nowifi_pct']}% |")
        prev = {x["id"] for x in rows}
    if P["target"] is None:                      # ниша без одного «целевого» типа → разбивка по типам
        types = sorted({P["type_fn"](x["name"]) for rows in months.values() for x in rows})
        print("\n| Месяц | " + " | ".join(f"{t}: шт / выручка / мед. цена" for t in types) + " |")
        print("|---|" + "---:|" * len(types))
        for m, rows in months.items():
            cells = []
            for t in types:
                g = [x for x in rows if P["type_fn"](x["name"]) == t]
                u, rv = sum(x.get("sales") or 0 for x in g), sum(x["revenue"] for x in g)
                med = st.median(x["final_price"] for x in g) if g else 0
                res[m].setdefault("types", {})[t] = dict(cards=len(g), units=u, revenue=round(rv), median_price=med)
                cells.append(f"{u:,} / {rv / 1e6:.1f} M / {med:,.0f} ₽")
            print(f"| {m} | " + " | ".join(cells) + " |")
    return res


def load_subject_trend(d: str, subject: int) -> dict[str, float]:
    path = os.path.join(RAW, d, "xborder", str(subject), f"subject{subject}_trends_monthly.csv")
    if not os.path.exists(path):
        return {}
    return {r["month"]: float(r["revenue"]) for r in csv.DictReader(open(path, encoding="utf-8"))}


def corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 4 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    return round(st.correlation(a, b), 2)


def seo(niche: str, d: str, subject: int) -> dict:
    P = preset(niche)
    files = sorted(glob.glob(os.path.join(RAW, d, niche, "seo", "keywords_*.json")))
    trend = load_subject_trend(d, subject)
    table, tracked = {}, {}
    per_month_q = {}
    for f in files:
        m = os.path.basename(f)[9:16]
        q = json.load(open(f, encoding="utf-8"))["queries"]
        per_month_q[m] = {x["word"]: x for x in q}
        tracked[m] = len(q)
        table[m] = {}
        for g, pat in P["seo"].items():
            hits = [x for x in q if re.search(pat, x["word"].lower())]
            table[m][g] = {"freq": sum(x["count"] for x in hits), "queries": len(hits),
                           "median_cards": st.median([x.get("items_count") or 0 for x in hits]) if hits else None}
    ms = sorted(table)
    # одни и те же запросы во всех месяцах (чтобы не путать рост спроса с ростом числа отслеживаемых запросов)
    core = set.intersection(*(set(per_month_q[m]) for m in ms)) if ms else set()
    core_rel = sorted(w for w in core if re.search(P["core"], w))
    print(f"Месяцев: {len(ms)}; отслеживаемых запросов по месяцам: {[tracked[m] for m in ms]}")
    print(f"Сквозных запросов (есть во всех {len(ms)} мес.), релевантных нише: {len(core_rel)}\n")
    print("| Группа запросов | " + " | ".join(ms) + " | корр. с выручкой предмета |")
    print("|---|" + "---:|" * len(ms) + "---:|")
    out = {"months": ms, "tracked": tracked, "groups": {}, "core": {}}
    sales = [trend.get(m) for m in ms]
    for g in P["seo"]:
        row = [table[m][g]["freq"] for m in ms]
        c = corr(row, sales) if all(s is not None for s in sales) else None
        out["groups"][g] = {"freq": dict(zip(ms, row)), "corr_revenue": c,
                            "median_cards": {m: table[m][g]["median_cards"] for m in ms}}
        print(f"| {g} | " + " | ".join(f"{v:,}" for v in row) + f" | {c if c is not None else '—'} |")
    print("| **Выручка предмета, M ₽** | " + " | ".join(f"{(trend.get(m) or 0)/1e6:.1f}" for m in ms) + " | — |")
    print("\n## Сквозные запросы (частота по месяцам)")
    for w in sorted(core_rel, key=lambda w: -sum(per_month_q[m][w]["count"] for m in ms))[:12]:
        row = [per_month_q[m][w]["count"] for m in ms]
        cards = [per_month_q[m][w].get("items_count") for m in ms]
        c = corr(row, sales) if all(s is not None for s in sales) else None
        out["core"][w] = {"freq": dict(zip(ms, row)), "cards": dict(zip(ms, cards)), "corr_revenue": c}
        print(f"- {w}: {row} | карточек {cards[0]}→{cards[-1]} | корр. {c}")
    print("\n## Новые сильные запросы месяца (нет в прошлом месяце, частота ≥ 500, релевантные нише)")
    out["new_queries"] = {}
    for a, b in zip(ms, ms[1:]):
        new = [x for w, x in per_month_q[b].items() if w not in per_month_q[a] and x["count"] >= 500
               and re.search(P["new"], w)]
        new.sort(key=lambda x: -x["count"])
        out["new_queries"][b] = [(x["word"], x["count"]) for x in new[:6]]
        if new:
            print(b, out["new_queries"][b])
    return out


def load_days(path: str) -> list[dict]:
    rows = json.load(open(path, encoding="utf-8"))
    rows.sort(key=lambda x: x["data"])
    return rows


def launch(niche: str, d: str) -> dict:
    res = {}
    for path in sorted(glob.glob(os.path.join(RAW, d, niche, "winners", "*", "by_period.json"))):
        sku = os.path.basename(os.path.dirname(path))
        rows = load_days(path)
        stock = [r for r in rows if (r.get("balance") or 0) > 0 or (r.get("sales") or 0) > 0]
        if not stock:
            continue
        start = stock[0]["data"]
        live = [r for r in rows if r["data"] >= start]
        s = [r.get("sales") or 0 for r in live]
        first7, first14, first30 = s[:7], s[:14], s[:30]
        c0 = live[0].get("comments") or 0
        def at(k: int, key: str):
            return live[min(k, len(live) - 1)].get(key)
        c21 = (at(21, "comments") or 0) - c0
        ads30 = sum(1 for r in live[:30] if (r.get("in_ads") or 0) > 0)
        if st.mean(first7) >= 8:
            kind = "рекламный старт"
        elif c21 >= 50:
            kind = "выкуп + органика"
        else:
            kind = "органика"
        monthly = defaultdict(lambda: defaultdict(float))
        for r in live:
            mm = r["data"][:7]
            M = monthly[mm]
            M["sales"] += r.get("sales") or 0
            M["revenue"] += r.get("revenue") or 0
            M["days"] += 1
            M["in_stock"] += 1 if (r.get("balance") or 0) > 0 else 0
            M["ads_days"] += 1 if (r.get("in_ads") or 0) > 0 else 0
            M["ad_words"] += r.get("search_words_in_ad") or 0
            M["words"] += r.get("search_words_count") or 0
            M["pos"] += r.get("search_position_avg") or 0
            M["promo_days"] += 1 if (r.get("in_action") or 0) > 0 else 0
            M["posts"] += (r.get("adv_stats") or {}).get("posts") or 0
            M["price_sum"] += r.get("final_price") or 0
            M["comments_end"] = r.get("comments") or 0
            M["base_price"] = r.get("price") or 0
        mon = {}
        for mm, M in sorted(monthly.items()):
            n = M["days"] or 1
            mon[mm] = dict(sales=int(M["sales"]), revenue=round(M["revenue"]), avg_price=round(M["price_sum"] / n),
                           base_price=int(M["base_price"]), in_stock_days=int(M["in_stock"]), days=int(n),
                           ads_days=int(M["ads_days"]), avg_ad_words=round(M["ad_words"] / n, 1),
                           avg_search_words=round(M["words"] / n, 1), avg_position=round(M["pos"] / n),
                           promo_days=int(M["promo_days"]), posts=int(M["posts"]), comments_end=int(M["comments_end"]))
        r = dict(sku=sku, start=start, kind=kind,
                 first7=first7, avg7=round(st.mean(first7), 1), avg14=round(st.mean(first14), 1), avg30=round(st.mean(first30), 1),
                 price_start=live[0].get("final_price"), base_price_start=live[0].get("price"),
                 price_30=at(30, "final_price"), price_90=at(90, "final_price"), price_now=live[-1].get("final_price"),
                 comments_start=c0, comments_21=c21, comments_60=(at(60, "comments") or 0) - c0, comments_now=live[-1].get("comments"),
                 ads_days_first30=ads30, monthly=mon)
        res[sku] = r
        print(f"\n### {sku} — старт {start} — **{kind}**")
        print(f"- первые 7 дней, шт/день: {first7}; среднее 7/14/30 дн: {r['avg7']} / {r['avg14']} / {r['avg30']}")
        print(f"- цена со скидкой: старт {r['price_start']} → +30 дн {r['price_30']} → +90 дн {r['price_90']} → сейчас {r['price_now']}; "
              f"базовая (зачёркнутая) на старте {r['base_price_start']}")
        print(f"- отзывы: на старте {c0}, +21 дн {c21}, +60 дн {r['comments_60']}, сейчас {r['comments_now']}; "
              f"дней в рекламе WB за первые 30: {ads30}")
        print("| Месяц | Продаж | Выручка | Ср. цена | Баз. цена | Дней в наличии | Дней в рекламе WB | Ключей в рекламе | Ключей в поиске | Ср. позиция | Акции, дн | Внеш. посты | Отзывов |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for mm, M in mon.items():
            print(f"| {mm} | {M['sales']} | {M['revenue']:,} | {M['avg_price']} | {M['base_price']} | {M['in_stock_days']}/{M['days']} | "
                  f"{M['ads_days']} | {M['avg_ad_words']} | {M['avg_search_words']} | {M['avg_position']} | {M['promo_days']} | {M['posts']} | {M['comments_end']} |")
    json.dump(res, open(os.path.join(RAW, d, niche, "winners", "launch.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return res


def gaps(niche: str, d: str) -> dict:
    P = preset(niche)
    months = load_months(niche, d)
    last = [x for m in sorted(months)[-3:] for x in months[m]]
    bands = P["bands"]
    print(f"## Ценовые окна, {P['target_label']} (последние 3 мес.)")
    print("| Полоса | Карточек | Выручка / карточко-мес | Мед. отзывов | Новинок (< 365 дн) |")
    print("|---|---:|---:|---:|---:|")
    out = {"bands": {}}
    mon = [x for x in last if is_target(P, x["name"])]
    for lo, hi in bands:
        rows = [x for x in mon if lo <= x["final_price"] < hi]
        if not rows:
            continue
        ids = {x["id"] for x in rows}
        r = dict(cards=len(ids), rev_per_card_month=round(sum(x["revenue"] for x in rows) / len(rows)),
                 median_comments=st.median(x.get("comments") or 0 for x in rows),
                 young=len({x["id"] for x in rows if (x.get("days_in_site") or 9999) < 365}))
        out["bands"][f"{lo}-{hi}"] = r
        print(f"| {lo}–{hi} ₽ | {r['cards']} | {r['rev_per_card_month']:,} ₽ | {r['median_comments']:,.0f} | {r['young']} |")
    feats = P["feats"]
    top30 = [x for m in sorted(months)[-3:] for x in months[m] if x["rank"] <= 30]
    print("\n## Признаки в названиях top-30 (последние 3 мес.)")
    out["features"] = {}
    for f, pat in feats.items():
        n = len({x["id"] for x in top30 if re.search(pat, x["name"].lower())})
        out["features"][f] = n
        print(f"- {f}: {n} из {len({x['id'] for x in top30})} карточек")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["market", "seo", "launch", "gaps"])
    ap.add_argument("--niche", default="videonyani")
    ap.add_argument("--date", default="2026-10-04")
    ap.add_argument("--subject", type=int, default=902)
    a = ap.parse_args()
    out = {"market": lambda: market(a.niche, a.date), "seo": lambda: seo(a.niche, a.date, a.subject),
           "launch": lambda: launch(a.niche, a.date), "gaps": lambda: gaps(a.niche, a.date)}[a.cmd]()
    if a.cmd != "launch":
        json.dump(out, open(os.path.join(RAW, a.date, a.niche, f"dna_{a.cmd}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
