"""Пересчёт ВСЕХ когда-либо выбранных ниш (22) одной моделью: am_fbs + карго YUANEXIM (2026-10-16). 0 запросов.
Для каждой ниши — один лучший товар (по новичкам-победителям в products500 июль 2026), его уровни новичков
P25/P50/P75 (шт/день, очищено от сезона июля), карго/шт, max ¥ (ДРР 15/10), маржа и финплан 12 мес на $2000.
Габарит — медиана упаковок карточек сегмента [факт], если в карточках 0 — [допущение]; вес и ¥ — [допущение].

    python -m src.recheck_all
"""
import json
import re
import statistics as st
import sys

from src import strategy as S, finplan as F
from src.cargo import per_unit
from src.screen_v4 import max_yuan
from src.unit_econ import unit_economics
from src import niche_v3 as V

sys.stdout.reconfigure(encoding="utf-8")
cfg = S.econ_config()
OUT = "data/processed/all_selected_recheck_2026-10-16.json"
SEAS = {r["id"]: r["index"] for r in json.load(open("data/processed/all_niches_season_2026-10-11.json", encoding="utf-8"))}
I52 = {"01": 96, "02": 139, "03": 113, "04": 79, "05": 79, "06": 76, "07": 86, "08": 93, "09": 96, "10": 96, "11": 94, "12": 150}
I7640 = {"09": 92, "10": 91, "11": 89, "12": 106, "01": 113, "02": 114, "03": 107, "04": 104, "05": 104, "06": 92, "07": 88, "08": 101}
I729 = json.load(open("data/processed/strategy_729_2026-10-11.json", encoding="utf-8"))["overview"]["season_index"]
I2486 = json.load(open("data/processed/strategy_2486_2026-10-11.json", encoding="utf-8"))["overview"]["season_index"]
P52 = "data/raw/saleflow/2026-10-15/strategy52/products500_2026-07.json"
SH = [0.45, 0.9] + [1.0] * 10
FLAT = {f"{m:02d}": 100 for m in range(1, 13)}  # нет сезонного индекса → ровный (отмечается season_flat)


def rows(p):
    d = json.load(open(p, encoding="utf-8"))
    return [x for x in (d.get("data", d) if isinstance(d, dict) else d) if isinstance(x, dict) and x.get("sales")]


def seg(path, lo, hi, k, rx=None, nrx=None):
    """Новички (первая продажа 2025-08…2026-05) в полосе цены покупателя + медианный объём упаковки."""
    new = [x for x in rows(path) if "2025-08-01" <= (x.get("sku_first_date") or "") <= "2026-05-31"
           and lo <= x["revenue"] / x["sales"] <= hi and (not rx or re.search(rx, x["name"].lower()))
           and (not nrx or not re.search(nrx, x["name"].lower()))]
    v = sorted(x["sales"] / 31 / k for x in new)
    q = lambda a: round(v[int(round(a * (len(v) - 1)))], 1) if v else None
    dims = [x["package_length"] * x["package_width"] * x["package_height"] / 1000 for x in new
            if (x.get("package_length") or 0) * (x.get("package_width") or 0) * (x.get("package_height") or 0) > 0]
    fp = [x["final_price"] for x in new if x.get("final_price")]
    win = [x for x in new if x["sales"] / 31 / k >= 5]
    return {"n": len(new), "lv": (q(.25), q(.5), q(.75)), "vol_cards": round(st.median(dims), 2) if dims else None,
            "fp_med": round(st.median(fp)) if fp else None, "win5": len(win), "win_sellers": len({x.get("seller") for x in win})}


def k07(n):
    return (SEAS.get(n, {}).get("07") or 100) / 100


