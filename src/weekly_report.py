"""Еженедельная сводка по НАШЕЙ карточке + решение по таблице правил (marketing_strategy_777 §8, winners_playbook §6).

    python -m src.weekly_report                     # → reports/weekly/weekly_<дата>.md
    python -m src.weekly_report --ad-spend 9500     # расход на рекламу за неделю, если API Продвижения его не отдал

Источники: config/launch.yaml (артикулы, дата старта, цена), WB Seller API (заказы и продажи — Статистика,
1 запрос/мин), ledger/ (остаток → дни запаса), слежка за конкурентами (src.competitor_watch, если запускалась).
Пока карточки нет (nm_ids пуст) — честно пишет «нечего проверять» и не тратит запросы.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import sys

import yaml

sys.stdout.reconfigure(encoding="utf-8")
CFG = "config/launch.yaml"
OUT_DIR = "reports/weekly"


def wb_week(nm_ids: list[int], d_from: dt.date) -> dict:
    from src.wb_seller import WBSellerClient
    c = WBSellerClient(quiet=True)
    since30 = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    orders = [o for o in (c.orders(since30) or []) if (o.get("nmId") or o.get("nmID")) in nm_ids]
    sales = [s for s in (c.sales(since30) or []) if (s.get("nmId") or s.get("nmID")) in nm_ids]
    wk = [o for o in orders if str(o.get("date", ""))[:10] >= d_from.isoformat()]
    ok = [o for o in wk if not o.get("isCancel")]
    sold = [s for s in sales if str(s.get("saleID", "")).startswith("S")]
    ret = [s for s in sales if str(s.get("saleID", "")).startswith("R")]
    sold_wk = [s for s in sold if str(s.get("date", ""))[:10] >= d_from.isoformat()]
    ok30 = [o for o in orders if not o.get("isCancel") and str(o.get("date", ""))[:10] <= (dt.date.today() - dt.timedelta(days=10)).isoformat()]
    spp = [o.get("spp") for o in ok if o.get("spp") is not None]
    return {"orders_week": len(ok), "orders_day": round(len(ok) / 7, 2), "cancels_week": len(wk) - len(ok),
            "revenue_week_buyer": round(sum(o.get("finishedPrice") or 0 for o in ok)),
            "revenue_week_before_spp": round(sum(o.get("priceWithDisc") or 0 for o in ok)),
            "spp_med": sorted(spp)[len(spp) // 2] if spp else None,
            "sold_week": len(sold_wk), "returns_30d": len(ret),
            "buyout_30d_pct": round(len(sold) / len(ok30) * 100, 1) if ok30 else None}


def decide(day: int | None, m: dict, reviews: int | None, cover_days: int | None, drr: float | None, price: float) -> list[str]:
    R = []
    od = m.get("orders_day")
    if cover_days is not None and cover_days < 21:
        R.append(f"🔴 Остатка на {cover_days} дн. (< 21) → ДОЗАКАЗАТЬ НЕМЕДЛЕННО (дефектура = −22…−69% продаж)")
    if day is not None and 30 <= day <= 60 and od is not None:
        if od < 1.5:
            R.append(f"🔴 День {day}: {od} заказа/день < 1,5 → СТОП-критерий: новую партию не заказывать")
        elif od < 4:
            R.append(f"🟡 День {day}: {od} заказа/день (1,5–4) → держать цену, ДРР ≤ 25%, усилить GAP-запросы")
        else:
            R.append(f"🟢 День {day}: {od} заказа/день ≥ 4 → по плану")
    if od is not None and od >= 4 and (reviews or 0) >= 50 and price < 1417:
        R.append("🟢 ≥ 4 заказа/день и ≥ 50 отзывов → поднять цену до СПП до 1 417 ₽ (+10%), смотреть 14 дней")
    if od is not None and od >= 4 and (reviews or 0) >= 100 and 1417 <= price < 1591:
        R.append("🟢 ≥ 100 отзывов → цена до СПП 1 591 ₽")
    if drr is not None:
        cap = 25 if price < 1400 else 18 if price < 1550 else 15
        if drr > cap:
            R.append(f"🟡 ДРР {drr}% > плана {cap}% → снизить ставки в неэффективных запросах, рекламу НЕ выключать")
    if m.get("buyout_30d_pct") is not None and m["buyout_30d_pct"] < 75:
        R.append(f"🔴 Выкуп {m['buyout_30d_pct']}% < 75% → стоп-критерий; разобрать возвраты/отзывы")
    if m.get("spp_med") is not None and m["spp_med"] < 20:
        R.append(f"ℹ️ СПП упала до {m['spp_med']}% → покупатель видит цену выше; цену до СПП 7 дней не трогать")
    return R or ["✅ Отклонений от плана нет — ничего не меняем (цена раз в 7–14 дней, реклама без пауз)"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ad-spend", type=float)
    ap.add_argument("--reviews", type=int, help="число отзывов карточки сейчас")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
    today = dt.date.today()
    lines = [f"# Еженедельная сводка — {today}", ""]
    if not cfg.get("nm_ids"):
        msg = "Карточка ещё не создана (config/launch.yaml → nm_ids пуст) — проверять нечего. Слежка за конкурентами: `python -m src.competitor_watch`."
        print(msg)
        lines.append(msg)
    else:
        start = dt.date.fromisoformat(str(cfg["launch_date"])) if cfg.get("launch_date") else None
        day = (today - start).days if start else None
        m = wb_week([int(x) for x in cfg["nm_ids"]], today - dt.timedelta(days=7))
        spend = a.ad_spend if a.ad_spend is not None else cfg.get("ad_spend_week_rub")
        drr = round(spend / m["revenue_week_before_spp"] * 100, 1) if spend and m["revenue_week_before_spp"] else None
        from src.ledger import summary
        led = summary(m["orders_day"] or None)
        lines += ["| Показатель | Значение |", "|---|---|",
                  f"| День с запуска | {day if day is not None else '—'} |",
                  f"| Заказов за 7 дней / в день | {m['orders_week']} / {m['orders_day']} |",
                  f"| Отмены за 7 дней | {m['cancels_week']} |",
                  f"| Выручка за 7 дней, до СПП / покупатель | {m['revenue_week_before_spp']} / {m['revenue_week_buyer']} ₽ |",
                  f"| СПП (медиана) | {m['spp_med'] if m['spp_med'] is not None else '—'} % |",
                  f"| ДРР | {drr if drr is not None else '— (впишите расход: --ad-spend)'} % |",
                  f"| Выкуп за 30 дней | {m['buyout_30d_pct'] if m['buyout_30d_pct'] is not None else '— (мало данных)'} % |",
                  f"| Остаток / хватит на | {led.get('stock', '—')} шт / {led.get('cover_days', '—')} дн. |",
                  "", "## Решение", ""]
        lines += [f"- {r}" for r in decide(day, m, a.reviews, led.get("cover_days"), drr, float(cfg.get("price_before_spp") or 0))]
    comp = sorted(glob.glob("reports/weekly/competitors_*.md"))
    if comp:
        lines += ["", f"Конкуренты: см. `{comp[-1]}`"]
    lines += ["", "Источник: WB Seller API (Статистика), ledger/, config/launch.yaml. Правила — reports/marketing_strategy_777_2026-10-08.md §8."]
    os.makedirs(OUT_DIR, exist_ok=True)
    out = f"{OUT_DIR}/weekly_{today}.md"
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("→", out)


if __name__ == "__main__":
    main()
