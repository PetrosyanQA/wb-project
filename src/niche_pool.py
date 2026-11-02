"""Копилка хороших ниш (пока ждём Saleflow): лучший сегмент каждой ниши + метки ловушек + что проверить. 0 запросов.

    python -m src.niche_pool                 # из самого свежего data/processed/screen_white_*_all.json
    python -m src.niche_pool --min-month 50000

Вход — `python -m src.screen_white --all` (все ниши, кроме одежды/обуви/магнитов). Выход:
  reports/niche_pool_<дата>.md                 — таблица кандидатов по статусам (полный текст для чтения)
  data/processed/niche_pool_<дата>.json        — то же для кода
  data/processed/niche_collect_queue_<дата>.json — ниши без товаров за июль (докачать, когда вернётся Saleflow)
Статусы: КАНДИДАТ — проходит отбор, без ловушек, топ-6 ≤ 65 % (монополию оцениваем только при ≥ 40 карточках сегмента), объём известен (метки «сезон ?», «документы» — для сведения);
ПРОВЕРИТЬ — топ-6 > 65 % или объём — допущение; ЛОВУШКА — летний сезон / громоздкое / брендовая электроника / книги. Цифры — Saleflow июль 2026
(данным > 30 дней — предварительно) и модель am_fbs с ¥ = 11 % цены [допущение]; прибыль — оценка до проверки ¥ на 1688.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
SUMMER = ("палат", "шатр", "беседк", "бассейн", "круги для плав", "сорняк", "защиты растений", "насосы", "ролики", "спальник",
          "туристич", "надувн", "солнцезащ", "вентилятор", "кондиционер", "удобрен", "семена", "газон", "садов", "полив", "купальн")
BULKY = ("наполнител", "аэрогрил", "водонагрев", "гантел", "штанг", "мебел", "матрас", "холодильник", "плиты", "стиральн")
BRAND_ELEC = ("наушник", "смарт-час", "смартфон", "планшет", "ssd", "накопител", "ноутбук", "телевизор", "приставк", "медиаплеер")
BOOKS = ("книг", "учебник", "журнал")
CLOTH_ROOTS = ("одежд", "обувь", "белье")


def tags(r: dict) -> list[str]:
    s, t, flags = str(r["subj"]).lower(), [], str(r.get("flags") or "").lower()
    if any(w in s for w in SUMMER):
        t.append("летний сезон")
    if any(w in s for w in BULKY) or (not r["vol_assumed"] and r["vol"] > 3):
        t.append("громоздкое")
    if any(w in s for w in BRAND_ELEC):
        t.append("брендовая электроника (¥ ≠ 11 %)")
    if any(w in s for w in BOOKS):
        t.append("книги")
    return t


def notes(r: dict) -> list[str]:
    n, flags = [], str(r.get("flags") or "").lower()
    if r["winter"] is None:
        n.append("сезон ?")
    elif r["winter"] < 0.8:
        n.append(f"зимой ×{r['winter']}")
    if r["verdict"] in ("🟡", "❓", "❌"):
        n.append({"🟡": "документы", "❓": "документы ?", "❌": "ЧЗ/документы — оформить"}[r["verdict"]])
    if "электро" in flags or "батарея" in flags:
        n.append("электроника/аккумулятор")
    if "жидкость" in flags:
        n.append("жидкость")
    if r["vol_assumed"]:
        n.append("объём — допущение 2 л")
    if r["top6"] > 60 and r["cards"] >= 40:
        n.append(f"топ-6 {r['top6']} %")
    return n


def score(r: dict) -> int:
    return r["month8_winter"] if r["month8_winter"] is not None else r["month8"]


def build(src: str, min_month: int) -> tuple[list[dict], list[dict]]:
    seg = json.load(open(src, encoding="utf-8"))
    good = [r for r in seg if r["ymax_pct"] >= 14.3 and r["new_p50"] >= 30 and r["top1"] <= 35 and r["batch_units"] >= 80
            and (r["winter"] is None or r["winter"] >= 0.6)]
    best: dict[int, dict] = {}
    for r in good:
        if score(r) >= min_month and (r["id"] not in best or score(r) > score(best[r["id"]])):
            best[r["id"]] = r
    pool = []
    for r in sorted(best.values(), key=lambda x: -score(x)):
        t = tags(r)
        n = notes(r)
        # документы и «сезон ?» — только метки (решение пользователя: запрет — магниты); в ПРОВЕРИТЬ — монополия и неизвестный объём
        status = "ЛОВУШКА" if t else ("ПРОВЕРИТЬ" if (r["top6"] > 65 and r["cards"] >= 40) or r["vol_assumed"] else "КАНДИДАТ")
        pool.append({"id": r["id"], "subject": r["subj"], "status": status, "band": r["band"], "buyer": r["buyer"],
                     "cards": r["cards"], "sales": r["sales"], "new": r["new"], "new_p50": r["new_p50"], "top1": r["top1"],
                     "top6": r["top6"], "sellers": r["sellers"], "vol": r["vol"], "spp": r["spp"], "com": r["com"],
                     "buyout": r["buyout"], "ymax": r["ymax"], "margin15": r["margin15"], "profit8": r["profit8"],
                     "month_est": score(r), "season": r["winter"], "traps": t, "notes": n,
                     "saleflow_todo": ["живая выдача 2–3 формулировки (src.radar)", f"niche_inside {r['id']} --month 2026-10",
                                       "жалобы product_deep", "свежие продажи сен–окт"]})
    return pool, seg


def queue(seg: list[dict]) -> list[dict]:
    req = json.load(open(sorted(glob.glob(str(ROOT / "data/processed/niche_requirements_2[0-9][0-9][0-9]-*.json")))[-1], encoding="utf-8"))
    have = {r["id"] for r in seg}
    from src.datastore import products
    out = []
    for r in req:
        if r["id"] in have or "магнит" in str(r.get("flags")).lower() or any(w in str(r.get("root")).lower() for w in CLOTH_ROOTS):
            continue
        if not (products(r["id"], "2026-07")[0] or []):
            out.append({"id": r["id"], "subject": r["subject"], "root": r.get("root"), "rev_mln": r.get("rev_mln"),
                        "median_price": r.get("median_price"), "verdict": r.get("verdict", "")[:2]})
    return sorted(out, key=lambda x: -(x["rev_mln"] or 0))


def render(pool: list[dict], q: list[dict], src: str) -> str:
    today = dt.date.today()
    lines = [f"# Копилка ниш — {today}", "",
             f"Источник: `{Path(src).name}` (Saleflow, июль 2026 — предварительно; ¥ = 11 % цены [допущение]). "
             f"Ниш в копилке: {len(pool)} (КАНДИДАТ {sum(p['status'] == 'КАНДИДАТ' for p in pool)}, "
             f"ПРОВЕРИТЬ {sum(p['status'] == 'ПРОВЕРИТЬ' for p in pool)}, ЛОВУШКА {sum(p['status'] == 'ЛОВУШКА' for p in pool)}). "
             f"Ниш без данных (докачать): {len(q)}.", "",
             "Колонки: лучший ценовой сегмент ниши; новички = карточки с 08.2025, P50 — медиана их продаж в месяц; "
             "₽/мес — прибыль/шт (ДРР 8 %) × P50 новичка (× зимний коэффициент, если сезон известен) — **оценка**.", ""]
    for st in ("КАНДИДАТ", "ПРОВЕРИТЬ", "ЛОВУШКА"):
        rows = [p for p in pool if p["status"] == st]
        lines += [f"## {st} ({len(rows)})", "",
                  "| id | Ниша | Сегмент | Цена | Карточек | Новички P50 | Топ-1 / топ-6 | ¥max | Маржа ДРР15 | ₽/мес (оценка) | Метки |",
                  "|---:|---|---|---:|---:|---:|---|---:|---:|---:|---|"]
        for p in rows:
            m = "; ".join(p["traps"] + p["notes"]) or "—"
            lines.append(f"| {p['id']} | {p['subject']} | {p['band']} | {p['buyer']} ₽ | {p['cards']} | {p['new_p50']} | "
                         f"{p['top1']} / {p['top6']} % | {p['ymax']} | {p['margin15']} % | {p['month_est']:,} | {m} |".replace(",", " "))
        lines.append("")
    lines += ["## Когда вернётся Saleflow — порядок", "",
              "1. Докачать ниши без данных (очередь `data/processed/niche_collect_queue_<дата>.json`, сначала крупные по выручке).",
              "2. `python -m src.screen_white --all` → `python -m src.niche_pool` (копилка обновится).",
              "3. Для КАНДИДАТОВ по убыванию ₽/мес: живая выдача (`src.radar`), жалобы, ¥ на 1688, экономика → решение до 09.11.", "",
              f"## Очередь на докачку — топ-40 из {len(q)} (по выручке ниши)", "",
              "| id | Ниша | Корень | Выручка, млн ₽ | Медиана цены | Документы |", "|---:|---|---|---:|---:|---|"]
    lines += [f"| {x['id']} | {x['subject']} | {x['root']} | {x['rev_mln']} | {x['median_price']} | {x['verdict']} |" for x in q[:40]]
    lines += ["", "Следующий шаг: новый токен Saleflow → шаг 1 очереди."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--min-month", type=int, default=50_000)
    a = ap.parse_args()
    src = a.src or sorted(glob.glob(str(ROOT / "data/processed/screen_white_*_all.json")))[-1]
    pool, seg = build(src, a.min_month)
    q = queue(seg)
    today = dt.date.today()
    json.dump(pool, open(ROOT / f"data/processed/niche_pool_{today}.json", "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(q, open(ROOT / f"data/processed/niche_collect_queue_{today}.json", "w", encoding="utf-8"), ensure_ascii=False)
    out = ROOT / f"reports/niche_pool_{today}.md"
    out.write_text(render(pool, q, src), encoding="utf-8")
    c = {s: sum(p["status"] == s for p in pool) for s in ("КАНДИДАТ", "ПРОВЕРИТЬ", "ЛОВУШКА")}
    print(f"копилка: {len(pool)} ниш {c}; без данных (докачать): {len(q)} → {out.relative_to(ROOT)}")
    for p in [p for p in pool if p["status"] == "КАНДИДАТ"][:25]:
        print(f"  {p['id']:>5} {p['subject'][:28]:<28} {p['band']:>9} {p['buyer']:>5} ₽ P50 {p['new_p50']:>6} топ1 {p['top1']:>2}% "
              f"топ6 {p['top6']:>3}% → {p['month_est']:>8} ₽/мес")


if __name__ == "__main__":
    main()
