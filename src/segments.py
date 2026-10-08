"""Сегменты top-100 предмета за последние N месяцев по пресету признаков. Только чтение.

    python -m src.segments --niche termos [--date 2026-10-03] [--months 6] [--price-cap 15000]

Вход: data/raw/saleflow/<date>/<niche>/monthly/products_YYYY-MM.json (см. src/niche_top100.py).
Выход: stdout (markdown) + <niche>/segments.json.
"""
import argparse, glob, json, os, re, statistics as st, sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BANDS = {
    "default": [(0, 800), (800, 1200), (1200, 1800), (1800, 2500), (2500, 4000), (4000, 10**9)],
    "vakuumatory": [(0, 1200), (1200, 1800), (1800, 2500), (2500, 4000), (4000, 15000)],
    "videonyani": [(0, 1500), (1500, 2700), (2700, 3700), (3700, 5000), (5000, 7000), (7000, 15000)],
}
# признак → regex по названию (нижний регистр)
FEATURES = {
    "videonyani": {
        "с монитором/экраном": r"монитор|экран|дисплей|дюйм", "wi-fi/телефон": r"(?<!без )(?<!без)wi.?fi|(?<!без )вай.?фай|телефон|смартфон|приложен",  # «без Wi-Fi» ≠ Wi-Fi
        "поворотная/360": r"поворот|360", "датчик температуры": r"температур", "колыбельные/ночник": r"колыбел|ночник",
        "2K/3+ Мп/4K": r"2k|[345]\s*мп|4k|1296|1440", "аккумулятор/автономная": r"аккумулятор|батаре|автоном",
        "для дома/видеонаблюдения": r"для дома|видеонаблюд", "радионяня": r"радионян", "в подарок": r"подар",
    },
    "vakuumatory": {
        "не прибор (пакеты/аксессуары)": r"^(пакеты|пакет|рулон)|пакеты для вакуум|пакеты фасов|к вакууматору",
        "резак": r"резак", "рулон (отсек)": r"рулон", "двойная запайка": r"двойн",
        "шланг (контейнеры)": r"шланг|трубк", "профессиональный": r"професс", "«мощный»": r"мощн",
        "с пакетами в комплекте": r"пакетами|\+\s*\d+\s*пакет",
    },
    "termos": {
        "до 0.6 л": r"\b0[,.][3-6]\d?\s*л|\b(350|450|500|600)\s*мл",
        "0.75–1 л": r"\b0[,.][7-9]\d?\s*л|\b1([,.]0)?\s*л|\b(750|800|1000)\s*мл",
        "1.2+ л": r"\b1[,.][2-9]\d?\s*л|\b[2-5]([,.]\d)?\s*л",
        "с чашкой/кружкой": r"чашк|кружк|стакан", "с ручкой": r"ручк",
        "для еды": r"для еды|пищев|ланч|суп", "с ситечком/для чая": r"ситеч|завар|чай",
        "туристический/походный": r"туристич|поход|рыбалк|охот", "кнопка/клапан": r"кнопк|клапан",
        "в подарок/набор": r"подар|набор", "нержавеющая сталь": r"нерж|стал",
    },
    "chasy-naruchnye": {
        "мужские": r"мужск", "женские": r"женск", "механические/скелетон": r"механ|скелет",
        "смарт/электронные": r"смарт|smart|электрон", "браслет": r"браслет", "ремешок": r"ремеш|кожан",
        "водонепроницаемые": r"водонепрон|водостой", "в подарок/набор": r"подар|набор|комплект",
        "бренд в названии": r"pandora|пандор|casio|касио|rolex|tissot|cartier|omega|seiko",
    },
    "nozhi-kuhonnye": {
        "набор": r"набор", "цельнолитые": r"цельнолит|цельнометал", "подставка/блок": r"подставк|блок",
        "магнит": r"магнит", "ножницы": r"ножниц", "точилка/мусат": r"точил|мусат",
        "разделочная доска": r"доск", "чехлы/ножны": r"чехл|ножн|футляр", "подарочная коробка": r"подар|коробк|кейс",
        "дамаск/японский": r"дамаск|японск|сантоку|кирицуке", "керамические": r"керам",
        "3 предмета": r"\b3\s*(предмет|шт)", "5 предметов": r"\b5\s*(предмет|шт)",
        "6–7 предметов": r"\b[67]\s*(предмет|шт)", "8+ предметов": r"\b(8|9|1\d|2\d)\s*(предмет|шт)",
    },
}


