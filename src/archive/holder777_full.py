"""Ниша 777 «Держатели в авто» — полный разбор на ВСЕХ сохранённых данных (2026-10-16). 0 запросов.
A рынок 2 года (by_date дневки) · B сегменты по месяцам (winners777_deep) · C сегменты products500 июль ·
D новички по ценовым полосам · E жалобы по всем файлам отзывов · F спрос по типам + SEO · G экономика am_fbs+карго
и финплан · H тактика запуска победителей (launch_summary, winners777_deep).

    python -m src.holder777_full
"""
import collections
import glob
import json
import os
import re
import statistics as st
import sys

from src import strategy as S, finplan as F
from src.recheck_all import econ_block, SH
from src.cargo import per_unit
from src.screen_v4 import max_yuan

sys.stdout.reconfigure(encoding="utf-8")
OUT = "data/processed/holder777_full_2026-10-16.json"
RAW = "data/raw/saleflow"
P500 = f"{RAW}/2026-10-05/dna/777/products500_2026-07.json"
NEW = ("2025-08-01", "2026-05-31")
COMM_AM = 20.0                                   # FBS AM-кабинет [факт, WB API]


def load(p):
    return json.load(open(p, encoding="utf-8"))


def q(v, a):
    v = sorted(v)
    return round(v[int(round(a * (len(v) - 1)))], 1) if v else None


def med(v, nd=0):
    v = [x for x in v if x is not None]
    return round(st.median(v), nd) if v else None


# ── A. рынок по месяцам ───────────────────────────────────────────────────────────────────────────────────────
def market():
    R = {}
    for p in glob.glob(f"{RAW}/2026-10-16/weekly/777/by_date_*.json"):
        for r in load(p):
            R[r["period"]] = r
    M = collections.defaultdict(lambda: {"sales": 0, "revenue": 0, "sellers": 0, "items": 0, "days": 0})
    for d, r in R.items():
        m = M[d[:7]]
        m["sales"] += r["sales"]; m["revenue"] += r["revenue"]; m["days"] += 1
        m["sellers"] += r["sellers_with_sells"]; m["items"] += r["items_with_sells"]
    out = {}
    for k in sorted(M):
        m = M[k]
        sd = m["sales"] / m["days"]
        out[k] = {"sales": m["sales"], "rev_mln": round(m["revenue"] / 1e6, 1), "sellers_day": round(m["sellers"] / m["days"]),
                  "cards_day": round(m["items"] / m["days"]), "per_seller_day": round(sd / (m["sellers"] / m["days"]), 1),
                  "per_card_day": round(sd / (m["items"] / m["days"]), 2), "avg_price": round(m["revenue"] / m["sales"])}
    yoy = {}
    for k in out:
        prev = f"{int(k[:4]) - 1}{k[4:]}"
        if prev in out:
            yoy[k] = {"sales_pct": round((out[k]["sales"] / out[prev]["sales"] - 1) * 100, 1),
                      "rev_pct": round((out[k]["rev_mln"] / out[prev]["rev_mln"] - 1) * 100, 1),
                      "per_seller_pct": round((out[k]["per_seller_day"] / out[prev]["per_seller_day"] - 1) * 100, 1)}
    by_m = collections.defaultdict(list)
    for k, v in out.items():
        by_m[k[5:]].append(v["sales"] / R_DAYS(k))
    base = st.mean(st.mean(v) for v in by_m.values())
    season = {m: round(st.mean(v) / base * 100) for m, v in sorted(by_m.items())}
    return {"months": out, "yoy": yoy, "season_index": season}


