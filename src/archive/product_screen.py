"""Отбор ТОВАРОВ для перепродажи (сначала товар, потом ниша). 0 запросов: все сохранённые выгрузки products Saleflow.

    python -m src.product_screen                 # → reports/product_screen_<дата>.md + data/processed/product_screen_<дата>.json

Логика (выводы 2026-10-23): при белом импорте выгоден лёгкий товар, дешёвый в Китае и дорогой на WB.
Фильтры по карточке: предмет 🟢/🟡 в niche_requirements (без ЧЗ, электроники, батарей, магнитов, запретов, не крупный);
страна Китай или не указана; цена покупателя 1 200–3 500 ₽; продажи ≥ 300 шт за период выгрузки (≈ 10/день, июль-2026);
упаковка ≤ 2 л, если габариты есть. «Перепродажа» = товар-дженерик: похожие названия (3 значимых слова) у ≥ 3 продавцов
в том же предмете — значит, его делают несколько фабрик и он есть на 1688. Новичок = первая дата ≥ 2025-06.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date.today().isoformat()
STOP = {"для", "и", "с", "на", "в", "из", "по", "от", "набор", "шт", "комплект", "новый", "подарок", "женский", "мужской",
        "детский", "универсальный", "большой", "маленький", "см", "мм", "л", "кг", "г"}


def key(name: str) -> str:
    w = [x for x in re.findall(r"[а-яёa-z]{3,}", name.lower()) if x not in STOP]
    return " ".join(sorted(w[:3]))


def load_all() -> dict[int, dict]:
    seen: dict[int, dict] = {}
    for f in glob.glob(str(ROOT / "data/raw/saleflow/**/*.json"), recursive=True):
        if not os.path.basename(f).startswith("products") or os.path.getsize(f) < 50_000:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        rows = d.get("data") if isinstance(d, dict) else d
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict) or "sales" not in rows[0]:
            continue
        for r in rows:
            i = r.get("id")
            if i is not None and (i not in seen or (r.get("sales") or 0) > (seen[i].get("sales") or 0)):
                seen[i] = r
    return seen


def main() -> None:
    req = {x["id"]: x for x in json.load(open(max(glob.glob(str(ROOT / "data/processed/niche_requirements_2*.json"))), encoding="utf-8"))}
    skus = load_all()
    ok_subj = {i for i, r in req.items() if r["verdict"][:1] in ("🟢", "🟡") and "крупн" not in r["verdict"]}
    groups = collections.defaultdict(set)
    for r in skus.values():
        groups[(r.get("subject_id"), key(r.get("name") or ""))].add(r.get("seller"))
    out = []
    for r in skus.values():
        sid, price, sales = r.get("subject_id"), r.get("final_price") or 0, r.get("sales") or 0
        if sid not in ok_subj or not (1200 <= price <= 3500) or sales < 300:
            continue
        if (r.get("country") or "Китай") != "Китай":
            continue
        L, W, H = r.get("package_length"), r.get("package_width"), r.get("package_height")
        vol = round(L * W * H / 1000, 2) if L and W and H else None
        if vol and vol > 2:
            continue
        sellers = len(groups[(sid, key(r.get("name") or ""))])
        out.append({"sku": r["id"], "name": (r.get("name") or "")[:60], "subject": req[sid]["subject"], "sid": sid,
                    "verdict": req[sid]["verdict"][:2], "price": price, "sales": sales, "rev_k": round((r.get("revenue") or 0) / 1e3),
                    "rating": r.get("rating"), "comments": r.get("comments"), "first": (r.get("sku_first_date") or "")[:10],
                    "new": (r.get("sku_first_date") or "") >= "2025-06", "vol_l": vol, "same_sellers": sellers,
                    "seller": r.get("seller"), "niche_rev_mln": req[sid]["rev_mln"], "niche_sellers": req[sid]["sellers"]})
    out.sort(key=lambda x: -x["rev_k"])
    json.dump(out, open(ROOT / "data" / "processed" / f"product_screen_{TODAY}.json", "w", encoding="utf-8"), ensure_ascii=False)
    gen = [x for x in out if x["same_sellers"] >= 3]
    T = [f"# Отбор товаров для перепродажи — {TODAY}",
         f"Карточек в сохранённых выгрузках Saleflow: {len(skus)}; прошли фильтры: {len(out)}; из них дженерики (≥ 3 продавцов): {len(gen)}.",
         "Период выгрузок в основном 2026-07-01 … 2026-07-31. [факт], погрешность Saleflow ±10–20 %.", "",
         "| # | SKU | Товар | Предмет | Цена, ₽ | Продаж/мес | Выручка, тыс ₽ | ★ / отзывов | Продавцов с таким товаром | Новичок | Документы |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, x in enumerate(gen[:60], 1):
        T.append(f"| {k} | {x['sku']} | {x['name']} | {x['subject']} | {x['price']} | {x['sales']} | {x['rev_k']} | {x['rating']} / {x['comments']} | "
                 f"{x['same_sellers']} | {'да' if x['new'] else ''} | {x['verdict']} |")
    rep = ROOT / "reports" / f"product_screen_{TODAY}.md"
    rep.write_text("\n".join(T), encoding="utf-8")
    print("\n".join(T[:75])); print("→", rep.relative_to(ROOT))


if __name__ == "__main__":
    main()
