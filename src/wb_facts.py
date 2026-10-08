"""Փաստացի թվեր WB Seller API-ից՝ մոդելի ենթադրությունները փոխարինելու համար.

  python -m src.wb_facts buyout --days 30      # ԻՐԱԿԱՆ выкуп % (ոչ թե ենթադրություն)
  python -m src.wb_facts funnel --days 30      # CTR, զամբյուղ, конверсия, выкуп ըստ քարտի
  python -m src.wb_facts regions --days 30     # որ ռեգիոններից են պատվերները (պահեստի ընտրություն)

Այս երեքը փակում են յունիտ-էկոնոմիկայի ամենավտանգավոր բացերը։
Եթե դեռ վաճառք չունես՝ գործարկիր առաջին խմբաքանակից 2 շաբաթ հետո։
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .wb_seller import WBSellerClient, rub

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "orders", "sales"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def buyout(client: WBSellerClient, days: int) -> str:
    """Реальный % выкупа = (վաճառք) / (պատվեր − չեղարկում), ըստ SKU-ի."""
    date_from = str(date.today() - timedelta(days=days))
    orders = _rows(client.orders(date_from))
    sales = _rows(client.sales(date_from))
    if not orders:
        return ("## Выкуп\n\nՊատվերներ չկան այս ժամանակահատվածում "
                "(կամ թոքենը չունի «Статистика» իրավունք)։")

    per_sku: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for o in orders:
        nm = o.get("nmId") or o.get("nmID") or 0
        per_sku[nm]["orders"] += 1
        per_sku[nm]["order_rub"] += rub(o.get("finishedPrice") or o.get("totalPrice"))
        if o.get("isCancel"):
            per_sku[nm]["cancels"] += 1
    for s in sales:
        nm = s.get("nmId") or s.get("nmID") or 0
        sale_id = str(s.get("saleID", ""))
        if sale_id.startswith("S"):          # S… = վաճառք, R… = վերադարձ
            per_sku[nm]["sales"] += 1
            per_sku[nm]["sale_rub"] += rub(s.get("finishedPrice"))
            per_sku[nm]["payout"] += rub(s.get("forPay"))
        elif sale_id.startswith("R"):
            per_sku[nm]["returns"] += 1

    lines = [f"## Իրական выкуп ({date_from} … {date.today()})", "",
             "| SKU | Պատվեր | Չեղարկ. | Վաճառք | Վերադարձ | Выкуп % | Միջին վճարում ₽ |",
             "|---|---|---|---|---|---|---|"]
    tot_o = tot_s = 0.0
    for nm, m in sorted(per_sku.items(), key=lambda kv: kv[1]["orders"], reverse=True)[:40]:
        net_orders = m["orders"] - m["cancels"]
        pct = m["sales"] / net_orders * 100 if net_orders else 0
        avg_payout = m["payout"] / m["sales"] if m["sales"] else 0
        tot_o += net_orders
        tot_s += m["sales"]
        lines.append(f"| {nm} | {m['orders']:.0f} | {m['cancels']:.0f} | {m['sales']:.0f} | "
                     f"{m['returns']:.0f} | **{pct:.1f}%** | {avg_payout:,.0f} |")
    total_pct = tot_s / tot_o * 100 if tot_o else 0
    lines += ["", f"**Ընդհանուր выкуп՝ {total_pct:.1f}%**  ← սա դիր "
              f"`config/unit_economics.yaml` → `operations.buyout_pct`",
              "", "> Եթե այս թիվը 10+ կետով ցածր է քո պլանավորածից՝ վերահաշվիր ամբողջ էկոնոմիկան "
              "նախքան երկրորդ խմբաքանակը։"]
    return "\n".join(lines)


def funnel(client: WBSellerClient, days: int, nm_ids: list[int]) -> str:
    d2, d1 = date.today() - timedelta(days=1), date.today() - timedelta(days=days)
    data = client.funnel(nm_ids, str(d1), str(d2))
    cards = (data.get("data") or {}).get("cards") or []
    if not cards:
        return "## Ձագար\n\nՏվյալ չկա (ստուգիր nmID-ները և «Аналитика» իրավունքը)։"

    lines = [f"## Վաճառքի ձագար ({d1} … {d2})", "",
             "| SKU | Բացումներ | Զամբյուղ | CR→զամբ. | Պատվեր | CR→պատվեր | Выкуп | Выкуп % |",
             "|---|---|---|---|---|---|---|---|"]
    for card in cards:
        st = (card.get("statistics") or {}).get("selectedPeriod") or {}
        conv = st.get("conversions") or {}
        lines.append(
            f"| {card.get('nmID')} | {st.get('openCardCount', 0):,} | {st.get('addToCartCount', 0):,} | "
            f"{conv.get('addToCartPercent', 0)}% | {st.get('ordersCount', 0):,} | "
            f"{conv.get('cartToOrderPercent', 0)}% | {st.get('buyoutsCount', 0):,} | "
            f"{conv.get('buyoutsPercent', 0)}% |")
    lines += ["", "### Ինչպես կարդալ",
              "- Ցածր **CR→զամբյուղ** (<3–5%) → խնդիրը գլխավոր նկարն ու գինն են, ոչ թե ապրանքը",
              "- Ցածր **CR→պատվեր** (<25%) → գինը/առաքման ժամկետը թույլ են մրցակիցների դեմ",
              "- Ցածր **выкуп %** → ապրանքի ակնկալիքի անհամապատասխանություն (նկար ≠ իրականություն)",
              "- Քիչ **բացումներ** → SEO/գովազդի խնդիր, քարտը չի երևում"]
    return "\n".join(lines)


def regions(client: WBSellerClient, days: int) -> str:
    date_from = str(date.today() - timedelta(days=days))
    orders = _rows(client.orders(date_from))
    if not orders:
        return "## Ռեգիոններ\n\nՏվյալ չկա։"
    by_region: dict[str, int] = defaultdict(int)
    by_wh: dict[str, int] = defaultdict(int)
    for o in orders:
        by_region[str(o.get("regionName") or o.get("oblastOkrugName") or "—")] += 1
        by_wh[str(o.get("warehouseName") or "—")] += 1
    lines = [f"## Պատվերների աշխարհագրություն ({date_from} …)", "", "| Ռեգիոն | Պատվեր |", "|---|---|"]
    for name, cnt in sorted(by_region.items(), key=lambda kv: kv[1], reverse=True)[:15]:
        lines.append(f"| {name} | {cnt} |")
    lines += ["", "| Պահեստ (որտեղից է գնացել) | Պատվեր |", "|---|---|"]
    for name, cnt in sorted(by_wh.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        lines.append(f"| {name} | {cnt} |")
    lines += ["", "> Եթե պատվերների մեծ մասը հեռու ռեգիոնից է՝ индекс локализации-ն "
              "բարձրացնում է լոգիստիկան։ Դիտարկիր բաշխված պահեստավորում։"]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="WB Seller API facts")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("buyout", "regions"):
        sp = sub.add_parser(name)
        sp.add_argument("--days", type=int, default=30)
    sp = sub.add_parser("funnel")
    sp.add_argument("--days", type=int, default=30)
    sp.add_argument("--nm", required=True, help="nmID-ներ ստորակետով")
    args = p.parse_args()

    client = WBSellerClient()
    if args.cmd == "buyout":
        out = buyout(client, args.days)
    elif args.cmd == "funnel":
        out = funnel(client, args.days, [int(x) for x in args.nm.split(",") if x.strip()])
    else:
        out = regions(client, args.days)

    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"wb_facts_{args.cmd}_{date.today():%Y%m%d}.md"
    path.write_text(out, encoding="utf-8")
    print(out)
    print(f"\n✔ {path}\n[wb api_calls={client.api_calls} cache_hits={client.cache_hits}]")


if __name__ == "__main__":
    main()
