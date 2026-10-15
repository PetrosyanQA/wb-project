"""Поиск ниши v3 — «новички-победители везде» (2026-10-15). Расширение v2 (src/niche_v2.py).

    python -m src.niche_v3 universe                  # шаг 1: все предметы ≥ 5 млн ₽/мес, только жёсткие запреты (0 запросов)
    python -m src.niche_v3 collect [--max N] [--dry-run]   # шаг 2: products500 июля по приоритету (1 запрос на нишу, кэш)
    python -m src.niche_v3 score                     # шаг 2–3: новички-победители, сегменты → data/processed/niche_v3_<дата>.json

Что изменено против v2 (согласовано 2026-10-15):
  • порог выручки 15 → 5 млн ₽/мес (малые ниши — меньше конкурентов);
  • текстиль разрешён (ТР ТС 017 принят), цена покупателя 700–3 000 ₽;
  • главный критерий — новички (старт 2025-08 … 2026-05), которые дошли до ≥ 10 шт/день, и P50 новичков ≥ 4/день;
  • наше структурное преимущество — комиссия кабинета AM в среднем на 17 п.п. ниже, чем у продавцов РФ (проверено по 3 000 ниш).
Жёсткие запреты остаются: магниты, батарейки/электроника, жидкости/химия, пищевой контакт, детское, ЧЗ (одежда/обувь),
оружие/ножи, габарит (мебель и т.п.).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
TODAY = dt.date.today().isoformat()
SUBJ = "data/raw/saleflow/2026-10-11/all/jul2026"
RAW = "data/raw/saleflow/v3_products500"                   # общий кэш, имя файла = предмет
UNIVERSE = "data/processed/niche_v3_universe.json"
OUT = f"data/processed/niche_v3_{TODAY}.json"
NEW = ("2025-08-01", "2026-05-31")
REV_MIN = 5e6
PRICE = (700, 3000)
EXTRA_BAN = re.compile(r"гел[ьи]|молок|уголь|бумаж|печать фото|велокомп|зонты садов|компостер|бордюр|дорожки и плитки|кусторез")  # жидкость/еда/расходники/услуги/габарит


def ban_regexes():
    from src.all_niches import DROP_NAME, DROP_ROOTS
    textile = r"полотенц|текстил|ткан|пряж"                 # ТР ТС 017 принят пользователем 2026-10-14
    name_rx = re.compile("|".join(p for p in DROP_NAME.pattern.split("|") if not re.fullmatch(textile, p)), re.I)
    return DROP_ROOTS, name_rx


def load_subjects() -> list[dict]:
    rows = []
    for f in glob.glob(f"{SUBJ}/*.json"):
        d = json.load(open(f, encoding="utf-8"))
        rows += d.get("data", d) if isinstance(d, dict) else d
    return rows


def universe() -> list[dict]:
    from src.dna_rank import commissions
    com = commissions()
    roots, name_rx = ban_regexes()
    out, why = [], {}
    for r in load_subjects():
        root = r["name"].split(" / ")[0]
        reason = None
        if (r.get("revenue") or 0) < REV_MIN:
            reason = "выручка < 5 млн"
        elif root in roots:
            reason = "корень: " + root
        elif name_rx.search(r["name"].lower()) or EXTRA_BAN.search(r["name"].lower()):
            reason = "название (запрет)"
        elif not PRICE[0] <= (r.get("median_price_final_with_sells") or 0) <= PRICE[1]:
            reason = "цена вне 700–3000"
        elif (r.get("sellers_with_sells") or 0) < 30:
            reason = "< 30 продавцов"
        if reason:
            why[reason.split(":")[0]] = why.get(reason.split(":")[0], 0) + 1
            continue
        out.append({"id": r["id"], "name": r["name"], "rev_mln": round(r["revenue"] / 1e6, 1),
                    "price_med": r.get("median_price_final_with_sells"), "sellers_ws": r.get("sellers_with_sells"),
                    "items_ws": r.get("items_with_sells"), "buyout": r.get("purchase_after_return"),
                    "new_items_pct": round((r.get("items_new") or 0) / max(r.get("items") or 1, 1) * 100, 1),
                    "rev_per_item": round(r["revenue"] / max(r.get("items_with_sells") or 1, 1)),
                    "rf_commission": r.get("commision_fbs"), "our_commission": com.get(r["id"]),
                    "seasonality": r.get("seasonality_level")})
    # приоритет сбора: выручка на продающую карточку × доля новых карточек × выкуп
    for u in out:
        u["prio"] = round(u["rev_per_item"] / 1000 * (1 + u["new_items_pct"] / 10) * ((u["buyout"] or 50) / 100), 1)
    out.sort(key=lambda u: -u["prio"])
    json.dump(out, open(UNIVERSE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"предметов в выгрузке: {len(load_subjects())}; прошло: {len(out)}; отсев: {why}")
    for u in out[:25]:
        print(f"  {u['id']:5} {u['name'][:50]:50} | {u['rev_mln']:6} млн | {u['price_med']} ₽ | прод. {u['sellers_ws']} | выкуп {u['buyout']} | "
              f"новых {u['new_items_pct']}% | prio {u['prio']}")
    return out


def p500_path(n: int) -> str | None:
    p = f"{RAW}/{n}.json"
    if os.path.exists(p):
        return p
    from src.datastore import latest
    return latest(n, "products500")


def collect(max_n: int, dry: bool) -> None:
    U = json.load(open(UNIVERSE, encoding="utf-8"))
    todo = [u["id"] for u in U if not p500_path(u["id"])][:max_n]
    print(f"есть products500: {sum(1 for u in U if p500_path(u['id']))}; к скачиванию сейчас: {len(todo)}")
    if dry or not todo:
        return
    from src.strategy_collect import Client, fetch, quota
    os.makedirs(RAW, exist_ok=True)
    c, streak = Client(), 0
    try:
        print("квота до:", quota(c))
        for k, n in enumerate(todo, 1):
            try:
                r = fetch(c, "wb_subject", {"subject_id": n, "report": "products", "d1": "2026-07-01", "d2": "2026-07-31", "limit": 500},
                          timeout=200)
                json.dump(r, open(f"{RAW}/{n}.json", "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{k}/{len(todo)}] ok {n}")
                streak = 0
            except Exception as e:                       # noqa: BLE001 — upstream Saleflow нестабилен
                print(f"[{k}/{len(todo)}] fail {n}: {str(e)[:80]}")
                streak += 1
                if streak >= 4:
                    print("4 сбоя подряд — стоп")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()


def score() -> None:
    U = json.load(open(UNIVERSE, encoding="utf-8"))
    seas = {}
    if os.path.exists("data/processed/all_niches_season_2026-10-11.json"):
        seas = {r["id"]: r for r in json.load(open("data/processed/all_niches_season_2026-10-11.json", encoding="utf-8"))}
    out = []
    for u in U:
        p = p500_path(u["id"])
        if not p:
            continue
        d = json.load(open(p, encoding="utf-8"))
        R = [x for x in (d.get("data", d) if isinstance(d, dict) else d) if isinstance(x, dict) and x.get("sales")]
        if len(R) < 50:
            continue
        k = (seas.get(u["id"], {}).get("index", {}).get("07") or 100) / 100
        new = [x for x in R if NEW[0] <= (x.get("sku_first_date") or "") <= NEW[1]]
        lv = sorted(x["sales"] / 31 / k for x in new)
        q = lambda a: round(lv[min(len(lv) - 1, int(round(a * (len(lv) - 1))))], 1) if lv else None
        winners = sorted([x for x in new if x["sales"] / 31 / k >= 10], key=lambda x: -x["sales"])
        tot = sum(x["revenue"] for x in R) or 1
        by_s = {}
        for x in R[:100]:
            by_s[x.get("seller")] = by_s.get(x.get("seller"), 0) + x["revenue"]
        top100 = sum(x["revenue"] for x in R[:100]) or 1
        win_sellers = {x.get("seller") for x in winners}
        out.append({**u, "cards": len(R), "newcomers": len(new), "nc_p25": q(.25), "nc_p50": q(.5), "nc_p75": q(.75),
                    "winners_10": len(winners), "winner_sellers": len(win_sellers),
                    "winners_rev_pct": round(sum(x["revenue"] for x in winners) / tot * 100, 1),
                    "top1_pct": round(max(by_s.values()) / top100 * 100, 1),
                    "china_pct": round(sum(x["revenue"] for x in R if "кита" in str(x.get("country") or "").lower()) / tot * 100, 1),
                    "examples": [{"id": x["id"], "name": x["name"][:60], "start": (x.get("sku_first_date") or "")[:10],
                                  "per_day": round(x["sales"] / 31 / k, 1), "buyer": round(x["revenue"] / x["sales"]),
                                  "seller": x.get("seller")} for x in winners[:5]]})
    # итоговый балл: медианный новичок + число разных продавцов-победителей (не один игрок) − монополия
    for o in out:
        o["score"] = round((o["nc_p50"] or 0) * 2 + min(o["winner_sellers"], 10) + (o["nc_p75"] or 0) * 0.5
                           - max(0, o["top1_pct"] - 25) * 0.3, 1)
    out.sort(key=lambda o: -o["score"])
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"оценено ниш: {len(out)} → {OUT}")
    for o in out[:30]:
        print(f"  {o['score']:5} {o['id']:5} {o['name'][:44]:44} | P50 {o['nc_p50']} P75 {o['nc_p75']} | победителей ≥10/д {o['winners_10']} "
              f"({o['winner_sellers']} продавцов) | top1 {o['top1_pct']}% | {o['price_med']} ₽ | выкуп {o['buyout']} | Китай {o['china_pct']}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["universe", "collect", "score"])
    ap.add_argument("--max", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "universe":
        universe()
    elif a.cmd == "collect":
        collect(a.max, a.dry_run)
    else:
        score()


if __name__ == "__main__":
    main()
