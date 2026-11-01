"""Նիշաների զանգվածային սքան → սքոր → ռեյտինգ (CSV + Markdown հաշվետվություն).

Օրինակներ:
  python -m src.niche_scan --path "Дом/Кухня" --children categories --top 12
  python -m src.niche_scan --path "Дом/Кухня/Аксессуары для кухни" --children none
  python -m src.niche_scan --demo          # առանց API-ի, ստուգում է pipeline-ը
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from .fields import fnum, pick
from .mpstats_client import MpstatsClient, rows
from .outliers import clean_items, report_lines
from .scoring import load_config, niche_metrics, score_niche

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RAW = ROOT / "data" / "raw"

CSV_COLUMNS = [
    "niche", "score", "verdict", "total_revenue", "sku_total", "pct_sku_with_sales",
    "revenue_per_selling_sku", "top10_revenue_share", "top_seller_share", "growth_mom_pct",
    "median_price", "median_comments_top", "new_sku_success_pct", "sellers_total",
    "price_dispersion_ratio", "flags", "fails",
]


# --------------------------------------------------------------------- demo
def demo_niches() -> dict[str, tuple[list[dict], list[dict]]]:
    """Սինթետիկ տվյալներ՝ pipeline-ը առանց API-ի ստուգելու համար."""
    random.seed(7)
    presets = {
        "Демо / здоровая ниша": dict(n=220, sell=0.62, top=260_000, decay=0.955, price=(950, 2100),
                                     comments=(20, 220), growth=1.28, fresh=0.34),
        "Демо / монополия": dict(n=180, sell=0.28, top=2_900_000, decay=0.80, price=(700, 1800),
                                 comments=(600, 4200), growth=0.97, fresh=0.04),
        "Демо / падающая ниша": dict(n=140, sell=0.45, top=190_000, decay=0.94, price=(400, 900),
                                     comments=(150, 900), growth=0.72, fresh=0.12),
    }
    out = {}
    today = date.today()
    for name, p in presets.items():
        items, revenue = [], p["top"]
        for i in range(p["n"]):
            has_sales = i < p["n"] * p["sell"]
            price = random.uniform(*p["price"])
            rev = revenue if has_sales else 0.0
            revenue *= p["decay"]
            age = random.randint(5, 900) if random.random() > p["fresh"] else random.randint(5, 110)
            items.append({
                "id": 100000 + i, "name": f"{name} товар {i}", "brand": f"BR{i % 18}",
                "seller": f"SEL{i % 25}", "revenue": round(rev), "sales": round(rev / price),
                "final_price": round(price), "rating": round(random.uniform(4.2, 5.0), 1),
                "comments": random.randint(*p["comments"]) if has_sales else 0,
                "balance": random.randint(0, 800),
                "start_date": str(today - timedelta(days=age)),
            })
        by_date, base = [], 1.0
        for day in range(60):
            base *= p["growth"] ** (1 / 60)
            by_date.append({"date": str(today - timedelta(days=60 - day)),
                            "revenue": sum(fnum(i, "revenue") for i in items) / 30 * base})
        out[name] = (items, by_date)
    return out


# ---------------------------------------------------------------- collection
def candidates_for(client: MpstatsClient, path: str, mode: str, d1: str, d2: str,
                   top: int) -> list[tuple[str, str]]:
    """Վերադարձնում է [(name, kind)] զույգեր, kind = category | subject."""
    if mode == "none":
        return [(path, "category")]
    report = "subjects" if mode == "subjects" else "categories"
    data = rows(client.category_report(path, report, d1, d2, limit=500))
    named = []
    for row in data:
        name = pick(row, "name") or pick(row, "path") or pick(row, "subject")
        if not name:
            continue
        full = str(name) if mode == "subjects" or str(name).startswith(path) else f"{path}/{name}"
        named.append((full, "subject" if mode == "subjects" else "category", fnum(row, "revenue")))
    named.sort(key=lambda x: x[2], reverse=True)
    return [(n, k) for n, k, _ in named[:top]]


def collect(client: MpstatsClient, name: str, kind: str, d1: str, d2: str, d0: str, d_year: str,
            max_rows: int, growth: bool) -> tuple[list[dict], list[dict]]:
    if kind == "subject":
        items = rows(client.subject_report(name, "items", d1, d2, limit=500))
        by_date = rows(client.subject_report(name, "by_date", d_year, d2, limit=420)) if growth else []
    else:
        items = client.category_items_all(name, d1, d2, max_rows=max_rows)
        by_date = rows(client.category_report(name, "by_date", d_year, d2, limit=420,
                                              sort_by=None)) if growth else []
    return items, by_date


# -------------------------------------------------------------------- report
def write_reports(results: list[dict], cfg: dict, tag: str) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS / f"niche_scan_{tag}.csv"
    md_path = REPORTS / f"niche_scan_{tag}.md"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {**r["metrics"], "niche": r["niche"], "score": r["score"],
                   "verdict": r["verdict"], "flags": "; ".join(r["flags"]),
                   "fails": "; ".join(r["fails"])}
            writer.writerow(row)

    lines = [f"# Նիշաների սքան — {tag}", "",
             f"Ժամանակահատված՝ {cfg['_period']}  |  Նիշաներ՝ {len(results)}", "",
             "| # | Նիշա | Սքոր | Վերդիկտ | Շրջ. 30օր ₽ | ₽/վաճառվող քարտ | %քարտ վաճառքով | Տոպ-10 % | Աճ % | Մեդ. գին | Մեդ. կարծիք |",
             "|---|------|------|---------|-------------|------------------|----------------|----------|------|----------|-------------|"]
    for i, r in enumerate(results, 1):
        m = r["metrics"]
        lines.append(
            f"| {i} | {r['niche']} | **{r['score']}** | {r['verdict']} | {m['total_revenue']:,} | "
            f"{m['revenue_per_selling_sku']:,} | {m['pct_sku_with_sales']} | {m['top10_revenue_share']} | "
            f"{m['growth_mom_pct'] if m['growth_mom_pct'] is not None else '—'} | {m['median_price']:,} | "
            f"{m['median_comments_top']:,} |")

    for r in results:
        m = r["metrics"]
        lines += ["", f"## {r['niche']} — {r['score']} միավոր, {r['verdict']}", "",
                  f"- SKU՝ {m['sku_total']} (վաճառքով՝ {m['sku_with_sales']}, {m['pct_sku_with_sales']}%)",
                  f"- Շրջանառություն՝ {m['total_revenue']:,} ₽ | վաճառք՝ {m['total_sales']:,} հատ",
                  f"- Մեդիան 1 վաճառվող քարտի վրա՝ {m['revenue_per_selling_sku']:,} ₽ "
                  f"(միջին՝ {m['avg_revenue_per_selling_sku']:,} ₽)",
                  f"- Կոնցենտրացիա՝ տոպ-10 = {m['top10_revenue_share']}%, ամենամեծ վաճառողը = {m['top_seller_share']}%",
                  f"- Վաճառողներ՝ {m['sellers_total']} | բրենդներ՝ {m['brands_total']}",
                  f"- Գին՝ p10 {m['price_p10']:,} / մեդ. {m['median_price']:,} / p90 {m['price_p90']:,} ₽ "
                  f"(ցրվածություն ×{m['price_dispersion_ratio']})",
                  f"- Տոպ-20 մուտքի բարիեր՝ {m['median_comments_top']:,} կարծիք, ռեյտինգ {m['median_rating_top']}",
                  f"- Թարմ քարտեր տոպ-50-ում (<120 օր)՝ "
                  f"{m['new_sku_success_pct'] if m['new_sku_success_pct'] is not None else '—'}%",
                  f"- Տոպ վաճառողներ՝ " + ", ".join(f"{n} ({v:,.0f} ₽)" for n, v in m["top_sellers"][:3])]
        if r["flags"]:
            lines.append(f"- ⚠️ **Կարմիր դրոշներ՝** {', '.join(r['flags'])}")
        if r["fails"]:
            lines.append(f"- ❌ **Ֆիլտրից դուրս՝** {'; '.join(r['fails'])}")
        lines.append("")
        lines.append("| Մետրիկա | Արժեք | Սքոր | Կշիռ |")
        lines.append("|---------|-------|------|------|")
        for name, part in r["parts"].items():
            lines.append(f"| {name} | {part['value'] if part['value'] is not None else '—'} | "
                         f"{part['score'] if part['score'] is not None else '—'} | {part['weight']} |")

    lines += ["", "---", "",
              "**Հաջորդ քայլը.** տոպ-3 նիշայի համար գործարկիր `python -m src.sku_audit --sku <артикул>` "
              "և `python -m src.unit_econ --price ... --cost ... --volume ...`։",
              "", "_Տվյալները՝ MPSTATS external analytics. Ցանկացած «թվային» որոշում ստուգիր "
              "2-րդ աղբյուրով (WB որոնման արդյունքներ, մրցակցի քարտի դինամիկա)._"]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def _load_filters_cfg() -> dict:
    try:
        from .gates import load_filters
        return load_filters()
    except Exception:                                         # noqa: BLE001
        return {}


def main() -> None:
    filters_cfg = _load_filters_cfg()
    p = argparse.ArgumentParser(description="MPSTATS niche scanner")
    p.add_argument("--path", action="append", default=[], help="կատեգորիայի ամբողջական path")
    p.add_argument("--from-csv", help="վերցնել path-երը discovery CSV-ից (tier A/B-ից)")
    p.add_argument("--tiers", default="A,B", help="որ խմբերը վերցնել CSV-ից")
    p.add_argument("--limit-niches", type=int, default=10, help="առավելագույնը քանի նիշա CSV-ից")
    p.add_argument("--children", choices=["categories", "subjects", "none"], default="categories")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--top", type=int, default=10, help="քանի ենթա-նիշա վերցնել ամեն path-ից")
    p.add_argument("--max-rows", type=int, default=500)
    p.add_argument("--no-growth", action="store_true")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", default=str(ROOT / "config" / "scoring.yaml"))
    args = p.parse_args()

    cfg = load_config(args.config)
    today = date.today()
    d2 = str(today - timedelta(days=1))
    d1 = str(today - timedelta(days=args.days))
    d0 = str(today - timedelta(days=args.days * 2))
    d_year = str(today - timedelta(days=400))   # YoY պիկ ամսով
    cfg["_period"] = f"{d1} … {d2}"
    tag = today.strftime("%Y%m%d")
    results: list[dict] = []

    if args.from_csv:
        wanted = {t.strip().upper() for t in args.tiers.split(",")}
        with open(args.from_csv, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if (row.get("tier") or "").upper() in wanted and row.get("path"):
                    args.path.append(row["path"])
                if len(args.path) >= args.limit_niches:
                    break
        print(f"[csv] վերցվեց {len(args.path)} նիշա {args.from_csv}-ից (tier {args.tiers})")

    if args.demo:
        cfg["_period"] = "DEMO"
        for name, (items, by_date) in demo_niches().items():
            items, clean_rep = clean_items(items, filters_cfg)
            metrics = niche_metrics(items, by_date)
            metrics['_outliers'] = clean_rep
            scored = score_niche(metrics, cfg)
            results.append({"niche": name, "metrics": metrics, **scored})
    else:
        if not args.path:
            p.error("նշիր առնվազն մեկ --path կամ --from-csv (փնտրիր՝ python -m src.mpstats_client categories «чехл»)")
        client = MpstatsClient()
        limit_info = client.api_limit()
        print(f"[limit] {json.dumps(limit_info, ensure_ascii=False)}")

        plan: list[tuple[str, str]] = []
        for path in args.path:
            if args.from_csv and args.children == "categories":
                plan.append((path, "category"))       # CSV-ից եկածները արդեն վերջնական նիշա են
            else:
                plan += candidates_for(client, path, args.children, d1, d2, args.top)
        est = len(plan) * (1 + (0 if args.no_growth else 1)) + len(args.path)
        print(f"[plan] {len(plan)} նիշա, ~{est} API հարցում")
        for name, kind in plan:
            print(f"   • {name} ({kind})")
        if args.dry_run:
            return

        RAW.mkdir(parents=True, exist_ok=True)
        saved = 0
        for name, kind in plan:
            try:
                items, by_date = collect(client, name, kind, d1, d2, d0, d_year,
                                         args.max_rows, not args.no_growth)
            except (TypeError, NameError, AttributeError, KeyError):   # [аудит 2026-11-02] ошибка кода ≠ «пустая ниша» — не глотаем
                raise
            except Exception as exc:                      # noqa: BLE001 — сеть/API: пропуск ниши
                print(f"[skip] {name}: {exc}")
                continue
            if not items:
                print(f"[skip] {name}: դատարկ պատասխան")
                continue
            (RAW / f"{tag}_{abs(hash(name))}.json").write_text(
                json.dumps({"niche": name, "items": items, "by_date": by_date},
                           ensure_ascii=False), encoding="utf-8")
            saved += 1
            items, clean_rep = clean_items(items, filters_cfg)
            metrics = niche_metrics(items, by_date)
            metrics['_outliers'] = clean_rep
            scored = score_niche(metrics, cfg)
            results.append({"niche": name, "metrics": metrics, **scored})
            print(f"[ok] {name}: score={scored['score']} {scored['verdict']}")
        print(f"[api] calls={client.api_calls} cache_hits={client.cache_hits}")
        if plan and saved == 0:                               # [аудит 2026-11-02] пустой результат — это сбой, а не «ниш нет»
            raise SystemExit("FAILED: ни одна ниша не собрана — проверьте токен/доступ/путь, отчёт не строим")

    results.sort(key=lambda r: (not r["fails"], r["score"]), reverse=True)
    csv_path, md_path = write_reports(results, cfg, tag)
    print(f"\n✔ {csv_path}\n✔ {md_path}")


if __name__ == "__main__":
    main()
