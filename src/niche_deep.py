"""Глубокий разбор ниши за 12 месяцев: продажи и предложение по месяцам, поисковые запросы по месяцам, дефицит, форматы.

    python -m src.niche_deep scan 1302 874 …        # новые ниши: products500 июль + тренды (2 запроса на нишу) → потом screen_white
    python -m src.niche_deep risers 8986 --include "сумк" --price 2300 3600   # восходящие модели июнь→июль + продажи по дням (1 + 6 запросов)
    python -m src.niche_deep collect 249 804        # Saleflow: 1 (тренды) + 12 (запросы по месяцам) на нишу; скачанное — 0
    python -m src.niche_deep report 249 804         # 0 запросов → reports/niche_deep_<id>_<дата>.md + вывод в чат
    python -m src.niche_deep report 249 --include "подтягив|турник"   # форматы только точного типа товара
    python -m src.niche_deep report 8986 --include "тоут|шоппер" --price 2400 3600   # формат и новички в премиум-сегменте

Период: 12 полных месяцев 2025-08 … 2026-07 (после 2026-07-31 Saleflow отдаёт неполные продажи) против 2024-08 … 2025-07.
Источники:
  тренды   — wb_subject trends group_by=month → data/raw/saleflow/niche_deep/trends_<id>.json
             (sales, revenue, items_with_sells = карточек с продажами, sellers_with_sells)
  запросы  — wb_subject keywords за каждый месяц → data/raw/saleflow/seo_gap/<месяц>/kw_<id>.json (общий кэш с seo_gap)
             wb_count = поисков WB в месяц, items_count = карточек ЭТОЙ ниши по запросу (count — НЕ предложение)
  форматы  — products500 июль 2026 (как в screen_white): одиночный товар / набор N шт по названию.
Раздел 4 (идеи WB Analyzer): упущенная выручка (lost_profit) по ценовым полосам, снайпер (лидер > 300 тыс. ₽, остаток < 7 дней),
уязвимые лидеры (топ-30 с < 5 фото / рейтингом < 4,2 / без видео / < 50 отзывов), восходящие звёзды (≤ 60 дней на сайте, > 30 продаж).
Дефицит:
  ниша    — продажи растут быстрее, чем число карточек с продажами → продаж на карточку больше (год к году);
  запрос  — поисков в месяц на одну карточку ниши (wb_count / items_count); высокий = спрос есть, предложения мало.
  Месяцы, где сумма поисков > ×2 или < ×0,5 медианы, — сбой выгрузки (2026-07: ×3), исключаются; тренд поиска = последние 3 мес к первым 3.
  Скачок карточек с продажами > ×1,67 / < ×0,6 за месяц = смена классификации → год к году ненадёжно.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "saleflow"
CUR = [f"{y}-{m:02d}" for y, m in [(2025, i) for i in range(8, 13)] + [(2026, i) for i in range(1, 8)]]
PREV = [f"{int(m[:4]) - 1}{m[4:]}" for m in CUR]
BRANDS = re.compile(r"pandora|пандор|cartier|картье|tiffany|тиффани|van ?cleef|ван ?клиф|hermes|гермес|chanel|шанель|dior|диор|ysl|"
                    r"balenciaga|баленсиага|gucci|гуччи|prada|прада|louis ?vuitton|луи ?витон|apple|nike|найк|adidas|адидас", re.I)   # копии брендов — риск ИС, не берём
SET_RE = re.compile(r"набор|комплект|\d+\s*(шт|штук|предмет)|\d+\s*в\s*1|\bпар[аы]?\b", re.I)


def trends_path(sid: int) -> Path:
    return RAW / "niche_deep" / f"trends_{sid}.json"


def kw_path(sid: int, month: str) -> Path:
    return RAW / "seo_gap" / month / f"kw_{sid}.json"


def month_range(ym: str) -> tuple[str, str]:
    y, m = map(int, ym.split("-"))
    return f"{ym}-01", f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


# ── сбор ─────────────────────────────────────────────────────────────────────
def collect(ids: list[int]) -> None:
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch, quota
    todo = []
    for sid in ids:
        if not trends_path(sid).exists():
            todo.append((trends_path(sid), {"subject_id": sid, "report": "trends", "d1": "2024-08-01", "d2": "2026-07-31", "group_by": "month"}))
        todo += [(kw_path(sid, m), {"subject_id": sid, "report": "keywords", "d1": month_range(m)[0], "d2": month_range(m)[1]})
                 for m in CUR + ["2025-07"] if not kw_path(sid, m).exists()]
    print(f"запросов Saleflow к сбору: {len(todo)}")
    if not todo:
        return
    c, streak = Client(), 0
    print("квота до:", quota(c))
    for n, (p, args) in enumerate(todo, 1):
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            json.dump(fetch(c, "wb_subject", args), open(p, "w", encoding="utf-8"), ensure_ascii=False)
            streak = 0
            print(f"{n}/{len(todo)} ok {p.relative_to(ROOT)}", flush=True)
        except Exception as e:                                        # noqa: BLE001
            streak += 1
            print(f"{n}/{len(todo)} ERR {p.name}: {str(e)[:90]}", flush=True)
            c = Client()
            if streak >= 3:
                print("3 сбоя подряд — стоп (сбои тоже списывают квоту)")
                break
    print("квота после:", quota(c))


def scan(ids: list[int], products_only: bool = False) -> None:
    """Быстрый сбор для ещё не просмотренных ниш: products500 за июль 2026 (+ запасной limit=100) и тренды по месяцам. 2 запроса на нишу."""
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch, quota
    pdir = RAW / "v3_products500"
    todo = []
    for sid in ids:
        if not (pdir / f"{sid}.json").exists() and not (RAW / "v3_products100" / f"{sid}.json").exists():
            todo.append(("p", sid))
        if not products_only and not trends_path(sid).exists():
            todo.append(("t", sid))
    print(f"запросов Saleflow к сбору: ≈ {len(todo)}")
    if not todo:
        return
    c, streak = Client(), 0
    print("квота до:", quota(c))
    for n, (kind, sid) in enumerate(todo, 1):
        try:
            if kind == "p":
                try:
                    res = fetch(c, "wb_subject", {"subject_id": sid, "report": "products", "d1": "2026-07-01", "d2": "2026-07-31", "limit": 500})
                    out = pdir / f"{sid}.json"
                except Exception:                                       # noqa: BLE001 — тяжёлый запрос, пробуем 100
                    c = Client()
                    res = fetch(c, "wb_subject", {"subject_id": sid, "report": "products", "d1": "2026-07-01", "d2": "2026-07-31", "limit": 100})
                    out = RAW / "v3_products100" / f"{sid}.json"
            else:
                res = fetch(c, "wb_subject", {"subject_id": sid, "report": "trends", "d1": "2024-08-01", "d2": "2026-07-31", "group_by": "month"})
                out = trends_path(sid)
            out.parent.mkdir(parents=True, exist_ok=True)
            json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)
            streak = 0
            print(f"{n}/{len(todo)} ok {out.relative_to(ROOT)}", flush=True)
        except Exception as e:                                          # noqa: BLE001
            streak += 1
            print(f"{n}/{len(todo)} ERR {kind} {sid}: {str(e)[:90]}", flush=True)
            c = Client()
            if streak >= 3:
                print("3 сбоя подряд — стоп")
                break
    print("квота после:", quota(c))


# ── разбор ───────────────────────────────────────────────────────────────────
def rows_of(d):
    if isinstance(d, dict):
        return d.get("data") or d.get("queries") or d.get("result") or []
    return d or []


def trends(sid: int) -> dict[str, dict]:
    p = trends_path(sid)
    if not p.exists():
        hit = sorted(RAW.glob(f"*/strategy{sid}/trends_month.json"))
        if not hit:
            return {}
        p = hit[-1]
    return {r["label_date"][:7]: r for r in rows_of(json.load(open(p, encoding="utf-8")))}


def pct(a, b):
    return round((a / b - 1) * 100) if a and b else None


def sales_block(sid: int) -> tuple[list[str], dict]:
    T = trends(sid)
    if not all(m in T for m in CUR):
        return [f"Нет помесячных продаж за 12 месяцев (нужно `collect {sid}`)."], {}
    g = lambda ms, k: sum(T[m].get(k) or 0 for m in ms if m in T)
    per = lambda m: (T[m]["sales"] / T[m]["items_with_sells"]) if T.get(m) and T[m].get("items_with_sells") else None
    L = ["| Месяц | Продаж, шт | Выручка, млн ₽ | Карточек с продажами | Продавцов | Продаж на карточку | Год к году, продажи |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for m, pm in zip(CUR, PREV):
        r = T[m]
        L.append(f"| {m} | {r['sales']:,} | {r['revenue'] / 1e6:.1f} | {r['items_with_sells']:,} | {r['sellers_with_sells']:,} | "
                 f"{per(m):.1f} | {pct(r['sales'], (T.get(pm) or {}).get('sales')) if T.get(pm) else '—'} % |".replace(",", " "))
    s_now, s_old = g(CUR, "sales"), g(PREV, "sales")
    i_now = st.mean(T[m]["items_with_sells"] for m in CUR)
    i_old = st.mean(T[m]["items_with_sells"] for m in PREV if m in T) if all(m in T for m in PREV) else None
    peak = max(CUR, key=lambda m: T[m]["sales"])
    low = min(CUR, key=lambda m: T[m]["sales"])
    peak_prev = f"{int(peak[:4]) - 1}{peak[4:]}"
    m = dict(sales_yoy=pct(s_now, s_old) if all(x in T for x in PREV) else None,
             items_yoy=pct(i_now, i_old) if i_old else None,
             peak=peak, peak_yoy=pct(T[peak]["sales"], (T.get(peak_prev) or {}).get("sales")),
             season_ratio=round(T[low]["sales"] / T[peak]["sales"], 2), low=low,
             winter=round(st.mean(T[x]["sales"] for x in ("2025-12", "2026-01", "2026-02")) / T["2026-07"]["sales"], 2),
             per_item_now=round(st.mean(per(x) for x in CUR), 1),
             per_item_old=round(st.mean(per(x) for x in PREV), 1) if all(per(x) for x in PREV if x in T) and i_old else None)
    seq = [x for x in PREV + CUR if x in T]
    jumps = [x for a_, x in zip(seq, seq[1:]) if T[a_]["items_with_sells"] and
             not 0.6 <= T[x]["items_with_sells"] / T[a_]["items_with_sells"] <= 1.67]
    m["reclass"] = jumps
    m["deficit"] = (m["sales_yoy"] - m["items_yoy"]) if m["sales_yoy"] is not None and m["items_yoy"] is not None else None
    after = [x for x in CUR if x >= max(jumps)] if jumps else (CUR if m["deficit"] is None else [])   # нет прошлого года → внутри 12 мес
    if len(after) >= 6:                                   # после смены классификации: последние 3 мес к первым 3 внутри окна
        s_tr = pct(st.mean(T[x]["sales"] for x in after[-3:]), st.mean(T[x]["sales"] for x in after[:3]))
        i_tr = pct(st.mean(T[x]["items_with_sells"] for x in after[-3:]), st.mean(T[x]["items_with_sells"] for x in after[:3]))
        m.update(sales_yoy=None, items_yoy=None, deficit=s_tr - i_tr, window=f"{after[0]} … {after[-1]}", sales_tr=s_tr, items_tr=i_tr)
    if jumps:
        L += ["", f"⚠️ Скачок числа карточек с продажами в {', '.join(jumps)} (> ×1,67 или < ×0,6 за месяц) — похоже на смену "
                  "классификации WB/Saleflow: сравнение год к году и дефицит ненадёжны, смотреть месяцы после скачка."]
    if m.get("window"):
        L += ["", f"После скачка ({m['window']}, последние 3 мес к первым 3): продажи **{m['sales_tr']:+} %**, карточек с продажами "
                  f"**{m['items_tr']:+} %** → дефицит **{m['deficit']:+} п.п.** (внутри года — сезон может искажать)."]
    L += [] if m.get("window") or m["deficit"] is None else ["", f"Продажи за 12 мес год к году: **{m['sales_yoy']} %**; карточек с продажами: **{m['items_yoy']} %** → "
          f"дефицит (спрос минус предложение): **{m['deficit']} п.п.**",
          f"Продаж на карточку в месяц: {m['per_item_old']} → {m['per_item_now']}. Пик — {peak} (к пику прошлого года "
          f"{m['peak_yoy']} %), минимум — {low} ({int(m['season_ratio'] * 100)} % пика); зима (дек–фев) = {int(m['winter'] * 100)} % июля."]
    return L, m


def seo_block(sid: int, top: int = 15) -> tuple[list[str], dict]:
    months = [m for m in CUR if kw_path(sid, m).exists()]
    if len(months) < 6:
        return [f"Запросы: есть {len(months)} мес из 12 (нужно `collect {sid}`)."], {}
    load_kw = lambda m: {q["word"]: q for q in rows_of(json.load(open(kw_path(sid, m), encoding="utf-8"))) if q.get("word")}
    K = {m: load_kw(m) for m in months}
    total = {m: sum(q.get("wb_count") or 0 for q in K[m].values()) for m in months}
    med = st.median(total.values())
    bad = [m for m in months if not 0.5 <= total[m] / med <= 2]          # сбой выгрузки Saleflow (так было с 2026-07: ×3)
    good = [m for m in months if m not in bad]
    freq = collections.defaultdict(dict)
    for m in good:
        for w, q in K[m].items():
            freq[w][m] = q.get("wb_count") or 0
    items = {w: (K[good[-1]].get(w) or {}).get("items_count") or max((K[m].get(w) or {}).get("items_count") or 0 for m in good) for w in freq}
    rows = []
    for w, f in freq.items():
        if len(f) < max(6, len(good) // 2):              # запрос есть хотя бы в половине месяцев — иначе разовый всплеск
            continue
        avg = sum(f.values()) / len(good)
        if avg < 1000:
            continue
        it = items.get(w) or 0
        early = st.mean(f.get(m, 0) for m in good[:3])
        late = st.mean(f.get(m, 0) for m in good[-3:])
        rows.append(dict(w=w, avg=round(avg), last=f.get(good[-1], 0), peak=max(f, key=f.get), items=it,
                         per_item=round(avg / it, 1) if it else None, trend=pct(late, early)))
    early_t = st.mean(total[m] for m in good[:3])
    late_t = st.mean(total[m] for m in good[-3:])
    L = ["Поисков по всем запросам ниши (сумма wb_count): " + ", ".join(f"{m[2:]} {total[m] / 1000:.0f}k" + (" ⚠️" if m in bad else "") for m in months)]
    if bad:
        L.append(f"⚠️ Месяцы {', '.join(bad)} выбиваются (> ×2 от медианы) — сбой выгрузки, исключены из расчёта.")
    trend = pct(late_t, early_t)
    L += [f"Поиск: последние 3 мес ({good[-3]} … {good[-1]}) к первым 3 ({good[0]} … {good[2]}): **{trend:+} %**", "",
          "| Запрос | Поисков в месяц (сред.) | Последний месяц | Пик | Карточек ниши | Поисков/мес на карточку | Тренд за год |",
          "|---|---:|---:|---|---:|---:|---:|"]
    by_def = sorted([r for r in rows if r["per_item"]], key=lambda r: -r["per_item"])[:top]
    for r in by_def:
        L.append(f"| {r['w']} | {r['avg']:,} | {r['last']:,} | {r['peak']} | {r['items']:,} | {r['per_item']} | "
                 f"{r['trend'] if r['trend'] is not None else '—'} % |".replace(",", " "))
    grow = sorted([r for r in rows if r["trend"] is not None and r["last"] >= 1000], key=lambda r: -r["trend"])[:8]
    if grow:
        L += ["", "Быстрее всего растут (последние 3 мес к первым 3, ≥ 1 000 поисков): " + "; ".join(f"«{r['w']}» {r['trend']:+} %" for r in grow)]
    return L, dict(queries=len(rows), seo_trend=trend, bad_months=bad, top_deficit=by_def[:5])


MONTH = {"value": "2026-07", "warning": None}           # какой месяц реально взят (пишется в отчёт)


def products(sid: int):
    """Карточки ниши: июль 2026 (надёжный) → иначе октябрь с пометкой «неполные» (аудит 2026-11-01: раньше брался октябрь,
    а в отчёте писалось «июль»)."""
    from src.datastore import products as P
    rows, meta = P(sid, "2026-07")
    if not rows:
        rows, meta = P(sid, "2026-10")
    MONTH.update(value=meta["month"], warning=meta["warning"])
    return rows or []


def format_block(sid: int, include: str | None = None, price: tuple | None = None) -> tuple[list[str], dict]:
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0
    allr = [r for r in products(sid) if r.get("sales") and (not include or re.search(include, r.get("name") or "", re.I))
            and (not price or price[0] <= P(r) < price[1])]
    rows = [r for r in allr if not BRANDS.search(r.get("name") or "")]
    if not rows:
        return [f"Нет карточек ниши (месяц {MONTH['value']})."], {}
    groups = collections.defaultdict(list)
    for r in rows:
        name = r.get("name") or ""
        if SET_RE.search(name):
            n = re.search(r"(\d+)\s*(шт|штук|предмет|в\s*1)", name, re.I)
            groups[f"набор {n.group(1)} {n.group(2)}" if n and int(n.group(1)) <= 50 else "набор (кол-во не указано)"].append(r)
        else:
            groups["1 шт (одиночный)"].append(r)
    total = sum(r["sales"] for r in rows)
    L = ["| Формат | Карточек | Продаж/мес | Доля | Медиана цены | Новичков (с 08.2025) | Продаж у новичка P50 |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    out = []
    for k, g in sorted(groups.items(), key=lambda kv: -sum(r["sales"] for r in kv[1])):
        s = sum(r["sales"] for r in g)
        if s / total < 0.01:
            continue
        new = sorted(r["sales"] for r in g if (r.get("sku_first_date") or "") >= "2025-08")
        out.append(dict(fmt=k, cards=len(g), sales=s, share=round(s / total * 100), med=round(st.median(P(r) for r in g)),
                        new=len(new), new_p50=st.median(new) if new else 0))
        L.append(f"| {k} | {len(g)} | {s:,} | {round(s / total * 100)} % | {round(st.median(P(r) for r in g)):,} ₽ | {len(new)} | "
                 f"{st.median(new) if new else '—'} |".replace(",", " "))
    nb = len(allr) - len(rows)
    if nb:
        L += ["", f"Исключено {nb} карточек — копии брендов ({sum(r['sales'] for r in allr if BRANDS.search(r.get('name') or ''))} шт/мес): риск ИС, такой товар не берём."]
    L += ["", "Формат определяется по названию (набор / комплект / N шт / N в 1) — перед решением проверить 5–10 карточек глазами."]
    return L, dict(formats=out)



def leaders_block(sid: int, include: str | None = None) -> tuple[list[str], dict]:
    """Упущенная выручка по ценовым полосам, снайпер, уязвимые лидеры, восходящие звёзды (идеи WB Analyzer, 2026-10-27)."""
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0
    rows = [r for r in products(sid) if (r.get("sales") or r.get("lost_profit"))
            and (not include or re.search(include, r.get("name") or "", re.I))]
    if not rows:
        return ["Нет products500."], {}
    link = lambda r: f"[{r['id']}](https://www.wildberries.ru/catalog/{r['id']}/detail.aspx)"
    L = [f"**Упущенная выручка по ценовым полосам** (продажи, которых не было из-за пустого склада, {MONTH['value']}):", "",
         "| Цена | Карточек | Выручка, тыс. ₽ | Упущено, тыс. ₽ | Доля упущенного |", "|---|---:|---:|---:|---:|"]
    bands = [(0, 500), (500, 800), (800, 1000), (1000, 1500), (1500, 2000), (2000, 2600), (2600, 3500), (3500, 5000), (5000, 10 ** 6)]
    lost_rows = []
    for lo, hi in bands:
        g = [r for r in rows if lo <= P(r) < hi]
        if len(g) < 3:
            continue
        rev, lost = sum(r.get("revenue") or 0 for r in g), sum(r.get("lost_profit") or 0 for r in g)
        share = round(lost / (rev + lost) * 100) if rev + lost else 0
        lost_rows.append(dict(band=f"{lo}-{hi}", share=share, lost=lost))
        L.append(f"| {lo}–{hi if hi < 10 ** 6 else '…'} ₽ | {len(g)} | {rev / 1000:,.0f} | {lost / 1000:,.0f} | {share} %{' ✅' if share >= 15 else ''} |".replace(",", " "))
    L += ["", "Доля ≥ 15 % = спрос в этой цене не закрыт (у продавцов кончается товар) — признак дефицита."]

    sn = sorted([r for r in rows if (r.get("revenue") or 0) > 300_000 and (r.get("balance") or 0) > 0 and r.get("sales_per_day_average")
                 and r["balance"] / r["sales_per_day_average"] < 7], key=lambda r: -(r.get("revenue") or 0))[:10]
    L += ["", "**Снайпер** — лидеры (> 300 тыс. ₽/мес), у которых остатка меньше чем на 7 дней (на конец периода; для живой работы — "
          "свежие данные в `/prodazhi`):"]
    L += [f"- {link(r)} {r['name'][:50]} — {round(P(r))} ₽, остаток {r['balance']} шт ≈ {r['balance'] / r['sales_per_day_average']:.1f} дн"
          for r in sn] or ["- нет"]

    top = sorted(rows, key=lambda r: -(r.get("revenue") or 0))[:30]
    vul = []
    for r in top:
        why = [w for w, bad in (("мало фото", (r.get("picscount") or 0) < 5), ("рейтинг < 4,2", 0 < (r.get("rating") or 5) < 4.2),
                                ("нет видео", not r.get("hasvideo")), ("< 50 отзывов", (r.get("comments") or 0) < 50)) if bad]
        if len(why) >= 2 or "рейтинг < 4,2" in why or "мало фото" in why:
            vul.append((r, why))
    L += ["", "**Уязвимые лидеры** (топ-30 по выручке со слабой карточкой — их покупателей можно забрать лучшей карточкой):"]
    L += [f"- {link(r)} {r['name'][:50]} — {round(P(r))} ₽, {r['sales']} шт/мес, {r.get('picscount')} фото, рейтинг {r.get('rating')}, "
          f"{r.get('comments')} отз.: {', '.join(w)}" for r, w in vul[:10]] or ["- нет: лидеры с сильными карточками"]

    stars = sorted([r for r in rows if (r.get("days_in_site") or 999) <= 60 and (r.get("sales") or 0) > 30],
                   key=lambda r: -(r["sales"] / max(1, min(r.get("days_with_sales") or 30, 31))))[:10]
    L += ["", "**Восходящие звёзды** (карточки ≤ 60 дней на сайте и > 30 продаж — кто и как взлетел быстрее всех):"]
    L += [f"- {link(r)} {r['name'][:50]} — {round(P(r))} ₽, {r['sales']} шт за {r.get('days_with_sales')} дн с продажами, "
          f"{r.get('days_in_site')} дн на сайте, {r.get('picscount')} фото, видео {'да' if r.get('hasvideo') else 'нет'}, {r.get('comments')} отз."
          + (" ⚠️ склейка: отзывы перенесены со старой карточки" if (r.get("comments") or 0) > 300 else "")
          for r in stars] or ["- нет"]
    return L, dict(lost=lost_rows, sniper=[r["id"] for r in sn], vulnerable=[r["id"] for r, _ in vul], stars=[r["id"] for r in stars])




def segments_block(sid: int, include: str | None = None) -> tuple[list[str], dict]:
    """Ценовые сегменты точного типа: карточки, продажи, новички P25/P50, монополия (доля топ-6 и топ-1 продавцов)."""
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0
    rows = [r for r in products(sid) if r.get("sales") and (not include or re.search(include, r.get("name") or "", re.I))
            and not BRANDS.search(r.get("name") or "")]
    if not rows:
        return ["Нет products500."], {}
    prices = sorted(P(r) for r in rows)
    q = lambda f: prices[int(len(prices) * f)]
    edges = sorted({round(q(f), -2) for f in (0, .2, .4, .6, .8)} | {round(prices[-1] + 100, -2)})
    L = ["| Цена | Карточек | Продаж/мес | Новичков (с 08.2025) | Новичок P25 / P50, шт/мес | Топ-6 продавцов | Топ-1 | Монополия |",
         "|---|---:|---:|---:|---:|---:|---:|---|"]
    out = []
    for lo, hi in zip(edges, edges[1:]):
        g = [r for r in rows if lo <= P(r) < hi]
        if len(g) < 5:
            continue
        sales = sum(r["sales"] for r in g)
        by = collections.Counter()
        for r in g:
            by[r.get("seller")] += r["sales"]
        top6 = round(sum(v for _, v in by.most_common(6)) / sales * 100)
        top1 = round(by.most_common(1)[0][1] / sales * 100)
        new = sorted(r["sales"] for r in g if (r.get("sku_first_date") or "") >= "2025-08")
        mono = "❌ > 60 %" if top6 > 60 else "✅"
        out.append(dict(band=f"{int(lo)}-{int(hi)}", cards=len(g), sales=sales, new=len(new), p25=new[len(new) // 4] if new else 0,
                        p50=st.median(new) if new else 0, top6=top6, top1=top1, ok=top6 <= 60))
        L.append(f"| {int(lo)}–{int(hi)} ₽ | {len(g)} | {sales:,} | {len(new)} | {new[len(new) // 4] if new else '—'} / {st.median(new) if new else '—'} | "
                 f"{top6} % | {top1} % | {mono} |".replace(",", " "))
    L += ["", "Монополия: топ-6 продавцов сегмента > 60 % продаж → сегмент закрыт для новичка (правило пользователя 2026-10-27). "
          "Цену выбираем там, где новички продают не меньше, а прибыль/шт выше (обычно продажи новичка почти не зависят от цены)."]
    return L, dict(segments=out)


def risers(sid: int, include: str | None = None, price: tuple | None = None, daily: int = 6) -> None:
    """Восходящие модели: продажи каждой карточки июнь → июль 2026 + новые карточки + дневные продажи лидеров роста.
    Запросы Saleflow: 1 (products июнь, кэш) + 1 на карточку для дневных данных (by_period, кэш)."""
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch
    P = lambda r: r.get("final_price_average") or r.get("final_price") or 0
    jun_p = RAW / "niche_deep" / f"products_2026-06_{sid}.json"
    c = None
    if not jun_p.exists():
        c = Client()
        json.dump(fetch(c, "wb_subject", {"subject_id": sid, "report": "products", "d1": "2026-06-01", "d2": "2026-06-30", "limit": 500}),
                  open(jun_p, "w", encoding="utf-8"), ensure_ascii=False)
    jun = {r["id"]: r for r in rows_of(json.load(open(jun_p, encoding="utf-8")))}
    ok = lambda r: (not include or re.search(include, r.get("name") or "", re.I)) and (not price or price[0] <= P(r) < price[1]) \
        and not BRANDS.search(r.get("name") or "")
    jul = [r for r in products(sid) if r.get("sales") and ok(r)]
    rows = []
    for r in jul:
        j = jun.get(r["id"]) or {}
        s6, s7 = j.get("sales") or 0, r["sales"]
        new = (r.get("sku_first_date") or "") >= "2026-05"
        if s7 < 60 or (not new and s7 < s6 * 1.5):
            continue
        rows.append(dict(id=r["id"], name=r["name"][:55], price=round(P(r)), jun=s6, jul=s7, growth=pct(s7, s6) if s6 else None,
                         start=(r.get("sku_first_date") or "")[:10], seller=r.get("seller"), new=new,
                         per_day=round(s7 / max(1, r.get("days_with_sales") or 31), 1), reviews=r.get("comments")))
    rows.sort(key=lambda x: -(x["jul"] - x["jun"]))
    L = [f"# Восходящие модели: ниша {sid}" + (f", «{include}»" if include else "") + (f", {price[0]}–{price[1]} ₽" if price else "")
         + f" — июнь → июль 2026 ({dt.date.today()})", "",
         "Отбор: в июле ≥ 60 шт и рост ≥ ×1,5 к июню, или новая карточка (старт с 05.2026). Копии брендов исключены.", "",
         "| SKU | Модель | Цена | Июнь | Июль | Рост | Старт | Шт/день с продажами | Отзывов | Продавец |",
         "|---|---|---:|---:|---:|---:|---|---:|---:|---|"]
    for x in rows[:20]:
        L.append(f"| [{x['id']}](https://www.wildberries.ru/catalog/{x['id']}/detail.aspx) | {x['name']} | {x['price']} ₽ | {x['jun']} | {x['jul']} | "
                 f"{('+' + str(x['growth']) + ' %') if x['growth'] is not None else ('новая' if x['new'] else 'не было в топ-500 июня')} | {x['start']} | {x['per_day']} | {x['reviews']} | {str(x['seller'])[:16]} |")
    if not rows:
        L.append("| — | восходящих моделей нет | | | | | | | | |")
    ddir = RAW / "niche_deep" / "daily"
    ddir.mkdir(parents=True, exist_ok=True)
    L += ["", f"## Продажи по дням: топ-{min(daily, len(rows))} растущих (с 01.05.2026; после 31.07 данные Saleflow неполные)", ""]
    for x in rows[:daily]:
        f = ddir / f"{x['id']}.json"
        if not f.exists():
            c = c or Client()
            try:
                json.dump(fetch(c, "wb_sku", {"sku": x["id"], "report": "by_period", "d1": "2026-05-01", "d2": "2026-07-31"}),
                          open(f, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception as e:                                       # noqa: BLE001
                L.append(f"- {x['id']}: дневные данные не получены ({str(e)[:60]})")
                c = Client()
                continue
        D = sorted(rows_of(json.load(open(f, encoding="utf-8"))), key=lambda d: d.get("data") or "")
        wk = collections.OrderedDict()
        for d in D:
            day = dt.date.fromisoformat(d["data"][:10])
            k = (day - dt.timedelta(days=day.weekday())).isoformat()[5:]
            w = wk.setdefault(k, dict(s=0, ads=0, price=[], stock0=0))
            w["s"] += d.get("sales") or 0
            w["ads"] += 1 if d.get("in_ads") else 0
            w["stock0"] += 0 if d.get("balance") else 1
            if d.get("final_price"):
                w["price"].append(d["final_price"])
        line = " · ".join(f"{k}: {round(v['s'] / 7)}/д" + (" 📣" if v["ads"] >= 4 else "") + (" ⛔" if v["stock0"] >= 4 else "")
                          for k, v in list(wk.items())[-13:])
        prices = [p for v in wk.values() for p in v["price"]]
        L += [f"**{x['id']}** {x['name']} — {x['price']} ₽ (цена за период {min(prices) if prices else '—'}–{max(prices) if prices else '—'} ₽)",
              f"- по неделям: {line}", ""]
    L += ["📣 — реклама ≥ 4 дней в неделю, ⛔ — без остатка ≥ 4 дней. Рост без рекламы и при наличии = органический спрос на модель."]
    text = "\n".join(L)
    out = ROOT / "reports" / f"risers_{sid}_{dt.date.today()}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {out.relative_to(ROOT)}")
    if c:
        c.close()


def report(ids: list[int], include: str | None = None, price: tuple | None = None) -> None:
    from src.screen_white import REQ
    for sid in ids:
        name = (REQ.get(sid) or {}).get("subject", sid)
        a, ms = sales_block(sid)
        b, mk = seo_block(sid)
        c, mf = format_block(sid, include, price)
        d, ml = leaders_block(sid, include)
        e, mseg = segments_block(sid, include)
        verdict = []
        if ms.get("deficit") is not None:
            verdict.append("дефицит ✅" if ms["deficit"] >= 5 else "перенасыщение ⚠️" if ms["deficit"] <= -10 else "баланс")
        if ms.get("sales_yoy") is not None:
            verdict.append("растёт" if ms["sales_yoy"] >= 10 else "падает ⚠️" if ms["sales_yoy"] <= -10 else "плато")
        if mk.get("seo_trend") is not None:
            verdict.append(f"поиск за год {mk['seo_trend']:+} %")
        if ms.get("reclass"):
            verdict.append("⚠️ смена классификации — год к году ненадёжно")
        text = "\n".join([f"# {sid} {name} — 12 месяцев (2025-08 … 2026-07) — {dt.date.today()}", "",
                          f"**Итог:** {', '.join(verdict) or '—'}", "", "## 1. Продажи и предложение по месяцам", *a, "",
                          "## 2. Поисковые запросы по месяцам (дефицит по запросам)", *b, "",
                          f"## 3. Форматы: одиночный или набор ({MONTH['value']})" + (f" {MONTH['warning']}" if MONTH['warning'] else "") + (f" — только «{include}»" if include else "") + (f", цена {price[0]}–{price[1]} ₽" if price else ""), *c, "",
                          "## 4. Лидеры и новички: упущенная выручка, снайпер, уязвимые лидеры, восходящие звёзды", *d, "",
                          "## 5. Ценовые сегменты и монополия (топ-6 продавцов ≤ 60 %)", *e, ""])
        out = ROOT / "reports" / f"niche_deep_{sid}_{dt.date.today()}.md"
        out.write_text(text, encoding="utf-8")
        json.dump(dict(id=sid, sales=ms, seo={k: v for k, v in mk.items()}, formats=mf.get("formats"), leaders=ml, segments=mseg.get("segments")),
                  open(ROOT / "data" / "processed" / f"niche_deep_{sid}_{dt.date.today()}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, default=str)
        print(text)
        print(f"\n→ {out.relative_to(ROOT)}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "report", "scan", "risers"])
    ap.add_argument("ids", nargs="+", type=int)
    ap.add_argument("--include", help="regex по названию: формат только для точного типа товара (например «подтягив|турник»)")
    ap.add_argument("--price", type=int, nargs=2, help="ценовой сегмент формата: продажи и новички только в нём (например 2400 3600)")
    ap.add_argument("--products-only", action="store_true", help="scan: только products500 (1 запрос на нишу), тренды — потом для прошедших")
    a = ap.parse_args()
    if a.cmd == "scan":
        scan(a.ids, a.products_only)
    elif a.cmd == "risers":
        for sid in a.ids:
            risers(sid, a.include, tuple(a.price) if a.price else None)
    else:
        collect(a.ids) if a.cmd == "collect" else report(a.ids, a.include, tuple(a.price) if a.price else None)


if __name__ == "__main__":
    main()