def load(niche, date, months, cap):
    out = {}
    for f in sorted(glob.glob(os.path.join("data", "raw", "saleflow", date, niche, "monthly", "products_*.json")))[-months:]:
        m = os.path.basename(f)[9:16]
        rows = [x for x in json.load(open(f, encoding="utf-8"))["data"] if x["final_price"] <= cap]
        rows.sort(key=lambda x: -x["revenue"])
        for i, x in enumerate(rows, 1):
            x["rank"] = i
            x["vol"] = (x.get("package_length") or 0) * (x.get("package_width") or 0) * (x.get("package_height") or 0) / 1000
        out[m] = rows
    return out


def summarize(months, key_fn, title):
    agg = defaultdict(lambda: {"rev": 0, "cm": 0, "ids": set(), "prices": [], "vols": [], "top30": set(), "new": set(), "cmt": []})
    total = 0
    for rows in months.values():
        for x in rows:
            k = key_fn(x)
            if k is None:
                continue
            a = agg[k]
            a["rev"] += x["revenue"]; a["cm"] += 1; a["ids"].add(x["id"]); a["prices"].append(x["final_price"])
            a["cmt"].append(x.get("comments") or 0)
            if x["vol"]:
                a["vols"].append(x["vol"])
            if x["rank"] <= 30:
                a["top30"].add(x["id"])
                if x.get("days_in_site", 9999) < 365:
                    a["new"].add(x["id"])
            total += x["revenue"]
    print(f"\n## {title}\n")
    print("| Сегмент | Карточек | Доля выручки | Выручка / карточко-мес | Мед. цена | Мед. объём, л | Мед. отзывов | В top-30 | Новинки в top-30 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    res = {}
    for k, a in sorted(agg.items(), key=lambda t: -t[1]["rev"]):
        r = dict(cards=len(a["ids"]), share_pct=round(100 * a["rev"] / total, 1) if total else 0,
                 rev_per_card_month=round(a["rev"] / a["cm"]), median_price=st.median(a["prices"]),
                 median_vol=round(st.median(a["vols"]), 1) if a["vols"] else None,
                 median_comments=st.median(a["cmt"]), top30=len(a["top30"]), top30_new=len(a["new"]))
        res[str(k)] = r
        print(f"| {k} | {r['cards']} | {r['share_pct']}% | {r['rev_per_card_month']:,} ₽ | {r['median_price']:,.0f} ₽ | "
              f"{r['median_vol'] if r['median_vol'] is not None else '—'} | {r['median_comments']:,.0f} | {r['top30']} | {r['top30_new']} |")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", required=True)
    ap.add_argument("--date", default="2026-10-03")
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--price-cap", type=float, default=15000)
    a = ap.parse_args()
    months = load(a.niche, a.date, a.months, a.price_cap)
    if not months:
        sys.exit("нет monthly/products_*.json")
    ms = sorted(months)
    print(f"период: {ms[0]} … {ms[-1]} ({len(ms)} мес), строк: {sum(len(v) for v in months.values())}")
    bands = BANDS.get(a.niche, BANDS["default"])
    feats = FEATURES.get(a.niche, {})
    band = lambda x: next((f"{lo}–{hi if hi < 10**9 else '∞'} ₽" for lo, hi in bands if lo <= x["final_price"] < hi), None)
    out = {"period": [ms[0], ms[-1]], "bands": summarize(months, band, "Ценовые полосы")}
    for name, pat in feats.items():
        out[name] = summarize(months, lambda x, p=pat: "да" if re.search(p, x["name"].lower()) else "нет", f"Признак: {name}")
    out["color"] = summarize(months, lambda x: (x.get("color") or "—").split(",")[0].strip(), "Цвет (первый)")
    out["country"] = summarize(months, lambda x: x.get("country") or "—", "Страна")
    json.dump(out, open(os.path.join("data", "raw", "saleflow", a.date, a.niche, "segments.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