# id, ниша, товар, цена до СПП, (¥lo,¥hi) [доп], кг [доп], объём л (None → из карточек), выкуп, комиссия AM, сегмент|уровни, сезон, старт
C = [
    (52, "Кошельки", "Картхолдер, нат. кожа", 1590, (8, 12), 0.12, 0.36, 70, 28,
     dict(path=P52, lo=1300, hi=1900, k=0.86, rx=r"картхолдер|для карт|зажим"), I52, "2027-01"),
    (52, "Кошельки", "Портмоне для автодокументов, нат. кожа", 1790, (12, 18), 0.20, 0.58, 70, 28,
     dict(path=P52, lo=1500, hi=2100, k=0.86, rx=r"автодок|документ"), I52, "2027-01"),
    (52, "Кошельки", "Кошелёк женский компактный, нат. кожа", 1690, (15, 20), 0.25, 0.58, 70, 28,
     dict(path=P52, lo=1500, hi=1800, k=0.86, rx=r"(маленьк|компакт)"), I52, "2027-01"),
    (777, "Держатели в авто", "Магнитный держатель MagSafe (без зарядки)", 1590, (12, 18), 0.15, None, 85, 20,
     dict(path=V.p500_path(777), lo=1000, hi=1700, k=k07(777), rx=r"магнит|magsafe", nrx=r"заряд"), SEAS.get(777), "2027-01"),
    (777, "Держатели в авто", "Держатель MagSafe с беспроводной зарядкой", 1590, (25, 35), 0.25, None, 85, 20,
     dict(path=V.p500_path(777), lo=1000, hi=1700, k=k07(777), rx=r"заряд"), SEAS.get(777), "2027-01"),
    (249, "Эспандеры", "Тканевые фитнес-резинки 3 шт, премиум", 1190, (6, 10), 0.30, 0.7, 82, 21,
     dict(path=V.p500_path(249), lo=900, hi=1500, k=k07(249), rx=r"ткан"), SEAS.get(249), "2027-01"),
    (731, "Игрушки для животных", "Интерактивная игрушка для кошек (электро)", 1490, (20, 30), 0.30, 1.5, 85, 15,
     dict(path=V.p500_path(731), lo=900, hi=2100, k=k07(731), rx=r"интерактив|прятк|летающ|автомат"), SEAS.get(731), "2027-01"),
    (729, "Поводки", "Поводок-рулетка 5 м", 1100, (10, 14), 0.32, 0.90, 75, 15, (38, 2.2, 3.3, 6.6), I729, "2027-02"),
    (2486, "Катушки рыболовные", "Катушка 3000", 1590, (20, 26), 0.45, 1.80, 79, 21, (59, 1.8, 3.1, 5.1), I2486, "2027-03"),
    (7640, "Сумки спортивные", "Сумка спортивная женская", 1590, (15, 20), 0.55, 2.0, 61, 23, (41, 4.2, 6.6, 9.0), I7640, "2027-01"),
    (937, "Коробки для хранения", "Коробка тканевая складная", 990, (6, 10), 0.60, 4.0, 82, 20,
     dict(path=V.p500_path(937), lo=800, hi=1300, k=0.90, rx=r"ткан|складн"), SEAS.get(937), "2027-01"),
    (2499, "Наборы для рыбалки", "Набор снастей подарочный", 1790, (25, 35), 0.80, 3.0, 70, 21,
     dict(path=V.p500_path(2499), lo=1000, hi=2000, k=k07(2499), rx=r"набор|бокс"), SEAS.get(2499), "2027-01"),
    (559, "Мультитулы", "Мультитул тактический", 1590, (20, 30), 0.35, None, 81, 25,
     dict(path=V.p500_path(559), lo=1000, hi=2300, k=k07(559)), SEAS.get(559), "2027-01"),
    (511, "Термосы", "Термос 1 л металлический", 1690, (25, 35), 0.60, None, 77, 23,
     dict(path=V.p500_path(511), lo=1000, hi=1800, k=k07(511), rx=r"1 ?л|1000 ?мл|1,0"), SEAS.get(511), "2027-01"),
    (236, "Фигурки и статуэтки", "Статуэтка интерьерная (Китай)", 1990, (25, 40), 0.50, 2.0, 82, 23,
     dict(path=V.p500_path(236), lo=1000, hi=2500, k=k07(236), rx=r"статуэтк"), SEAS.get(236), "2027-01"),
    (138, "Рюкзаки", "Рюкзак городской", 1590, (25, 35), 0.50, None, 55, 28,
     dict(path=V.p500_path(138), lo=900, hi=2500, k=k07(138), rx=r"городск|спортивн"), SEAS.get(138), "2027-01"),
    (2556, "Подарочные боксы", "Подарочный бокс для женщин", 1790, (20, 30), 0.50, None, 90, 26,
     dict(path=V.p500_path(2556), lo=1000, hi=2500, k=k07(2556), rx=r"женщин|девушк"), SEAS.get(2556), "2027-01"),
    (235, "Фотоальбомы", "Фотоальбом магнитный/бархатный", 2090, (20, 30), 0.60, 2.5, 75, 23,
     dict(path=V.p500_path(235), lo=1300, hi=2300, k=k07(235)), SEAS.get(235), "2027-01"),
]
# Ниши без products500: только экономика по цене около медианы ниши, спрос «—»
NO_P500 = [
    (316, "Визитницы", "Картхолдер / визитница, нат. кожа", 1590, (8, 12), 0.12, 0.36, 81.5, 28),
    (1381, "Кредитницы", "Кредитница, нат. кожа", 1590, (8, 12), 0.12, 0.36, 72.3, 28),
    (60, "Часы наручные", "Часы наручные кварцевые", 1990, (25, 40), 0.15, 0.5, 65.6, 28),
    (811, "Ножи кухонные", "Нож кухонный", 1190, (15, 25), 0.30, 1.0, 83.9, 23),
    (722, "Упаковщики вакуумные", "Вакууматор", 1590, (40, 60), 1.00, 4.0, 72.1, 18),
    (902, "Видеоняни", "Видеоняня с монитором (без Wi-Fi)", 3990, (150, 220), 0.80, 3.0, 71.4, 20),
    (5070, "Мастурбаторы мужские", "Мастурбатор (18+)", 2090, (25, 40), 0.50, 1.5, 89.7, 23),
]


