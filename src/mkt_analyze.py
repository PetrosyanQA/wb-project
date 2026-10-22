"""Маркетинговый анализ ниши из ДАННЫХ ПРОЕКТА (0 запросов Saleflow; Evirma — 1 запрос, при ограничении — пропуск).

    python -m src.mkt_analyze --niche 249            # → reports/marketing/249_<дата>.md (+ печать)
    python -m src.mkt_analyze --niche 249 --no-evirma

Сводит в один план то, что уже собрано другими модулями:
  1. SEO-ядро        — data/processed/keywords<niche>_12m_*.json (частоты WB по месяцам) + слова из keywords_<niche>_*.json
  2. Боли покупателей → УТП — data/processed/complaints_<niche>_*.json (темы негатива)
  3. Живая выдача    — data/processed/pulse_<niche>/last.json (competitor_pulse): реклама, цены, остатки топ-10/30
  4. Реклама конкурентов — data/processed/competitors<niche>_byperiod_*.json: доля дней в рекламе, продажи с/без рекламы
  5. Цена и СПП      — Evirma subject-ranges (что увидит покупатель при нашей цене продавца)
  6. Рекламный бюджет — config/launch.yaml → seller_prices × допустимый ДРР
Метки: [факт] — из сохранённых данных, [оценка] — расчёт, [допущение] — параметр конфига.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import statistics as st
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date.today().isoformat()


def latest(pattern: str) -> Path | None:
    files = sorted(glob.glob(str(ROOT / pattern)))
    return Path(files[-1]) if files else None


def load(p: Path | None):
    return json.load(open(p, encoding="utf-8")) if p else None


def seo(niche: int) -> list[str]:
    L = ["## 1. SEO-ядро (частота запросов WB в месяц)"]
    k = load(latest(f"data/processed/keywords{niche}_12m_*.json"))
    if not k:
        return L + ["— нет файла keywords_12m (собрать: niche_monitor / strategy_collect)"]
    months = sorted(k)
    last, first = months[-1], months[0]
    rows = sorted(((q, k[last].get(q), k[first].get(q)) for q in k[last]), key=lambda r: -(r[1] or 0))
    L += [f"| Запрос | {last} | {first} | Динамика |", "|---|---|---|---|"]
    for q, a, b in rows:
        dyn = f"{(a / b - 1) * 100:+.0f} %" if a and b else "—"
        L.append(f"| {q} | {a or '—'} | {b or '—'} | {dyn} |")
    L.append(f"\n_Период {first} … {last}, [факт] Saleflow `wb_subject keywords` (wb_count)._")
    w = load(latest(f"data/raw/saleflow/*/unique/keywords_{niche}_*.json"))
    if w and w.get("words"):
        top = sorted(w["words"], key=lambda r: -(r.get("wb_count") or 0))[:20]
        L.append("\n**Слова для названия и описания** (топ-20 по частоте): " + ", ".join(r["word"] for r in top))
    return L


def pains(niche: int) -> list[str]:
    L = ["## 2. Боли покупателей → наше УТП"]
    c = load(latest(f"data/processed/complaints_{niche}_*.json"))
    if not c:
        return L + ["— нет complaints-файла"]
    neg = c["neg"] or 1
    L += [f"Отзывов {c['total']}, негативных {c['neg']} [факт].", "", "| Тема негатива | Шт | % негатива | Что пишем/показываем |", "|---|---|---|---|"]
    fix = {"порв": "слайд «не рвётся»: тест растяжения, ТПЭ, гарантия обмена", "нагруз": "таблица цвет → кг, честная нагрузка", "слаб": "подбор ленты по весу тела: таблица кг ↔ вес",
           "жёстк": "линейка нагрузок, совет «начни с лёгкой»", "липн": "ТПЭ без талька и порошка",
           "размер": "размеры в см на фото, сравнение с ладонью", "запах": "«без запаха», ТПЭ без латекса",
           "цвет": "реальный цвет без фильтров", "брак": "проверка каждой ленты, обмен", "упаков": "плотный пакет + вкладыш"}
    for theme, n in c["themes"]:
        hint = next((v for key, v in fix.items() if key in theme.lower()), "—")
        L.append(f"| {theme} | {n} | {n / neg * 100:.0f} % | {hint} |")
    return L


def live(niche: int) -> list[str]:
    L = ["## 3. Живая выдача сейчас (competitor_pulse)"]
    p = ROOT / "data" / "processed" / f"pulse_{niche}" / "last.json"
    d = load(p if p.exists() else None)
    if not d:
        return L + ["— пульс ещё не запускался: `python -m src.competitor_pulse --niche 249`"]
    for top in (10, 30):
        t = [v for v in d.values() if v["pos"] <= top]
        if not t:
            continue
        prices = [v["price"] for v in t if v.get("price")]
        ads = sum(v["ads"] for v in t) / len(t) * 100
        low = sum(1 for v in t if v.get("balance") is not None and v["balance"] <= 5)
        L.append(f"- Топ-{top}: карточек {len(t)}, **в рекламе {ads:.0f} %**, цена покупателя медиана "
                 f"{st.median(prices):.0f} ₽ (мин {min(prices)}, макс {max(prices)}), остаток ≤ 5 шт у {low} [факт]")
    ts = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    L.append(f"\n_Снимок {ts}, Москва._ Вывод: без рекламы в топ-10 не попасть, если доля ≥ 80 %.")
    return L


def rivals(niche: int) -> list[str]:
    L = ["## 4. Реклама и продажи конкурентов (by_period)"]
    f = latest(f"data/processed/competitors{niche}_byperiod_*.json")
    c = load(f)
    if not c:
        return L + ["— нет by_period по конкурентам"]
    L += ["| SKU | Дней | В рекламе | Продаж/день | с рекламой | без | Цена продавца | Нет в наличии, дн |", "|---|---|---|---|---|---|---|---|"]
    lift = []
    for sku, r in sorted(c.items(), key=lambda kv: -(kv[1].get("sales_day") or 0)):
        L.append(f"| {sku} | {r['days']} | {r['ads_pct']} % | {r['sales_day']} | {r['sales_ads']} | {r['sales_noads']} | "
                 f"{r['seller_price']:.0f} ₽ | {r['oos_days']} |")
        if r["sales_noads"] and r["sales_ads"]:
            lift.append(r["sales_ads"] / r["sales_noads"])
    if lift:
        L.append(f"\nПродажи в дни рекламы выше в **×{st.median(lift):.1f}** (медиана) [оценка; корреляция, не причина].")
    L.append(f"_Источник: {f.name}, Saleflow ≤ 2026-07-31 надёжно._")
    return L


def price_spp(niche: int, prices: dict, use_evirma: bool) -> list[str]:
    L = ["## 5. Цена продавца → цена покупателя (СПП, Evirma)"]
    if not prices:
        return L + ["— в config/launch.yaml нет seller_prices"]
    from src import evirma as E
    r = None
    if use_evirma:
        try:
            r = E.ranges([niche], retries=1).get(niche)
        except Exception as e:                                   # noqa: BLE001
            L.append(f"Evirma недоступна ({str(e)[:60]}) — СПП не посчитан.")
    L += ["| Артикул | Цена продавца | СПП FBS | Видит покупатель | Порог СПП рядом? |", "|---|---|---|---|---|"]
    for name, p in prices.items():
        spp = E.spp_at(r, p, "fbs") if r else None
        bands = [b["price_from"] for b in (r or {}).get("fbs", []) if b["price_from"]]
        near = next((f"порог {b} ₽: −{p - b} ₽" for b in bands if 0 <= p - b <= 100), "") or next(
            (f"до порога {b} ₽: +{b - p} ₽" for b in bands if 0 < b - p <= 100), "—")
        L.append(f"| {name} | {p} ₽ | {f'{spp:g} %' if spp is not None else '—'} | "
                 f"{f'{p * (1 - spp / 100):.0f} ₽' if spp is not None else '—'} | {near} |")
    if r:
        L.append(f"\n_Evirma {r['date']}, FBS-полосы: " + "; ".join(f"{b['price_from']}–{b['price_to'] or '∞'} → {b['spp']:g} %" for b in r["fbs"]) + "._")
    return L


def budget(prices: dict, drr: float, buyout: float) -> list[str]:
    L = [f"## 6. Рекламный бюджет при ДРР {drr:g} % [допущение]", "| Артикул | Цена | На рекламу с заказа | С выкупа (выкуп {:g} %) |".format(buyout), "|---|---|---|---|"]
    for name, p in prices.items():
        per_order = p * drr / 100
        L.append(f"| {name} | {p} ₽ | {per_order:.0f} ₽ | {per_order / (buyout / 100):.0f} ₽ |")
    L.append("\nСтавка за клик не выше: «на рекламу с заказа» × конверсия клик→заказ (при 3 % [допущение] → ×0,03).")
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, default=249)
    ap.add_argument("--no-evirma", action="store_true")
    a = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "launch.yaml").read_text(encoding="utf-8")) or {}
    prices = cfg.get("seller_prices") or {}
    mk = cfg.get("marketing") or {}
    parts = [f"# Маркетинговый анализ ниши {a.niche} — {TODAY}", "Собрано из данных проекта командой `python -m src.mkt_analyze`.",
             *seo(a.niche), "", *pains(a.niche), "", *live(a.niche), "", *rivals(a.niche), "",
             *price_spp(a.niche, prices, not a.no_evirma), "", *budget(prices, mk.get("drr_pct", 15), mk.get("buyout_pct", 82)),
             "", "Հաջորդ քայլը: перенести SEO-слова и УТП в карточку (`src/wb_card.py`), первый слайд — главная боль из п. 2."]
    text = "\n".join(parts)
    out = ROOT / "reports" / "marketing" / f"{a.niche}_{TODAY}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print("\n→", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
