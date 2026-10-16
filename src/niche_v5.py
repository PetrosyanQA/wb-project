"""Поиск ниши v5 «с нуля» (2026-10-16): БЕЗ фильтра декларации/сертификации, Честный знак и карго-запреты остаются.

    python -m src.niche_v5 universe            # 0 запросов: все предметы ≥ 5 млн ₽/мес → кандидаты
    python -m src.niche_v5 collect [--max N]   # products500 июля для кандидатов без кэша (1 запрос/ниша)
    python -m src.niche_v5 score               # этап 1: новички по ценовым полосам + грубая экономика → шорт-лист
    python -m src.niche_v5 cards [--top N]     # этап 2: 2 карточки лидеров шорт-листа (need_kiz, certificate, габарит, вес) — 1 запрос/карточка
    python -m src.niche_v5 final               # этап 3: экономика по реальным габаритам (схема am_fbs + карго YUANEXIM) → итог

Запреты (оставлены): Честный знак (одежда/обувь/бельё/6302/ремни/косметика/шины/…; плюс need_kiz карточки),
карго (магниты, батарейки/электроника, жидкости/химия, оружие), регистрация (медизделия, лекарства, БАД),
еда, ювелирка, 18+, табак, мебель/стройматериалы/сантехника/автозапчасти (габарит/подбор).
Разрешено с 2026-10-16: детские товары и игрушки (если need_kiz = False), контакт с пищей, аксессуары красоты (не жидкости),
текстиль (кроме 6302), декор, спорт, автоаксессуары, мототовары.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
SUBJ = "data/raw/saleflow/2026-10-11/all/jul2026"
RAW = "data/raw/saleflow/v3_products500"
CARDS = "data/raw/saleflow/v5_cards"
UNIVERSE = "data/processed/niche_v5_universe.json"
STAGE1 = "data/processed/niche_v5_stage1.json"
FINAL = "data/processed/niche_v5_final.json"
NEW = ("2025-08-01", "2026-05-31")
REV_MIN = 5e6
BAN_ROOTS = {
    # Честный знак
    "Одежда", "Обувь", "Белье", "Белье для малышей", "Одежда для малышей", "Детская одежда", "Детская обувь", "Спортивная одежда",
    "Спортивная обувь", "Шины и диски", "Спецодежда и СИЗы",
    # электроника / карго
    "Бытовая техника", "Крупная бытовая техника", "Климатическая техника", "Техника для кухни", "Техника для красоты и здоровья",
    "Ноутбуки и компьютеры", "Смартфоны и гаджеты", "Телевизоры и аудиотехника", "Сетевое оборудование", "Периферия и аксессуары",
    "Оргтехника", "Игровые консоли и игры", "Умный дом и безопасность", "Электроинструмент и оборудование", "Электрика", "Освещение",
    "Автоэлектроника", "Аккумуляторы для ТС", "Садовая техника", "Электротранспорт", "Фото и Видеотехника",
    # жидкости / химия
    "Бытовая химия", "Автохимия и автокосметика", "Масла и технические жидкости",
    # регистрация / еда / прочее
    "Здоровье", "Аптека", "Ветаптека", "Медицинские изделия", "Продукты", "Детское питание", "Спортивное питание и косметика",
    "Зоокорма", "Корма для животных", "Товары для курения", "Книги", "Книжная продукция и диски", "Цифровые товары",
    "Ювелирные украшения", "Товары для взрослых", "Транспортные средства",
    # габарит / подбор
    "Мебель", "Мебель корпусная и мебель для хранения", "Мебель мягкая", "Мебель для сна", "Мебель садовая", "Мебель на заказ",
    "Мебель офисная и торговое оборудование", "Мебель малых форм", "Строительные материалы", "Отделочные материалы", "Сантехника",
    "Автозапчасти", "Запчасти для легковых автомобилей", "Запчасти для грузовых автомобилей",
}
BAN_NAME = re.compile(
    r"магнит|аккумулят|батаре|заряд|электр|светодиод|\bled\b|гирлянд|ламп|фонар|наушник|колонк|камер[аы]? (видео|наблюд)|датчик|"
    r"видеорегистр|навигатор|пульт|радио|часы|весы|термометр|"
    r"жидк|спрей|масл|клей|краск|гель|крем|шампун|бальзам|скраб|сыворот|тоник|лосьон|духи|парфюм|туалетная вода|дезодор|"
    r"помад|тушь|тени для|пудр|румян|консилер|тональн|лак для ногт|лак[и ]|эмал|аэрозол|средств|чистящ|антисептик|"
    r"нож|оружи|пневмат|арбалет|патрон|пиротех|"
    r"одежд|обув|бель[её]|носк|колготк|полотенц|простын|постельн|пододеяльн|наволоч|скатерт|салфетки столов|ремни|ремень|пояс[аи]? |"
    r"перчат|жилет|шины|велосипед|"
    r"корм|лакомств|витамин|бад\b|лекарств|медицинск|ортопед|бандаж|тонометр|"
    r"чай|кофе|конфет|шоколад|сахар|мёд|мед\b|орех|продукт|напит|вода питьев|"
    r"сигарет|кальян|вейп|табак|"
    r"секс|эротик|вибратор|интим|"
    r"косметич|пенк|воск|светильн|интерактивн|радиоуправл|на пульте|роботы|мульч|торф|грунт", re.I)   # дополнено 2026-10-16


def load(p):
    return json.load(open(p, encoding="utf-8"))


def rows(p):
    d = load(p)
    return [x for x in (d.get("data", d) if isinstance(d, dict) else d) if isinstance(x, dict)]


def subjects() -> list[dict]:
    import glob
    out = []
    for f in glob.glob(f"{SUBJ}/*.json"):
        out += rows(f)
    return out


def universe() -> list[dict]:
    from src.dna_rank import commissions
    com = commissions()
    why, out = collections.Counter(), []
    for r in subjects():
        root, n = r["name"].split(" / ")[0], r["name"].lower()
        if (r.get("revenue") or 0) < REV_MIN:
            continue
        if root in BAN_ROOTS:
            why["корень (ЧЗ/карго/регистрация/еда/габарит)"] += 1
            continue
        if BAN_NAME.search(n):
            why["название (ЧЗ/карго/еда/…)"] += 1
            continue
        if (r.get("sellers_with_sells") or 0) < 30:
            why["< 30 продавцов"] += 1
            continue
        if (r.get("median_price_final_with_sells") or 0) < 400:
            why["медиана < 400 ₽"] += 1
            continue
        if (r.get("purchase_after_return") or 0) < 55:
            why["выкуп < 55 %"] += 1
            continue
        out.append({"id": r["id"], "name": r["name"], "rev_mln": round(r["revenue"] / 1e6, 1), "price_med": r.get("median_price_final_with_sells"),
                    "buyout": r.get("purchase_after_return"), "sellers_ws": r.get("sellers_with_sells"), "com": com.get(r["id"]),
                    "rf_com": r.get("commision_fbs")})
    out.sort(key=lambda u: -u["rev_mln"])
    json.dump(out, open(UNIVERSE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("отсев:", dict(why), "| кандидатов:", len(out), "| products500 уже есть:", sum(1 for u in out if p500(u["id"])))
    return out


def p500(n: int) -> str | None:
    p = f"{RAW}/{n}.json"
    if os.path.exists(p):
        return p
    from src.datastore import latest
    return latest(n, "products500")


def collect(max_n: int) -> None:
    from src.strategy_collect import Client, fetch
    U = [u for u in load(UNIVERSE) if not p500(u["id"])][:max_n]
    print("к скачиванию:", len(U))
    os.makedirs(RAW, exist_ok=True)
    c, streak = Client(), 0
    try:
        for k, u in enumerate(U, 1):
            try:
                r = fetch(c, "wb_subject", {"subject_id": u["id"], "report": "products", "d1": "2026-07-01", "d2": "2026-07-31", "limit": 500},
                          timeout=200)
                json.dump(r, open(f"{RAW}/{u['id']}.json", "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{k}/{len(U)}] ok {u['id']}")
                streak = 0
            except Exception as e:                       # noqa: BLE001
                print(f"[{k}/{len(U)}] fail {u['id']}: {str(e)[:70]}")
                streak += 1
                if "закрылся" in str(e):
                    c = Client()
                if streak >= 4:
                    print("4 сбоя подряд — стоп")
                    break
    finally:
        c.close()


def season_k(n: int) -> float:
    S = {r["id"]: r for r in load("data/processed/all_niches_season_2026-10-11.json")}
    return ((S.get(n, {}).get("index", {}) or {}).get("07") or 100) / 100


BANDS = [(500, 800), (800, 1100), (1100, 1400), (1400, 1800), (1800, 2300), (2300, 3000), (3000, 4000)]


def band_stats(R: list[dict], lo: float, hi: float, k: float) -> dict:
    B = [x for x in R if lo <= x["revenue"] / x["sales"] < hi]
    new = [x for x in B if NEW[0] <= (x.get("sku_first_date") or "") <= NEW[1]]
    lv = sorted(x["sales"] / 31 / k for x in new)
    q = lambda a: round(lv[min(len(lv) - 1, int(round(a * (len(lv) - 1))))], 1) if lv else 0
    win = [x for x in new if x["sales"] / 31 / k >= 5]
    by_s = collections.Counter()
    for x in B:
        by_s[x.get("seller")] += x["revenue"]
    tot = sum(by_s.values()) or 1
    return {"band": [lo, hi], "cards": len(B), "newcomers": len(new), "p25": q(.25), "p50": q(.5), "p75": q(.75), "winners5": len(win),
            "winner_sellers": len({x.get("seller") for x in win}), "top1_pct": round(max(by_s.values()) / tot * 100) if by_s else None,
            "buyer_med": round(st.median(x["revenue"] / x["sales"] for x in B)) if B else None,
            "seller_price_med": round(st.median(x.get("final_price") or x["revenue"] / x["sales"] for x in B)) if B else None,
            "china_pct": round(sum(x["revenue"] for x in B if "кита" in str(x.get("country") or "").lower()) / tot * 100) if B else None,
            "top_ids": [x["id"] for x in sorted(B, key=lambda x: -x["revenue"])[:3]],
            "examples": [{"id": x["id"], "name": x["name"][:60], "per_day": round(x["sales"] / 31 / k, 1), "buyer": round(x["revenue"] / x["sales"]),
                          "seller": x.get("seller")} for x in sorted(win, key=lambda x: -x["sales"])[:3]]}


def margin_at(price: float, yuan: float, kg: float, vol: float, buyout: float, comm: float, drr: float) -> float:
    from src import strategy as S
    from src.unit_econ import unit_economics
    cost = S.cost_rub(yuan, kg, vol)[0]
    return unit_economics(price, cost, vol, S.econ_config(), with_breakeven=False, buyout_pct=buyout, commission_pct=comm,
                          ad_share_of_revenue_pct=drr, packaging_rub=S.PACK)["net_margin_pct"]


def score() -> None:
    from src.screen_v4 import max_yuan
    out = []
    for u in load(UNIVERSE):
        p = p500(u["id"])
        if not p:
            continue
        R = [x for x in rows(p) if x.get("sales") and x.get("revenue")]
        if len(R) < 50:
            continue
        k = season_k(u["id"])
        if k < 0.5:                                      # июль < 50 % среднего: пересчёт июля «без сезона» раздувает спрос (ёлочные игрушки ×10)
            continue
        best = None
        for lo, hi in BANDS:
            b = band_stats(R, lo, hi, k)
            if b["newcomers"] < 5 or b["p50"] < 4 or b["winner_sellers"] < 3 or (b["top1_pct"] or 100) > 35:
                continue
            price = b["seller_price_med"]
            comm = u["com"] or 25.0
            b["max_yuan_drr10"] = max_yuan(price, 0.8, 0.35, u["buyout"], comm, 10, 0)     # грубо: 0,8 л / 0,35 кг — до карточек
            b["max_yuan_drr15"] = max_yuan(price, 0.8, 0.35, u["buyout"], comm, 15, 0)
            b["ratio"] = round(price / max(b["max_yuan_drr10"], 0.1), 1)                   # сколько ₽ цены на 1 ¥ допустимой закупки
            b["score"] = round(b["p50"] * b["max_yuan_drr10"], 1)                            # спрос × запас по ¥
            if not best or b["score"] > best["score"]:
                best = b
        if best:
            out.append({**u, "best": best})
    out.sort(key=lambda o: -o["best"]["score"])
    json.dump(out, open(STAGE1, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"прошли этап 1: {len(out)} ниш → {STAGE1}")
    for o in out[:60]:
        b = o["best"]
        print(f"  {b['score']:6} {o['id']:5} {o['name'][:46]:46} | полоса {b['band'][0]}–{b['band'][1]} | нов {b['newcomers']} P50 {b['p50']} P75 {b['p75']} | "
              f"поб {b['winners5']}({b['winner_sellers']}) | top1 {b['top1_pct']}% | цена {b['seller_price_med']} | выкуп {o['buyout']} ком {o['com']} | max¥ 10%:{b['max_yuan_drr10']} 15%:{b['max_yuan_drr15']}")


def card_dims(d: dict) -> dict:
    opts = {o["name"]: o["value"] for o in d.get("options", [])}
    num = lambda s: float(re.search(r"\d+(?:[.,]\d+)?", str(s)).group().replace(",", ".")) if s and re.search(r"\d", str(s)) else None
    L = [num(opts.get(k)) for k in ("Длина упаковки", "Ширина упаковки", "Высота упаковки")]
    if not all(L):
        L = [num(opts.get(k)) for k in ("Глубина предмета", "Ширина предмета", "Высота предмета")]
    g = num(opts.get("Вес товара с упаковкой (г)")) or num(opts.get("Вес товара без упаковки (г)"))
    kg = num(opts.get("Вес с упаковкой (кг)")) or (g / 1000 if g else None)
    txt = (d.get("imt_name", "") + " " + " ".join(f"{k} {v}" for k, v in opts.items())).lower()
    electro = bool(re.search(r"аккумулят|батаре|usb|электр|питани[ея] от сети|led|светодиод|магнит", txt))
    return {"need_kiz": d.get("need_kiz"), "electro": electro, "cert": (d.get("certificate") or {}).get("verified"),
            "vol_l": round(L[0] * L[1] * L[2] / 1000, 2) if all(L) else None, "kg": kg, "name": d.get("imt_name", "")[:60]}


def cards(top: int) -> None:
    from src.strategy_collect import Client, fetch
    os.makedirs(CARDS, exist_ok=True)
    S1 = load(STAGE1)[:top]
    todo = [(o["id"], sku) for o in S1 for sku in o["best"]["top_ids"][:2] if not os.path.exists(f"{CARDS}/{sku}.json")]
    print("карточек к скачиванию:", len(todo))
    c, streak = Client(), 0
    try:
        for k, (n, sku) in enumerate(todo, 1):
            try:
                json.dump(fetch(c, "wb_card_content", {"sku": str(sku)}, timeout=150), open(f"{CARDS}/{sku}.json", "w", encoding="utf-8"),
                          ensure_ascii=False)
                print(f"[{k}/{len(todo)}] ok {n}/{sku}")
                streak = 0
            except Exception as e:                       # noqa: BLE001
                print(f"[{k}/{len(todo)}] fail {sku}: {str(e)[:60]}")
                streak += 1
                if streak >= 4:
                    print("стоп")
                    break
    finally:
        c.close()


def final(assumed_share: float = 0.09) -> None:
    """Экономика по реальным габаритам/весу карточек; ¥ неизвестен → max ¥ и прибыль при допущении «закупка = 9 % цены покупателя»."""
    from src import finplan as F
    from src.screen_v4 import max_yuan
    from src.strategy import econ_config
    cny = econ_config()["cargo"]["cny_to_rub"]
    seas = {r["id"]: r["index"] for r in load("data/processed/all_niches_season_2026-10-11.json")}
    out = []
    for o in load(STAGE1):
        b = o["best"]
        dims = [card_dims(load(f"{CARDS}/{s}.json")) for s in b["top_ids"][:2] if os.path.exists(f"{CARDS}/{s}.json")]
        if not dims:
            continue
        kiz = any(x["need_kiz"] for x in dims)
        electro = any(x.get("electro") for x in dims)
        vols = [x["vol_l"] for x in dims if x["vol_l"]]
        kgs = [x["kg"] for x in dims if x["kg"]]
        vol = round(st.median(vols), 2) if vols else 0.8
        kg = round(st.median(kgs), 2) if kgs else 0.35
        price, comm = b["seller_price_med"], o["com"] or 25.0
        y_assumed = round(b["buyer_med"] * assumed_share / cny, 1)
        prod = {"name": o["name"], "price": price, "yuan": y_assumed, "vol": vol, "kg": kg, "buyout": float(o["buyout"]), "commission": float(comm)}
        idx = seas.get(o["id"]) or {f"{m:02d}": 100 for m in range(1, 13)}
        try:
            batch = F.fit_batch(prod)
            runs = {lab: F.run(lab, prod, [lv * x for x in [0.45, 0.9] + [1.0] * 10], F.season_from(idx, "2027-01"), batch)["net_12m"]
                    for lab, lv in (("p25", b["p25"]), ("p50", b["p50"]), ("p75", b["p75"]))}
        except Exception as e:                           # noqa: BLE001
            runs, batch = {"err": str(e)[:60]}, None
        out.append({**o, "need_kiz": kiz, "electro": electro, "cert_share": sum(1 for x in dims if x["cert"]) / len(dims), "vol_l": vol, "kg": kg,
                    "card_names": [x["name"] for x in dims],
                    "max_yuan_drr10": max_yuan(price, vol, kg, o["buyout"], comm, 10, 0), "max_yuan_drr15": max_yuan(price, vol, kg, o["buyout"], comm, 15, 0),
                    "yuan_assumed": y_assumed, "margin_drr15_assumed": margin_at(price, y_assumed, kg, vol, o["buyout"], comm, 15),
                    "margin_drr10_assumed": margin_at(price, y_assumed, kg, vol, o["buyout"], comm, 10), "batch": batch, "runs": runs})
    out.sort(key=lambda r: (r["need_kiz"] or r["electro"], -(r["runs"].get("p50") or -1e9)))
    json.dump(out, open(FINAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"итог: {len(out)} → {FINAL}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["universe", "collect", "score", "cards", "final"])
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()
    {"universe": universe, "score": score, "final": final}.get(a.cmd, lambda: None)()
    if a.cmd == "collect":
        collect(a.max)
    if a.cmd == "cards":
        cards(a.top)


if __name__ == "__main__":
    main()