def econ_block(price, y, kg, vol, bo, com):
    c = per_unit(y, kg, vol)["landed_rub"]
    e = {d: unit_economics(price, c, vol, cfg, with_breakeven=False, buyout_pct=bo, commission_pct=com,
                           ad_share_of_revenue_pct=d, packaging_rub=50) for d in (15, 10)}
    return c, e


def main():
    res = []
    for n, niche, name, price, (ylo, yhi), kg, vol, bo, com, lvl, idx, start in C:
        if isinstance(lvl, dict):
            s = seg(**lvl)
            if vol is None:
                vol = s["vol_cards"] or 1.0
            nn, (p25, p50, p75) = s["n"], s["lv"]
        else:
            s, (nn, p25, p50, p75) = {}, lvl
        u = per_unit(ylo, kg, vol)
        o = {"id": n, "niche": niche, "name": name, "price": price, "kg": kg, "vol": vol, "buyout": bo, "comm": com,
             "n": nn, "lv": (p25, p50, p75), "win5": s.get("win5"), "win_sellers": s.get("win_sellers"), "fp_med": s.get("fp_med"),
             "pcs": u["pcs_per_carton"], "cargo": u["cargo_rub"],
             "max15": max_yuan(price, vol, kg, bo, com, 15, 0), "max10": max_yuan(price, vol, kg, bo, com, 10, 0)}
        for tag, y in (("lo", ylo), ("hi", yhi)):
            c, e = econ_block(price, y, kg, vol, bo, com)
            r = {"y": y, "landed": c, "m15": e[15]["net_margin_pct"], "m10": e[10]["net_margin_pct"], "pr10": round(e[10]["net_profit"])}
            if p50:
                prod = {"name": name, "price": price, "yuan": y, "vol": vol, "kg": kg, "buyout": float(bo), "commission": float(com)}
                b = F.fit_batch(prod)
                season = F.season_from(idx or FLAT, start)
                o["season_flat"] = idx is None
                r["batch"] = b
                r.update({l: F.run(l, prod, [x * sh for sh in SH], season, b)["net_12m"]
                          for l, x in (("p25", p25), ("p50", p50), ("p75", p75), ("fail", 1.5)) if x is not None})
            o[tag] = r
        res.append(o)
    for n, niche, name, price, (ylo, yhi), kg, vol, bo, com in NO_P500:
        u = per_unit(ylo, kg, vol)
        o = {"id": n, "niche": niche, "name": name, "price": price, "kg": kg, "vol": vol, "buyout": bo, "comm": com,
             "n": None, "lv": (None, None, None), "pcs": u["pcs_per_carton"], "cargo": u["cargo_rub"],
             "max15": max_yuan(price, vol, kg, bo, com, 15, 0), "max10": max_yuan(price, vol, kg, bo, com, 10, 0)}
        for tag, y in (("lo", ylo), ("hi", yhi)):
            c, e = econ_block(price, y, kg, vol, bo, com)
            o[tag] = {"y": y, "landed": c, "m15": e[15]["net_margin_pct"], "m10": e[10]["net_margin_pct"], "pr10": round(e[10]["net_profit"])}
        res.append(o)
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for o in res:
        print(f"\n{o['id']} {o['niche']} — {o['name']} | {o['price']} ₽ | {o['kg']} кг {o['vol']} л | выкуп {o['buyout']} ком {o['comm']} | "
              f"новичков {o['n']} P25/50/75 {o['lv']} поб≥5 {o.get('win5')}({o.get('win_sellers')}) | карго {o['cargo']} ₽ | max¥ 15/10: {o['max15']}/{o['max10']}")
        for t in ("lo", "hi"):
            r = o[t]
            fin = (f" | партия {r['batch']} | 12м P25 {r.get('p25', 0):+,} P50 {r.get('p50', 0):+,} P75 {r.get('p75', 0):+,} "
                   f"провал {r.get('fail', 0):+,}") if "batch" in r else ""
            print(f"   ¥{r['y']}: маржа ДРР15 {r['m15']}% / ДРР10 {r['m10']}% ({r['pr10']} ₽/шт){fin}")


if __name__ == "__main__":
    main()
