"""Скрин предметов WB из выгрузок wb_subjects_list (filter_model по выручке). Только чтение.

    python -m src.subject_screen [--date 2026-10-04] [--pages subjects_all] [--aov-min 800 --aov-max 2500]
                                 [--rev-min 0 --rev-max 1e12] [--allow beauty,toys,gadget,decor] [--tag base] [--top 40]

Вход: data/raw/saleflow/<date>/<pages>/page_*.json.
Жёсткие фильтры — средний чек, выручка, выкуп, сезонность, «Честный знак», электроника/габарит/продукты.
--allow снимает часть исключений по категориям (пулы «исключённые категории»).
Пред-балл (только для очерёдности воронки): недовольство покупателей (низкая оценка отзывов),
доля новых карточек, разброс продавцов, конверсия корзина→заказ.
"""
import argparse, glob, json, os, re, sys

from .saleflow_eval import load_strategy, regulatory_check

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.join("data", "raw", "saleflow")

# всегда исключаем: крупное, техника с питанием, продукты/здоровье, одежда, хрупкие строительные и т.п.
BASE_EXCLUDE = (
    r"техника для|электр|аккумул|батаре|зарядн|наушн|смартф|телефон|ноутб|компьют|телевиз|колонк|"
    r"освещен|светильн|люстр|ламп|мебел|кроват|диван|матрас|шкаф|стол|стул|кресл|комод|"
    r"ковр|ковров|штор|тюль|карниз|обои|панел|плитк|ламинат|дверь|окн|сантехн|ванн|унитаз|раковин|мойк|смесит|"
    r"одеял|подушк|плед|покрывал|кастрюл|сковород|казан|сервиз|чайники для плиты|сушилк|гладильн|"
    r"велосипед|самокат|коляск|автокресл|шины|диски|запчаст|аккумулятор|двигат|"
    r"продукт|кофе|чай|напит|сладост|конфет|шоколад|снек|орех|круп|макарон|консерв|соус|специ|мясн|рыбн|"
    r"корм|наполнит|лекарств|здоровье|ветаптек|бад|витамин|спортивное питание|протеин|детское пит|"
    r"бытовая хими|стираль|моющ|чистящ|удобрен|грунт|семен|растени|"
    r"книг|журнал|картридж|принтер|игры|консол|"
    r"одежд|белье|бельё|обув|головные|платк|шарф|перчат|носк|колгот|купальн|"
    r"сумки$|рюкзак|чемодан|зонт|очки|парик|бижутер|часы|взрослых|"
    r"парфюм|шампун|крем|бальзам|сыворот|тоник|маск|космет(?!ичк)|краск|лак|эмал|грунтов|штукатур|пен[аы] монт")
# исключения, которые можно снять флагом --allow
OPTIONAL_EXCLUDE = {
    "beauty": r"^красота /",                     # аксессуары красоты (средства — в BASE)
    "toys": r"игрушк|конструктор|кукл|машинк|малыш",
    "gadget": r"аксессуары для электроники|периферия",
    "decor": r"декор интерьера",
}


# xborder: вес решает больше категории → лёгкие аксессуары больше не исключаем
XBORDER_ALLOWED = ("часы", "очки", "бижутер", "зонт", "парик", "сумки$")


def build_exclude(allow, mode="base"):
    base = BASE_EXCLUDE
    if mode == "xborder":
        for word in XBORDER_ALLOWED:
            base = base.replace(word + "|", "", 1)
    parts = [base] + [p for k, p in OPTIONAL_EXCLUDE.items() if k not in allow]
    return re.compile("|".join(parts), re.I)


