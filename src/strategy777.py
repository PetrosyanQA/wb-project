"""Глубокий разбор ниши 777 «Держатели в авто» под шаблон «Senior E-commerce Strategist» (2026-10-06). 0 запросов.

    python -m src.strategy777            # → data/processed/strategy777_2026-10-06.json + таблицы в stdout

Вход (всё уже сохранено):
  data/raw/saleflow/2026-10-06/strategy777/  trends_month, products_30d, price_seg_*, keywords_30d, sku_*_{keywords,comments}
  data/raw/saleflow/2026-10-05/dna/777/      keywords_2025-09…2026-08, products500_2026-07, comments/, top100/cards, winners/
  data/processed/top100_777_2026-10-05.json  (top-100 июль: фото, видео, rich, реклама, позиции, остатки)
⚠️ Saleflow 2026-08…09 неполные (остаток = 0 при продажах) → «30 дней» = июль 2026, «90 дней» = май–июль 2026.
"""
from __future__ import annotations

import collections
import glob
import json
import re
import statistics as st
import sys

from src.unit_econ import load_config, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
NEW = "data/raw/saleflow/2026-10-06/strategy777"
OLD = "data/raw/saleflow/2026-10-05/dna/777"
TOP = "data/processed/top100_777_2026-10-05.json"
OUT = "data/processed/strategy777_2026-10-06.json"
SEG_IDS = {487711855, 485786521, 740582525, 397439115, 264729116, 494403950, 390437007, 1146446018, 481858028,
           913853487, 848134054, 148983914}                 # «магнит + вакуум» (top100_777 §7 + HYRO из сентября)
COMPLAINTS = {
    "магнит слабый / телефон падает": r"слаб\w* магнит|магнит\w* слаб|пада|пада[её]т|упал|пада|не держит телефон|телефон не держ|отва\w+ телефон|слетает",
    "присоска/основа отклеивается": r"присоск\w* (не|отва|отклеи|слет)|отклеи|отвал\w*(ся|ась)? (от|с) (панел|стекл|торпед)|не держится на|не прилип|не присас|отпада",
    "шарнир болтается / не держит угол": r"шарнир|болта|опуска|не держит угол|провис|клони|наклон",
    "не держит через чехол": r"чехл|чехол",
    "кольцо/пластина отклеивается": r"кольц\w* (отклеи|отва)|пластин\w* (отклеи|отва)|отклеил\w* кольц|отклеил\w* пластин",
    "жара/холод (лето, мороз)": r"жар|солнц|мороз|холод|зим|плав",
    "царапает/следы": r"царап|след",
    "брак/некомплект": r"брак|не (тот|та) |некомплект|не хватает|без кольц|пришл\w* (без|сломан)",
}


def load(p):
    return json.load(open(p, encoding="utf-8"))


def overview() -> dict:
    t = {r["label_date"]: r for r in load(f"{NEW}/trends_month.json")}
    jul, may_jul = t["2026-07"], [t[m] for m in ("2026-05", "2026-06", "2026-07")]
    months = [m for m in sorted(t) if "2024-09" <= m <= "2026-07"]
    # сезонность: средняя доля месяца от среднего по году (2 года, без неполных 08–09.2026)
    by_m = collections.defaultdict(list)
    for m in months:
        by_m[m[5:]].append(t[m]["sales"])
    mean_all = st.mean(t[m]["sales"] for m in months)
    season = {mm: round(st.mean(v) / mean_all * 100) for mm, v in sorted(by_m.items())}
    return {
        "rev_30d": jul["revenue"], "sales_30d": jul["sales"], "rev_90d": sum(r["revenue"] for r in may_jul),
        "sales_90d": sum(r["sales"] for r in may_jul), "sellers_total": jul["sellers"],
        "sellers_with_sells": jul["sellers_with_sells"], "items": jul["items"], "items_with_sells": jul["items_with_sells"],
        "aov": jul["average_order_value"],
        "yoy_peak_dec_sales": round((t["2025-12"]["sales"] / t["2024-12"]["sales"] - 1) * 100, 1),
        "yoy_peak_dec_rev": round((t["2025-12"]["revenue"] / t["2024-12"]["revenue"] - 1) * 100, 1),
        "yoy_jul_sales": round((t["2026-07"]["sales"] / t["2025-07"]["sales"] - 1) * 100, 1),
        "yoy_h1_sales": round((sum(t[f"2026-0{i}"]["sales"] for i in range(1, 8)) /
                               sum(t[f"2025-0{i}"]["sales"] for i in range(1, 8)) - 1) * 100, 1),
        "season_index": season,
        "series": {m: [t[m]["sales"], round(t[m]["revenue"] / 1e6, 1), t[m]["items_with_sells"], t[m]["sellers_with_sells"]]
                   for m in sorted(t) if m >= "2024-09"},
    }


