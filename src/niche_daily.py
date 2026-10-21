"""Ежедневный журнал ниши: продажи, новые отзывы, цены, реклама, позиции — по каждой карточке, каждый день.

    python -m src.niche_daily --niche 249            # ≈ 2 + 40 запросов Saleflow, отзывы WB бесплатно
    python -m src.niche_daily --niche 249 --no-saleflow

Что пишет (дописывает, повторный запуск в тот же день ничего не дублирует):
  data/processed/monitor_249/daily.csv    — строка на (дата, SKU): отзывы за день (+негатив, «порвалась»), всего отзывов,
                                             рейтинг, продажи Saleflow (FBS видны, FBO с 09-2026 нет), оценка продаж по отзывам,
                                             цена, реклама, акция, позиция, место в живой выдаче, FBS/FBO;
  data/processed/monitor_249/reviews/<imt>.jsonl — каждый новый отзыв один раз (без данных покупателя);
  reports/monitor/daily/249_<дата>.md     — итоги вчерашнего дня.
Отзывы приходят с задержкой модерации, поэтому последние 7 дней пересчитываются каждый запуск (upsert), как и by_period.
Охват: все ленты из products500 (≈ 270 карточек) + топ-100 живой выдачи по запросам пресета; Saleflow by_period —
топ-30 по выручке + новые карточки из топ-30 выдачи (до --sf-max).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor

from src.niche_monitor import PRESETS, RIP, products

sys.stdout.reconfigure(encoding="utf-8")
TODAY = dt.date.today()
YDAY = (TODAY - dt.timedelta(days=1)).isoformat()
DAYS = [(TODAY - dt.timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
FIELDS = ["date", "sku", "imt", "name", "source", "fbs", "rev_new", "rev_neg", "rev_rip", "rev_total", "rating",
          "sf_sales", "balance", "sales", "sales_src", "est_sales", "price", "ads", "promo", "pos_avg", "words", "search_pos"]


def bands(niche: int) -> list[dict]:
    cfg = PRESETS[niche]
    inc, exc = re.compile(cfg["include"], re.I), re.compile(cfg["exclude"], re.I)
    return sorted((r for r in products(niche) if inc.search(r["name"]) and not exc.search(r["name"])), key=lambda r: -r["revenue"])


def imt_of(sku: int, cache: dict) -> int | None:
    if str(sku) not in cache:
        from src import wb_cdn_card
        imt = (wb_cdn_card.fetch(sku) or {}).get("imt_id")
        if not imt:
            return None                                                  # не кэшируем промах — завтра попробуем снова
        cache[str(sku)] = imt
    return cache[str(sku)]


def get_feedbacks(imt: int) -> dict:
    import requests
    for h in ("feedbacks1", "feedbacks2"):
        try:
            r = requests.get(f"https://{h}.wb.ru/feedbacks/v1/{imt}", headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if r.status_code == 200 and r.text.startswith("{"):
                return r.json()
        except Exception:                                                # noqa: BLE001
            pass
    return {}


def store_reviews(base: str, imt: int, F: list[dict]) -> None:
    """Новые отзывы — в jsonl по склейке; id покупателя и прочие персональные поля не сохраняем."""
    p = f"{base}/reviews/{imt}.jsonl"
    seen = set()
    if os.path.exists(p):
        seen = {json.loads(x)["id"] for x in open(p, encoding="utf8")}
    new = [f for f in F if f["id"] not in seen]
    if new:
        with open(p, "a", encoding="utf8") as fh:
            for f in sorted(new, key=lambda f: f["createdDate"]):
                fh.write(json.dumps({k: f.get(k) for k in ("id", "nmId", "createdDate", "productValuation", "text", "pros", "cons",
                                                            "color", "size")} | {"answered": bool(f.get("answer"))}, ensure_ascii=False) + "\n")


def calib_k(base: str, B: list[dict], fb: dict) -> dict:
    """Продаж на один отзыв по июлю-2026 (последний полный месяц продаж Saleflow) для каждого SKU; иначе медиана ниши."""
    p = f"{base}/k.json"
    if os.path.exists(p):
        return json.load(open(p, encoding="utf8"))
    k = {}
    for r in B:
        F = (fb.get(r.get("itemid")) or {}).get("feedbacks") or []
        jul = sum(1 for f in F if f.get("nmId") == r["id"] and f["createdDate"][:7] == "2026-07")
        if jul >= 5 and len(F) < 1000:
            k[str(r["id"])] = round(r["sales"] / jul, 1)
    med = st.median(k.values()) if k else 20
    k = {"_median": med, **{s: min(max(v, med / 4), med * 4) for s, v in k.items()}}
    json.dump(k, open(p, "w", encoding="utf8"), indent=1)
    return k


def load_rows(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    return {(r["date"], r["sku"]): r for r in csv.DictReader(open(path, encoding="utf8"))}


def run(niche: int, saleflow: bool, sf_max: int) -> str:
    base = f"data/processed/monitor_{niche}"
    raw = f"data/raw/monitor/{niche}/daily/{TODAY.isoformat()}"
    os.makedirs(f"{base}/reviews", exist_ok=True); os.makedirs(raw, exist_ok=True)
    B = bands(niche)
    cards = {r["id"]: {"sku": r["id"], "imt": r.get("itemid"), "name": r["name"][:60], "source": "products500"} for r in B}
    jul_rank = {r["id"]: i for i, r in enumerate(B)}

    # 1. живая выдача (Saleflow, 1 запрос на запрос) — кто в топ-100 сейчас, FBS/FBO, место
    search, c = {}, None
    if saleflow:
        from src.saleflow_stdio import Client
        from src.strategy_collect import fetch
        c = Client()
        for i, q in enumerate(PRESETS[niche]["queries"]):
            p = f"{raw}/search_{i}.json"
            if not os.path.exists(p):
                try:
                    json.dump(fetch(c, "wb_check_rates", {"query": q, "region": "Москва", "limit": 100}), open(p, "w", encoding="utf8"), ensure_ascii=False)
                except Exception as e:                                   # noqa: BLE001
                    print("  выдача не получена:", q, str(e)[:80]); c = Client(); continue
            for x in json.load(open(p, encoding="utf8")).get("data") or []:
                s = search.setdefault(x["id"], {"pos": x["position_general"], "fbs": x.get("is_fbs"), "name": x.get("name", "")})
                s["pos"] = min(s["pos"], x["position_general"])
    imt_cache_p = f"{base}/imt.json"
    imt_cache = json.load(open(imt_cache_p, encoding="utf8")) if os.path.exists(imt_cache_p) else {}
    for sku, s in search.items():
        if sku not in cards:
            cards[sku] = {"sku": sku, "imt": imt_of(sku, imt_cache), "name": s["name"][:60], "source": "выдача"}
    json.dump(imt_cache, open(imt_cache_p, "w", encoding="utf8"))

    # 2. отзывы WB по всем склейкам (бесплатно)
    imts = sorted({v["imt"] for v in cards.values() if v["imt"]})
    with ThreadPoolExecutor(16) as ex:
        fb = dict(zip(imts, ex.map(get_feedbacks, imts)))
    for imt, d in fb.items():
        store_reviews(base, imt, d.get("feedbacks") or [])
    K = calib_k(base, B, fb)

    # 3. Saleflow by_period за 7 дней: топ-30 + новые из топ-30 выдачи
    daily = {}
    if saleflow:
        top = [r["id"] for r in B[:PRESETS[niche]["top"]]] + PRESETS[niche]["extra_skus"]
        top += [s for s, v in sorted(search.items(), key=lambda kv: kv[1]["pos"]) if v["pos"] <= 30 and s not in top]
        for sku in list(dict.fromkeys(top))[:sf_max]:
            p = f"{raw}/daily_{sku}.json"
            if not os.path.exists(p):
                try:
                    json.dump(fetch(c, "wb_sku", {"sku": sku, "report": "by_period", "d1": DAYS[0], "d2": YDAY}), open(p, "w", encoding="utf8"), ensure_ascii=False)
                except Exception as e:                                   # noqa: BLE001
                    print("  by_period не получен:", sku, str(e)[:80]); c = Client(); continue
            d = json.load(open(p, encoding="utf8"))
            for r in (d if isinstance(d, list) else d.get("data", [])):
                if r.get("data"):
                    daily[(r["data"], sku)] = r

    # 4. upsert строк за последние 7 дней
    path = f"{base}/daily.csv"
    rows = load_rows(path)
    for sku, v in cards.items():
        d = fb.get(v["imt"]) or {}
        F = [f for f in d.get("feedbacks") or [] if f.get("nmId") == sku] or []
        for day in DAYS:
            new = [f for f in F if f["createdDate"][:10] == day]
            neg = [f for f in new if (f.get("productValuation") or 5) <= 3]
            sf = daily.get((day, sku), {})
            k = K.get(str(sku), K["_median"])
            old = rows.get((day, str(sku)), {})
            rows[(day, str(sku))] = {
                "date": day, "sku": sku, "imt": v["imt"], "name": v["name"], "source": v["source"],
                "fbs": search.get(sku, {}).get("fbs", old.get("fbs", "")),
                "rev_new": len(new), "rev_neg": len(neg),
                "rev_rip": sum(1 for f in neg if RIP.search(f"{f.get('text') or ''} {f.get('cons') or ''}".lower())),
                "rev_total": sf.get("comments") or (d.get("feedbackCount") if day == YDAY else old.get("rev_total", "")),
                "rating": sf.get("rating") or (d.get("valuation") if day == YDAY else old.get("rating", "")),
                "sf_sales": sf.get("sales", old.get("sf_sales", "")),
                "balance": sf.get("balance", old.get("balance", "")),
                "est_sales": round(len(new) * k, 1),
                "price": sf.get("final_price", old.get("price", "")), "ads": sf.get("in_ads", old.get("ads", "")),
                "promo": sf.get("in_action", old.get("promo", "")), "pos_avg": sf.get("search_position_avg", old.get("pos_avg", "")),
                "words": sf.get("search_words_count", old.get("words", "")),
                "search_pos": search.get(sku, {}).get("pos", "") if day == YDAY else old.get("search_pos", ""),
            }
    # Надёжность продаж. Saleflow видит только FBS-часть продавца: если за 7 дней отзывов > 25 % от продаж Saleflow
    # (норма 2–6 %), значит, часть продаж идёт с FBO и скрыта → «факт, неполный» (нижняя граница).
    rev7, sf7 = {}, {}
    for (d, s_), r in rows.items():
        if d in DAYS:
            rev7[s_] = rev7.get(s_, 0) + int(r.get("rev_new") or 0)
            sf7[s_] = sf7.get(s_, 0) + float(r.get("sf_sales") or 0)
    for (d, s_), r in rows.items():
        has_sf = r.get("sf_sales") not in ("", None) and float(r.get("balance") or 0) > 0
        if has_sf and (rev7.get(s_, 0) < 3 or rev7[s_] <= 0.25 * sf7.get(s_, 0)):
            r["sales"], r["sales_src"] = r["sf_sales"], "факт"
        elif has_sf:
            r["sales"], r["sales_src"] = r["sf_sales"], "факт, неполный"
        else:
            r["sales"], r["sales_src"] = r["est_sales"], "оценка"
    with open(path, "w", encoding="utf8", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS); w.writeheader()
        for key in sorted(rows):
            w.writerow({f: rows[key].get(f, "") for f in FIELDS})
    return report(niche, rows, jul_rank, len(cards), len(daily) > 0)


def report(niche: int, rows: dict, jul_rank: dict, n_cards: int, has_sf: bool) -> str:
    num = lambda x: float(x) if x not in ("", None) else None                     # noqa: E731
    y = [r for (d, _), r in rows.items() if d == YDAY]
    w = [r for (d, _), r in rows.items() if d in DAYS[:-1]]
    tot = lambda R, f: round(sum(num(r[f]) or 0 for r in R), 1)                     # noqa: E731
    L = [f"# Ниша {niche}: день {YDAY}", "",
         f"Карточек под наблюдением: {n_cards} (ленты из products500 + живая выдача). Отзывы WB — все карточки; "
         f"Saleflow (цена/реклама/продажи) — топ-30 + новые в выдаче. Отзывы за последние дни ещё дописываются модерацией WB.", "",
         "| Показатель | Вчера | Среднее за 6 дней до |", "|---|---:|---:|",
         f"| Новых отзывов (все карточки) | {tot(y, 'rev_new')} | {round(tot(w, 'rev_new') / 6, 1)} |",
         f"| из них негатив (≤3★) | {tot(y, 'rev_neg')} | {round(tot(w, 'rev_neg') / 6, 1)} |",
         f"| из них «порвалась» | {tot(y, 'rev_rip')} | {round(tot(w, 'rev_rip') / 6, 1)} |",
         f"| Продажи, шт (FBS — факт Saleflow, FBO — оценка по отзывам) | {tot(y, 'sales')} | {round(tot(w, 'sales') / 6, 1)} |",
         *[f"| из них {k} | {tot([r for r in y if r['sales_src'] == k], 'sales')} | "
           f"{round(tot([r for r in w if r['sales_src'] == k], 'sales') / 6, 1)} |" for k in ("факт", "факт, неполный", "оценка")]]
    week = {}
    for (d, s_), r in rows.items():
        if d in DAYS:
            a = week.setdefault(str(s_), {"r": r, "sales": 0, "rev": 0, "neg": 0, "rip": 0, "src": set()})
            a["sales"] += num(r["sales"]) or 0; a["rev"] += int(r["rev_new"] or 0); a["neg"] += int(r["rev_neg"] or 0)
            a["rip"] += int(r["rev_rip"] or 0); a["src"].add(r["sales_src"])
            if d == YDAY:
                a["r"] = r
    L += ["", f"## Топ-20 карточек за 7 дней ({DAYS[0]} … {YDAY})", "",
          "Одна карточка за один день — шум (1–2 отзыва), поэтому по карточкам показываю сумму за 7 дней.", "",
          "| SKU | Товар | FBS/FBO | Продажи 7д | Надёжность | Отзывы 7д | Негатив | Порв. | Цена ₽ | Реклама | Место в выдаче |",
          "|---|---|:-:|---:|---|---:|---:|---:|---:|:-:|---:|"]
    for s_, a in sorted(week.items(), key=lambda kv: -kv[1]["sales"])[:20]:
        r = a["r"]; fbs = {"1": "FBS", "0": "FBO"}.get(str(r["fbs"]), "—")
        src = "факт, неполный" if "факт, неполный" in a["src"] else ("факт" if a["src"] == {"факт"} else "оценка ±50 %")
        L.append(f"| {s_} | {str(r['name'])[:34]} | {fbs} | {round(a['sales'])} | {src} | {a['rev']} | {a['neg']} | {a['rip']} | "
                 f"{r['price'] or '—'} | {'да' if str(r['ads']) == '1' else ('нет' if str(r['ads']) == '0' else '—')} | {r['search_pos'] or '—'} |")
    sig = []
    by = {(d, str(s)): r for (d, s), r in rows.items()}
    for r in y:
        old = by.get((DAYS[0], str(r["sku"])), {})
        p0, p1 = num(old.get("price", "")), num(r["price"])
        if p0 and p1 and abs(p1 / p0 - 1) >= 0.1:
            sig.append(f"💸 {r['sku']} цена {int(p0)} → {int(p1)} ₽ за неделю")
        if r["source"] == "выдача" and r["search_pos"] and int(r["search_pos"]) <= 30:
            sig.append(f"🆕 {r['sku']} в топ-30 выдачи (место {r['search_pos']}), не было в июльском топ-500")
        if (num(r["rev_neg"]) or 0) >= 3:
            sig.append(f"⚠️ {r['sku']} {r['rev_neg']} негативных отзывов за день (порвалась: {r['rev_rip']})")
    L += ["", "## Сигналы", *(sig or ["— без резких изменений"]), "",
          f"Данные: data/processed/monitor_{niche}/daily.csv (по дням и SKU), отзывы — data/processed/monitor_{niche}/reviews/. "
          "Оценка продаж = новые отзывы × (продажи/отзывы июля-2026 этой карточки) — [оценка]. Проверка 2026-10-21: по карточке "
          "ошибка до ×19 к факту FBS; по нише сумма в 2–2,5 раза ниже июльского уровня с поправкой на сезон. Поэтому оценку "
          "читать как ИНДЕКС (рост/падение день к дню, неделя к неделе), а не как штуки. Надёжно: число отзывов, негатив, "
          "цена, реклама, место в выдаче; продажи «факт» — только у чистых FBS-продавцов."]
    os.makedirs("reports/monitor/daily", exist_ok=True)
    p = f"reports/monitor/daily/{niche}_{YDAY}.md"
    open(p, "w", encoding="utf8").write("\n".join(L))
    print("\n".join(L))
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, default=249)
    ap.add_argument("--no-saleflow", action="store_true")
    ap.add_argument("--sf-max", type=int, default=45)
    a = ap.parse_args()
    print("отчёт:", run(a.niche, not a.no_saleflow, a.sf_max))


if __name__ == "__main__":
    main()
