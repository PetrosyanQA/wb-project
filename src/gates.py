"""ԴԱՐՊԱՍՆԵՐ — ֆիլտրերը դասավորված ըստ ԱՐԺԵՔԻ, ոչ թե ըստ հարմարության.

    regulatory  →  economics  →  concentration  →  yoy_peak  →  profile  →  audit
       0 հարց.      0 հարց.         1 հարց.         1 հարց.      0 հարց.     4+

Առաջին ՉԱՆՑԱԾ դարպասը կանգնեցնում է շղթան։ Նիշան, որը պետք է «Честный знак»,
դուրս է մնում ԱՌԱՆՑ մեկ API հարցման։ Հինը հակառակն էր անում՝ նախ քաշում էր 500 քարտ,
հետո պարզվում, որ ապրանքը մարկավորման ենթակա է։

    python -m src.gates --demo
    python -m src.gates --path "Дом/Хранение вещей" --volume 0.8
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

from .fields import fnum, median, parse_date, pick
from .unit_econ import load_config as load_econ, unit_economics, wb_logistics

ROOT = Path(__file__).resolve().parents[1]
FILTERS = ROOT / "config" / "filters.yaml"

PASS, FAIL, WARN, UNKNOWN = "PASS", "FAIL", "WARN", "UNKNOWN"
MARK = {PASS: "✅", FAIL: "❌", WARN: "🟡", UNKNOWN: "⚪️"}


def load_filters(path: Path | str = FILTERS) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


@dataclass
class GateResult:
    name: str
    status: str
    message: str
    cost: int = 0
    details: dict = field(default_factory=dict)


# ───────────────────────────────────────────────────── համատեքստ (ծույլ բեռնում)
class NicheCtx:
    """Տվյալները քաշվում են ՄԻԱՅՆ երբ տվյալ դարպասին պետք են."""

    def __init__(self, path: str, client=None, aggregate: dict | None = None,
                 volume_l: float | None = None, demo: dict | None = None,
                 days: int = 30):
        self.path = path
        self.client = client
        self.aggregate = aggregate or {}
        self.volume_l = volume_l
        self.demo = demo or {}
        self.days = days
        self.api_calls = 0
        self._top20: list[dict] | None = None
        self._series: list[dict] | None = None

    def _period(self, days: int) -> tuple[str, str]:
        today = date.today()
        return str(today - timedelta(days=days)), str(today - timedelta(days=1))

    def top20(self) -> list[dict]:
        if self._top20 is None:
            if "top20" in self.demo:
                self._top20 = self.demo["top20"]
            else:
                from .mpstats_client import rows
                d1, d2 = self._period(self.days)
                self._top20 = rows(self.client.category_report(
                    self.path, "items", d1, d2, limit=20))
                self.api_calls += 1
        return self._top20

    def series(self) -> list[dict]:
        """400 օր = 1 հարցում (500 տողի cap-ի ներսում) → բավական է YoY-ի համար."""
        if self._series is None:
            if "series" in self.demo:
                self._series = self.demo["series"]
            else:
                from .mpstats_client import rows
                d1, d2 = self._period(400)
                self._series = rows(self.client.category_report(
                    self.path, "by_date", d1, d2, limit=420, sort_by=None))
                self.api_calls += 1
        return self._series


# ─────────────────────────────────────────────────────────────── 1. ԿԱՐԳԱՎՈՐՈՒՄ
def gate_regulatory(ctx: NicheCtx, f: dict) -> GateResult:
    cfg = f["regulatory"]
    text = f"{ctx.path} {ctx.aggregate.get('subject', '')}".lower()

    hits = [w for w in cfg["hard_exclude_keywords"] if w in text]
    if hits:
        return GateResult("regulatory", FAIL, f"արգելված կատեգորիա ({', '.join(hits)})")

    marking = [w for w in cfg["marking_keywords"] if w in text]
    if marking and not cfg.get("allow_marking"):
        return GateResult("regulatory", FAIL,
                          f"«Честный знак» պարտադիր է ({marking[0]}) → +ծախս, +ռիսկ նորեկի համար",
                          details={"keywords": marking})

    cert = [w for w in cfg["certification_keywords"] if w in text]
    if cert and not cfg.get("allow_certification"):
        return GateResult("regulatory", FAIL,
                          f"պահանջվում է սերտիֆիկատ/դեկլարացիա ({cert[0]})",
                          details={"keywords": cert})

    return GateResult("regulatory", PASS, "մարկավորում և սերտիֆիկացում չեն պահանջվում")


# ─────────────────────────────────────────────────────────────── 2. ՏՆՏԵՍՈՒԹՅՈՒՆ
def gate_economics(ctx: NicheCtx, f: dict) -> GateResult:
    cfg = f["economics"]
    price = float(ctx.aggregate.get("avg_price") or 0)
    if price <= 0:
        return GateResult("economics", UNKNOWN, "գինը հայտնի չէ ագրեգատից")

    if not (cfg["price_min_rub"] <= price <= cfg["price_max_rub"]):
        return GateResult("economics", FAIL,
                          f"միջին գին {price:,.0f} ₽ դուրս է "
                          f"{cfg['price_min_rub']}–{cfg['price_max_rub']} ₽ միջանցքից")

    volume = ctx.volume_l if ctx.volume_l is not None else float(cfg["volume_liters_max"])
    if volume > cfg["volume_liters_max"]:
        return GateResult("economics", FAIL,
                          f"ծավալ {volume} լ > {cfg['volume_liters_max']} լ → լոգիստիկան ուտում է մարժան")

    econ_cfg = load_econ()
    ship = wb_logistics(volume, econ_cfg)
    storage_30d = volume * float(econ_cfg["operations"].get("storage_rub_per_liter_day", 0.08)) * 30
    share = (ship + storage_30d) / price
    if share > cfg["logistics_share_max"]:
        return GateResult("economics", FAIL,
                          f"լոգիստիկա+պահեստավորում = {share*100:.1f}% գնից "
                          f"(սահմանը {cfg['logistics_share_max']*100:.0f}%)",
                          details={"logistics_rub": round(ship), "storage_rub": round(storage_30d)})

    cost = price * float(cfg["assumed_cost_share"])
    econ = unit_economics(price, cost, volume, econ_cfg)
    breakeven = econ["breakeven_price"]
    limit = price * (1 - float(cfg["breakeven_margin_min"]))
    if cfg.get("breakeven_below_median") and breakeven > limit:
        return GateResult("economics", FAIL,
                          f"break-even {breakeven:,.0f} ₽ չափազանց մոտ է մեդիան գնին "
                          f"{price:,.0f} ₽ (պետք է ≤ {limit:,.0f} ₽)",
                          details=econ)

    units = int(cfg["budget_usd"] * float(econ_cfg.get("budget", {}).get("goods_share", 0.55))
                * cfg["fx_rub_per_usd"] / max(cost, 1))
    if units < cfg["min_first_batch_units"]:
        return GateResult("economics", FAIL,
                          f"բյուջեով հերիքում է ընդամենը {units} միավոր "
                          f"(նվազագույնը {cfg['min_first_batch_units']})")

    return GateResult("economics", PASS,
                      f"գին {price:,.0f} ₽, լոգիստիկա {share*100:.0f}%, "
                      f"break-even {breakeven:,.0f} ₽, խմբաքանակ ~{units} հատ",
                      details={"units": units, "breakeven": breakeven, "margin_pct": econ["net_margin_pct"]})


# ────────────────────────────────────────────────────────────── 3. ԿՈՆՑԵՆՏՐԱՑԻԱ
def gate_concentration(ctx: NicheCtx, f: dict) -> GateResult:
    cfg = f["concentration"]
    top = ctx.top20()
    if not top:
        return GateResult("concentration", UNKNOWN, "տոպ-20 չի ստացվել", cost=1)

    ranked = sorted(top, key=lambda r: fnum(r, "revenue"), reverse=True)
    total = float(ctx.aggregate.get("revenue") or sum(fnum(r, "revenue") for r in ranked))
    top10 = sum(fnum(r, "revenue") for r in ranked[:10]) / total * 100 if total else 0

    sellers: dict[str, float] = {}
    brands_top10: dict[str, int] = {}
    for i, row in enumerate(ranked):
        sellers[str(pick(row, "seller", "—"))] = sellers.get(str(pick(row, "seller", "—")), 0) + fnum(row, "revenue")
        if i < 10:
            b = str(pick(row, "brand", "—"))
            brands_top10[b] = brands_top10.get(b, 0) + 1
    top1 = max(sellers.values()) / total * 100 if total and sellers else 0
    details = {"top10_share": round(top10, 1), "top1_seller_share": round(top1, 1),
               "sellers_in_top20": len(sellers),
               "max_brand_cards_top10": max(brands_top10.values()) if brands_top10 else 0}

    if top10 > cfg["top10_share_max"]:
        return GateResult("concentration", FAIL,
                          f"տոպ-10 = {top10:.0f}% (սահմանը {cfg['top10_share_max']:.0f}%)",
                          cost=1, details=details)
    if top1 > cfg["top1_seller_share_max"]:
        return GateResult("concentration", FAIL,
                          f"մեկ վաճառող = {top1:.0f}% (սահմանը {cfg['top1_seller_share_max']:.0f}%)",
                          cost=1, details=details)
    if len(sellers) < cfg["min_sellers_in_top20"]:
        return GateResult("concentration", FAIL,
                          f"տոպ-20-ում ընդամենը {len(sellers)} վաճառող", cost=1, details=details)
    if details["max_brand_cards_top10"] > cfg["max_one_brand_cards_in_top10"]:
        return GateResult("concentration", WARN,
                          f"մեկ բրենդ զբաղեցնում է տոպ-10-ի {details['max_brand_cards_top10']} տեղ",
                          cost=1, details=details)

    return GateResult("concentration", PASS,
                      f"տոպ-10 {top10:.0f}%, տոպ-1 {top1:.0f}%, {len(sellers)} վաճառող",
                      cost=1, details=details)


# ──────────────────────────────────────────────── 4. ՏԱՐԵԿԱՆ ԴԻՆԱՄԻԿԱ ՊԻԿ ԱՄՍՈՎ
def monthly_series(series: list[dict], drop_partial: bool = True) -> dict[str, float]:
    """Ամսական գումարներ։ Թերի ամիսները (շարքի սկիզբ/վերջ) դուրս են նետվում —
    առանց դրա վերջին կիսատ ամիսը կեղծ «անկում» է ցույց տալիս."""
    totals: dict[str, float] = {}
    days: dict[str, set] = {}
    for row in series:
        d = parse_date(pick(row, "date"))
        if not d:
            continue
        key = f"{d.year}-{d.month:02d}"
        totals[key] = totals.get(key, 0.0) + fnum(row, "revenue")
        days.setdefault(key, set()).add(d.day)
    if drop_partial:
        totals = {k: v for k, v in totals.items() if len(days[k]) >= 25}
    return totals


def yoy_peak(series: list[dict]) -> dict:
    """Համեմատում է ՊԻԿ ամիսը տարվա կտրվածքով, ոչ թե պատահական 30 օրը."""
    months = monthly_series(series)
    if len(months) < 13:
        return {"ok": False, "months": len(months), "reason": "short"}
    keys = sorted(months)
    # պիկը ընտրում ենք ՄԻԱՅՆ այն ամիսներից, որոնք ունեն տարի առաջվա զույգ
    pairs = [(k, f"{int(k[:4])-1}-{k[5:]}") for k in keys[-12:]]
    pairs = [(cur, prev) for cur, prev in pairs if prev in months]
    if not pairs:
        return {"ok": False, "months": len(months), "reason": "no_pair"}
    peak, prev_key = max(pairs, key=lambda kv: months[kv[0]])
    cur, prev = months[peak], months[prev_key]
    return {"ok": True, "peak_month": peak, "prev_month": prev_key,
            "peak_revenue": round(cur), "prev_revenue": round(prev),
            "yoy_pct": round((cur - prev) / prev * 100, 1) if prev else None,
            "months": len(months)}


def gate_yoy_peak(ctx: NicheCtx, f: dict) -> GateResult:
    cfg = f["yoy_peak"]
    res = yoy_peak(ctx.series())
    if not res.get("ok"):
        why = ("պատմությունը կարճ է" if res.get("reason") == "short"
               else "չկա տարի առաջվա նույն ամիսը")
        return GateResult("yoy_peak", UNKNOWN,
                          f"{why} ({res.get('months', 0)} լրիվ ամիս)", cost=1)
    yoy = res["yoy_pct"]
    if yoy is None:
        return GateResult("yoy_peak", UNKNOWN, "չհաշվվեց", cost=1, details=res)
    if yoy < cfg["min_yoy_pct"]:
        return GateResult("yoy_peak", FAIL,
                          f"պիկ ամիսը ({res['peak_month']}) տարվա կտրվածքով {yoy:+.0f}% → նիշան ընկնում է",
                          cost=1, details=res)
    if yoy > cfg["explosive_yoy_pct"]:
        return GateResult("yoy_peak", WARN,
                          f"պայթուցիկ աճ {yoy:+.0f}% — սովորաբար պահում է մեկ վաղ խաղացող, "
                          f"$2000-ով դեմ գնալը ռիսկային է", cost=1, details=res)
    return GateResult("yoy_peak", PASS,
                      f"պիկ {res['peak_month']}՝ {yoy:+.0f}% տարվա կտրվածքով", cost=1, details=res)


# ───────────────────────────────────────────────────────────────── 5. ՊՐՈՖԻԼ
def trend_slope_pct_month(series: list[dict]) -> float | None:
    months = monthly_series(series)
    keys = sorted(months)[-12:]
    values = [months[k] for k in keys if months[k] > 0]
    if len(values) < 6:
        return None
    import math
    n = len(values)
    xs = list(range(n))
    ys = [math.log(v) for v in values]
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return round((math.exp(slope) - 1) * 100, 1)


def gate_profile(ctx: NicheCtx, f: dict) -> GateResult:
    cfg = f["profile"]
    top = ctx.top20()
    slope = trend_slope_pct_month(ctx.series())
    ratings = [fnum(r, "rating") for r in top if fnum(r, "rating") > 0]
    rating_med = median(ratings) if ratings else 0
    sellers = len({str(pick(r, "seller", "—")) for r in top})
    sellers_total = int(ctx.aggregate.get("sellers") or sellers)

    details = {"slope_pct_month": slope, "median_rating_top20": round(rating_med, 2),
               "sellers_total": sellers_total}
    notes = []

    if slope is None:
        notes.append("թեքությունը չհաշվվեց")
    elif slope < cfg["slope_min_pct_month"]:
        return GateResult("profile", FAIL, f"շուկան ընկնում է ({slope:+.1f}%/ամիս)", details=details)
    elif slope > cfg["slope_max_pct_month"]:
        notes.append(f"արագ աճ {slope:+.1f}%/ամիս — ստուգիր՝ մեկ խաղացո՞ղ է քաշում")
    else:
        notes.append(f"սարահարթ {slope:+.1f}%/ամիս ✅")

    if sellers_total < cfg["min_sellers_total"]:
        return GateResult("profile", FAIL,
                          f"ընդամենը {sellers_total} վաճառող — շուկան բաշխված չէ", details=details)
    notes.append(f"{sellers_total} վաճառող ✅")

    if rating_med and rating_med >= cfg["rating_ceiling"]:
        return GateResult("profile", FAIL,
                          f"տոպ-20-ի մեդիան ռեյտինգը {rating_med:.2f} ≥ {cfg['rating_ceiling']} — "
                          f"գնորդը գոհ է, բարելավելու տեղ չկա", details=details)
    notes.append(f"ռեյտինգ {rating_med:.2f} → կա բարելավման տեղ ✅")

    notes.append("բողոքի թեման դեռ չի ստուգված → հաջորդ քայլը՝ sku_audit կարծիքներով")
    return GateResult("profile", WARN if slope and slope > cfg["slope_max_pct_month"] else PASS,
                      "; ".join(notes), details=details)


def gate_audit(ctx: NicheCtx, f: dict) -> GateResult:
    cfg = f["audit"]
    return GateResult("audit", UNKNOWN,
                      f"հերթն է՝ {cfg['sku_per_niche']} SKU-ի աուդիտ + կարծիքների մայնինգ "
                      f"(≈{cfg['sku_per_niche'] * 4} հարցում)")


GATES: dict[str, Callable[[NicheCtx, dict], GateResult]] = {
    "regulatory": gate_regulatory, "economics": gate_economics,
    "concentration": gate_concentration, "yoy_peak": gate_yoy_peak,
    "profile": gate_profile, "audit": gate_audit,
}


def run_gates(ctx: NicheCtx, f: dict | None = None,
              stop_on_fail: bool = True) -> tuple[list[GateResult], str]:
    f = f or load_filters()
    results: list[GateResult] = []
    for name in f["gate_order"]:
        gate = GATES.get(name)
        if not gate:
            continue
        try:
            res = gate(ctx, f)
        except Exception as exc:                                  # noqa: BLE001
            res = GateResult(name, UNKNOWN, f"սխալ՝ {exc}")
        results.append(res)
        if res.status == FAIL and stop_on_fail:
            return results, f"❌ կանգնեց «{name}» դարպասի վրա"
    unknown = [r.name for r in results if r.status == UNKNOWN]
    if unknown:                                                    # [аудит 2026-11-02] нет данных ≠ «прошёл»
        return results, f"⏸ HOLD — нет данных / не выполнено: {', '.join(unknown)} (финальный PASS невозможен)"
    if any(r.status == WARN for r in results):
        return results, "🟡 անցավ, բայց զգուշացումներով"
    return results, "✅ անցավ բոլոր դարպասները"


def format_results(path: str, results: list[GateResult], verdict: str, api_calls: int) -> str:
    lines = [f"### `{path}` — {verdict}", "",
             "| # | Դարպաս | Արդյունք | API | Մեկնաբանություն |", "|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r.name} | {MARK[r.status]} {r.status} | {r.cost} | {r.message} |")
    lines += ["", f"_Ծախսվեց {api_calls} API հարցում_"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────── demo
def demo_niches() -> list[tuple[str, dict, dict]]:
    import random
    random.seed(7)

    def series(base: float, growth: float, season: list[float], months: int = 26) -> list[dict]:
        out = []
        today = date.today()
        for i in range(months * 30, 0, -1):
            d = today - timedelta(days=i)
            k = season[(d.month - 1) % 12]
            drift = (1 + growth / 100) ** ((months * 30 - i) / 30)
            out.append({"date": str(d), "revenue": base * k * drift * random.uniform(0.85, 1.15)})
        return out

    flat = [1.0, 0.95, 1.05, 1.0, 1.1, 1.0, 0.9, 0.95, 1.05, 1.1, 1.2, 1.15]
    return [
        ("Красота/Парфюмерия/Духи женские",
         {"avg_price": 1800, "revenue": 50_000_000, "sellers": 120}, {}),
        ("Дом/Кухня/Контейнеры пищевые",
         {"avg_price": 640, "revenue": 30_000_000, "sellers": 90}, {}),
        ("Дом/Хранение вещей/Органайзеры",
         {"avg_price": 1450, "revenue": 34_000_000, "sellers": 85},
         {"top20": [{"id": i, "name": f"Органайзер {i}", "revenue": 900_000 / (i + 2),
                     "seller": f"ООО-{i % 9}", "brand": f"BR{i % 7}", "rating": 4.6,
                     "comments": 180 + i * 7, "price": 1400 + i * 10} for i in range(20)],
          "series": series(95_000, 1.2, flat)}),
        ("Спорт/Термосы",
         {"avg_price": 1700, "revenue": 41_000_000, "sellers": 70},
         {"top20": [{"id": i, "name": f"Термос {i}", "revenue": 1_500_000 / (i + 1.4),
                     "seller": "ООО-Лидер" if i < 4 else f"ООО-{i % 6}",
                     "brand": f"TB{i % 5}", "rating": 4.5, "comments": 240 + i * 9,
                     "price": 1650 + i * 20} for i in range(20)],
          "series": series(120_000, 0.4, [0.8, 0.8, 0.9, 1.0, 1.1, 1.1, 1.0, 1.0, 1.2, 1.4, 1.6, 1.5])}),
    ]


def main() -> None:
    p = argparse.ArgumentParser(description="Ֆիլտրերի շարք՝ էժանից թանկ")
    p.add_argument("--path")
    p.add_argument("--volume", type=float, help="ապրանքի ծավալ, լ")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--all-gates", action="store_true", help="չկանգնել առաջին ձախողման վրա")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args()

    f = load_filters()
    blocks = []
    if args.demo:
        for path, agg, demo in demo_niches():
            ctx = NicheCtx(path, aggregate=agg, volume_l=args.volume, demo=demo)
            results, verdict = run_gates(ctx, f, stop_on_fail=not args.all_gates)
            blocks.append(format_results(path, results, verdict, ctx.api_calls))
    else:
        if not args.path:
            p.error("պետք է --path կամ --demo")
        from .mpstats_client import MpstatsClient, rows
        client = MpstatsClient()
        parent = args.path.rsplit("/", 1)[0] if "/" in args.path else args.path
        agg = {}
        try:
            from .discover import children_aggregates
            d1 = str(date.today() - timedelta(days=args.days))
            d2 = str(date.today() - timedelta(days=1))
            for row in children_aggregates(client, parent, d1, d2):
                if row["path"] == args.path:
                    agg = row
                    break
        except Exception as exc:                                  # noqa: BLE001
            print(f"[warn] ագրեգատը չստացվեց՝ {exc}")
        ctx = NicheCtx(args.path, client=client, aggregate=agg, volume_l=args.volume,
                       days=args.days)
        results, verdict = run_gates(ctx, f, stop_on_fail=not args.all_gates)
        blocks.append(format_results(args.path, results, verdict, ctx.api_calls))

    out = "\n\n".join(blocks)
    print(out)
    rep = ROOT / "reports" / f"gates_{date.today():%Y%m%d}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(f"# Դարպասների ստուգում — {date.today()}\n\n{out}\n", encoding="utf-8")
    print(f"\n✔ {rep}")


if __name__ == "__main__":
    main()
