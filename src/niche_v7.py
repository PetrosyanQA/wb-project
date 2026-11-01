"""Отбор ниш v7 (01.11.2026): единственный жёсткий фильтр — магниты. ЧЗ, декларации, электроника — не фильтр, а пометка.

Этап 1 (0 запросов) — сводка всех ниш WB, октябрь-2026 против октября-2025 (Saleflow wb_subjects_list):
    python -m src.niche_v7 screen            → data/processed/niche_v7_screen_2026-11-01.json + короткий список
Три подхода (каждый даёт свой топ, в короткий список идёт объединение):
    A «спрос растёт быстрее конкуренции» — выручка год к году относительно рынка минус рост числа карточек с продажами;
    B «деньги на продавца» — выручка ниши на одного продавца с продажами (сколько реально зарабатывает средний игрок);
    C «дефицит» — упущенная выручка из-за пустых складов, % (спрос есть, товара не хватает).
⚠️ Сводка Saleflow после 08.2026 занижена (рынок 10.2026 = 0,61 от 10.2025 — так не бывает), поэтому рост считаем
относительно рынка, а абсолютные цифры берём из карточек (этап 2, fbs=1 — там данные полные).

Этап 2 (1 запрос на нишу) — карточки за октябрь (products, fbs=1) для короткого списка:
    python -m src.niche_v7 cards             → новички-победители, доля топ-6 продавцов, цена, потолок ¥, требования
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
SUBJ = "data/raw/saleflow/2026-11-01/subjects"
P500 = "data/raw/saleflow/2026-11-01/p500"
OUT = "data/processed/niche_v7_screen_2026-11-01.json"
REQ = {r["id"]: r for r in json.load(open("data/processed/niche_requirements_2026-10-23.json", encoding="utf-8"))}
PRICE = (500, 8000)          # ₽ медиана с продажами: дешевле — белый ввоз не окупается, дороже — партия не влезает в $2 000
MIN_REV = 15e6               # ₽/мес по (заниженной) сводке


def _load(pat: str) -> dict[int, dict]:
    return {r["id"]: r for f in sorted(glob.glob(f"{SUBJ}/{pat}")) for r in json.load(open(f, encoding="utf-8"))["data"]}


def req(sid: int, name: str) -> dict:
    r = REQ.get(sid)
    if r:
        return {"chz": r["chz"], "docs": r["docs"], "flags": r["flags"], "verdict": r["verdict"]}
    return {"chz": "?", "docs": "проверить", "flags": "магнит" if "магнит" in name.lower() else "—", "verdict": "❓ нет в справочнике"}


def screen() -> list[dict]:
    a, b = _load("p*.json"), _load("y2025_p*.json")
    com = set(a) & set(b)
    m_rev = sum(a[i]["revenue"] for i in com) / sum(b[i]["revenue"] for i in com)
    m_sup = sum(a[i]["items_with_sells"] for i in com) / sum(b[i]["items_with_sells"] for i in com)
    rows = []
    for sid, x in a.items():
        rq = req(sid, x["name"])
        if "магнит" in rq["flags"].lower() or "запрет" in rq["verdict"]:
            continue
        p = x.get("median_price_final_with_sells") or 0
        if not (PRICE[0] <= p <= PRICE[1]) or x["revenue"] < MIN_REV:
            continue
        y = b.get(sid)
        yoy = (x["revenue"] / y["revenue"] / m_rev - 1) * 100 if y and y["revenue"] else None
        sup = (x["items_with_sells"] / y["items_with_sells"] / m_sup - 1) * 100 if y and y["items_with_sells"] else None
        s = x["sellers_with_sells"] or 1
        rows.append({"id": sid, "name": x["name"], "rev_mln": round(x["revenue"] / 1e6, 1), "price": round(p),
                     "sellers": x["sellers_with_sells"], "cards": x["items_with_sells"],
                     "sell_share": x["sellers_with_sells_percent"], "rev_per_seller": round(x["revenue"] / s),
                     "yoy_rel": None if yoy is None else round(yoy), "supply_rel": None if sup is None else round(sup),
                     "gap": None if yoy is None or sup is None else round(yoy - sup),
                     "lost_pct": x.get("lost_profit_percent"), "turnover": x.get("turnover_in_days"),
                     "rating": x.get("avg_rating_with_sells"), "buyout": x.get("purchase"), "com_fbs": x.get("commision_fbs"),
                     "season": x.get("seasonality_level"), **rq})
    for key, nm in (("gap", "A"), ("rev_per_seller", "B"), ("lost_pct", "C")):
        ok = [r for r in rows if r[key] is not None and (key != "gap" or r["sellers"] >= 30)]
        for k, r in enumerate(sorted(ok, key=lambda r: -r[key])):
            r[f"rank_{nm}"] = k + 1
    json.dump({"market_rev_ratio": round(m_rev, 3), "market_supply_ratio": round(m_sup, 3), "rows": rows},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return rows


def shortlist(rows: list[dict], top: int = 40) -> list[dict]:
    """Объединение топов трёх подходов; B — только где ≥ 30 продавцов с продажами (иначе это 2–3 монополиста)."""
    pick = {}
    for nm, cond in (("A", lambda r: True), ("B", lambda r: r["sellers"] >= 30), ("C", lambda r: r["sellers"] >= 30)):
        for r in sorted([r for r in rows if r.get(f"rank_{nm}") and cond(r)], key=lambda r: r[f"rank_{nm}"])[:top]:
            pick.setdefault(r["id"], r).setdefault("why", []).append(nm)
    return list(pick.values())


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "screen"
    if cmd == "screen":
        rows = screen()
        sl = shortlist(rows)
        json.dump([r["id"] for r in sl], open("data/processed/niche_v7_shortlist_2026-11-01.json", "w"), indent=0)
        print(f"ниш после магнитов/цены/выручки: {len(rows)}; короткий список: {len(sl)}")
        for r in sorted(sl, key=lambda r: -len(r["why"])):
            print(f"{r['id']:>6} {''.join(r['why']):3} {r['name'][:45]:45} {r['rev_mln']:>6} млн {r['price']:>5} ₽ прод {r['sellers']:>5} "
                  f"рост {r['yoy_rel']}% конк {r['supply_rel']}% упущ {r['lost_pct']}% | {r['verdict']}")
    elif cmd == "cards":
        from src.niche_v7_cards import run
        run()


if __name__ == "__main__":
    main()
