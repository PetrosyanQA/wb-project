"""Доп. срезы Saleflow по нише перед решением (2026-10-14): позиции FBS/FBO по регионам, клоны, полки, фото, вопросы,
запросы победителей, регионы продаж, ассортимент продавцов. Ответы — в data/raw/saleflow/<RUN>/strategy<niche>/extra/.

    python -m src.extra_collect --niche 7640 [--dry-run]

Уже скачанное пропускается; 3 сбоя подряд → пауза 60 с; 6 подряд → стоп (неудачные вызовы тоже списываются с квоты).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
PLANS = {
    52: {
        "run": "2026-10-15",
        "queries": [], "regions": [],
        "queries_once": ["кошелек женский", "кошелек мужской", "картхолдер"],
        "focus": [757094033, 529165808],                      # маленький из нат. кожи 30/д; портмоне 25/д
        "winners": [757094033, 529165808, 427625224, 482096084],
        "faq": [757094033, 529165808, 981066887],
        "keywords": [757094033, 529165808],
        "sellers": {},
        "d1": "2026-07-01", "d2": "2026-07-31", "kw_d1": "2026-09-14", "kw_d2": "2026-10-14",
    },
    729: {
        "run": "2026-10-11",
        "queries": [], "regions": [],
        "queries_once": ["поводок рулетка", "рулетка для собак 5 м", "поводок рулетка 360"],
        "focus": [111647586, 803883203],                       # Красницкий 5 м, ФРИ 10 м
        "winners": [111647586, 803883203, 291113901, 642674096],
        "faq": [111647586, 803883203, 291113901],
        "keywords": [],
        "sellers": {"Красницкий": None, "ФРИ": None},
        "d1": "2026-07-01", "d2": "2026-07-31", "kw_d1": "2026-09-13", "kw_d2": "2026-10-13",
    },
    7640: {
        "run": "2026-10-14",
        "queries": ["сумка спортивная", "сумка дорожная", "сумка спортивная с отделом для обуви"],
        "regions": ["Москва", "Новосибирск", "Краснодар", "Екатеринбург", "Казань"],
        "focus": [769180126, 492558830],                       # Кондрашов, Галсанов
        "winners": [769180126, 492558830, 597298281, 768361554, 1009195748, 453512938],
        "faq": [769180126, 492558830, 768361554],
        "keywords": [769180126, 597298281, 1009195748, 492558830, 768361554],
        "sellers": {"Кондрашов": 250026838, "Галсанов": 1153127, "Поликутин": 42792, "Slimberg": 39672},
        "d1": "2026-07-01", "d2": "2026-07-31", "kw_d1": "2026-09-13", "kw_d2": "2026-10-13",
        "queries_once": ["ручная кладь в самолет", "сумка ручная кладь победа 36 30 27", "сумка дорожная ручная кладь",
                         "рюкзак ручная кладь победа"],
        "subjects": {"Рюкзаки": 138, "Сумки": 50},
        "ozon_queries": ["сумка спортивная", "поводок рулетка"],
    },
}


def tasks(niche: int) -> list[tuple[str, str, dict]]:
    P = PLANS[niche]
    o = f"data/raw/saleflow/{P['run']}/strategy{niche}/extra"
    T = []
    for q in P["queries"]:
        for r in P["regions"]:
            T.append((f"{o}/check_rates/{q.replace(' ', '_')}__{r}.json", "wb_check_rates", {"query": q, "region": r, "limit": 100}))
    for s in P["focus"]:
        T.append((f"{o}/similar_identical_{s}.json", "wb_similar", {"family": "identical", "path_value": str(s), "report": "products",
                                                                   "d1": P["d1"], "d2": P["d2"]}))
        T.append((f"{o}/similar_identical_wb_{s}.json", "wb_similar", {"family": "identical_wb", "path_value": str(s), "report": "products",
                                                                      "d1": P["d1"], "d2": P["d2"]}))
        T.append((f"{o}/shelves_items_{s}.json", "wb_shelves", {"sku": s, "report": "items", "d1": P["d1"], "d2": P["d2"], "limit": 100}))
        T.append((f"{o}/shelves_stats_{s}.json", "wb_shelves", {"sku": s, "report": "stats", "d1": P["d1"], "d2": P["d2"]}))
        T.append((f"{o}/sales_by_region_{s}.json", "wb_sku", {"sku": s, "report": "sales_by_region", "d1": P["d1"], "d2": P["d2"]}))
    for s in P["winners"]:
        T.append((f"{o}/photos_history_{s}.json", "wb_sku", {"sku": s, "report": "photos_history"}))
    for s in P["faq"]:
        T.append((f"{o}/faq_{s}.json", "wb_sku", {"sku": s, "report": "faq"}))
    for s in P["keywords"]:
        T.append((f"{o}/keywords_{s}.json", "wb_sku", {"sku": s, "report": "keywords", "d1": P["kw_d1"], "d2": P["kw_d2"]}))
    for name, sid in P["sellers"].items():
        if not sid:
            continue
        T.append((f"{o}/seller_{name}_products.json", "wb_seller", {"supplier_id": sid, "report": "products", "d1": P["d1"], "d2": P["d2"],
                                                                     "limit": 100}))
        T.append((f"{o}/seller_{name}_trends.json", "wb_seller", {"supplier_id": sid, "report": "trends", "d1": "2025-06-01", "d2": P["d2"]}))
    for q in P.get("queries_once", []):                        # только Москва — регионы дали одинаковую выдачу (2026-10-15)
        T.append((f"{o}/check_rates/{q.replace(' ', '_')}__Москва.json", "wb_check_rates", {"query": q, "region": "Москва", "limit": 100}))
    for sub, sid in P.get("subjects", {}).items():
        T.append((f"{o}/subject_{sid}_products500_2026-07.json", "wb_subject", {"subject_id": sid, "report": "products", "d1": "2026-07-01",
                                                                                "d2": "2026-07-31", "limit": 500}))
        T.append((f"{o}/subject_{sid}_trends.json", "wb_subject", {"subject_id": sid, "report": "trends", "d1": "2024-09-01",
                                                                   "d2": "2026-09-30", "group_by": "month"}))
    for q in P.get("ozon_queries", []):
        T.append((f"{o}/ozon_search_{q.replace(' ', '_')}.json", "ozon_categories_search", {"query": q}))
    return T


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    T = [t for t in tasks(a.niche) if not os.path.exists(t[0])]
    T.sort(key=lambda t: t[1] == "wb_check_rates")          # живой поиск WB падает чаще — в конец (2026-10-14)
    print(f"к скачиванию: {len(T)} (= запросов Saleflow)")
    if a.dry_run or not T:
        return
    from src.strategy_collect import Client, fetch, quota
    c, streak, fails = Client(), 0, []
    bad_kind = __import__("collections").Counter()             # 2 сбоя одного вида отчёта → пропускаем вид (не жжём квоту)
    kind = lambda tool, args: f"{tool}:{args.get('report') or args.get('family') or ''}"
    try:
        print("квота до:", quota(c))
        for k, (path, tool, args) in enumerate(T, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if bad_kind[kind(tool, args)] >= 2:
                fails.append(path)
                continue
            try:
                json.dump(fetch(c, tool, args, timeout=200), open(path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"[{k}/{len(T)}] ok {os.path.basename(path)}")
                streak = 0
            except Exception as e:                       # noqa: BLE001 — upstream Saleflow нестабилен
                print(f"[{k}/{len(T)}] fail {os.path.basename(path)}: {str(e)[:90]}")
                fails.append(path)
                bad_kind[kind(tool, args)] += 1
                streak += 1
                if "закрылся" in str(e):
                    c = Client()
                if streak == 3:
                    time.sleep(60)
                if streak >= 8:
                    print("6 сбоев подряд — стоп")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()
    print("не скачано:", len(fails))


if __name__ == "__main__":
    main()
