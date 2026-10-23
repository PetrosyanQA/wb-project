"""Поиск «спрос есть — товара мало» по поисковым запросам WB во всех разрешённых нишах.

    python -m src.seo_gap collect [--month 2026-07] [--limit 170]   # 1 запрос Saleflow на нишу (wb_subject keywords)
    python -m src.seo_gap analyze [--month 2026-07]                 # 0 запросов → data/processed/seo_demand_<дата>.json
    python -m src.seo_gap supply --top 200                          # 1 запрос на запрос (wb_check_rates) → seo_supply_<дата>.json

Ниши: data/processed/niche_requirements_2026-10-23.json — 🟢 без документов или 🟡 декларация (не «крупный»),
медиана цены 1 000–6 000 ₽, выручка ≥ 30 млн ₽/мес. Нет ЧЗ, батарей, магнитов, электроники (правило пользователя).
Поля Saleflow keywords: wb_count = частота WB (поисков/мес), count = результатов WB (товаров в выдаче),
items_count = карточек ЭТОЙ ниши по запросу (memory: saleflow-keywords-fields).
⚠️ count — НЕ число товаров (это частота точного написания), поэтому предложение меряем живой выдачей (шаг supply).
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data" / "processed" / "niche_requirements_2026-10-23.json"
OUT = ROOT / "data" / "raw" / "saleflow" / "seo_gap"
OK = ("🟢 без обязательных документов", "🟡 нужна декларация / сертификат")


def universe() -> list[dict]:
    r = json.load(open(REQ, encoding="utf-8"))
    U = [x for x in r if x["verdict"] in OK and x["median_price"] and x["rev_mln"]
         and 1000 <= x["median_price"] <= 6000 and x["rev_mln"] >= 30]
    return sorted(U, key=lambda x: -x["rev_mln"])


def path(sid: int, month: str) -> Path:
    return OUT / month / f"kw_{sid}.json"


def collect(month: str, limit: int) -> None:
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch, quota
    y, m = map(int, month.split("-"))
    d1, d2 = f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"
    todo = [x for x in universe() if not path(x["id"], month).exists()][:limit]
    print(f"ниш к сбору {len(todo)} (запросов Saleflow ≈ {len(todo)})")
    if not todo:
        return
    c, streak = Client(), 0
    print("квота до:", quota(c))
    for n, x in enumerate(todo, 1):
        p = path(x["id"], month)
        p.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                res = fetch(c, "wb_subject", {"subject_id": x["id"], "report": "keywords", "d1": d1, "d2": d2})
                json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False)
                streak = 0
                print(f"{n}/{len(todo)} ok {x['id']} {x['subject']} — {len(res.get('queries') or [])} запросов", flush=True)
                break
            except Exception as e:                                      # noqa: BLE001
                print(f"{n}/{len(todo)} ERR {x['id']} {x['subject']}: {str(e)[:90]}", flush=True)
                c = Client()
        else:
            streak += 1
            if streak >= 5:
                print("5 сбоев подряд — стоп"); break
        if n % 25 == 0:
            q = quota(c)
            print("квота:", q, flush=True)
            mm = re.search(r"Остаток:\s*(\d+)", q)
            if mm and int(mm.group(1)) < 15:
                print("осталось < 15 запросов — стоп"); break
    print("квота после:", quota(c))


GENERIC = re.compile(r"^(подар|набор$|наборы|кухня|для дома|для кухни|товары|новинк|распродаж|скидк|wildberries|вб )|подарок|подарки")


def shortlist(month: str, per_niche: int = 3, min_freq: int = 5000, max_freq: int = 150000) -> list[dict]:
    """Спрос: уточняющие продуктовые запросы ниши (min_freq ≤ wb_count ≤ max_freq — «головные» запросы без дефицита отброшены;
    items_count ≥ 50 — запрос про ЭТУ нишу; ≥ 3 слов), по одному на кластер, без общих слов («подарок», «набор»)."""
    U = {x["id"]: x for x in universe()}
    out = []
    for sid, x in U.items():
        p = path(sid, month)
        if not p.exists():
            continue
        seen, rows = set(), []
        for q in sorted(json.load(open(p, encoding="utf-8")).get("queries") or [], key=lambda q: -(q.get("wb_count") or 0)):
            f, it, cl = q.get("wb_count") or 0, q.get("items_count") or 0, q.get("query_cluster") or q["word"]
            if not min_freq <= f <= max_freq or it < 50 or cl in seen or GENERIC.search(q["word"]) or len(q["word"].split()) < 3:
                continue
            seen.add(cl)
            rows.append({"subject_id": sid, "subject": x["subject"], "word": q["word"], "freq": f, "items": it,
                         "median_price": x["median_price"], "rev_mln": x["rev_mln"], "sellers": x["sellers"], "docs": x["verdict"]})
        out += rows[:per_niche]
    best = {}
    for r in out:                                                       # один запрос — одна ниша (где больше карточек)
        if r["word"] not in best or r["items"] > best[r["word"]]["items"]:
            best[r["word"]] = r
    return sorted(best.values(), key=lambda r: -r["freq"])


STOP = {"для", "на", "с", "и", "в", "из", "по", "от", "к", "без", "под", "женская", "женский", "женские", "мужской", "мужская",
        "мужские", "детский", "детская", "детские"}


def stems(word: str) -> list[str]:
    return [w[:5] for w in re.findall(r"[a-zа-яё0-9]+", word.lower()) if w not in STOP and len(w) > 2]


def supply(month: str, top: int) -> None:
    """Шаг 2 (1 запрос Saleflow на запрос): живая выдача Москва, топ-100 → насколько выдача закрывает спрос."""
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch, quota
    import statistics as st
    today = dt.date.today().isoformat()
    S = json.load(open(sorted((ROOT / "data" / "processed").glob("seo_demand_*.json"))[-1], encoding="utf-8"))["queries"][:top]
    rd = OUT / "live"
    rd.mkdir(parents=True, exist_ok=True)
    c, res = None, []
    for n, r in enumerate(S, 1):
        f = rd / (re.sub(r"[^a-zа-яё0-9]+", "_", r["word"].lower()) + ".json")
        if not f.exists():
            c = c or Client()
            try:
                d = fetch(c, "wb_check_rates", {"query": r["word"], "region": "Москва", "limit": 100})
                json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"{n}/{len(S)} ok {r['word']}", flush=True)
            except Exception as e:                                      # noqa: BLE001
                print(f"{n}/{len(S)} ERR {r['word']}: {str(e)[:80]}", flush=True); c = None; continue
        rows = json.load(open(f, encoding="utf-8")).get("data") or []
        if not rows:
            continue
        k = stems(r["word"])
        rel = [x for x in rows if all(any(t.startswith(s) for t in re.findall(r"[a-zа-яё0-9]+", (x.get("name") or "").lower())) for s in k)]
        t30 = rows[:30]
        res.append(r | {"relevant_share": round(len(rel) / len(rows), 2), "weak_top30": sum(1 for x in t30 if (x.get("comments") or 0) < 100),
                        "med_comments_top30": st.median(x.get("comments") or 0 for x in t30),
                        "sales_top100": sum(x.get("sales") or 0 for x in rows), "sales_relevant": sum(x.get("sales") or 0 for x in rel),
                        "med_price_top30": st.median(x.get("final_price") or 0 for x in t30),
                        "sellers_top30": len({x.get("seller") for x in t30}), "promoted": sum(1 for x in rows if x.get("promoted"))})
    for x in res:                                                       # дефицит: много поисков, мало точных и/или слабые карточки наверху
        x["gap_score"] = round(x["freq"] / 1000 * ((1 - x["relevant_share"]) * 0.5 + x["weak_top30"] / 30 * 0.5), 1)
    res.sort(key=lambda x: -x["gap_score"])
    json.dump(res, open(ROOT / "data" / "processed" / f"seo_supply_{today}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("запрос | ниша | поисков/мес | точных в топ-100 | слабых (<100 отзывов) в топ-30 | мед. отзывов топ-30 | продаж топ-100 | мед. цена | score")
    for x in res[:50]:
        print(f"{x['word']} | {x['subject']} | {x['freq']} | {x['relevant_share']:.0%} | {x['weak_top30']} | {x['med_comments_top30']:.0f} | "
              f"{x['sales_top100']} | {x['med_price_top30']:.0f} | {x['gap_score']}")
    if c:
        print("квота:", quota(c))


def analyze(month: str) -> None:
    """Шаг 1 (0 запросов): спрос — список сильных продуктовых запросов для проверки живой выдачей (шаг supply)."""
    U = universe()
    got = sum(1 for x in U if path(x["id"], month).exists())
    S = shortlist(month)
    today = dt.date.today().isoformat()
    json.dump({"month": month, "queries": S}, open(ROOT / "data" / "processed" / f"seo_demand_{today}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"ниш с данными {got}/{len(U)}; запросов на проверку выдачи {len(S)}")
    for r in S[:40]:
        print(f"  {r['freq']:>8,} | {r['word']} | {r['subject']} | мед. {r['median_price']} ₽".replace(",", " "))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["collect", "analyze", "supply"])
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--month", default="2026-07")
    ap.add_argument("--limit", type=int, default=170)
    a = ap.parse_args()
    {"collect": lambda: collect(a.month, a.limit), "analyze": lambda: analyze(a.month), "supply": lambda: supply(a.month, a.top)}[a.step]()


if __name__ == "__main__":
    main()
