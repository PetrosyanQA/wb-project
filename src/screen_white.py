"""Скрин ценовых сегментов под белый ввоз (исправленная модель 2026-10-27). 0 запросов.

    python -m src.screen_white                    # все сегменты → data/processed/screen_white_<дата>.json + топ в консоль
    python -m src.screen_white --top 40 --batch 400 --china-pct 11

Сегмент = предмет × ценовая полоса (топ-500 Saleflow 07.2026, очищенный clean_items).
Цена продавца = медиана цены покупателя / (1 − СПП FBS Evirma); комиссия FBS AM — WB API; выкуп — медиана поля purchase
карточек сегмента (≥ 5 карточек), иначе по нише, иначе 80 % [допущение] — до 2026-10-27 стояло 80 % по умолчанию (ошибка: сумки 51–55 %).
Себестоимость белого ввоза = 1,446 × ¥ × 13,29 + $1,5/кг + 15 800 ₽ / партия (КП YUAN EXIM 22.10.2026).
¥max — потолок цены в Китае, при котором маржа ≥ 18 % и ROI ≥ 60 % при ДРР 8 % (обычная работа).
¥ оценка = china_pct % от цены покупателя [допущение: по 1688 для 7 ниш ¥ = 8–19 % цены WB, медиана ≈ 11 %].
Прибыль/мес = прибыль/шт при ¥ оценке и ДРР 8 % × продажи новичка P50 × зимний коэффициент (дек–фев / июль).
Фильтр: зимний спрос ≥ 60 % июля (сезон известен для 241 ниши), первая партия ≥ 80 шт на 100 000 ₽.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import statistics as st
import sys

from src.outliers import clean_items
from src.unit_econ import load_scheme, unit_economics

sys.stdout.reconfigure(encoding="utf-8")
A = ".arena/run-20261025-153238-s146793/scratch/a001"
CFG = load_scheme("am_fbs")
BANDS = [(500, 800), (800, 1000), (1000, 1500), (1500, 2000), (2000, 2600), (2600, 3500), (3500, 5000), (5000, 7000), (7000, 10000)]
from src.white_import import CNY, CUSTOMS, K, USD, landed  # noqa: E402,F401 — landed() реэкспорт для старых импортов — параметры белого ввоза в config/landed_cost.yaml


def jl(p):
    return json.load(open(p, encoding="utf-8"))


EV = jl(f"{A}/evirma_2026-10-25.json")
COM = {r["subjectID"]: r["kgvpMarketplace"] for r in jl("data/raw/wb_seller/commission_2026-10-23.json")["report"]}
REQ = {r["id"]: r for r in jl("data/processed/niche_requirements_2026-10-23.json")}
NC = {r["id"]: r for r in jl("data/processed/niche_nocargo_2026-10-22.json")}
SEASON = {r["id"]: r["index"] for r in jl("data/processed/all_niches_season_2026-10-11.json")}   # индекс спроса по месяцам, 241 ниша
BUDGET_GOODS = 100_000   # ₽ на первую партию из $2 000 (остальное — реклама и резерв) [допущение]


def winter_factor(sid):
    """Спрос дек–фев к июлю (продажи в выборке — июль 2026). None = нет данных о сезоне."""
    ix = SEASON.get(sid)
    if not ix or not ix.get("07"):
        t = f"data/raw/saleflow/niche_deep/trends_{sid}.json"          # запасной путь: помесячные продажи niche_deep
        if not os.path.exists(t):
            return None
        d = jl(t)
        m = {r["label_date"][:7]: r["sales"] for r in ((d.get("data") if isinstance(d, dict) else d) or [])}
        if not m.get("2026-07") or not all(m.get(x) for x in ("2025-12", "2026-01", "2026-02")):
            return None
        return round((m["2025-12"] + m["2026-01"] + m["2026-02"]) / 3 / m["2026-07"], 2)
    return round((ix["12"] + ix["01"] + ix["02"]) / 3 / ix["07"], 2)


def spp_fbs(sid, seller):
    for x in EV.get(str(sid), {}).get("fbs") or []:
        if seller >= (x["price_from"] or 0) and (x["price_to"] is None or seller < x["price_to"]):
            return x["spp"]
    return None


VOL_ASSUMED = 2.0   # л, если у сегмента < 3 карточек с габаритами


def seller_for(sid, buyer):
    s = s2 = buyer
    for _ in range(30):
        p = spp_fbs(sid, s)
        if p is None:
            return None, None
        s2 = buyer / (1 - p / 100)
        if abs(s2 - s) < 1:
            break
        s = s2
    return round(s2), spp_fbs(sid, s2)


def econ(seller, yuan, vol, kg, com, buyout, drr, batch):
    return unit_economics(seller, landed(yuan, kg, batch), vol, CFG, with_breakeven=False, buyout_pct=buyout,
                          ad_share_of_revenue_pct=drr, commission_pct=com, tax_rate_pct=10)


def max_yuan(seller, vol, kg, com, buyout, batch, drr=8):
    ok = lambda y: (lambda e: e["net_margin_pct"] >= 18 and e["roi_on_goods_pct"] >= 60)(econ(seller, y, vol, kg, com, buyout, drr, batch))
    if not ok(0):
        return 0.0
    lo, hi = 0.0, seller / CNY
    for _ in range(40):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if ok(m) else (lo, m)
    return round(lo, 1)


def load(sid):
    for p in (f"data/raw/saleflow/v3_products500/{sid}.json", f"data/raw/saleflow/v3_products100/{sid}.json", f"{A}/p500/{sid}.json"):
        if os.path.exists(p):
            d = jl(p)
            return (d.get("data") if isinstance(d, dict) else d) or []
    return None


def run(ids, batch, china_pct):
    out = []
    for sid in ids:
        rows = load(sid)
        if not rows:
            continue
        for r in rows:
            r["price"] = r.get("final_price_average") or r.get("final_price")
        kept, rep = clean_items(rows, {"outliers": {"price_upper_ratio": 15, "price_lower_ratio": 0.05}}, expected_subject=sid)
        com = COM.get(sid)
        buyout_niche = (NC.get(sid) or {}).get("buyout_real") or (NC.get(sid) or {}).get("buyout") or 80   # запасной; 80 — допущение
        for lo, hi in BANDS:
            seg = [r for r in kept if lo <= (r["price"] or 0) < hi and (r.get("sales") or 0) > 0]
            if len(seg) < 5:
                continue
            sales = sum(r["sales"] for r in seg)
            newp = sorted(r["sales"] for r in seg if "2025-08-01" <= (r.get("sku_first_date") or "") <= "2026-06-15")
            bysel = collections.Counter()
            for r in seg:
                bysel[r.get("seller")] += r["sales"]
            vols = [r["package_length"] * r["package_width"] * r["package_height"] / 1000 for r in seg
                    if r.get("package_length") and r.get("package_width") and r.get("package_height")]
            buyer = st.median(r["price"] for r in seg)
            seller, spp = seller_for(sid, buyer)
            if seller is None or com is None:
                continue
            vol_assumed = len(vols) < 3                                        # в новых выгрузках Saleflow габаритов часто нет
            vol = st.median(vols) if not vol_assumed else VOL_ASSUMED          # [допущение] → проверить по карточкам WB (wb_cdn_card)
            pur = [r["purchase"] for r in seg if r.get("purchase")]                # реальный выкуп карточек сегмента (Saleflow)
            buyout = st.median(pur) if len(pur) >= 5 else buyout_niche
            kg = (NC.get(sid) or {}).get("kg") or max(0.1, 0.22 * vol)
            ymax = max_yuan(seller, vol, kg, com, buyout, batch)
            yest = buyer * china_pct / 100 / CNY
            e8 = econ(seller, yest, vol, kg, com, buyout, 8, batch)
            e15 = econ(seller, yest, vol, kg, com, buyout, 15, batch)
            p50 = st.median(newp) if newp else 0
            wf = winter_factor(sid)
            unit_cost = landed(yest, kg, batch)
            out.append(dict(id=sid, subj=REQ.get(sid, {}).get("subject"), band=f"{lo}-{hi}", cards=len(seg), sales=sales,
                            new=len(newp), new_p25=newp[len(newp) // 4] if newp else 0, new_p50=p50,
                            top1=round(bysel.most_common(1)[0][1] / sales * 100), top6=round(sum(v for _, v in bysel.most_common(6)) / sales * 100), sellers=len(bysel), vol=round(vol, 2),
                            buyer=round(buyer), seller=seller, spp=spp, com=com, buyout=buyout,
                            ymax=ymax, ymax_pct=round(ymax * CNY / buyer * 100, 1), yest=round(yest, 1),
                            profit8=round(e8["net_profit"]), margin8=e8["net_margin_pct"], margin15=e15["net_margin_pct"],
                            month8=round(e8["net_profit"] * p50), winter=wf,
                            month8_winter=round(e8["net_profit"] * p50 * wf) if wf else None,
                            unit_cost=round(unit_cost), batch_units=int(BUDGET_GOODS // unit_cost), kg=kg, dropped=rep["dropped_pct"],
                            verdict=REQ.get(sid, {}).get("verdict", "")[:2], flags=REQ.get(sid, {}).get("flags"), vol_assumed=vol_assumed))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--china-pct", type=float, default=11.0)
    a = ap.parse_args()
    ids = sorted({int(os.path.basename(p)[:-5]) for p in glob.glob("data/raw/saleflow/v3_products500/*.json")
                  + glob.glob("data/raw/saleflow/v3_products100/*.json") + glob.glob(f"{A}/p500/*.json")})
    ok = [i for i in ids if i in REQ and REQ[i]["verdict"][:1] in ("🟢", "🟡")]
    res = run(ok, a.batch, a.china_pct)
    out = f"data/processed/screen_white_{dt.date.today()}.json"
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    good = [r for r in res if r["ymax_pct"] >= a.china_pct * 1.3 and r["new_p50"] >= 30 and r["top1"] <= 35
            and r["winter"] and r["winter"] >= 0.6 and r["batch_units"] >= 80]
    good.sort(key=lambda r: -r["month8_winter"])
    print(f"ниш {len(ok)}, сегментов {len(res)}; проходят (¥max ≥ {a.china_pct * 1.3:.0f} % цены, новичок P50 ≥ 30, топ-1 ≤ 35 %, "
          f"зимний спрос ≥ 60 % июля, партия ≥ 80 шт на {BUDGET_GOODS} ₽): {len(good)} → {out}")
    for r in good[:a.top]:
        print(f"{r['id']:>5} {str(r['subj'])[:26]:<26} {r['band']:>9} {r['buyer']:>5}₽ СПП{r['spp']:>3} ком{r['com']:>5} выкуп{r['buyout']:>3} "
              f"¥max{r['ymax']:>6} ({r['ymax_pct']:>4}%) маржа8 {r['margin8']:>5}% маржа15 {r['margin15']:>5}% "
              f"новичок P50 {r['new_p50']:>5} топ1 {r['top1']:>2}% зима×{r['winter']} партия {r['batch_units']} шт → {r['month8_winter']:>8} ₽/мес зимой {r['verdict']}")


if __name__ == "__main__":
    main()
