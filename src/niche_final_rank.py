"""Финальный рейтинг ниш (2026-10-17): экономика по ориентиру цены поставщика + свежие отзывы WB. 0 запросов Saleflow.

    python -m src.niche_final_rank [дата picks]     # → data/processed/niche_final_rank_<дата>.json

Берёт кандидатов из niche_picks_<дата>.json (+ поля niche_nocargo_<дата>.json) и для каждого считает:
1. маржу/ROI по схеме am_fbs при ¥ из config/supplier_prices_2026-10-17.yaml (lo/hi листингов Alibaba) — DRR 15 и 10,
   стресс цена −15 %; без ориентира — запас = max ¥ (DRR 15) / ¥-допущение nocargo (9 % цены покупателя);
2. капитал: сколько штук влезает в goods-часть бюджета (config/scoring.yaml) при landed-цене;
3. независимых победителей: склейки (одинаковое число отзывов или один imt_id) считаются одной карточкой;
4. отзывы победителей из публичного feedbacks1.wb.ru (до 1000 новейших на склейку, кэш data/raw/wb_feedbacks/):
   доля негатива (≤ 3★), темы жалоб, главная исправимая тема ≥ 12 %, отзывов по карточке за 30 дней против июля 2026.
Ярусы: I — экономика держится при ¥ поставщика; II — ориентира нет, ранжируем по запасу ¥; III — не держится.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
import yaml

from src import strategy as S
from src.unit_econ import unit_economics
from src.wb_cdn_card import fetch as cdn

sys.stdout.reconfigure(encoding="utf-8")
DAY = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
FB_DIR = "data/raw/wb_feedbacks"
UA = {"User-Agent": "Mozilla/5.0"}
TODAY = dt.date.fromisoformat(DAY)
D30 = (TODAY - dt.timedelta(days=30)).isoformat()
JUL = ("2026-07-01", "2026-07-31")
THEMES = {
    "брак / не работает": r"брак|не работа|перестал|сломал|не включа|умер|отказал",
    "заряд / батарея": r"заряд|батаре|аккумулятор|не держит",
    "слабый / плохо выполняет": r"слаб|мощност|не тянет|плохо бре|не бре|дерг|тупы|плохо стри|не стри|не греет",
    "качество / хлипкий": r"хлипк|дешев|пластик|качеств|разваливается|трескает|трещин",
    "не соответствует описанию": r"не соответств|не как на фото|отличается|другой цвет|обман|не тот",
    "шум / громко": r"шум|громк|гудит|пищит|жужж",
    "подключение / звук": r"подключ|блютуз|bluetooth|сопряж|отваливается|звук|микрофон|связь",
    "некомплект / б/у": r"некомплект|не хватает|вскрыт|б/у|был в употреблении|использован",
    "размер": r"\bмал[аеоы]?\b|маленьк|велик|размер",
    "запах": r"запах|воня",
    "нагрев": r"греет|нагрева|горяч|перегрев",
    "кожа / порезы": r"раздраж|царапа|порез|режет|кож",
    "протекает": r"протек|теч[её]т|подтека",
    "яркость / свет": r"тускл|ярк|светит",
    "инструкция / непонятно": r"инструкц|непонятн|разобраться",
    "доставка / упаковка": r"упаковк|коробк|доставк|помят|подмен|не привез|пришел разбит",
}
REJECT = {"доставка / упаковка", "некомплект / б/у"}           # не исправить товаром


def feedbacks(imt: int) -> dict | None:
    p = f"{FB_DIR}/{imt}.json"
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:                                      # обрывок от прерванного запуска — перекачиваем
            os.remove(p)
    for h in ("feedbacks1", "feedbacks2"):
        try:
            r = requests.get(f"https://{h}.wb.ru/feedbacks/v1/{imt}", headers=UA, timeout=15)
            if r.status_code == 200 and r.text.startswith("{"):
                d = r.json()
                os.makedirs(FB_DIR, exist_ok=True)
                with open(p + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
                os.replace(p + ".tmp", p)
                return d
        except (requests.RequestException, ValueError):
            pass
    return None


def econ(price, yuan, kg, vol, buyout, comm, drr):
    cost = S.cost_rub(yuan, kg, vol)[0]
    e = unit_economics(price, cost, vol, S.econ_config(), with_breakeven=False, buyout_pct=buyout, commission_pct=comm,
                       ad_share_of_revenue_pct=drr, packaging_rub=S.PACK)
    return {"margin": e["net_margin_pct"], "roi": e["roi_on_goods_pct"], "net": round(e["net_profit"]), "landed": round(cost)}


def ok(e) -> bool:
    t = S.econ_config()["targets"]
    return e["margin"] >= t["min_net_margin_pct"] and e["roi"] >= t["min_roi_on_cost_pct"]


def reviews(winners: list[dict]) -> dict:
    """Независимые победители (склейки сливаем) и отзывы по их imt."""
    seen_c, uniq = set(), []
    for w in winners:
        c = w.get("comments")
        if c and c in seen_c:
            continue
        seen_c.add(c)
        uniq.append(w)
    with ThreadPoolExecutor(8) as ex:
        cards = list(ex.map(lambda w: cdn(w["id"]), uniq))
    imts, groups = {}, []
    for w, c in zip(uniq, cards):
        imt = (c or {}).get("imt_id")
        if imt and imt in imts:
            continue
        imts[imt] = w["id"]
        groups.append((w, imt))
    top = [g for g in groups if g[1]][:5]
    with ThreadPoolExecutor(5) as ex:
        fbs = list(ex.map(lambda g: feedbacks(g[1]), top))
    neg, total, theme, val, vel = 0, 0, collections.Counter(), [], []
    for (w, imt), d in zip(top, fbs):
        F = (d or {}).get("feedbacks") or []
        if not F:
            continue
        val.append(d.get("valuation"))
        for f in F:
            total += 1
            if (f.get("productValuation") or 5) <= 3:
                neg += 1
                txt = " ".join(str(f.get(k) or "") for k in ("text", "cons")).lower()
                for t, rx in THEMES.items():
                    if re.search(rx, txt):
                        theme[t] += 1
        own = [f["createdDate"][:10] for f in F if f.get("nmId") == w["id"]]
        oldest = min(f["createdDate"][:10] for f in F)
        f30 = sum(1 for x in own if x >= D30)
        jul = sum(1 for x in own if JUL[0] <= x <= JUL[1]) if oldest <= JUL[0] else None
        vel.append({"id": w["id"], "fb30": f30, "fb_jul": jul, "count": d.get("feedbackCount"), "val": d.get("valuation")})
    fix = [(t, c) for t, c in theme.most_common() if t not in REJECT]
    top_t = fix[0] if fix else (None, 0)
    jul_ok = [v for v in vel if v["fb_jul"]]
    trend = round(sum(v["fb30"] for v in jul_ok) / sum(v["fb_jul"] for v in jul_ok) * 100) if jul_ok else None
    return {"winners_raw": len(winners), "winners_indep": len(groups), "fb_cards": len(vel), "fb_total": total, "neg": neg,
            "neg_pct": round(neg / total * 100, 1) if total else None,
            "themes": [(t, c, round(c / neg * 100)) for t, c in theme.most_common(6)] if neg else [],
            "top_fix": top_t[0], "top_fix_pct": round(top_t[1] / neg * 100) if neg else None,
            "valuation_med": sorted(val)[len(val) // 2] if val else None, "fresh_vs_jul_pct": trend, "cards": vel}


def rank_one(p: dict, r: dict, sup: dict, budget_rub: float, min_units: int) -> dict:
    b = r["best"]
    price, kg, vol = b["seller_price_med"], r["kg"], r["vol_l"]
    buyout, comm = r.get("buyout_real") or r.get("buyout"), r.get("com") or 25.0
    out = {"id": p["id"], "name": p["name"], "band": p["band"], "price": price, "buyer_med": b["buyer_med"], "kg": kg, "vol": vol,
           "buyout": buyout, "comm": comm, "max15": r.get("max_yuan_drr15"), "max10": r.get("max_yuan_drr10"),
           "yuan_assumed": r.get("yuan_assumed"), "win_rate": p["win_rate_pct"], "win_sellers": p["win_sellers"],
           "win_copy": p["win_copy_pct"], "top1": b.get("top1_pct"), "net12_p50": p["net_12m_p50"], "flags": r.get("flags") or []}
    s = sup.get(p["id"])
    if s:
        k = 1 if s.get("unit") == "cny" else S.econ_config()["cargo"]["usd_to_rub"] / S.econ_config()["cargo"]["cny_to_rub"]
        lo, hi = round(s["lo"] * k, 1), round(s["hi"] * k, 1)
        out["sup"] = {"lo": lo, "hi": hi, "match": s.get("match"), "moq": s.get("moq"), "src": s.get("src")}
        for tag, y in (("lo", lo), ("hi", hi)):
            out[f"e15_{tag}"] = econ(price, y, kg, vol, buyout, comm, 15)
            out[f"e10_{tag}"] = econ(price, y, kg, vol, buyout, comm, 10)
            out[f"st_{tag}"] = econ(price * 0.85, y, kg, vol, buyout, comm, 15)
        out["units"] = int(budget_rub // out["e15_lo"]["landed"])
        if ok(out["e15_lo"]) and out["units"] >= min_units:
            out["tier"] = "I"
        elif ok(out["e10_lo"]) and out["units"] >= min_units:
            out["tier"] = "I-"                                      # держится только при DRR 10
        else:
            out["tier"] = "III"
        out["headroom"] = round(out["max15"] / lo, 2) if lo else None
    else:
        y = r.get("yuan_assumed")
        out["tier"] = "II"
        out["headroom"] = round(out["max15"] / y, 2) if y else None
        out["units"] = int(budget_rub // S.cost_rub(out["max15"], kg, vol)[0]) if out["max15"] else None
    out["rev"] = reviews(p["top_winners"])
    risk = []
    if (p["win_copy_pct"] or 0) > 25:
        risk.append(f"копии брендов у победителей {p['win_copy_pct']}%")
    if (b.get("top1_pct") or 0) > 25:
        risk.append(f"top-1 полосы {b['top1_pct']}%")
    if buyout and buyout < 75:
        risk.append(f"выкуп {buyout}%")
    if kg and kg > 1:
        risk.append(f"вес {kg} кг")
    if (r.get("season") or {}).get("peak"):
        risk.append(f"сезон, пик {r['season']['peak']}")
    if p["id"] in (5067,):
        risk.append("18+ (ограничения рекламы/модерации)")
    if out["rev"]["winners_indep"] < 4:
        risk.append(f"независимых победителей {out['rev']['winners_indep']}")
    out["risks"] = risk
    return out


def main():
    P = json.load(open(f"data/processed/niche_picks_{DAY}.json", encoding="utf-8"))
    N = {r["id"]: r for r in json.load(open(f"data/processed/niche_nocargo_{DAY}.json", encoding="utf-8"))}
    sup = yaml.safe_load(open(f"config/supplier_prices_{DAY}.yaml", encoding="utf-8"))
    bud = yaml.safe_load(open("config/scoring.yaml", encoding="utf-8"))["budget"]
    goods = bud["total_usd"] * bud["fx_rub_per_usd"] * bud["goods_share"]
    out = []
    for p in P:
        out.append(rank_one(p, N[p["id"]], sup, goods, bud["min_first_batch_units"]))
        o = out[-1]
        print(f"{o['id']:>5} {o['name'][:24]:<24} {o['tier']:<3} запас {o['headroom']} | индеп {o['rev']['winners_indep']} "
              f"| негатив {o['rev']['neg_pct']}% топ {o['rev']['top_fix']} {o['rev']['top_fix_pct']}% | 30д/июль {o['rev']['fresh_vs_jul_pct']}%",
              flush=True)
    order = {"I": 0, "I-": 1, "II": 2, "III": 3}
    out.sort(key=lambda o: (order[o["tier"]], -len(o["risks"]) * 0.3 - (o["headroom"] or 0)))
    json.dump(out, open(f"data/processed/niche_final_rank_{DAY}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ data/processed/niche_final_rank_{DAY}.json, goods-бюджет {goods:.0f} ₽")


if __name__ == "__main__":
    main()