def top20() -> list[dict]:
    T = load(TOP)
    P = {p["id"]: p for p in load(f"{OLD}/products500_2026-07.json")["data"]}
    rows = sorted(T, key=lambda c: -c["revenue_jul"])[:20]
    out = []
    for i, c in enumerate(rows, 1):
        p = P.get(c["id"], {})
        typ = "+".join(k for k in ("магнит", "MagSafe", "присоска/вакуум", "зажим/захват", "воздуховод", "зарядка") if c.get(k))
        out.append({"n": i, "id": c["id"], "name": c["name"], "brand": c["brand"], "seller": c["seller"], "type": typ,
                    "revenue": c["revenue_jul"], "sales": c["sales_jul_products"], "price": c["price_jul"],
                    "old_price": p.get("start_price"), "discount": p.get("basic_sale"), "spp": p.get("spp_avg"),
                    "buyer_price": round(c["revenue_jul"] / max(c["sales_jul_products"], 1)),
                    "rating": c["rating"], "comments": c["comments"], "pics": c["pics"], "video": c["video"], "rich": c["rich"],
                    "pos_med": c.get("pos_med"), "ads_pct": c.get("ads_pct"), "oos_days": c.get("oos_days"),
                    "start": c["start"], "growth": c.get("growth_jul_apr")})
    return out


def keywords() -> dict:
    """Год (2025-09…2026-08) по месяцам + последние 30 дней. wb_count = частота, count = товаров в выдаче."""
    year = collections.defaultdict(lambda: {"freq": 0, "months": 0, "count": [], "items": []})
    for f in sorted(glob.glob(f"{OLD}/keywords_20*.json")):
        for q in load(f)["queries"]:
            y = year[q["word"]]
            y["freq"] += q.get("wb_count") or 0
            y["months"] += 1
            y["count"].append(q.get("count") or 0)
            y["items"].append(q.get("items_count") or 0)
            y["cluster"] = q.get("query_cluster")
    last = {q["word"]: q for q in load(f"{NEW}/keywords_30d.json")["queries"]}
    rows = []
    for w, y in year.items():
        items = st.median(y["items"])
        if items < 20 or y["months"] < 6:
            continue                                            # чужие запросы (мало карточек 777 в выдаче)
        l = last.get(w, {})
        cnt = l.get("count") or st.median(y["count"])
        freq_m = l.get("wb_count") or round(y["freq"] / y["months"])
        rows.append({"q": w, "cluster": y.get("cluster"), "freq_year": y["freq"], "freq_30d": freq_m, "results": cnt,
                     "items_777": round(items), "deficit": round(freq_m / max(cnt, 1), 2)})
    rows.sort(key=lambda r: -r["freq_year"])
    top50 = rows[:50]
    seg_re = re.compile(r"магнит|присоск|вакуум|magsafe|магсейф|мagsafe|на панел|торпед|на стекл", re.I)
    gap = sorted([r for r in rows if r["freq_30d"] >= 1500 and seg_re.search(r["q"])], key=lambda r: -r["deficit"])[:20]
    return {"top50": top50, "gap": gap, "n_rel": len(rows)}


def positions() -> dict:
    """Средняя органическая позиция лидеров сегмента по ключам (сентябрь 2026)."""
    out = {}
    for f in glob.glob(f"{NEW}/sku_*_keywords.json"):
        sku = int(re.search(r"sku_(\d+)_", f).group(1))
        words = load(f)["data"]["words"]
        out[sku] = {w["query"]: {"pos": w.get("avg_position"), "org": w.get("avg_organic_position"),
                                 "ad": w.get("avg_ad_position"), "freq": w.get("wb_count")} for w in words}
    return out


