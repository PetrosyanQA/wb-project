"""Сегменты top-100 subject 722 (вакуумные упаковщики) за последние N месяцев. Только чтение.

    python -m src.vacuum_segments [months=6]

Источник: data/raw/saleflow/2026-10-03/vakuumatory/monthly/products_YYYY-MM.json.
Выброс: final_price > 15 000 ₽ (карточка 1095144353, 2026-08) отбрасывается.
"""
import glob, json, os, re, statistics as st, sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join("data", "raw", "saleflow", "2026-10-03", "vakuumatory", "monthly")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
PRICE_CAP = 15000

FEATURES = {
    "не прибор (пакеты/аксессуары)": r"^(пакеты|пакет|рулон)|пакеты для вакуум|пакеты фасов|к вакууматору",
    "резак": r"резак",
    "рулон (отсек)": r"рулон",
    "двойная запайка": r"двойн",
    "шланг (контейнеры)": r"шланг|трубк",
    "профессиональный": r"професс",
    "«мощный»": r"мощн",
    "с пакетами в комплекте": r"пакетами|\+\s*\d+\s*пакет",
}
BANDS = [(0, 1200), (1200, 1800), (1800, 2500), (2500, 4000), (4000, PRICE_CAP)]


def load():
    months = {}
    for f in sorted(glob.glob(os.path.join(D, "products_*.json")))[-N:]:
        m = os.path.basename(f)[9:16]
        rows = [x for x in json.load(open(f, encoding="utf-8"))["data"] if x["final_price"] <= PRICE_CAP]
        rows.sort(key=lambda x: -x["revenue"])
        for i, x in enumerate(rows, 1):
            x["rank"] = i
        months[m] = rows
    return months


def summarize(months, key_fn, title):
    agg = defaultdict(lambda: {"rev": 0, "cm": 0, "ids": set(), "prices": [], "top30_new": set(), "top30": set()})
    total = 0
    for m, rows in months.items():
        for x in rows:
            k = key_fn(x)
            if k is None:
                continue
            a = agg[k]
            a["rev"] += x["revenue"]; a["cm"] += 1; a["ids"].add(x["id"]); a["prices"].append(x["final_price"])
            if x["rank"] <= 30:
                a["top30"].add(x["id"])
                if x["days_in_site"] < 365:
                    a["top30_new"].add(x["id"])
            total += x["revenue"]
    print(f"\n## {title}\n")
    print("| Сегмент | Карточек | Карточко-мес | Доля выручки | Выручка / карточко-мес | Мед. цена | В top-30 | Из них новинки <365 дн |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    out = {}
    for k, a in sorted(agg.items(), key=lambda t: -t[1]["rev"]):
        r = dict(cards=len(a["ids"]), card_months=a["cm"], share_pct=round(100 * a["rev"] / total, 1),
                 rev_per_card_month=round(a["rev"] / a["cm"]), median_price=st.median(a["prices"]),
                 top30=len(a["top30"]), top30_new=len(a["top30_new"]))
        out[str(k)] = r
        print(f"| {k} | {r['cards']} | {r['card_months']} | {r['share_pct']}% | {r['rev_per_card_month']:,} ₽ | "
              f"{r['median_price']:,.0f} ₽ | {r['top30']} | {r['top30_new']} |")
    return out


def band(x):
    for lo, hi in BANDS:
        if lo <= x["final_price"] < hi:
            return f"{lo}–{hi} ₽"


if __name__ == "__main__":
    months = load()
    ms = sorted(months)
    print(f"период: {ms[0]} … {ms[-1]} ({len(ms)} мес), строк: {sum(len(v) for v in months.values())}")
    res = {"period": [ms[0], ms[-1]]}
    is_device = lambda x: not re.search(FEATURES["не прибор (пакеты/аксессуары)"], x["name"].lower())
    res["bands"] = summarize(months, lambda x: band(x) if is_device(x) else None, "Ценовые полосы (только приборы)")
    for name, pat in FEATURES.items():
        res[name] = summarize(months, lambda x, p=pat: ("да" if re.search(p, x["name"].lower()) else "нет")
                              if (is_device(x) or name.startswith("не прибор")) else None, f"Признак: {name}")
    res["color"] = summarize(months, lambda x: (x["color"] or "—").split(",")[0].strip() if is_device(x) else None, "Цвет (первый)")
    res["country"] = summarize(months, lambda x: x["country"] or "—" if is_device(x) else None, "Страна")
    json.dump(res, open(os.path.join(D, "..", "segments.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