def R_DAYS(k):
    y, m = int(k[:4]), int(k[5:])
    return [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


# ── C/D. сегменты products500 июль ───────────────────────────────────────────────────────────────────────────
CARDS = {int(os.path.basename(f)[:-5]): f for g in ("top100/cards", "cards")
         for f in glob.glob(f"{RAW}/2026-10-05/dna/777/{g}/*.json")}


def card_opt(sku, key):
    if sku not in CARDS:
        return None
    c = load(CARDS[sku])
    c = c.get("data", c) if isinstance(c, dict) and "options" not in c else c
    try:
        return S.opt(c, key)
    except (TypeError, KeyError, AttributeError):
        return None


def segment(name, sku=None):
    """По названию; если есть карточка (топ-100) — добавляем «Тип крепления» (у 485786521 «вакуум» только в карточке)."""
    n = name.lower()
    n += " " + (card_opt(sku, "Тип крепления") or "").lower()
    if re.search(r"заряд|беспроводн|\bqi\b|\d+\s?w\b|ватт", n):
        return "с зарядкой"
    mag, vac = bool(re.search(r"магнит", n)), bool(re.search(r"вакуум|присоск", n))
    if mag and vac:
        return "магнит + вакуум"
    if re.search(r"magsafe|магсейф", n):
        return "MagSafe (магнит)"
    if mag:
        return "магнит"
    if vac:
        return "присоска/вакуум + зажим"
    if re.search(r"воздуховод|дефлектор|решетк|решётк", n):
        return "воздуховод"
    return "прочие (зажим, гравитац., на руль…)"


def rows():
    d = load(P500)
    return [x for x in (d.get("data", d) if isinstance(d, dict) else d) if x.get("sales")]


def vol(x):
    v = (x.get("package_length") or 0) * (x.get("package_width") or 0) * (x.get("package_height") or 0) / 1000
    return v or None


def newcomers(X, k):
    new = [x for x in X if NEW[0] <= (x.get("sku_first_date") or "") <= NEW[1]]
    lv = [x["sales"] / 31 / k for x in new]
    win = [x for x in new if x["sales"] / 31 / k >= 5]
    return {"n": len(new), "P25": q(lv, .25), "P50": q(lv, .5), "P75": q(lv, .75), "win5": len(win),
            "win_sellers": len({x.get("seller") for x in win}),
            "win_pct": round(len(win) / len(new) * 100) if new else None}


def segments(k):
    X = rows()
    tot = sum(x["revenue"] for x in X)
    G = collections.defaultdict(list)
    for x in X:
        x["_seg"] = segment(x["name"], x["id"]); x["_bp"] = x["revenue"] / x["sales"]
        G[x["_seg"]].append(x)
    out = {}
    for s, L in sorted(G.items(), key=lambda kv: -sum(x["revenue"] for x in kv[1])):
        rv = sum(x["revenue"] for x in L)
        top = max(L, key=lambda x: x["revenue"])
        sellers = {x.get("seller") for x in L}
        out[s] = {"cards": len(L), "sellers": len(sellers), "rev_mln": round(rv / 1e6, 2),
                  "rev_share": round(rv / tot * 100, 1),
                  "top_seller_share": round(max(sum(x["revenue"] for x in L if x.get("seller") == sl) for sl in sellers) / rv * 100, 1),
                  "buyer_price_med": med([x["_bp"] for x in L]), "price_before_spp_med": med([x.get("final_price") for x in L]),
                  "spp_med": med([x.get("spp_avg") for x in L]), "buyout_med": med([x.get("purchase") for x in L]),
                  "vol_med_l": med([vol(x) for x in L], 2), "video_pct": round(sum(1 for x in L if x.get("hasvideo")) / len(L) * 100),
                  "fbs_pct": round(sum(1 for x in L if x.get("is_fbs")) / len(L) * 100),
                  "rating_med": med([x.get("rating") for x in L], 2),
                  "leader": {"id": top["id"], "seller": top.get("seller"), "sales_day": round(top["sales"] / 31, 1)},
                  "new": newcomers(L, k)}
    return X, out


def bands(X, k, seg, edges=(0, 500, 700, 900, 1100, 1400, 1800, 99999)):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        L = [x for x in X if x["_seg"] in seg and lo <= x["_bp"] < hi]
        if not L:
            continue
        rv = sum(x["revenue"] for x in L)
        out.append({"band": f"{lo}–{hi if hi < 99999 else '∞'}", "cards": len(L), "rev_mln": round(rv / 1e6, 2),
                    "price_before_spp_med": med([x.get("final_price") for x in L]), "buyout_med": med([x.get("purchase") for x in L]),
                    **{f"new_{a}": b for a, b in newcomers(L, k).items()}})
    return out


def leaders(X, seg, n=12):
    L = sorted([x for x in X if x["_seg"] in seg], key=lambda x: -x["revenue"])[:n]
    return [{"id": x["id"], "seller": x.get("seller"), "name": x["name"][:60], "seg": x["_seg"], "start": x.get("sku_first_date"),
             "sales_day": round(x["sales"] / 31, 1), "buyer_price": round(x["_bp"]), "price_before_spp": x.get("final_price"),
             "spp": x.get("spp_avg"), "buyout": x.get("purchase"), "rating": x.get("rating"), "comments": x.get("comments"),
             "pics": x.get("picscount"), "video": x.get("hasvideo"), "wh": x.get("warehouses_count"),
             "words": x.get("search_words_count"), "vol_l": round(vol(x), 2) if vol(x) else None} for x in L]


# ── E. отзывы ───────────────────────────────────────────────────────────────────────────────────────────────
def reviews():
    best = {}
    for f in glob.glob(f"{RAW}/2026-10-*/**/*.json", recursive=True):
        ff = f.replace("\\", "/")
        if "777" not in ff or "comment" not in ff.lower():
            continue
        ids = re.findall(r"(\d{6,})", os.path.basename(f))
        if not ids:
            continue
        try:
            c = load(f)["comments"]
        except Exception:
            continue
        if len(c) > len(best.get(int(ids[0]), ([], ""))[0]):
            best[int(ids[0])] = (c, ff)
    per, pooled, praise, quotes = {}, collections.Counter(), collections.Counter(), collections.defaultdict(list)
    tot_neg = tot_pos = 0
    for sku, (c, f) in best.items():
        rec = [x for x in c if (x.get("date") or "") >= S.COMMENTS_SINCE and (x.get("text") or "").strip()]
        neg = [x for x in rec if x["valuation"] <= 3]
        pos = [x for x in rec if x["valuation"] >= 5]
        tot_neg += len(neg); tot_pos += len(pos)
        hit = collections.Counter()
        for x in neg:
            t = x["text"].lower()
            for th, rx in S.COMPLAINTS_777.items():
                if re.search(rx, t):
                    hit[th] += 1
                    if len(quotes[th]) < 3 and 30 < len(x["text"]) < 200:
                        quotes[th].append(x["text"].replace("\n", " "))
        for x in pos:
            t = x["text"].lower()
            for th, rx in S.PAINS_777.items():
                if re.search(rx, t):
                    praise[th] += 1
        pooled.update(hit)
        per[sku] = {"file": f, "texts_365": len(rec), "neg": len(neg),
                    "neg_pct": round(len(neg) / max(len(rec), 1) * 100, 1), "top": hit.most_common(2)}
    return {"skus": len(best), "neg_total": tot_neg, "pos_total": tot_pos, "per_sku": per,
            "themes": [(k, v, round(v / max(tot_neg, 1) * 100)) for k, v in pooled.most_common()],
            "praise": [(k, v, round(v / max(tot_pos, 1) * 100)) for k, v in praise.most_common()], "quotes": dict(quotes)}


# ── F. спрос ────────────────────────────────────────────────────────────────────────────────────────────────
def demand(deep):
    seo = []
    p = f"{RAW}/2026-10-05/dna/777/keywords_2026-07.json"
    if os.path.exists(p):
        Q = load(p)["queries"]
        seo = sorted([w for w in Q if re.search(r"магнит|вакуум|присоск|magsafe|магсейф", w["word"])],
                     key=lambda w: -(w.get("wb_count") or 0))[:25]
        seo = [{"word": w["word"], "freq": w["wb_count"], "cards": w.get("items_count")} for w in seo]
    return {"by_type": deep["demand_by_month"], "seo_jul": seo}


# ── G. экономика кандидатов ─────────────────────────────────────────────────────────────────────────────────
MAGS = ("магнит + вакуум", "магнит", "MagSafe (магнит)")
# имя, сегменты-аналоги для уровней новичков, полоса цены покупателя ₽, цена до СПП (None → медиана полосы), ¥ (lo, hi) [допущение], кг [допущение]
CAND = [
    ("A. Магнит+вакуум MagSafe, премиум-набор (кольца+пластины)", MAGS, (1000, 1500), 1590, (12, 18), 0.15),
    ("B. Магнит+вакуум, средняя цена", MAGS, (650, 1000), None, (8, 12), 0.14),
    ("C. MagSafe с беспроводной зарядкой", ("с зарядкой",), (1000, 2200), None, (25, 35), 0.25),
    ("D. Присоска/вакуум + зажим (автозахват)", ("присоска/вакуум + зажим", "прочие (зажим, гравитац., на руль…)"), (450, 800), None, (8, 14), 0.20),
    ("E. Магнитный на воздуховод", ("воздуховод",), (300, 800), None, (5, 9), 0.10),
]


def economics(X, k, season):
    out = []
    for name, seg, (lo, hi), price, (ylo, yhi), kg in CAND:
        L = [x for x in X if x["_seg"] in seg and lo <= x["_bp"] < hi]
        nc = newcomers(L, k)
        fp_med = med([x.get("final_price") for x in L])
        price = price or int(round(fp_med / 10) * 10)
        bo = med([x.get("purchase") for x in L]) or 85
        v = med([vol(x) for x in L], 2) or 0.75
        u = per_unit(ylo, kg, v)
        o = {"name": name, "n_cards": len(L), "price": price, "fp_med_band": fp_med, "buyer_price": med([x["_bp"] for x in L]), "buyout": bo,
             "vol": v, "kg": kg, "pcs_carton": u["pcs_per_carton"], "cargo": u["cargo_rub"], "new": nc,
             "max15": max_yuan(price, v, kg, bo, COMM_AM, 15, 0), "max10": max_yuan(price, v, kg, bo, COMM_AM, 10, 0)}
        for tag, y in (("lo", ylo), ("hi", yhi)):
            c, e = econ_block(price, y, kg, v, bo, COMM_AM)
            r = {"y": y, "landed": c, "m15": e[15]["net_margin_pct"], "m10": e[10]["net_margin_pct"],
                 "pr15": round(e[15]["net_profit"]), "pr10": round(e[10]["net_profit"]), "roi10": e[10].get("roi_on_cost_pct")}
            if nc["P50"] and nc["n"] >= 5:
                prod = {"name": name, "price": price, "yuan": y, "vol": v, "kg": kg, "buyout": float(bo), "commission": COMM_AM}
                b = F.fit_batch(prod)
                ss = F.season_from(season, "2027-01")
                r["batch"] = b
                r.update({l: F.run(l, prod, [x * sh for sh in SH], ss, b)["net_12m"]
                          for l, x in (("p25", nc["P25"]), ("p50", nc["P50"]), ("p75", nc["P75"]), ("fail", 1.5)) if x})
            o[tag] = r
        # стресс при ¥ lo, ДРР 10: цена −15 % (война цен) и выкуп −10 п.п.
        o["stress_price85_m10"] = econ_block(round(price * 0.85), ylo, kg, v, bo, COMM_AM)[1][10]["net_margin_pct"]
        o["stress_bo-10_m10"] = econ_block(price, ylo, kg, v, bo - 10, COMM_AM)[1][10]["net_margin_pct"]
        out.append(o)
    return out


# ── H. запуск ───────────────────────────────────────────────────────────────────────────────────────────────
def launch(deep):
    ls = load("data/processed/launch_summary_2026-10-08.json")
    W = [{"id": w["id"], "seller": w["seller"], "start": w["start"], "segment": w["segment"], "jul_sales_day": w["jul_sales_day"],
          "launch": w["launch"], "price_w1": w["entry_price_buyer_w1"], "photos": w["card"]["photos"], "video": w["card"]["video"],
          "kit": w["card"].get("kit"), "neg_pct": w["own_reviews"]["neg_pct"], "days_to": w["tactics"]["days_to"],
          "ads_w1_4": w["tactics"]["w1_8_ads"][:4], "promo_w1_4": w["tactics"]["w1_8_promo"][:4],
          "sales_w1_8": w["tactics"]["w1_8_sales"]} for w in deep["winners"]]
    return {"n777": ls["n777"], "all_niches": {k: ls[k] for k in ("n", "days_to_reviews", "reach_50_reviews_pct", "price_w1_vs_w8",
                                                                     "launch_types", "corr")}, "winners777": W}


def main():
    deep = load("data/processed/winners777_deep_2026-10-08.json")
    A = market()
    k = A["season_index"]["07"] / 100
    X, C = segments(k)
    res = {"market": A, "k_july": k, "segments": C,
           "bands_magvac": bands(X, k, ("магнит + вакуум",)),
           "bands_all": bands(X, k, tuple(C)),
           "leaders_magvac": leaders(X, ("магнит + вакуум",)),
           "leaders_all": leaders(X, tuple(C), 10),
           "segments_by_month": deep["markets"], "reviews": reviews(), "demand": demand(deep),
           "economics": economics(X, k, A["season_index"]), "launch": launch(deep)}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("k_july", k, "| season", A["season_index"])
    print("yoy", {m: v for m, v in A["yoy"].items() if m[5:] in ("12", "02", "03", "05", "07")})
    for s, v in C.items():
        print(f"{s:36} карт {v['cards']:3} прод {v['sellers']:3} выр {v['rev_share']:5}% топ-прод {v['top_seller_share']}% | "
              f"покуп {v['buyer_price_med']} до СПП {v['price_before_spp_med']} СПП {v['spp_med']} выкуп {v['buyout_med']} "
              f"V {v['vol_med_l']} видео {v['video_pct']}% | нов {v['new']}")
    print("\nполосы магнит+вакуум"); [print(" ", b) for b in res["bands_magvac"]]
    print("\nполосы все"); [print(" ", b) for b in res["bands_all"]]
    print("\nлидеры магнит+вакуум"); [print(" ", l) for l in res["leaders_magvac"]]
    print("\nлидеры все"); [print(" ", l) for l in res["leaders_all"]]
    r = res["reviews"]
    print(f"\nотзывы: {r['skus']} SKU, негатив {r['neg_total']}, 5★ {r['pos_total']}")
    print(" темы", r["themes"]); print(" хвалят", r["praise"])
    for s, v in r["per_sku"].items():
        print(" ", s, v["texts_365"], v["neg_pct"], v["top"])
    print("\nSEO", res["demand"]["seo_jul"][:15])
    for o in res["economics"]:
        print(f"\n{o['name']} | карт {o['n_cards']} | цена до СПП {o['price']} покуп {o['buyer_price']} выкуп {o['buyout']} V {o['vol']} "
              f"| карго {o['cargo']} | max¥ {o['max15']}/{o['max10']} | нов {o['new']} | стресс цена−15% {o['stress_price85_m10']}% "
              f"выкуп−10 {o['stress_bo-10_m10']}%")
        for t in ("lo", "hi"):
            print("  ", o[t])


if __name__ == "__main__":
    main()