def prices() -> dict:
    P = [p for p in load(f"{OLD}/products500_2026-07.json")["data"] if p.get("final_price")]
    fp = [p["final_price"] for p in P]
    bp = [p["revenue"] / p["sales"] for p in P if p.get("sales")]
    segs = {}
    for tag in ("2026-07", "30d"):
        ps = load(f"{NEW}/price_seg_{tag}.json")
        tot = sum(r["revenue"] for r in ps)
        segs[tag] = [{"range": r["range"], "items": r["items"], "iws": r["items_with_sells"], "sales": r["sales"],
                      "rev": r["revenue"], "share": round(r["revenue"] / tot * 100, 1),
                      "rev_per_iws": round(r["revenue"] / max(r["items_with_sells"], 1)),
                      "comp_index": round(r["items"] / max(r["revenue"] / 1e6, 0.01))} for r in ps]
    return {"before_spp": {"min": min(fp), "med": st.median(fp), "mean": round(st.mean(fp)), "max": max(fp)},
            "buyer": {"min": round(min(bp)), "med": round(st.median(bp)), "mean": round(st.mean(bp)), "max": round(max(bp))},
            "segments": segs}


def content() -> dict:
    T = sorted(load(TOP), key=lambda c: -c["revenue_jul"])[:20]
    cards = []
    for c in T:
        try:
            cards.append(load(f"{OLD}/top100/cards/{c['id']}.json"))
        except FileNotFoundError:
            pass
    words = collections.Counter()
    pains = collections.Counter()
    pain_re = {"не падает / надёжно держит": r"не пада|надёжн|надежн|крепк|прочн|стабильн|держит",
               "на кочках / резкое торможение": r"кочк|торможен|манёвр|маневр|тряс|неровн",
               "360° / угол обзора": r"360|поворот|угол",
               "без следов / легко снять": r"без следов|не оставля|легко сн",
               "одной рукой / быстро": r"одной рук|быстро|мгновенн|секунд",
               "универсальный / любой телефон": r"любо\w+ (телефон|смартфон)|универсальн|iphone|samsung|android",
               "MagSafe": r"magsafe|магсейф",
               "жара/мороз": r"жар|мороз|температур",
               "подарок": r"подар"}
    for c in cards:
        for w in re.findall(r"[а-яёa-z0-9°]+", c["imt_name"].lower()):
            if len(w) > 2:
                words[w] += 1
        d = (c.get("description") or "").lower()
        for k, rx in pain_re.items():
            if re.search(rx, d):
                pains[k] += 1
    tops = [c for c in load(TOP)]
    return {"n": len(cards), "title_words": words.most_common(25), "pains": pains.most_common(),
            "pics_med_top20": st.median(c["pics"] or 0 for c in T), "video_top20": sum(bool(c["video"]) for c in T),
            "rich_top20": sum(bool(c["rich"]) for c in T), "pics_med_top100": st.median(c["pics"] or 0 for c in tops),
            "video_top100": sum(bool(c["video"]) for c in tops), "rich_top100": sum(bool(c["rich"]) for c in tops),
            "titles": [c["imt_name"] for c in cards]}


def complaints() -> dict:
    files = {**{int(re.search(r"(\d+)\.json", f).group(1)): f for f in glob.glob(f"{OLD}/comments/*.json")},
             **{int(re.search(r"sku_(\d+)_", f).group(1)): f for f in glob.glob(f"{NEW}/sku_*_comments.json")}}
    per, pooled, total = {}, collections.Counter(), 0
    quotes = collections.defaultdict(list)
    for sku, f in files.items():
        c = load(f)["comments"]
        neg = [x for x in c if x["valuation"] <= 3 and (x.get("text") or "").strip() and x["date"] >= "2025-10-06"]
        total += len(neg)
        hit = collections.Counter()
        for x in neg:
            t = x["text"].lower()
            for k, rx in COMPLAINTS.items():
                if re.search(rx, t):
                    hit[k] += 1
                    if len(quotes[k]) < 3 and len(x["text"]) > 25:
                        quotes[k].append(x["text"][:140].replace("\n", " "))
        pooled.update(hit)
        per[sku] = {"reviews": len(c), "neg365": len(neg), "neg_pct": round(len(neg) / max(len(c), 1) * 100, 1),
                    "top": hit.most_common(3)}
    return {"per_sku": per, "total_neg": total,
            "themes": [(k, v, round(v / max(total, 1) * 100)) for k, v in pooled.most_common()], "quotes": dict(quotes)}


