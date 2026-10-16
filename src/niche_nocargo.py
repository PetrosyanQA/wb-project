"""Поиск ниши «v1 без карго» (2026-10-16): одна воронка, объединяющая методы всех волн v1–v6, БЕЗ карго-фильтров. 0 запросов.

    python -m src.niche_nocargo          # → data/processed/niche_nocargo_<дата>.json, reports/niche_nocargo_<дата>.md/.xlsx

Снято (карго): «чувств. груз» (v1/v2), запрет по названию магнит/аккумулятор/батарейки/электроника/жидкости (v1, v5),
отсев карточек electro (v5). Оставлено: Честный знак, регистрация/оружие/еда/18+, габарит-корни (список src.niche_v6).
Этапы (функции всех волн; источник в скобках):
  0. universe   — все предметы июля ≥ 5 млн ₽, ≥ 30 продавцов, медиана ≥ 400 ₽, выкуп ≥ 55 % (v5/v6, без карго-запретов);
  1. регуляторка — ЧЗ/запрет по filters.yaml regulatory (gates №1, по началу слова) + ЧЗ-косметика; сертификация — флаг (принята с v5);
  2. очистка    — outliers.clean_items на products500 (CLAUDE.md): цена > 4× / < 0,25× медианы, 1 день продаж, чужой предмет;
  3. новички    — ценовые полосы v5 (+4 000–6 000), новичок 2025-08…2026-05, P50 ≥ 4/день, ≥ 5 новичков, ≥ 3 продавцов-победителей,
                  top-1 полосы ≤ 35 % (v4/v5); сезон: июль < 50 % среднего → отсев (v5);
  4. рынок      — top-3 у одного продавца → ❌ (CLAUDE.md, v2); копии брендов > 30 % → ❌ (v2); YoY пика < −5 % → ❌ (gates №4, где есть trends);
  5. экономика  — выкуп = медиана purchase_after_return top-100 (v2); max ¥ при марже ≥ 18 % и ROI ≥ 60 % (v4); маржа ДРР 15 % при
                  закупке = 9 % цены покупателя [допущение v5]; стресс цена −15 % → маржа ≥ 15 % (v2); габарит из карточек, иначе 0,8 л / 0,35 кг;
  6. финплан    — src.finplan.run: партия fit_batch, спрос P25/P50/P75 новичков полосы × разгон 40/70/100 % [допущение] × сезон, старт 2026-12;
                  окупаемость «деньги вернулись» ≤ 6 мес. при P50 (v2/v5);
  7. строго     — gates №3/№5 и v2 как отдельная колонка: top-10 ≤ 40 %, top-1 продавец ≤ 25 %, ≥ 8 продавцов в top-20, ≤ 4 карточки бренда
                  в top-10, медиана рейтинга top-20 < 4,75, доля новых (с 2025-01) ≥ 25 %, Китай среди указанных ≥ 50 %;
  8. флаги      — тайминг пика (v2), сигналы ниши checklist v2 (winner_decisions: продажи/продавца ≥ 190, рост продавцов ≤ 12 %, YoY ≤ 45 %),
                  очистка > 40 %, сертификация, габарит —, ЧЗ? проверить;
  9. история    — статусы ниши во всех прошлых волнах (niche_merge), отметка «карго мешал раньше».
Статус: ✅ полоса прошла, маржа ≥ 18 %, стресс ≥ 15 %, окупаемость ≤ 6 мес. · 🟡 полоса прошла, маржа > 0 · ❌ причина · ⏳ нет products500.
«✅ строго» — ✅ и ни одного провала этапа 7.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys

from src import niche_v6  # noqa: F401  — подменяет запреты/полосы niche_v5 на «без карго»
from src import niche_v5 as V
from src import finplan as F
from src import winner_decisions as WD
from src.gates import load_filters
from src.outliers import clean_items
from src.screen_v4 import max_yuan
from src.strategy import econ_config

sys.stdout.reconfigure(encoding="utf-8")
P = "data/processed"
TODAY = dt.date.today().isoformat()
OUT_J = f"{P}/niche_nocargo_{TODAY}.json"
OUT_MD = f"reports/niche_nocargo_{TODAY}.md"
OUT_X = f"reports/niche_nocargo_{TODAY}.xlsx"
CARGO = re.compile(r"чувств|магнит|карго|electro|аккум|батаре|жидк", re.I)
KIZ = re.compile(r"косметик|пилинг|депиляц|красота / пенки", re.I)   # ЧЗ-косметика, которую пропускает BAN_NAME v6 («косметич»)
KIZ_CHECK = re.compile(r"туалетн|пеленк|подгузн", re.I)   # возможен ЧЗ — проверить need_kiz по карточке
BRAND_COPY = re.compile(r"trionda|mikasa|молтен|molten|adidas|nike|fifa|чемпионат мира|лиги чемпионов|евро ?2\d|premier league|flexi|tug\b", re.I)
SHARE = 0.09                                           # закупка = 9 % цены покупателя [допущение v5]
RAMP = [0.4, 0.7] + [1.0] * 10                         # разгон новой карточки по месяцам [допущение]
START = "2026-12"                                      # первая продажа: заказ сейчас + производство + карго ≈ 1,5 мес. [допущение]
ORDER_MONTH = 11                                       # тайминг v2: заказ в ноябре, пик через 3–6 мес.
WAVES = ["v1", "v2", "v3", "v4", "v5", "v6", "итог"]
FLT = load_filters()
CC = FLT["concentration"]
NR = FLT["newcomer_rules"]["checklist"]


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def kw_hits(text: str, words) -> list[str]:
    """Совпадение по началу слова («шин» ≠ «машин», «бель» ≠ «мебель»)."""
    return [w for w in words if re.search(r"(?<![а-яёa-z])" + re.escape(w), text, re.I)]


def history() -> dict[int, dict]:
    fs = sorted(f for f in glob.glob(f"{P}/niche_merge_*.json"))
    return {r["id"]: r["waves"] for r in (load(fs[-1]) if fs else [])}


def dims_for(ids) -> tuple[float, float, str]:
    d = [V.card_dims(load(f"{V.CARDS}/{s}.json")) for s in ids[:2] if os.path.exists(f"{V.CARDS}/{s}.json")]
    vols = [x["vol_l"] for x in d if x["vol_l"]]
    kgs = [x["kg"] for x in d if x["kg"]]
    if vols and kgs:
        return round(sorted(vols)[len(vols) // 2], 2), round(sorted(kgs)[len(kgs) // 2], 2), "карточки"
    return 0.8, 0.35, "допущение"


def band_fail(b) -> list[str]:
    f = []
    if b["newcomers"] < 5:
        f.append(f"новичков {b['newcomers']} < 5")
    if b["p50"] < 4:
        f.append(f"новичок P50 {b['p50']} < 4/день")
    if b["winner_sellers"] < 3:
        f.append(f"продавцов-победителей {b['winner_sellers']} < 3")
    if (b["top1_pct"] or 100) > 35:
        f.append(f"top-1 полосы {b['top1_pct']}% > 35")
    return f


def market(R: list[dict], total_rev: float) -> dict:
    """Ниша целиком (gates №3/№5, v2 screen) по очищенному top-500 июля; доли — от выручки предмета за июль."""
    top = sorted(R, key=lambda x: -x["revenue"])
    t100, t20, t10 = top[:100], top[:20], top[:10]
    tot100 = sum(x["revenue"] for x in t100) or 1
    total = max(total_rev, sum(x["revenue"] for x in top)) or 1
    by_s = {}
    for x in top:
        by_s[x.get("seller")] = by_s.get(x.get("seller"), 0) + x["revenue"]
    brands = {}
    for x in t10:
        brands[x.get("brand")] = brands.get(x.get("brand"), 0) + 1
    share = lambda cond: round(sum(x["revenue"] for x in t100 if cond(x)) / tot100 * 100, 1)
    rat = [x["rating"] for x in t20 if x.get("rating")]
    if all(float(v).is_integer() for v in rat):          # products500 отдаёт целые звёзды (5/4) → правило ≤ 4,75 неприменимо
        rat = []
    china, known = share(lambda x: "кита" in str(x.get("country") or "").lower()), share(lambda x: bool(x.get("country")))
    bo = [x["purchase_after_return"] for x in t100 if x.get("purchase_after_return")]
    return {"top10_pct": round(sum(x["revenue"] for x in t10) / total * 100, 1),
            "top1_seller_pct": round(max(by_s.values()) / total * 100, 1) if by_s else None,
            "sellers_top20": len({x.get("seller") for x in t20}),
            "brand_top10": max(brands.values()) if brands else 0,
            "rating_top20": round(st.median(rat), 2) if rat else None,
            "new_share": share(lambda x: (x.get("sku_first_date") or "") >= "2025-01-01"),
            "china_of_known": round(china / known * 100, 1) if known >= 40 else None,
            "brand_copy_pct": share(lambda x: bool(BRAND_COPY.search(x.get("name") or ""))),
            "top3_one_seller": len({x.get("seller") for x in top[:3]}) == 1,
            "buyout_top100": round(st.median(bo), 1) if bo else None}


def strict_fails(m: dict) -> list[str]:
    f = []
    if m["top10_pct"] > CC["top10_share_max"]:
        f.append(f"top-10 {m['top10_pct']}%")
    if (m["top1_seller_pct"] or 0) > CC["top1_seller_share_max"]:
        f.append(f"top-1 продавец {m['top1_seller_pct']}%")
    if m["sellers_top20"] < CC["min_sellers_in_top20"]:
        f.append(f"продавцов в top-20 {m['sellers_top20']}")
    if m["brand_top10"] > CC["max_one_brand_cards_in_top10"]:
        f.append(f"бренд {m['brand_top10']} карт. в top-10")
    if m["rating_top20"] and m["rating_top20"] >= FLT["profile"]["rating_ceiling"]:
        f.append(f"рейтинг top-20 {m['rating_top20']}")
    if m["new_share"] < 25:
        f.append(f"новые {m['new_share']}%")
    if m["china_of_known"] is not None and m["china_of_known"] < 50:
        f.append(f"Китай {m['china_of_known']}%")
    return f


def season_list(nid: int, seas: dict) -> tuple[list[int], str]:
    s = seas.get(nid)
    if s and s.get("index"):
        return F.season_from(s["index"], START), "сезон 2026"
    try:
        prof = WD.season_index(nid, "2026-08")
    except (ValueError, AttributeError, TypeError, KeyError):
        prof = {}
    if prof:
        return F.season_from({f"{k:02d}": round(v * 100) for k, v in prof.items()}, START), "trends"
    return [100] * 12, "без сезона [допущение]"


def peak_ok(s: dict) -> tuple[bool, str]:
    idx = s.get("index") or {}
    if not idx:
        return True, "—"
    trough = min(idx.values()) / max(idx.values()) * 100
    if trough >= 60:
        return True, f"круглый год ({trough:.0f}%)"
    lag = (int(s["peak_month"]) - ORDER_MONTH) % 12
    return 3 <= lag <= 6, f"пик {int(s['peak_month']):02d} через {lag} мес. после заказа"


def checklist_flags(mk: dict) -> tuple[list[str], dict]:
    """checklist v2, группа niche (winner_decisions): только наблюдения → флаги."""
    if not mk.get("yoy_peak") and mk.get("yoy_peak") != 0:
        return [], {}
    vals = {"m_sps_3m": mk.get("sps_3m"), "m_sellers_6m": mk.get("sellers_6m"), "m_yoy_peak": mk.get("yoy_peak")}
    out = []
    for k, v in vals.items():
        c = NR[k]
        if v is None:
            continue
        ok = v >= c["cut"] if c["op"] == ">=" else v <= c["cut"]
        if not ok:
            out.append(f"{k} {v} (норма {c['op']} {c['cut']})")
    return out, vals


def evaluate(u: dict, seas: dict, cny: float) -> dict:
    r = {k: u.get(k) for k in ("id", "name", "rev_mln", "price_med", "buyout", "sellers_ws", "com")}
    s = seas.get(u["id"]) or {}
    r["season"] = {"peak": s.get("peak_month"), "type": s.get("type")}
    reg = FLT["regulatory"]
    hard = kw_hits(u["name"], reg["hard_exclude_keywords"])
    kiz = kw_hits(u["name"], [w for w in reg["marking_keywords"] if w != "активн"])   # «активн» = БАД, но ловит «Активный отдых»
    if hard:
        return {**r, "status": f"❌ запрещённая категория ({hard[0]})", "fails": ["регуляторка"]}
    if KIZ.search(u["name"]) or kiz:
        return {**r, "status": f"❌ Честный знак ({(kiz or ['косметика'])[0]})", "fails": ["ЧЗ"]}
    p = V.p500(u["id"])
    if not p:
        return {**r, "status": "⏳ products500 не собран", "fails": []}
    raw = [x for x in V.rows(p) if x.get("sales") and x.get("revenue")]
    R, rep = clean_items(raw, FLT, u["id"])
    r["clean"] = {"kept": rep["kept"], "dropped_pct": rep.get("dropped_pct", 0), "suspicious": rep.get("suspicious", False)}
    if len(R) < 50:
        return {**r, "status": f"❌ мало карточек с продажами ({len(R)})", "fails": ["< 50 карточек"]}
    k = V.season_k(u["id"])
    if k < 0.5:
        return {**r, "status": f"❌ июль {round(k * 100)}% среднего — сезон не летом", "fails": ["сезон"]}
    m = market(R, (u.get("rev_mln") or 0) * 1e6)
    try:
        mk = WD.market_at(u["id"], "2026-08-01")
    except (ValueError, AttributeError, TypeError, KeyError):   # пустой/битый trends-файл
        mk = {}
    r["market"], r["strict_fails"] = m, strict_fails(m)
    r["yoy_peak"] = mk.get("yoy_peak")
    bands = [V.band_stats(R, lo, hi, k) for lo, hi in V.BANDS]
    ok = [b for b in bands if not band_fail(b)]
    if not ok:
        b = max(bands, key=lambda b: (b["p50"], b["newcomers"]))
        return {**r, "status": "❌ " + "; ".join(band_fail(b))[:80], "fails": band_fail(b), "best": b}
    if m["top3_one_seller"]:
        return {**r, "status": "❌ top-3 у одного продавца", "fails": ["top-3 один продавец"]}
    if m["brand_copy_pct"] > 30:
        return {**r, "status": f"❌ копии брендов {m['brand_copy_pct']}%", "fails": ["копии брендов"]}
    if r["yoy_peak"] is not None and r["yoy_peak"] < FLT["yoy_peak"]["min_yoy_pct"]:
        return {**r, "status": f"❌ YoY пика {r['yoy_peak']}%", "fails": ["YoY пика"]}
    comm = u.get("com") or 25.0
    buyout = m["buyout_top100"] or u["buyout"]
    r["buyout_real"] = buyout
    for b in ok:
        b["max_yuan_drr10"] = max_yuan(b["seller_price_med"], 0.8, 0.35, buyout, comm, 10, 0)
        b["score"] = round(b["p50"] * b["max_yuan_drr10"], 1)
    b = max(ok, key=lambda b: b["score"])
    vol, kg, src = dims_for(b["top_ids"])
    price = b["seller_price_med"]
    y = round(b["buyer_med"] * SHARE / cny, 1)
    m15 = round(V.margin_at(price, y, kg, vol, buyout, comm, 15), 1)
    stress = round(V.margin_at(price * 0.85, y, kg, vol, buyout, comm, 15), 1)
    r.update(best=b, vol_l=vol, kg=kg, dims_src=src, yuan_assumed=y, margin_drr15=m15, stress_margin=stress,
             max_yuan_drr10=max_yuan(price, vol, kg, buyout, comm, 10, 0), max_yuan_drr15=max_yuan(price, vol, kg, buyout, comm, 15, 0))
    # финплан 12 мес. (src.finplan) при P25/P50/P75 новичков полосы
    prod = {"yuan": y, "kg": kg, "vol": vol, "buyout": buyout, "commission": comm, "price": price}
    seasn, s_src = season_list(u["id"], seas)
    try:
        batch = F.fit_batch(prod)
        fp = {}
        for q in ("p25", "p50", "p75"):
            res = F.run(q, prod, [b[q] * x for x in RAMP], seasn, batch)
            fp[q] = {"net_12m": res["net_12m"], "payback_money": res["payback_money"], "lost": res["lost_units"]}
        r["finplan"] = {"batch": batch, "season_src": s_src, **fp}
    except Exception as e:                             # noqa: BLE001
        r["finplan"] = {"error": str(e)[:80]}
    pb = (r["finplan"].get("p50") or {}).get("payback_money")
    flags = []
    if (b["china_pct"] or 0) < 50:
        flags.append(f"Китай в полосе {b['china_pct']}%")
    if s.get("type") and s["type"] != "круглый год":
        flags.append(f"{s['type']}, пик {s.get('peak_month')}")
    t_ok, t_why = peak_ok(s)
    if not t_ok:
        flags.append(f"тайминг: {t_why}")
    cf, r["checklist"] = checklist_flags(mk)
    flags += cf
    if r["yoy_peak"] is not None and r["yoy_peak"] > FLT["yoy_peak"]["explosive_yoy_pct"]:
        flags.append(f"взрывной YoY {r['yoy_peak']}%")
    if rep.get("suspicious"):
        flags.append(f"очистка {rep['dropped_pct']}% > 40")
    cert = kw_hits(u["name"], FLT["regulatory"]["certification_keywords"])
    if cert:
        flags.append(f"декларация ({cert[0]})")
    if src != "карточки":
        flags.append("габарит —")
    if KIZ_CHECK.search(u["name"]):
        flags.append("ЧЗ? проверить")
    r["flags"] = flags
    why = []
    if m15 < 18:
        why.append(f"маржа {m15}%")
    if stress < 15:
        why.append(f"стресс −15 %: {stress}%")
    if pb is None or pb > 6:
        why.append(f"окупаемость P50 {pb or '>12'} мес.")
    mkk = "✅" if not why else "🟡" if m15 > 0 else "❌"
    r["status"] = f"{mkk} полоса {b['band'][0]}–{b['band'][1]} ₽, P50 {b['p50']}/день, маржа ДРР15 {m15}%" + (f" ({'; '.join(why)})" if why and mkk == "🟡" else "")
    r["fails"] = [] if mkk != "❌" else [f"маржа ДРР15 {m15}%"]
    r["strict"] = mkk == "✅" and not r["strict_fails"]
    return r


def main():
    cny = econ_config()["cargo"]["cny_to_rub"]
    seas = {r["id"]: r for r in load(f"{P}/all_niches_season_2026-10-11.json") or []}
    hist = history()
    v5u = {u["id"] for u in load(f"{P}/niche_v5_universe.json") or []}
    U = load(V.UNIVERSE) or V.universe()               # niche_v6_universe.json (без карго-запретов)
    out = []
    for u in U:
        r = evaluate(u, seas, cny)
        h = hist.get(u["id"], {})
        r["history"] = {w: x["status"] for w, x in h.items()}
        r["cargo_blocked_before"] = (u["id"] not in v5u) or any(CARGO.search(x["status"]) for x in h.values())
        out.append(r)
    rank = {"✅": 0, "🟡": 1, "❌": 2, "⏳": 3}
    out.sort(key=lambda r: (rank[r["status"][0]], not r.get("strict"),
                            -(((r.get("finplan") or {}).get("p50") or {}).get("net_12m") or -1e9) if r["status"][0] in "✅🟡" else 0, -r["rev_mln"]))
    json.dump(out, open(OUT_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cnt = {k: sum(1 for r in out if r["status"][0] == k) for k in rank}
    n_strict = sum(1 for r in out if r.get("strict"))
    good = [r for r in out if r["status"][0] in "✅🟡"]
    from collections import Counter
    why = Counter(re.sub(r"[\d.,%₽ ()<>−-]+.*", "", r["status"][2:]).strip() for r in out if r["status"][0] == "❌")
    L = [f"# Поиск ниши «v1 без карго» — все волны и все функции в одной воронке ({TODAY})", "",
         "Код: `src/niche_nocargo.py`, 0 запросов. Данные: Saleflow products500 июль 2026 (2026-07-01…2026-07-31), предметы июля 2026,",
         "сезонность 2026 (all_niches_season), trends ≤ 2026-07 (где есть), карточки лидеров (кэш v5). Снято: чувств. груз, магниты/батарейки/электроника/жидкости.",
         "Строки очищены `outliers.clean_items`. ¥ = 9 % цены покупателя [допущение]; финплан: разгон 40/70/100 % [допущение], старт 2026-12.", "",
         "| Этап | Ниш |", "|---|---:|", f"| universe (без карго-запретов) | {len(out)} |",
         f"| products500 есть | {len(out) - cnt['⏳']} |", f"| ✅ | {cnt['✅']} |", f"| из них ✅ строго (gates №3/№5 + v2) | {n_strict} |",
         f"| 🟡 | {cnt['🟡']} |", f"| ❌ | {cnt['❌']} |", f"| ⏳ ждёт сбора | {cnt['⏳']} |", "",
         "Причины ❌: " + ", ".join(f"{k} {v}" for k, v in why.most_common(12)), "",
         "## Прошли (✅/🟡)", "",
         "| # | Ниша | Полоса ₽ | Нов. | P50/день | Цена прод. ₽ | Выкуп top-100 % | Ком. % | max ¥ ДРР15 | ¥ доп. | Маржа % | Стресс −15 % | "
         "Партия | Чистыми 12 мес. P25 / P50 ₽ | Окуп. P50 мес. | Очистка % | Строго: провалы | Флаги | Ст. |",
         "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|---|"]
    for i, r in enumerate(good, 1):
        b, fp = r["best"], r.get("finplan") or {}
        L.append(f"| {i} | {r['id']} {r['name'].split(' / ')[-1][:30]} | {b['band'][0]}–{b['band'][1]} | {b['newcomers']} | {b['p50']} | "
                 f"{b['seller_price_med']} | {r['buyout_real']} | {r['com']} | {r['max_yuan_drr15']} | {r['yuan_assumed']} | {r['margin_drr15']} | "
                 f"{r['stress_margin']} | {fp.get('batch', '—')} | {(fp.get('p25') or {}).get('net_12m', '—')} / {(fp.get('p50') or {}).get('net_12m', '—')} | "
                 f"{(fp.get('p50') or {}).get('payback_money') or '>12'} | {r['clean']['dropped_pct']} | {'; '.join(r['strict_fails']) or '—'} | "
                 f"{'; '.join(r['flags'])} | {'✅✅' if r.get('strict') else r['status'][0]} |")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "без карго"
        ws.append(["id", "ниша", "статус", "строго", "выручка млн ₽", "медиана ₽", "выкуп предмета %", "выкуп top-100 %", "продавцов", "ком. %",
                   "очистка %", "полоса", "новичков", "P50/день", "поб. продавцов", "top-1 полосы %", "цена прод. ₽", "Китай полосы %", "объём л", "кг",
                   "габарит", "max ¥ ДРР10", "max ¥ ДРР15", "¥ доп.", "маржа ДРР15 %", "стресс −15 %", "партия", "чистыми 12м P25", "чистыми 12м P50",
                   "чистыми 12м P75", "окуп. P50 мес.", "top-10 %", "top-1 продавец %", "продавцов top-20", "бренд в top-10", "рейтинг top-20",
                   "новые с 2025 %", "Китай среди указ. %", "копии брендов %", "YoY пика %", "продажи/продавца 3м", "рост продавцов 6м %",
                   "строго: провалы", "карго мешал раньше", "флаги", *WAVES])
        for r in out:
            b, m, fp, ch = r.get("best") or {}, r.get("market") or {}, r.get("finplan") or {}, r.get("checklist") or {}
            ws.append([r["id"], r["name"], r["status"], "да" if r.get("strict") else "", r["rev_mln"], r["price_med"], r["buyout"], r.get("buyout_real"),
                       r["sellers_ws"], r["com"], (r.get("clean") or {}).get("dropped_pct"),
                       f"{b['band'][0]}–{b['band'][1]}" if b else None, b.get("newcomers"), b.get("p50"), b.get("winner_sellers"), b.get("top1_pct"),
                       b.get("seller_price_med"), b.get("china_pct"), r.get("vol_l"), r.get("kg"), r.get("dims_src"), r.get("max_yuan_drr10"),
                       r.get("max_yuan_drr15"), r.get("yuan_assumed"), r.get("margin_drr15"), r.get("stress_margin"), fp.get("batch"),
                       *[(fp.get(q) or {}).get("net_12m") for q in ("p25", "p50", "p75")], (fp.get("p50") or {}).get("payback_money"),
                       m.get("top10_pct"), m.get("top1_seller_pct"), m.get("sellers_top20"), m.get("brand_top10"), m.get("rating_top20"),
                       m.get("new_share"), m.get("china_of_known"), m.get("brand_copy_pct"), r.get("yoy_peak"), ch.get("m_sps_3m"), ch.get("m_sellers_6m"),
                       "; ".join(r.get("strict_fails") or []), "да" if r["cargo_blocked_before"] else "нет",
                       "; ".join(r.get("flags") or []), *[r["history"].get(w, "·") for w in WAVES]])
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(OUT_X)
    except Exception as e:                             # noqa: BLE001
        print("xlsx:", e)
    print(f"universe {len(out)} | ✅ {cnt['✅']} (строго {n_strict}) 🟡 {cnt['🟡']} ❌ {cnt['❌']} ⏳ {cnt['⏳']} → {OUT_MD}")
    print("❌:", why.most_common(12))


if __name__ == "__main__":
    main()
