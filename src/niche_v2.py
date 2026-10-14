"""Поиск ниши v2 — «от новичков, а не от лидеров» под бюджет $2 000 (согласовано с пользователем 2026-10-14).

    python -m src.niche_v2 screen                 # блок 1 + часть блоков 2/3 по уже сохранённым данным (0 запросов)
    python -m src.niche_v2 collect [--dry-run]    # products500 июля для прошедших screen (1 запрос на нишу, кэш)
    python -m src.niche_v2 score                  # блоки 2–5 → data/processed/niche_v2_<дата>.json + reports/niche_v2_<дата>.xlsx

Вход: all_niches 2026-10-11 (prefilter keep = 243 ниши после фильтров сертификации/магнитов/батареек/жидкостей/габарита,
season, finalists = top-100 месяца пика с полем country). Пороги — THRESH ниже; ¥ 1688 пока не проверяется (Apify до 01.11).
Новичок = sku_first_date 2025-08-01 … 2026-05-31 (≥ 2 мес. к июлю). Уровень новичка = продажи июля / 31 / индекс сезона июля.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
TODAY = dt.date.today().isoformat()
A11 = "data/raw/saleflow/2026-10-11/all"
PREFILTER = "data/processed/all_niches_prefilter_2026-10-11.json"
SEASON = "data/processed/all_niches_season_2026-10-11.json"
FIN = f"{A11}/finalists"
RAW = f"data/raw/saleflow/{TODAY}/v2"
SCREEN_OUT = f"data/processed/niche_v2_screen_{TODAY}.json"
OUT = f"data/processed/niche_v2_{TODAY}.json"
XLSX = f"reports/niche_v2_{TODAY}.xlsx"
NEW = ("2025-08-01", "2026-05-31")
ORDER_MONTH = 11                     # заказ в ноябре → товар к январю; пик должен быть через 3–6 мес.
THRESH = {
    "china_min": 50,                 # % выручки top-100 с «Страна производства» = Китай
    "new_share_min": 25,             # % выручки top-100 у карточек моложе 12 мес.
    "top1_max": 25,
    "buyer_min": 900, "buyer_max": 2500,
    "newcomer_p50_min": 4.0,         # заказов/день без сезона в нашей ценовой полосе
    "vol_max": 1.0,
    "margin_min": 20, "roi_min": 70, "stress_margin_min": 15,
    "year_round_trough": 60,         # «круглый год», если худший месяц ≥ 60 % пика
    "payback_max_months": 6,
    "budget_rub": 167_000, "start_costs": 48_000, "reserve_pct": 20, "min_batch": 200,
}
SENS = r"магнит|magsafe|аккумулят|батаре|заряд|usb|led\b|светодиод|электр|жидк|спрей|масл|гель\b"
BRAND_COPY = r"trionda|mikasa|молтен|molten|adidas|nike|fifa|чемпионат мира|лиги чемпионов|евро ?2\d|premier league|flexi|tug\b"


def load(p):
    return json.load(open(p, encoding="utf-8"))


def rows(p):
    d = load(p)
    return d.get("data", d) if isinstance(d, dict) else d


def peak_ok(season: dict) -> tuple[bool, str]:
    idx = season["index"]
    trough = min(idx.values()) / max(idx.values()) * 100
    if trough >= THRESH["year_round_trough"]:
        return True, f"круглый год ({trough:.0f}%)"
    pk = int(season["peak_month"])
    lag = (pk - ORDER_MONTH) % 12
    return 3 <= lag <= 6, f"пик {pk:02d} через {lag} мес. после заказа"


# ── блок 1 (+2/3 по top-100 месяца пика) — 0 запросов ───────────────────────────────────────────────────────
def screen() -> list[dict]:
    keep = {r["id"]: r for r in load(PREFILTER)["keep"]}
    seas = {r["id"]: r for r in load(SEASON)}
    out = []
    for n, k in keep.items():
        f = f"{FIN}/products_{n}.json"
        s = seas.get(n)
        r = {"id": n, "name": k["name"], "median_price": k.get("median_price"), "buyout": k.get("buyout"), "fails": [], "notes": []}
        if not s or not os.path.exists(f):
            r["fails"].append("нет данных top-100")
            out.append(r)
            continue
        R = sorted(rows(f), key=lambda p: -(p.get("revenue") or 0))[:100]
        tot = sum(p.get("revenue") or 0 for p in R) or 1
        share = lambda cond: round(sum(p.get("revenue") or 0 for p in R if cond(p)) / tot * 100, 1)
        sellers = {}
        for p in R:
            sellers[p.get("seller")] = sellers.get(p.get("seller"), 0) + (p.get("revenue") or 0)
        r.update({
            "china_pct": share(lambda p: "кита" in str(p.get("country") or "").lower()),
            "country_known_pct": share(lambda p: bool(p.get("country"))),
            "new_share": share(lambda p: (p.get("sku_first_date") or "") >= "2025-01-01"),
            "top1_pct": round(max(sellers.values()) / tot * 100, 1),
            "top3_one_seller": len({p.get("seller") for p in R[:3]}) == 1,
            "sens_pct": share(lambda p: bool(re.search(SENS, p["name"].lower()))),
            "brand_copy_pct": share(lambda p: bool(re.search(BRAND_COPY, p["name"].lower()))),
            "buyer_med": round(st.median(p["revenue"] / p["sales"] for p in R if p.get("sales"))),
            "season": s["type"], "peak_month": s["peak_month"],
        })
        ok, why = peak_ok(s)
        r["timing"] = why
        T = THRESH
        if r["sens_pct"] > 20:
            r["fails"].append(f"чувств. груз {r['sens_pct']}%")
        if r["brand_copy_pct"] > 30:
            r["fails"].append(f"копии брендов {r['brand_copy_pct']}%")
        cn_known = r["china_pct"] / r["country_known_pct"] * 100 if r["country_known_pct"] >= 40 else 0   # пустая страна ≠ «не Китай»
        r["china_of_known_pct"] = round(cn_known, 1)
        if cn_known < T["china_min"]:
            r["fails"].append(f"Китай {r['china_pct']}% (среди указанных {cn_known:.0f}%) < {T['china_min']}")
        if r["new_share"] < T["new_share_min"]:
            r["fails"].append(f"новички {r['new_share']}% < {T['new_share_min']}")
        if r["top1_pct"] > T["top1_max"]:
            r["fails"].append(f"top-1 {r['top1_pct']}%")
        if r["top3_one_seller"]:
            r["fails"].append("top-3 у одного продавца")
        if not T["buyer_min"] <= r["buyer_med"] <= T["buyer_max"]:
            r["fails"].append(f"цена покупателя {r['buyer_med']} ₽ вне {T['buyer_min']}–{T['buyer_max']}")
        if not ok:
            r["fails"].append(f"тайминг: {why}")
        out.append(r)
    json.dump(out, open(SCREEN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    passed = [r for r in out if not r["fails"]]
    print(f"screen: {len(out)} ниш, прошли {len(passed)} → {SCREEN_OUT}")
    from collections import Counter
    c = Counter(re.sub(r"[\d.,%₽ ]+.*", "", x["fails"][0]).strip() if x["fails"] else "OK" for x in out)
    print("первый провал:", c.most_common())
    for r in sorted(passed, key=lambda r: -r["new_share"]):
        print(f"  {r['id']} {r['name'][:48]} | Китай {r['china_pct']}% | новички {r['new_share']}% | top-1 {r['top1_pct']}% | "
              f"{r['buyer_med']} ₽ | {r['timing']}")
    return out


def products500_path(n: int) -> str | None:
    from src.datastore import latest
    p = f"{RAW}/products500_{n}_2026-07.json"
    return p if os.path.exists(p) else latest(n, "products500")


def collect(dry: bool) -> None:
    S = [r for r in load(SCREEN_OUT) if not r["fails"]]
    todo = [r["id"] for r in S if not products500_path(r["id"])]
    print(f"products500 нужно скачать: {len(todo)} (= запросов Saleflow); уже есть: {len(S) - len(todo)}")
    if dry or not todo:
        return
    from src.strategy_collect import Client, fetch, quota
    os.makedirs(RAW, exist_ok=True)
    c, streak = Client(), 0
    try:
        print("квота до:", quota(c))
        for n in todo:
            try:
                res = fetch(c, "wb_subject", {"subject_id": n, "report": "products", "d1": "2026-07-01", "d2": "2026-07-31", "limit": 500})
                json.dump(res, open(f"{RAW}/products500_{n}_2026-07.json", "w", encoding="utf-8"), ensure_ascii=False)
                print("ok", n)
                streak = 0
            except Exception as e:                       # noqa: BLE001 — upstream Saleflow нестабилен
                print("fail", n, str(e)[:100])
                streak += 1
                if streak >= 3:
                    print("3 сбоя подряд — стоп")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()


# ── блоки 2–5 ───────────────────────────────────────────────────────────────────────────────────────────────
def econ_row(price: float, yuan: float, commission: float, buyout: float) -> dict:
    from src import strategy as S
    from src.deep_pair import fbs_config
    base = S.load_config
    S.load_config = lambda: fbs_config(base())
    try:
        e = S.econ(None, {"price": price, "yuan": yuan, "vol": 0.9, "kg": 0.4, "buyout": buyout, "commission": commission,
                          "buyer_price": price * 0.9})
    finally:
        S.load_config = base
    return e


def score() -> None:
    from src.dna_rank import commissions
    com = commissions()
    seas = {r["id"]: r for r in load(SEASON)}
    T = THRESH
    out = []
    for r in [x for x in load(SCREEN_OUT) if not x["fails"]]:
        p = products500_path(r["id"])
        if not p:
            r["fails"].append("нет products500 (collect)")
            out.append(r)
            continue
        R = [x for x in rows(p) if x.get("sales")]
        k_jul = seas[r["id"]]["index"]["07"] / 100
        band = (r["buyer_med"] * 0.8, r["buyer_med"] * 1.25)
        new = [x for x in R if NEW[0] <= (x.get("sku_first_date") or "") <= NEW[1]]
        lvl = sorted(x["sales"] / 31 / k_jul for x in new if band[0] <= x["revenue"] / x["sales"] <= band[1])
        q = lambda a: round(lvl[min(len(lvl) - 1, int(round(a * (len(lvl) - 1))))], 1) if lvl else None
        winners = sorted([x for x in new if x["sales"] / 31 / k_jul >= 5], key=lambda x: -x["sales"])
        seller_price = st.median(x["final_price"] for x in R if x.get("final_price"))
        commission = com.get(r["id"]) or 21.0
        buyout = r.get("buyout") or 75.0
        e = econ_row(seller_price, 15.0, commission, buyout)          # ¥15 — опорная точка до проверки 1688
        b, s15 = e["база ДРР 15%"], e["цена −15%"]
        units_budget = (T["budget_rub"] * (1 - T["reserve_pct"] / 100) - T["start_costs"])
        max_cost_for_batch = units_budget / T["min_batch"]
        yuan_cap = min(e["max_yuan"], round((max_cost_for_batch - 83) / 17, 1))
        p50 = q(0.5)
        monthly = (p50 or 0) * 30 * buyout / 100 * b["net_profit"] - 10_000
        invest = T["budget_rub"] * (1 - T["reserve_pct"] / 100)
        r.update({"newcomers_in_band": len(lvl), "nc_p25": q(0.25), "nc_p50": p50, "nc_p75": q(0.75),
                  "newcomer_winners": [{"id": x["id"], "name": x["name"][:60], "start": x.get("sku_first_date", "")[:10],
                                        "per_day": round(x["sales"] / 31 / k_jul, 1), "buyer": round(x["revenue"] / x["sales"]),
                                        "seller": x.get("seller")} for x in winners[:8]],
                  "seller_price_med": seller_price, "commission": commission, "margin_y15": b["net_margin_pct"],
                  "roi_y15": b["roi_on_goods_pct"], "stress_margin_y15": s15["net_margin_pct"], "yuan_cap": yuan_cap,
                  "profit_unit_y15": round(b["net_profit"]), "monthly_profit_p50": round(monthly),
                  "payback_months_p50": round(invest / monthly, 1) if monthly > 0 else None})
        if (p50 or 0) < T["newcomer_p50_min"]:
            r["fails"].append(f"новичок P50 {p50}/день < {T['newcomer_p50_min']}")
        if b["net_margin_pct"] < T["margin_min"] or b["roi_on_goods_pct"] < T["roi_min"]:
            r["fails"].append(f"маржа/ROI при ¥15: {b['net_margin_pct']}/{b['roi_on_goods_pct']}")
        if s15["net_margin_pct"] < T["stress_margin_min"]:
            r["fails"].append(f"цена −15%: маржа {s15['net_margin_pct']}")
        if r["payback_months_p50"] is None or r["payback_months_p50"] > T["payback_max_months"]:
            r["fails"].append(f"окупаемость P50 {r['payback_months_p50']} мес.")
        out.append(r)
    out.sort(key=lambda r: (len(r["fails"]), -(r.get("nc_p50") or 0)))
    json.dump({"thresholds": THRESH, "order_month": ORDER_MONTH, "rows": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_xlsx(out)
    for r in out:
        print(f"{'✅' if not r['fails'] else '❌'} {r['id']} {r['name'][:44]} | новичок P25/P50/P75 {r.get('nc_p25')}/{r.get('nc_p50')}/"
              f"{r.get('nc_p75')} (n={r.get('newcomers_in_band')}) | {r.get('seller_price_med')} ₽ | маржа¥15 {r.get('margin_y15')} | "
              f"¥max {r.get('yuan_cap')} | окуп. {r.get('payback_months_p50')} | {r['fails']}")
    print("→", OUT, XLSX)


def write_xlsx(out: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "v2"
    cols = ["id", "name", "china_pct", "new_share", "top1_pct", "buyer_med", "timing", "newcomers_in_band", "nc_p25", "nc_p50",
            "nc_p75", "seller_price_med", "commission", "margin_y15", "roi_y15", "stress_margin_y15", "yuan_cap",
            "monthly_profit_p50", "payback_months_p50", "fails"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496")
    for r in out:
        ws.append([("; ".join(r.get(k) or []) if k == "fails" else r.get(k)) for k in cols])
    ws2 = wb.create_sheet("новички-победители")
    ws2.append(["ниша", "артикул", "название", "старт", "шт/день (без сезона)", "цена покуп.", "продавец"])
    for r in out:
        for w in r.get("newcomer_winners", []):
            ws2.append([r["id"], w["id"], w["name"], w["start"], w["per_day"], w["buyer"], w["seller"]])
    wb.save(XLSX)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["screen", "collect", "score"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    {"screen": screen, "score": score}.get(a.cmd, lambda: collect(a.dry_run))()


if __name__ == "__main__":
    main()
