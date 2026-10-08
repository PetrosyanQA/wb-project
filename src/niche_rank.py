"""Рейтинг ниш по сохранённым выводам saleflow_eval (ничего не запрашивает).

    python -m src.niche_rank [YYYY-MM-DD]

Допуск: шаги 2, 3, 4, 5 = PASS (+ рег не FAIL). Балл 0–100 — нормировка по допущенным нишам.
Экономика пересчитывается по медианной цене/объёму из items.json (econ.json перезаписывается
каждым ручным расчётом и для сравнения не годится). Комиссия — реальная из wb_seller (COMMISSION).
"""
import json, os, sys, glob

from .saleflow_eval import load_strategy, napkin_econ
from .unit_econ import load_config as load_ue_config

sys.stdout.reconfigure(encoding="utf-8")
# реальная FBO-комиссия из `python -m src.wb_seller commission --subject ...`
COMMISSION = {"termos": 19.5, "nozhi-kuhonnye": 19.5, "stolovye-pribory": 19.5, "tochilka": 19.5,
              "chehly-planshet": 24.5, "koshelki": 24.5, "nozhi-turist": 17.5, "vakuumatory": 14.5,
              "chasy-naruchnye": 24.5}
# «Реальность» для бюджета $2 000 (товар 104 500 ₽). batch_days = партия / продажи 50-го места
# (products-снимок 15 дн, пересчёт на 30). Источник расчёта — reports/niche2_*.md.
REALISM = {
    "nozhi-kuhonnye":   {"batch_days": 18, "electronics": False, "size_m": 257},
    "stolovye-pribory": {"batch_days": 12, "electronics": False, "size_m": 225},
    "vakuumatory":      {"batch_days": 7,  "electronics": True,  "size_m": 241},
    "chasy-naruchnye":  {"batch_days": 12, "electronics": False, "size_m": 567},
    "termos":           {"batch_days": None, "electronics": False, "size_m": None},
}


def realism_penalty(n):
    r = REALISM.get(n, {})
    pen, why = 0, []
    if r.get("batch_days") is not None and r["batch_days"] < 10:
        pen += 10; why.append(f"партия = {r['batch_days']} дн продаж")
    if r.get("electronics"):
        pen += 10; why.append("электроника/брак")
    if (r.get("size_m") or 0) > 250:
        pen += 5; why.append(f"ниша {r['size_m']} M ₽ > 250 M ₽")
    return pen, why
# объём упаковки, когда products-ответ не содержит габаритов (источник — в комментарии)
VOLUME_OVERRIDE = {"vakuumatory": 4.0}  # wb_card_content 964706217: товар 36×10×7 см + коробка
DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-03"
ROOT = os.path.join("data", "raw", "saleflow", DATE)

# (ключ, вес, больше_лучше)
WEIGHTS = [("peak_lo", 20, True), ("r12_lo", 15, True), ("comments_top20", 15, False),
           ("fresh_top20", 10, True), ("top1", 10, False), ("ceiling_pct", 15, True),
           ("logistics_pct", 5, False), ("complaint_pct", 10, True)]
SEASON_PENALTY = (4.0, 10)  # пик/дно > ×4 → −10


def load(n, f):
    p = os.path.join(ROOT, n, f)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def complaint_share(cm):
    """Средняя доля общей темы у лидеров с достаточным негативом."""
    themes = (cm or {}).get("common_themes") or {}
    best = 0.0
    for t in themes:
        shares = [s["themes"][t]["share_pct"] for s in cm["per_sku"]
                  if s.get("enough") and t in s.get("themes", {})]
        if shares:
            best = max(best, sum(shares) / len(shares))
    return best


def econ_at_median(n, it, ec_saved, ue, s):
    price = (it or {}).get("median_price")
    vol = (it or {}).get("median_volume_l") or VOLUME_OVERRIDE.get(n)
    if not price or not vol:
        return ec_saved
    return napkin_econ(price, vol, COMMISSION.get(n, s["default_commission_pct"]), ue, s)


def collect():
    rows = []
    ue, s = load_ue_config(), load_strategy()
    for tp in sorted(glob.glob(os.path.join(ROOT, "*", "trends.json"))):
        n = os.path.basename(os.path.dirname(tp))
        tr, se, it, ec, cm, rg = (load(n, f) for f in
                                  ("trends.json", "sellers.json", "items.json", "econ.json", "comments.json", "reg.json"))
        ec = econ_at_median(n, it, ec, ue, s)
        v = {k: (d or {}).get("verdict") for k, d in
             (("reg", rg), ("sellers", se), ("items", it), ("econ", ec), ("trends", tr), ("comments", cm))}
        pk = (tr or {}).get("peak_yoy") or [{}]
        rows.append(dict(
            niche=n, v=v,
            peak_lo=pk[-1].get("lo_pct"), r12_lo=((tr or {}).get("rolling12") or {}).get("lo_pct"),
            comments_top20=(it or {}).get("median_comments_top20"), fresh_top20=(it or {}).get("fresh_in_top20"),
            top1=(se or {}).get("top1_pct"), ceiling_pct=(ec or {}).get("max_cost_share_pct"),
            logistics_pct=(ec or {}).get("logistics_share_pct"), complaint_pct=complaint_share(cm),
            season=((tr or {}).get("seasonal") or {}).get("peak_to_trough"),
        ))
    return rows


def admitted(r):
    v = r["v"]
    return (v["reg"] != "FAIL" and all(v[k] == "PASS" for k in ("sellers", "items", "trends", "comments"))
            and v["econ"] in ("PASS", None) and all(r[k] is not None for k, _, _ in WEIGHTS))


def score(rows):
    ok = [r for r in rows if admitted(r)]
    for k, w, up in WEIGHTS:
        vals = [r[k] for r in ok]
        lo, hi = min(vals), max(vals)
        for r in ok:
            x = 0.5 if hi == lo else (r[k] - lo) / (hi - lo)
            r.setdefault("parts", {})[k] = round(w * (x if up else 1 - x), 1)
    for r in ok:
        pen = SEASON_PENALTY[1] if (r["season"] or 0) > SEASON_PENALTY[0] else 0
        r["score"] = round(sum(r["parts"].values()) - pen, 1)
        rp, why = realism_penalty(r["niche"])
        r["real_score"], r["real_why"] = round(r["score"] - rp, 1), why
    return sorted(ok, key=lambda r: -r["real_score"]), [r for r in rows if not admitted(r)]


if __name__ == "__main__":
    ok, rest = score(collect())
    print("## Допущены (шаги 2–5 PASS)\n")
    print("| # | Ниша | Итог (с реальностью) | Балл рынка | пик YoY низ | 12м низ | отзывы топ-20 | свежих | top-1 | потолок % | логист. % | жалоба % | пик/дно | штрафы реальности |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for i, r in enumerate(ok, 1):
        print(f"| {i} | {r['niche']} | {r['real_score']} | {r['score']} | {r['peak_lo']} | {r['r12_lo']} | {r['comments_top20']} | "
              f"{r['fresh_top20']} | {r['top1']} | {r['ceiling_pct']} | {r['logistics_pct']} | "
              f"{round(r['complaint_pct'], 1)} | {r['season']} | {'; '.join(r['real_why']) or '—'} |")
    print("\n## Не допущены\n")
    for r in rest:
        bad = [f"{k}={v}" for k, v in r["v"].items() if v not in ("PASS",)]
        print(f"- {r['niche']}: {', '.join(bad) or 'нет данных метрик'}")
    json.dump([{k: v for k, v in r.items()} for r in ok], open(os.path.join(ROOT, "ranking.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
