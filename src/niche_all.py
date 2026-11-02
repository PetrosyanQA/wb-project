"""Все ниши WB одной таблицей (кроме одежды, обуви, магнитов): статус + причина + что сделать, когда вернётся Saleflow. 0 запросов.

    python -m src.niche_all

Источник — снимок Saleflow wb_subjects_list за июль 2026 по всем предметам (`data/raw/saleflow/2026-10-11/all/jul2026*/`,
3 020 предметов; данным > 30 дней — вывод предварительный) + справочник документов `niche_requirements_*.json` + копилка
сегментов `niche_pool_*.json` (для ниш, где товары уже скачаны).
Пороги цикла (фиксированы до расчёта, /analiz 0.5): выручка после возвратов ≥ 5 млн ₽/мес; продавцов с продажами ≥ 30;
продаж на продавца ≥ 30 шт/мес; выкуп ≥ 60 %; медиана цены ≤ 7 000 ₽; при медиане ≥ 700 ₽ — маржа при ДРР 15 % ≥ 10 %
(¥ = 11 % цены, объём 2 л, если нет габаритов — допущения), при медиане < 700 ₽ — «нужен премиум-сегмент» (минус один порог).
Статус: ХОРОШАЯ (0 промахов) · ПОГРАНИЧНАЯ (1) · СЛАБАЯ (≥ 2) · ЛОВУШКА (лето / громоздкое (флаг «габарит», мебель, шины) /
брендовая электроника / книги / продукты и корма / медизделия) — ловушки только помечаются, ниша остаётся в списке.
Выход: reports/niche_master_<дата>.md, data/processed/niche_master_<дата>.json,
data/processed/niche_collect_queue_<дата>.json (только ХОРОШИЕ и ПОГРАНИЧНЫЕ без скачанных товаров — их качаем первыми).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
TH = {"rev": 5_000_000, "sellers": 30, "per_seller": 30, "buyout": 60, "price_max": 7000, "price_premium": 700, "margin15": 10}
CLOTH = ("одежд", "обувь", "белье")
FOOD = ("продукт", "корм", "кофе", "чай", "протеин", "витамин", "бад", "спортивное питание", "напитк", "снеки", "сладост")
MEDICAL = ("линз", "подгузник", "медицин", "лекарств", "ортопед", "тест", "шприц", "бандаж", "тонометр")
HEAVY = ("шины", "диски", "масла моторные", "шкаф", "комод", "гарнитур", "диван", "кроват", "стеллаж", "обувниц", "унитаз",
         "ванн", "раковин", "плитка", "ламинат", "обои", "панели стеновые", "двер", "окна", "кресл")
DEFAULT_SPP = 18          # если у ниши нет снимка Evirma [допущение]


def extra_traps(subj: str, root: str, flags: str) -> list[str]:
    s, r, f = subj.lower(), root.lower(), str(flags).lower()
    t = []
    if "габарит" in f or any(w in s for w in HEAVY):
        t.append("громоздкое / тяжёлое")
    if any(w in s or w in r for w in FOOD):
        t.append("продукты / корма (СГР, срок годности, вес)")
    if any(w in s for w in MEDICAL):
        t.append("медизделие / гигиена (РУ, ЧЗ)")
    return t
VOL_ASSUMED = 2.0


def subjects() -> dict[int, dict]:
    rows = {}
    for pat in ("jul2026_rev15m", "jul2026"):              # jul2026 — полный список, перекрывает
        for f in glob.glob(str(ROOT / f"data/raw/saleflow/2026-10-11/all/{pat}/page_*.json")):
            for r in json.load(open(f, encoding="utf-8"))["data"]:
                rows[r["id"]] = r
    return rows


def classify(m: dict, traps: list[str], margin15: float | None) -> tuple[str, list[str]]:
    miss = []
    if m["rev"] < TH["rev"]:
        miss.append(f"выручка {m['rev'] / 1e6:.1f} млн < 5")
    if m["sellers"] < TH["sellers"]:
        miss.append(f"продавцов с продажами {m['sellers']} < 30")
    if m["per_seller"] < TH["per_seller"]:
        miss.append(f"продаж на продавца {m['per_seller']} < 30")
    if m["buyout"] < TH["buyout"]:
        miss.append(f"выкуп {m['buyout']} % < 60")
    if (m["price"] or 0) > TH["price_max"]:
        miss.append(f"медиана {m['price']} ₽ > 7 000")
    elif (m["price"] or 0) < TH["price_premium"]:
        miss.append(f"дёшево (медиана {m['price']} ₽) — нужен премиум-сегмент")
    elif margin15 is None:
        miss.append("нет комиссии кабинета — экономика не посчитана")
    elif margin15 < TH["margin15"]:
        miss.append(f"маржа при ДРР 15 % {margin15} % < 10")
    if traps:
        return "ЛОВУШКА", traps + miss
    return ("ХОРОШАЯ" if not miss else "ПОГРАНИЧНАЯ" if len(miss) == 1 else "СЛАБАЯ"), miss


def econ15(sid: int, buyer: float, sw) -> tuple[float | None, int | None, bool]:
    com = sw.COM.get(sid)
    if not com or not buyer:
        return None, None, False
    seller, spp = sw.seller_for(sid, buyer)
    spp_assumed = seller is None
    if spp_assumed:
        spp, seller = DEFAULT_SPP, round(buyer / (1 - DEFAULT_SPP / 100))
    nc = sw.NC.get(sid) or {}
    vol = nc.get("vol") or VOL_ASSUMED
    kg = nc.get("kg") or max(0.1, 0.22 * vol)
    buyout = 80
    e = sw.econ(seller, buyer * 0.11 / sw.CNY, vol, kg, com, buyout, 15, 300)
    return e["net_margin_pct"], spp, spp_assumed


def main() -> None:
    from src import screen_white as sw
    from src.niche_pool import tags
    req = {r["id"]: r for r in json.load(open(sorted(glob.glob(str(ROOT / "data/processed/niche_requirements_2[0-9][0-9][0-9]-*.json")))[-1], encoding="utf-8"))}
    pool_f = sorted(glob.glob(str(ROOT / "data/processed/niche_pool_2*.json")))
    pool = {p["id"]: p for p in json.load(open(pool_f[-1], encoding="utf-8"))} if pool_f else {}
    from src.datastore import products
    raw = subjects()
    out, excluded = [], 0
    for sid, r in raw.items():
        q = req.get(sid, {})
        root = q.get("root") or r["name"].split(" / ")[0]
        if any(w in root.lower() for w in CLOTH) or "магнит" in str(q.get("flags")).lower():
            excluded += 1
            continue
        sellers = r.get("sellers_with_sells") or 0
        m = {"rev": (r.get("revenue_purchase_after_return") or 0), "sellers": sellers,
             "per_seller": round((r.get("sales") or 0) / sellers) if sellers else 0,
             "buyout": r.get("purchase_after_return") or 0, "price": r.get("median_price_final_with_sells")}
        subj = q.get("subject") or r["name"].split(" / ")[-1]
        tr = tags({"subj": subj, "vol_assumed": True, "vol": 0}) + extra_traps(subj, root, q.get("flags"))
        tr = list(dict.fromkeys(tr))
        margin15, spp, spp_assumed = econ15(sid, m["price"], sw) if m["price"] and m["price"] >= TH["price_premium"] else (None, None, False)
        status, why = classify(m, tr, margin15)
        has_products = bool(products(sid, "2026-07")[0] or [])
        p = pool.get(sid)
        if p and p["status"] == "КАНДИДАТ":
            todo = "живая выдача + жалобы + ¥ 1688 (кандидат копилки)"
        elif status in ("ХОРОШАЯ", "ПОГРАНИЧНАЯ") and not has_products:
            todo = "скачать товары (1 запрос) → копилка"
        elif status in ("ХОРОШАЯ", "ПОГРАНИЧНАЯ"):
            todo = "сегменты в копилке" + (f": {p['status']} {p['band']}" if p else " — не прошли отбор сегментов")
        else:
            todo = "—"
        out.append({"id": sid, "subject": subj, "root": root, "status": status, "why": why,
                    "rev_mln": round(m["rev"] / 1e6, 1), "sales": r.get("sales"), "sellers": sellers, "per_seller": m["per_seller"],
                    "price": m["price"], "buyout": m["buyout"], "turnover": r.get("turnover_in_days"),
                    "lost_pct": r.get("lost_profit_percent"), "new_items_pct": round((r.get("items_new") or 0) / (r.get("items") or 1) * 100, 1),
                    "season": r.get("seasonality_level"), "margin15": margin15, "spp": spp, "spp_assumed": spp_assumed,
                    "docs": (q.get("verdict") or "")[:2], "flags": q.get("flags"), "has_products": has_products,
                    "pool": p["status"] if p else None, "todo": todo})
    order = {"ХОРОШАЯ": 0, "ПОГРАНИЧНАЯ": 1, "СЛАБАЯ": 2, "ЛОВУШКА": 3}
    out.sort(key=lambda x: (order[x["status"]], -x["rev_mln"]))
    today = dt.date.today()
    json.dump(out, open(ROOT / f"data/processed/niche_master_{today}.json", "w", encoding="utf-8"), ensure_ascii=False)
    queue = [x for x in out if x["status"] in ("ХОРОШАЯ", "ПОГРАНИЧНАЯ") and not x["has_products"]]
    json.dump(queue, open(ROOT / f"data/processed/niche_collect_queue_{today}.json", "w", encoding="utf-8"), ensure_ascii=False)
    cnt = {s: sum(x["status"] == s for x in out) for s in order}
    lines = [f"# Все ниши WB — мастер-список ({today})", "",
             f"Просмотрено **{len(out)}** ниш из {len(raw)} (исключено одежда/обувь/бельё/магниты: {excluded}). "
             f"ХОРОШАЯ {cnt['ХОРОШАЯ']} · ПОГРАНИЧНАЯ {cnt['ПОГРАНИЧНАЯ']} · СЛАБАЯ {cnt['СЛАБАЯ']} · ЛОВУШКА {cnt['ЛОВУШКА']}. "
             f"Очередь на скачивание товаров (хорошие/пограничные без данных): **{len(queue)}** → ≈ {len(queue)} запросов Saleflow.", "",
             "Источник: Saleflow, все предметы, июль 2026 (предварительно: данным > 30 дней). Пороги: выручка ≥ 5 млн ₽/мес, "
             "продавцов с продажами ≥ 30, продаж на продавца ≥ 30 шт/мес, выкуп ≥ 60 %, медиана ≤ 7 000 ₽, маржа ДРР 15 % ≥ 10 % "
             "(¥ = 11 % цены, объём 2 л — допущения; СПП Evirma или 18 %). Ниши с медианой < 700 ₽ — «нужен премиум-сегмент».", ""]
    for st in order:
        rows = [x for x in out if x["status"] == st]
        lines += [f"## {st} ({len(rows)})", "",
                  "| id | Ниша | Выручка, млн ₽ | Продавцов | Продаж/продавца | Медиана | Выкуп | Маржа ДРР15 | Док. | Копилка | Причина / что сделать |",
                  "|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|"]
        for x in rows:
            why = "; ".join(x["why"]) or "все пороги"
            lines.append(f"| {x['id']} | {x['subject']} | {x['rev_mln']} | {x['sellers']} | {x['per_seller']} | {x['price']} ₽ | "
                         f"{x['buyout']} % | {x['margin15'] if x['margin15'] is not None else '—'} | {x['docs']} | {x['pool'] or '—'} | "
                         f"{why} → {x['todo']} |")
        lines.append("")
    lines += ["Следующий шаг: новый токен Saleflow → скачать товары по очереди → `python -m src.screen_white --all` → "
              "`python -m src.niche_pool` → `python -m src.niche_all` (статусы обновятся)."]
    (ROOT / f"reports/niche_master_{today}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"ниш {len(out)} (исключено {excluded}): {cnt}; очередь скачивания {len(queue)} → reports/niche_master_{today}.md")
    for x in [x for x in out if x["status"] == "ХОРОШАЯ"][:40]:
        print(f"  {x['id']:>5} {x['subject'][:30]:<30} {x['rev_mln']:>7} млн  продавцов {x['sellers']:>5}  на продавца {x['per_seller']:>4}  "
              f"{x['price']:>5} ₽  маржа {x['margin15']}  {x['docs']}  копилка {x['pool'] or '—'}")


if __name__ == "__main__":
    main()