def checked_ids():
    """subject_id, которые уже проверялись (CSV трендов + список ручных проверок)."""
    ids = set()
    for f in glob.glob(os.path.join(ROOT, "*", "*", "subject*_trends_monthly.csv")):
        m = re.search(r"subject(\d+)_", f)
        if m:
            ids.add(int(m.group(1)))
    known = {511, 811, 829, 722, 986, 8551, 804, 308, 136, 968, 52, 908, 1352, 2021, 28, 881, 7688, 1625, 7162,
             2431, 1137, 941, 874, 824, 1220, 393, 202, 6422, 4144, 388, 3734, 1445, 2588, 782, 781, 3206, 2232,
             3208, 735, 839, 820, 995, 2023, 1205, 559, 833, 988, 60, 59, 61, 7640, 8986,
             3778, 1766, 1274, 1290, 847, 1545, 7354, 27, 339, 878, 2011}
    return ids | known


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-04")
    ap.add_argument("--pages", default="subjects_all")
    ap.add_argument("--aov-min", type=float, default=800)
    ap.add_argument("--aov-max", type=float, default=2500)
    ap.add_argument("--rev-min", type=float, default=0)
    ap.add_argument("--rev-max", type=float, default=1e12)
    ap.add_argument("--min-sellers", type=int, default=150)
    ap.add_argument("--allow", default="")
    ap.add_argument("--tag", default="base")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--mode", choices=["base", "xborder"], default="base",
                    help="xborder: лёгкие аксессуары разрешены, все --allow включены, проверенные не пропускаем")
    a = ap.parse_args()
    allow = {x for x in a.allow.split(",") if x}
    if a.mode == "xborder":
        allow |= set(OPTIONAL_EXCLUDE)
        a.tag = a.tag if a.tag != "base" else "xborder"
    excl = build_exclude(allow, a.mode)

    rows = {}
    for f in sorted(glob.glob(os.path.join(ROOT, a.date, a.pages, "page_*.json"))):
        for x in json.load(open(f, encoding="utf-8"))["data"]:
            rows[x["id"]] = x
    s = load_strategy()
    done = checked_ids()
    print(f"[{a.tag}] предметов в выгрузке: {len(rows)}; чек {a.aov_min:.0f}–{a.aov_max:.0f} ₽; allow={sorted(allow) or '—'}")
    out = []
    stats = {k: 0 for k in ("выручка", "чек", "выкуп", "сезон", "продавцы", "ЧЗ", "категория", "уже проверен")}
    for x in rows.values():
        sales = x.get("sales") or 0
        aov = x["revenue"] / sales if sales else 0
        name = x["name"]
        if not a.rev_min <= x["revenue"] <= a.rev_max:
            stats["выручка"] += 1; continue
        if not a.aov_min <= aov <= a.aov_max:
            stats["чек"] += 1; continue
        if (x.get("purchase_after_return") or 0) < 65:
            stats["выкуп"] += 1; continue
        if (x.get("seasonality_level") or 0) > 2:
            stats["сезон"] += 1; continue
        if (x.get("sellers") or 0) < a.min_sellers:
            stats["продавцы"] += 1; continue
        if regulatory_check(name, s)["verdict"] == "FAIL":
            stats["ЧЗ"] += 1; continue
        if excl.search(name):
            stats["категория"] += 1; continue
        if x["id"] in done and a.mode != "xborder":
            stats["уже проверен"] += 1; continue
        val = x.get("comment_valuation_average") or x.get("avg_rating") or 5
        fresh = (x.get("items_new") or 0) / max(x.get("items") or 1, 1)
        score = (5 - val) * 40 + min(fresh, 0.2) * 100 + min(x["sellers"], 3000) / 300 + (x.get("cart_to_order_percent") or 0) / 5
        out.append(dict(id=x["id"], name=name, revenue_m=round(x["revenue"] / 1e6, 1), aov=round(aov), sellers=x["sellers"],
                        buyout=x.get("purchase_after_return"), season=x.get("seasonality_level"), rating=val,
                        fresh_pct=round(100 * fresh, 1), c2o=x.get("cart_to_order_percent"), score=round(score, 1), pool=a.tag,
                        commission_fbo=x.get("commision_fbo"), commission_fbs=x.get("commision_fbs"),
                        checked=x["id"] in done))
    print("отсеяно:", stats)
    out.sort(key=lambda r: -r["score"])
    print(f"кандидатов: {len(out)}; топ-{a.top} по пред-баллу\n")
    print("| id | Предмет | M ₽ | чек | продавцов | выкуп | сезон | оценка | новых % | корз→заказ | пред-балл |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in out[:a.top]:
        print(f"| {r['id']} | {r['name']} | {r['revenue_m']} | {r['aov']} | {r['sellers']} | {r['buyout']} | {r['season']} | "
              f"{r['rating']} | {r['fresh_pct']} | {r['c2o']} | {r['score']} |")
    json.dump(out, open(os.path.join(ROOT, a.date, a.pages, f"screen_{a.tag}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