def barriers() -> dict:
    T = sorted(load(TOP), key=lambda c: -c["revenue_jul"])
    top10 = T[:10]
    seg = [c for c in T if c["id"] in SEG_IDS]
    new = [c for c in T if c["start"] >= "2025-10-01"]
    # скорость выхода: 494403950 по дням от первого дня продаж
    w = sorted(load(f"{OLD}/winners/494403950_by_period.json"), key=lambda r: r["data"])
    first = next(r["data"] for r in w if (r.get("sales") or 0) > 0)
    hit10 = next((r["data"] for r in w if r["data"] >= first and (r.get("sales") or 0) >= 10), None)
    hit30 = next((r["data"] for r in w if r["data"] >= first and (r.get("sales") or 0) >= 30), None)
    com_at = {r["data"]: r.get("comments") for r in w}
    return {"reviews_top10_med": st.median(c["comments"] for c in top10),
            "reviews_seg_med": st.median(c["comments"] for c in seg) if seg else None,
            "reviews_top100_min": min(c["comments"] for c in T),
            "new_cards_in_top100": len(new), "new_cards_share": round(sum(c["revenue_jul"] for c in new) /
                                                                       sum(c["revenue_jul"] for c in T) * 100, 1),
            "ads_med_top100": st.median(c.get("ads_pct") or 0 for c in T),
            "winner_494403950": {"first_sale": first, "day10": hit10, "day30": hit30,
                                 "reviews_at_10": com_at.get(hit10), "reviews_at_30": com_at.get(hit30),
                                 "series_len": len(w)}}


def econ() -> dict:
    cfg = load_config()
    kw = dict(buyout_pct=84.6, commission_pct=20.0, ad_share_of_revenue_pct=15.0, packaging_rub=15)
    out = {}
    for tag, price, yuan, vol, drr in (("старт ДРР 25%", 1590, 18, 0.4, 25.0), ("база ДРР 15%", 1590, 18, 0.4, 15.0),
                                       ("зрелость ДРР 10%", 1590, 18, 0.4, 10.0), ("цена −15%", 1352, 18, 0.4, 15.0),
                                       ("СПП-сценарий (от цены покупателя 1 000 ₽)", 1000, 18, 0.4, 15.0)):
        e = unit_economics(price, yuan * 17, vol, cfg, **{**kw, "ad_share_of_revenue_pct": drr})
        out[tag] = {**{k: e[k] for k in ("price", "commission", "logistics_with_returns", "storage", "goods_cost_full",
                                         "ads", "tax", "net_profit", "net_margin_pct", "roi_on_goods_pct", "breakeven_price")},
                    "yuan": yuan}
    # макс. себестоимость при 18% / 60%
    lo, hi = 0.0, 1590.0
    for _ in range(50):
        mid = (lo + hi) / 2
        e = unit_economics(1590, mid, 0.4, cfg, with_breakeven=False, **kw)
        lo, hi = (mid, hi) if e["net_margin_pct"] >= 18 and e["roi_on_goods_pct"] >= 60 else (lo, mid)
    out["max_cost_rub"] = round(lo)
    out["max_yuan"] = round(lo / 17, 1)
    out["fixed_month_rub"] = 10000                              # минимум фулфилмента (память: user-hard-gates)
    out["breakeven_units_month"] = round(10000 / out["база ДРР 15%"]["net_profit"])
    out["tariffs_source"] = cfg.get("_tariffs_source")
    return out


def main() -> None:
    D = {"overview": overview(), "top20": top20(), "keywords": keywords(), "positions": positions(), "prices": prices(),
         "content": content(), "complaints": complaints(), "barriers": barriers(), "econ": econ()}
    json.dump(D, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    o = D["overview"]
    print("OVERVIEW", {k: v for k, v in o.items() if k != "series"})
    print("SERIES", o["series"])
    print("\nTOP20")
    for r in D["top20"]:
        print(r)
    k = D["keywords"]
    print(f"\nKEYWORDS rel={k['n_rel']}")
    for r in k["top50"]:
        print(r)
    print("\nGAP")
    for r in k["gap"]:
        print(r)
    print("\nPRICES", D["prices"]["before_spp"], D["prices"]["buyer"])
    print("\nCONTENT", {kk: v for kk, v in D["content"].items() if kk != "titles"})
    for t in D["content"]["titles"]:
        print("  T:", t)
    print("\nCOMPLAINTS", json.dumps(D["complaints"], ensure_ascii=False)[:4000])
    print("\nBARRIERS", D["barriers"])
    print("\nECON", json.dumps(D["econ"], ensure_ascii=False))


if __name__ == "__main__":
    main()
