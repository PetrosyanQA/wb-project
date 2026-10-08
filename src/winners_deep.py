"""Глубокий разбор 12 новичков-победителей 777: какой был рынок при входе, что они закрыли, как заходили (2026-10-08). 0 запросов.

    python -m src.winners_deep      # → data/processed/winners777_deep_2026-10-08.json + таблицы в stdout

Источники (всё уже сохранено; сбор — src.winners_deep_collect):
  срез top-500 ниши в МЕСЯЦ ВХОДА  data/raw/saleflow/2026-10-08/winners777/market/products500_YYYY-MM.json
  спрос по запросам по месяцам     keywords_YYYY-MM (dna/777 + strategy777/keywords) — wb_count = частота
  карточки WB (комплект, материал)  dna/777/top100/cards/<sku>.json
  отзывы                            каталог (src.datastore files(777,'comments')) + winners777/comments
  траектория запуска                data/processed/launch_patterns_2026-10-08.json (недели, реклама, акции, взлёты)
Сегмент по названию: «с зарядкой» > «MagSafe» > «присоска/вакуум» > «воздуховод» > «магнитный» > «зажим» > «прочее».
Цены в срезах: final_price = до СПП, final_price_average = цена покупателя (memory saleflow-price-fields).
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import statistics as st
import sys

from src.datastore import files, rows

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-08"
MKT = "data/raw/saleflow/2026-10-08/winners777/market"
CARDS = "data/raw/saleflow/2026-10-05/dna/777/top100/cards"
OUT = f"data/processed/winners777_deep_{RUN}.json"
SEGS = [("с зарядкой", r"зарядк|беспроводн|qi\b"), ("MagSafe", r"magsafe|магсейф|маг сейф"),
        ("присоска/вакуум", r"вакуум|присоск"), ("воздуховод", r"воздуховод|дефлектор|решетк|решётк"),
        ("магнитный", r"магнит"), ("зажим", r"зажим|захват|автоматическ|клипс")]
PHONE = r"телефон|смартфон|iphone|айфон|magsafe|магсейф|навигатор"
COMPLAINTS = {
    "магнит слабый / телефон падает": r"слаб\w* магнит|магнит\w* слаб|пада|упал|не держит|слетает|отва\w+ телефон",
    "присоска/основа отклеивается": r"отклеи|отвал\w* присоск|присоск\w* (не|отва|отпад)|не прили|не клеит|отпада",
    "шарнир болтается": r"болта|шарнир|разбалт|не фиксир|провисает|опускается|крутится",
    "через чехол не держит": r"чехл|чехол",
    "сломался / качество": r"слома|трещ|хлипк|некачеств|брак|развалил",
}


def seg(name: str) -> str:
    t = (name or "").lower()
    for s, rx in SEGS:
        if re.search(rx, t):
            return s
    return "прочее"


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else None


def minus_months(month: str, n: int) -> str:
    """'2025-11', 4 → '2025-07-01' (карточки моложе 4 мес. на момент входа = «свежие конкуренты»)."""
    y, m = map(int, month.split("-"))
    m -= n
    while m <= 0:
        m += 12; y -= 1
    return f"{y}-{m:02d}-01"


def market(month: str) -> list[dict]:
    p = next((f for f in (f"{MKT}/products500_{month}.json", f"{MKT}/products100_{month}.json") if os.path.exists(f)), "")
    return sorted(rows(p), key=lambda r: -(r.get("revenue") or 0)) if os.path.exists(p) else []


def demand() -> dict[str, dict[str, int]]:
    """месяц → сегмент → сумма wb_count запросов про держатель телефона."""
    out = {}
    for c in files(777, "keywords"):
        m = re.search(r"keywords_(\d{4}-\d\d)\.json$", c["path"])
        if not m or m.group(1) in out:
            continue
        d = json.load(open(c["path"], encoding="utf-8"))
        Q = d.get("queries", []) if isinstance(d, dict) else []
        agg = collections.Counter()
        for q in Q:
            w = (q.get("word") or "").lower()
            if re.search(r"держател|подставк|крепл|магнит", w) and re.search(PHONE + r"|машин|авто", w):
                agg[seg(w)] += q.get("wb_count") or 0
                agg["ВСЕГО"] += q.get("wb_count") or 0
        out[m.group(1)] = dict(agg)
    return dict(sorted(out.items()))


def card(sku: int) -> dict:
    p = f"{CARDS}/{sku}.json"
    if not os.path.exists(p):
        return {}
    c = json.load(open(p, encoding="utf-8"))
    opt = {o["name"]: o["value"] for o in c.get("options", [])}
    return {"mount": opt.get("Тип крепления"), "material": opt.get("Материал изделия"), "kit": opt.get("Комплектация"),
            "weight": opt.get("Вес с упаковкой (кг)"), "color": opt.get("Цвет"), "photos": c.get("media", {}).get("photo_count"),
            "video": bool(c.get("media", {}).get("has_video")), "rich": bool(c.get("has_rich")), "desc_len": len(c.get("description") or "")}


def comments(sku: int) -> list[dict]:
    paths = [c["path"] for c in files(777, "comments") if c["sku"] == sku]
    paths += glob.glob(f"data/raw/saleflow/2026-10-08/winners777/comments/{sku}.json") + glob.glob(f"data/raw/saleflow/*/fresh777/comments/{sku}.json")
    best = []
    for p in set(paths):
        d = json.load(open(p, encoding="utf-8"))
        C = d.get("comments", []) if isinstance(d, dict) else []
        if len(C) > len(best):
            best = C
    return best


def complaint_profile(C: list[dict], lo: str = "0000", hi: str = "9999") -> dict:
    P = [c for c in C if lo <= c.get("date", "") <= hi]
    neg = [c for c in P if (c.get("valuation") or 5) <= 3 and (c.get("text") or "").strip()]
    hit = collections.Counter()
    for c in neg:
        t = c["text"].lower()
        for k, rx in COMPLAINTS.items():
            if re.search(rx, t):
                hit[k] += 1
    return {"reviews": len(P), "neg": len(neg), "neg_pct": round(len(neg) / len(P) * 100, 1) if P else None,
            "themes": {k: round(v / len(neg) * 100) for k, v in hit.most_common()} if neg else {}}


def main() -> None:
    S = json.load(open("data/processed/launch_sample_2026-10-08.json", encoding="utf-8"))["777"]
    LP = {c["id"]: c for c in json.load(open("data/processed/launch_patterns_2026-10-08.json", encoding="utf-8")) if c["niche"] == 777}
    jul = market("2026-07") or sorted(rows("data/raw/saleflow/2026-10-05/dna/777/products500_2026-07.json"), key=lambda r: -(r.get("revenue") or 0))
    D = demand()
    out = {"demand_by_month": D, "winners": [], "markets": {}}
    for p in S["win"]:
        sku, m = p["id"], p["sku_first_date"][:7]
        M = market(m)
        name = p["name"]
        cd = card(sku)
        my_seg = seg(f"{name} {cd.get('mount') or ''}")
        top = [r for r in M[:100]]
        rev = sum(r.get("revenue") or 0 for r in top) or 1
        segtop = [r for r in top if seg(r.get("name")) == my_seg]
        leaders = segtop[:3]
        lp = LP.get(sku, {})
        W = lp.get("weeks", [])
        entry_price = W[0]["price"] if W else None
        seller_cards_before = [r for r in M if r.get("seller") == p["seller"] and r["id"] != sku]
        seller_cards_jul = [r for r in jul if r.get("seller") == p["seller"]]
        # жалобы лидеров сегмента ДО входа (если их отзывы есть) и свои — после
        inc = []
        for L in leaders[:2]:
            prof = complaint_profile(comments(L["id"]), hi=p["sku_first_date"][:10])
            if prof["reviews"]:
                inc.append({"id": L["id"], **prof})
        mine = complaint_profile(comments(sku))
        # спрос сегмента: месяц входа vs +3 мес.
        months = list(D)
        dm = D.get(m, {}).get(my_seg)
        later = months[months.index(m) + 3] if m in months and months.index(m) + 3 < len(months) else None
        rec = {
            "id": sku, "name": name, "seller": p["seller"], "start": p["sku_first_date"][:10], "entry_month": m, "segment": my_seg,
            "jul_rank": p["rank"], "jul_sales_day": lp.get("jul_per_day"), "launch": lp.get("launch"),
            "market": {
                "snapshot": bool(M), "top100_revenue_mln": round(rev / 1e6, 1),
                "top10_share_pct": round(sum(r.get("revenue") or 0 for r in top[:10]) / rev * 100, 1) if M else None,
                "sellers_top100": len({r.get("seller") for r in top}) if M else None,
                "new_cards_top100_4m": sum(1 for r in top if (r.get("sku_first_date") or "")[:10] >= minus_months(m, 4)) if M else None,
                "seg_cards_top100": len(segtop), "seg_revenue_share_pct": round(sum(r.get("revenue") or 0 for r in segtop) / rev * 100, 1) if M else None,
                "seg_price_med_buyer": med([r.get("final_price_average") for r in segtop]),
                "seg_leaders": [{"id": r["id"], "name": (r.get("name") or "")[:45], "seller": r.get("seller"), "buyer_price": r.get("final_price_average"),
                                 "sales": r.get("sales"), "rating": r.get("rating"), "comments": r.get("comments")} for r in leaders],
                "price_med_top100_buyer": med([r.get("final_price_average") for r in top]),
            },
            "entry_price_buyer_w1": entry_price,
            "price_vs_seg_median": round(entry_price / med([r.get("final_price_average") for r in segtop]), 2) if entry_price and segtop else None,
            "demand_seg_entry": dm, "demand_seg_plus3": D.get(later, {}).get(my_seg) if later else None,
            "card": cd, "incumbent_complaints_before_entry": inc, "own_reviews": mine,
            "seller_cards_top500_at_entry": len(seller_cards_before), "seller_cards_top500_jul": len(seller_cards_jul),
            "tactics": {"reviews_day0": lp.get("reviews_day0"), "days_to": lp.get("days_to"),
                        "w1_8_sales": [w["sales"] for w in W[:8]], "w1_8_ads": [w["ads"] for w in W[:8]],
                        "w1_8_promo": [w["promo"] for w in W[:8]], "w1_8_price": [w["price"] for w in W[:8]],
                        "w1_8_wh": [w["wh"] for w in W[:8]], "breakouts": lp.get("breakouts", [])[:3]},
        }
        out["winners"].append(rec)
    for m in sorted({w["entry_month"] for w in out["winners"]}):
        M = market(m)
        if M:
            top = M[:100]
            rev = sum(r.get("revenue") or 0 for r in top) or 1
            sc = collections.Counter(seg(r.get("name")) for r in top)
            sr = collections.Counter()
            for r in top:
                sr[seg(r.get("name"))] += r.get("revenue") or 0
            out["markets"][m] = {"segments_cards": dict(sc), "segments_rev_pct": {k: round(v / rev * 100, 1) for k, v in sr.most_common()},
                                 "price_med_buyer": med([r.get("final_price_average") for r in top]),
                                 "top10_share_pct": round(sum(r.get("revenue") or 0 for r in top[:10]) / rev * 100, 1)}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", OUT)
    print("\nСпрос (wb_count) по сегментам:")
    for m, d in D.items():
        print(" ", m, {k: d.get(k) for k in ("ВСЕГО", "магнитный", "присоска/вакуум", "MagSafe", "воздуховод", "с зарядкой", "зажим")})
    print("\nРынок в месяцы входа:")
    for m, d in out["markets"].items():
        print(" ", m, d)
    for w in out["winners"]:
        print("\n=====", w["id"], w["name"][:50], "|", w["seller"], "| старт", w["start"], "| сегмент", w["segment"], "| июль", w["jul_sales_day"], "шт/д")
        mk = w["market"]
        print("  рынок:", {k: mk[k] for k in ("top100_revenue_mln", "top10_share_pct", "sellers_top100", "seg_cards_top100", "seg_revenue_share_pct", "seg_price_med_buyer", "price_med_top100_buyer")})
        print("  лидеры сегмента:", mk["seg_leaders"])
        print("  цена входа:", w["entry_price_buyer_w1"], "× мед. сегмента", w["price_vs_seg_median"], "| спрос сегмента вход/+3мес", w["demand_seg_entry"], w["demand_seg_plus3"])
        print("  карточка:", w["card"])
        print("  жалобы лидеров до входа:", w["incumbent_complaints_before_entry"])
        print("  свои отзывы:", w["own_reviews"])
        print("  продавец: карточек в top-500 при входе", w["seller_cards_top500_at_entry"], "| в июле", w["seller_cards_top500_jul"])
        t = w["tactics"]
        print("  тактика:", w["launch"], "| отзывы д0", t["reviews_day0"], "| дней до 10/50/100", t["days_to"])
        print("    шт/д", t["w1_8_sales"], "| реклама", t["w1_8_ads"], "| акции", t["w1_8_promo"], "| цена", t["w1_8_price"], "| склады", t["w1_8_wh"])
        for b in t["breakouts"]:
            print("    взлёт", b["date"], "д", b["day"], b["sales_before"], "→", b["sales_after"], "цена", b["price_before"], "→", b["price_at"], "рекл", b["ads_before"], "→", b["ads_at"], "акц", b["promo_before"], "→", b["promo_at"], "отз", b["reviews_before"], "→", b["reviews_at"], "скл", b["wh_before"], "→", b["wh_at"])


if __name__ == "__main__":
    main()
