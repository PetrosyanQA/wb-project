"""Отбор ниш v7, этап 2 — по карточкам ниши (топ-500 по выручке, Saleflow wb_subject products). 0 запросов.

    python -m src.niche_v7 cards               # октябрь (2026-11-01/p500), где нет — июль (v3_products500)

По каждой нише:
  B новички — карточки со стартом ≤ 6 мес до конца периода; склейка (первый отзыв раньше старта на 30+ дней) не считается;
    победитель = новичок с выручкой ≥ 150 тыс. ₽/мес; ожидаемые продажи новичка = среднее продаж всех новичков топ-500
    (с обрезкой по P90; провалы внутри топ-500 тоже учтены) [оценка];
  C концентрация — доля топ-1 и топ-6 продавцов в выручке топ-500, число продавцов;
  D дефицит — упущенная выручка (lost_profit) топ-500, % победителей с остатком < 7 дней продаж;
  E экономика белого ввоза при медиане цены победителей: цена продавца (СПП Evirma, иначе spp_avg карточек),
    комиссия AM FBS из WB API (иначе комиссия FBS карточек — завышена, консервативно), выкуп карточек, объём по упаковке
    (нет — 2 л [допущение]); ¥max — потолок при марже ≥ 18 % и ROI ≥ 60 % (ДРР 8 %); прибыль при ¥ = 11 % цены [допущение].
Магниты исключены; ЧЗ/декларации — только пометка «что нужно».
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import statistics as st

from src.niche_v7 import P500, REQ as REQS, _load, req
from src.outliers import clean_items
from src.screen_white import BANDS, CNY, COM, NC, VOL_ASSUMED, econ, landed, max_yuan, seller_for

OLD = "data/raw/saleflow/v3_products500"
ARENA = ".arena/run-20261025-153238-s146793/scratch/a001/p500"   # ещё 1 000+ ниш, июль
OUT = "data/processed/niche_v7_cards_2026-11-01.json"
WIN_REV = 150_000
CHINA_PCT = 11
CHINA_PCT_ELECTRO = 25   # электроника/батареи: по 1688 доля фабрики в цене WB выше [допущение]
BUDGET_GOODS = 100_000


def _rows(sid: int) -> tuple[list[dict], str] | tuple[None, None]:
    for path, per in ((f"{P500}/{sid}.json", "2026-10"), (f"{OLD}/{sid}.json", "2026-07"), (f"{ARENA}/{sid}.json", "2026-07")):
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            return ((d.get("data") if isinstance(d, dict) else d) or []), per
    return None, None


def _d(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def analyse(sid: int, china_pct: float = CHINA_PCT) -> dict | None:
    rows, per = _rows(sid)
    if not rows:
        return None
    for r in rows:
        r["price"] = r.get("final_price_average") or r.get("final_price")
    kept, rep = clean_items(rows, {"outliers": {"price_upper_ratio": 15, "price_lower_ratio": 0.05}}, expected_subject=sid)
    kept = [r for r in kept if (r.get("revenue") or 0) > 0]
    if len(kept) < 30:
        return None
    end = dt.date(2026, 10, 31) if per == "2026-10" else dt.date(2026, 7, 31)
    start = end - dt.timedelta(days=183)
    rev = sum(r["revenue"] for r in kept)
    bysel = collections.Counter()
    for r in kept:
        bysel[r.get("seller")] += r["revenue"]
    newset = set()
    for r in kept:
        d0, c0 = _d(r.get("sku_first_date")), _d(r.get("firstcommentdate"))
        if d0 and d0 >= start and not (c0 and c0 < d0 - dt.timedelta(days=30)):
            newset.add(r["id"])
    new = [r for r in kept if r["id"] in newset]
    win = [r for r in new if r["revenue"] >= WIN_REV]
    bands = []
    for lo, hi in BANDS:                                               # E: лучший ценовой сегмент внутри ниши
        seg = [r for r in kept if lo <= (r["price"] or 0) < hi]
        if len(seg) >= 15:
            b = _segment(sid, seg, [r for r in seg if r["id"] in newset], china_pct)
            if b:
                bands.append(b | {"band": f"{lo}-{hi}"})
    best = max(bands, key=lambda b: (b["win"] >= 2, b["month_profit"]), default=None)
    if not best:
        return None
    return dict(id=sid, period=per, cards_niche=len(kept), dropped=rep.get("dropped_pct"), rev500_mln=round(rev / 1e6, 1),
                sellers=len(bysel), top1=round(bysel.most_common(1)[0][1] / rev * 100), top6=round(sum(v for _, v in bysel.most_common(6)) / rev * 100),
                new_all=len(new), win_all=len(win), win_sellers_all=len({r.get("seller") for r in win}),
                lost_mln=round(sum(r.get("lost_profit") or 0 for r in kept) / 1e6, 1),
                china=round(sum(1 for r in kept if (r.get("country") or "") == "Китай") / len(kept) * 100),
                china_pct=china_pct, bands=[{k: b[k] for k in ("band", "cards", "win", "exp_sales", "buyer", "profit8", "month_profit")} for b in bands],
                **best)


def _segment(sid: int, seg: list[dict], new: list[dict], china_pct: float) -> dict | None:
    win = [r for r in new if r["revenue"] >= WIN_REV]
    ref = win if len(win) >= 3 else seg
    buyer = st.median(r["price"] for r in ref)
    exp_sales = round(st.median(r["sales"] for r in new)) if len(new) >= 3 else 0   # P50 новичка сегмента [оценка]
    seller, spp = seller_for(sid, buyer)
    if seller is None:
        spp = st.median(r.get("spp_avg") or 0 for r in ref)
        seller = round(buyer / (1 - spp / 100))
    com_src = "AM"
    com = COM.get(sid)
    if com is None:
        com = st.median(r.get("commission_fbs") or 30 for r in ref)
        com_src = "карточки"
    vols = [r["package_length"] * r["package_width"] * r["package_height"] / 1000 for r in ref
            if r.get("package_length") and r.get("package_width") and r.get("package_height")]
    vol = st.median(vols) if len(vols) >= 3 else VOL_ASSUMED
    kg = (NC.get(sid) or {}).get("kg") or max(0.1, 0.22 * vol)
    pur = [r["purchase"] for r in ref if r.get("purchase")]
    buyout = st.median(pur) if pur else 80
    yest = buyer * china_pct / 100 / CNY
    batch = max(50, min(400, int(BUDGET_GOODS // landed(yest, kg, 300))))
    e8 = econ(seller, yest, vol, kg, com, buyout, 8, batch)
    e15 = econ(seller, yest, vol, kg, com, buyout, 15, batch)
    ymax = max_yuan(seller, vol, kg, com, buyout, batch)
    bysel = collections.Counter()
    for r in seg:
        bysel[r.get("seller")] += r["revenue"]
    srev = sum(bysel.values()) or 1
    low_stock = sum(1 for r in win if (r.get("sales_per_day_average") or 0) > 0 and (r.get("balance") or 0) / r["sales_per_day_average"] < 7)
    return dict(cards_seg=len(seg), seg_sellers=len(bysel), seg_top1=round(bysel.most_common(1)[0][1] / srev * 100),
                seg_top6=round(sum(v for _, v in bysel.most_common(6)) / srev * 100),
                new=len(new), win=len(win), win_sellers=len({r.get("seller") for r in win}), exp_sales=exp_sales,
                win_med_sales=round(st.median(r["sales"] for r in win)) if win else 0, cards=len(seg),
                buyer=round(buyer), seller=seller, spp=spp, com=com, com_src=com_src, buyout=round(buyout),
                vol=round(vol, 2), vol_assumed=len(vols) < 3, kg=round(kg, 2), batch=batch,
                ymax=ymax, ymax_pct=round(ymax * CNY / buyer * 100, 1), yest=round(yest, 1), unit_cost=round(landed(yest, kg, batch)),
                profit8=round(e8["net_profit"]), profit15=round(e15["net_profit"]), margin8=e8["net_margin_pct"],
                month_profit=round(e8["net_profit"] * exp_sales), win_low_stock=low_stock,
                examples=[f"{r['id']} {r['name'][:50]} — {r['price']:.0f} ₽, {r['sales']} шт" for r in sorted(win, key=lambda r: -r["revenue"])[:3]])


def _oct_vs_jul(sid: int) -> float | None:
    """Выручка топ-500 октябрь / июль (по тем же источникам Saleflow) — грубый признак сезона: < 0,7 = летний товар."""
    o = f"{P500}/{sid}.json"
    j = next((p for p in (f"{OLD}/{sid}.json", f"{ARENA}/{sid}.json") if os.path.exists(p)), None)
    if not (os.path.exists(o) and j):
        return None
    rev = lambda p: sum(r.get("revenue") or 0 for r in (json.load(open(p, encoding="utf-8")).get("data") or []))   # noqa: E731
    rj = rev(j)
    return round(rev(o) / rj, 2) if rj else None


def gates(r: dict) -> list[str]:
    bad = []
    if r["top6"] > 60: bad.append("топ-6 ниши > 60 %")
    if r["seg_top1"] > 30: bad.append("в сегменте 1 продавец > 30 %")
    if r["sellers"] < 30: bad.append("< 30 продавцов")
    if r["win"] < 3: bad.append("< 3 новичков-победителей в сегменте")
    elif r["win_sellers"] < 3: bad.append("победители у 1–2 продавцов")
    if r["ymax"] < r["yest"]: bad.append("¥ оценка выше потолка")
    if r["month_profit"] < 30_000: bad.append("прибыль < 30 тыс./мес")
    if r.get("season_oct_jul") is not None and r["season_oct_jul"] < 0.6: bad.append("летний товар (октябрь < 60 % июля)")
    return bad


def run() -> list[dict]:
    names = {}
    scr = json.load(open("data/processed/niche_v7_screen_2026-11-01.json", encoding="utf-8"))["rows"]
    s1 = {r["id"]: r for r in scr}
    allsub = _load("p*.json")                                    # все ниши ≥ 7 млн ₽ из сводки 10.2026 (имена)
    ids = set()
    for d in (P500, OLD, ARENA):                                 # все ниши, по которым есть карточки (сегменты считаем везде)
        if os.path.isdir(d):
            ids |= {int(f[:-5]) for f in os.listdir(d) if f[:-5].isdigit()}
    out = []
    for sid in sorted(ids):
        rq = req(sid, (s1.get(sid) or allsub.get(sid) or {}).get("name") or "")
        pct = CHINA_PCT_ELECTRO if any(w in rq["flags"] for w in ("электрон", "батарея")) else CHINA_PCT
        try:
            a = analyse(sid, pct)
        except Exception as e:                                                   # noqa: BLE001
            print(f"{sid}: ошибка {e}")
            continue
        if not a:
            continue
        x = s1.get(sid, {})
        names[sid] = x.get("name") or (allsub.get(sid) or {}).get("name") or (REQS.get(sid) or {}).get("subject") or str(sid)
        if "магнит" in rq["flags"].lower() or "запрет" in rq["verdict"]:
            continue
        a.update(name=names[sid], yoy_rel=x.get("yoy_rel"), gap=x.get("gap"), lost_pct=x.get("lost_pct"), **rq)
        a["season_oct_jul"] = _oct_vs_jul(sid)
        a["fails"] = gates(a)
        out.append(a)
    out.sort(key=lambda r: (len(r["fails"]), -r["month_profit"]))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = [r for r in out if not r["fails"]]
    print(f"ниш с карточками: {len(out)} (октябрь {sum(r['period'] == '2026-10' for r in out)}), прошли все условия: {len(ok)}")
    for r in ok[:60]:
        print(f"{r['id']:>6} {r['period'][5:]} {r['name'][:42]:42} {r['buyer']:>5} ₽ прибыль/шт {r['profit8']:>4} × {r['exp_sales']:>4} шт = "
              f"{r['month_profit'] // 1000:>4} тыс | топ6 {r['top6']}% прод {r['sellers']} поб {r['win']}/{r['win_sellers']} "
              f"¥max {r['ymax']} рост {r['yoy_rel']}% | {r['verdict'][:28]}")
    return out
