"""Մրցակցի/ապրանքի խորը աուդիտ՝ քարտ, դինամիկա, բանալի բառեր, նմանատիպներ.

  python -m src.sku_audit --sku 12345678 --days 30
  python -m src.sku_audit --sku 12345678 --cost 350 --volume 0.6
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .fields import fnum, median, num, pick
from .mpstats_client import MpstatsClient, rows
from .unit_econ import load_config as load_econ_config, unit_economics

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def unwrap(payload) -> dict:
    if isinstance(payload, dict):
        for key in ("item", "data", "result"):
            if isinstance(payload.get(key), dict):
                return payload[key]
        return payload
    return {}


def audit(client: MpstatsClient, sku: str, d1: str, d2: str,
          cost: float | None, volume: float | None) -> str:
    card = unwrap(client.item(sku, "card", d1, d2))
    sales_rows = rows(client.item(sku, "sales", d1, d2))
    kw_rows = rows(client.item(sku, "keywords", d1, d2))
    similar_rows = rows(client.similar(sku, "items", "similar", d1, d2, limit=50))

    name = pick(card, "name", f"SKU {sku}")
    brand = pick(card, "brand", "—")
    seller = pick(card, "seller", "—")
    price = fnum(card, "price")
    rating = fnum(card, "rating")
    comments = fnum(card, "comments")
    balance = fnum(card, "balance")

    rev_series = [fnum(r, "revenue") for r in sales_rows]
    sales_series = [fnum(r, "sales") for r in sales_rows]
    days_with_sales = sum(1 for v in sales_series if v > 0)
    revenue_period = sum(rev_series)
    sales_period = sum(sales_series)

    lines = [f"# SKU {sku} — {name}", "",
             f"- Բրենդ / վաճառող՝ **{brand}** / **{seller}**",
             f"- Գին՝ **{price:,.0f} ₽** | ռեյտինգ՝ {rating} | կարծիքներ՝ {comments:,.0f}",
             f"- Ընթացիկ մնացորդ՝ {balance:,.0f} հատ",
             f"- Ժամանակահատված {d1} … {d2}՝ **{revenue_period:,.0f} ₽**, {sales_period:,.0f} վաճառք, "
             f"{days_with_sales} օր վաճառքով"]
    if sales_series:
        half = len(sales_series) // 2 or 1
        first, second = sum(sales_series[:half]), sum(sales_series[half:])
        trend = "📈 աճ" if second > first * 1.1 else "📉 անկում" if second < first * 0.9 else "➡️ կայուն"
        lines.append(f"- Դինամիկա (2-րդ կես vs 1-ին)՝ {trend} ({first:,.0f} → {second:,.0f} հատ)")
        if balance and sales_period:
            lines.append(f"- Օրական միջին վաճառք՝ {sales_period / max(len(sales_series), 1):,.1f} հատ "
                         f"| պաշարը բավարարում է ~{balance / max(sales_period / max(len(sales_series),1), 0.1):,.0f} օր")

    if kw_rows:
        lines += ["", "## Տոպ բանալի բառեր (SEO հիմք)", "",
                  "| Հարցում | Հաճախականություն | Դիրք |", "|---|---|---|"]
        def kw_freq(r): return fnum(r, "count") or num(r.get("frequency")) or num(r.get("total"))
        for row in sorted(kw_rows, key=kw_freq, reverse=True)[:20]:
            kw = pick(row, "keyword") or row.get("word") or row.get("name") or "—"
            lines.append(f"| {kw} | {kw_freq(row):,.0f} | {num(row.get('position')) or '—'} |")

    if similar_rows:
        comp = sorted(similar_rows, key=lambda r: fnum(r, "revenue"), reverse=True)[:12]
        lines += ["", "## Մրցակիցներ (similar)", "",
                  "| SKU | Անուն | Գին ₽ | Շրջ. ₽ | Վաճառք | Կարծիք | Ռեյտ. |", "|---|---|---|---|---|---|---|"]
        for row in comp:
            lines.append(
                f"| {pick(row,'id','—')} | {str(pick(row,'name','—'))[:42]} | {fnum(row,'price'):,.0f} | "
                f"{fnum(row,'revenue'):,.0f} | {fnum(row,'sales'):,.0f} | {fnum(row,'comments'):,.0f} | "
                f"{fnum(row,'rating')} |")
        revs = [fnum(r, "revenue") for r in comp]
        prices = [fnum(r, "price") for r in comp if fnum(r, "price") > 0]
        lines += ["", f"- Մեդիան շրջանառություն մրցակիցների մոտ՝ {median(revs):,.0f} ₽",
                  f"- Գնային միջանցք՝ {min(prices):,.0f} – {max(prices):,.0f} ₽ (մեդ. {median(prices):,.0f} ₽)"
                  if prices else ""]

    if cost is not None and volume is not None and price > 0:
        econ = unit_economics(price, cost, volume, load_econ_config())
        lines += ["", "## Յունիտ-էկոնոմիկա այս գնով", "",
                  f"- WB ծախսեր՝ {econ['wb_costs_total']:,.0f} ₽ | վճարում՝ {econ['payout_from_wb']:,.0f} ₽",
                  f"- Ինքնարժեք (full)՝ {econ['goods_cost_full']:,.0f} ₽ | գովազդ՝ {econ['ads']:,.0f} ₽ | "
                  f"հարկ՝ {econ['tax']:,.0f} ₽",
                  f"- **Զուտ շահույթ՝ {econ['net_profit']:,.0f} ₽ ({econ['net_margin_pct']}%), "
                  f"ROI {econ['roi_on_goods_pct']}%**",
                  f"- Break-even գին՝ {econ['breakeven_price']:,.0f} ₽"]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="MPSTATS SKU audit")
    p.add_argument("--sku", action="append", required=True)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--cost", type=float)
    p.add_argument("--volume", type=float)
    args = p.parse_args()

    today = date.today()
    d2, d1 = str(today - timedelta(days=1)), str(today - timedelta(days=args.days))
    client = MpstatsClient()
    REPORTS.mkdir(parents=True, exist_ok=True)

    chunks = []
    for sku in args.sku:
        try:
            chunks.append(audit(client, sku, d1, d2, args.cost, args.volume))
        except Exception as exc:                          # noqa: BLE001
            chunks.append(f"# SKU {sku}\n\n❌ Սխալ՝ {exc}")
    out = REPORTS / f"sku_audit_{today:%Y%m%d}.md"
    out.write_text("\n\n---\n\n".join(chunks), encoding="utf-8")
    print(f"[api] calls={client.api_calls} cache_hits={client.cache_hits}")
    print(f"✔ {out}")


if __name__ == "__main__":
    main()
