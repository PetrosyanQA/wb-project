"""Ежемесячный монитор конкурентов ниши — работает и для FBO-продавцов (их продажи/остатки WB скрыл с 08-2026).

    python -m src.niche_monitor --niche 249                 # сбор + отчёт (≈ N+2 запросов Saleflow, остальное бесплатно)
    python -m src.niche_monitor --niche 249 --report-only   # только отчёт из уже собранного

Источники (все, кроме Saleflow, бесплатные):
  • индекс отзывов WB (feedbacks1.wb.ru) — отзывы за последние 30 дней vs предыдущие 30 → заменитель продаж;
    оценка продаж/день = отзывы_30д × (продажи_июль / отзывы_июль) — калибровка по последнему целому месяцу Saleflow;
  • Saleflow wb_sku by_period за 35 дней — цена покупателя, дни рекламы, акции, средняя позиция (не зависят от FBO);
  • Saleflow wb_check_rates (живая выдача) по главным запросам — кто в топ-100 сейчас, кто новый, кто выпал;
  • WB CDN card.json — смена фото/характеристик.
Bright Data: WB-страницы через Web Unlocker возвращают пустой ответ (проверено 2026-10-18), поэтому как резерв не используется.
Снимки: data/raw/monitor/<niche>/<дата>/ ; отчёт: reports/monitor/<niche>_<дата>.md (+ сравнение с прошлым снимком).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
TODAY = dt.date.today()
D2 = (TODAY - dt.timedelta(days=1)).isoformat()
PRESETS = {
    249: {"queries": ["резинка для подтягивания", "резинка для подтягивания на турник"],
          "include": r"подтяг|турник|петл|жгут|лент|резинк", "exclude": r"кистев|ткан|мини|ягодиц|для ног|файтбол|мяч|скул|лиц",
          "extra_skus": [498296546, 558287767], "top": 30},
}
RIP = re.compile(r"порв|лопн|разорв|надорв|треснул|трещин")


def products(niche: int) -> list[dict]:
    from src import datastore as D
    p = D.latest(niche, "products500")
    if not p:
        raise SystemExit(f"нет products500 для {niche}")
    return [r for r in D.rows(p) if r.get("sales")]


def watchlist(niche: int) -> list[dict]:
    cfg = PRESETS[niche]
    inc, exc = re.compile(cfg["include"], re.I), re.compile(cfg["exclude"], re.I)
    rows = sorted(products(niche), key=lambda r: -r["revenue"])
    seen, out = set(), []
    for r in rows:
        if not inc.search(r["name"]) or exc.search(r["name"]) or r.get("itemid") in seen:
            continue
        seen.add(r.get("itemid")); out.append(r)
        if len(out) >= cfg["top"]:
            break
    have = {r["id"] for r in out}
    out += [r for r in rows if r["id"] in cfg["extra_skus"] and r["id"] not in have]
    return out


def feedbacks(imt: int, fb_dir: str) -> list[dict]:
    import requests
    p = f"{fb_dir}/{imt}.json"
    if os.path.exists(p):
        return json.load(open(p, encoding="utf8")).get("feedbacks") or []
    for h in ("feedbacks1", "feedbacks2"):
        try:
            r = requests.get(f"https://{h}.wb.ru/feedbacks/v1/{imt}", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code == 200 and r.text.startswith("{"):
                os.makedirs(fb_dir, exist_ok=True)
                open(p, "w", encoding="utf8").write(r.text)
                return r.json().get("feedbacks") or []
        except Exception:                                                # noqa: BLE001
            pass
    return []


def reviews_window(imt: int, fb_dir: str) -> dict:
    F = feedbacks(imt, fb_dir)
    d30, d60 = (TODAY - dt.timedelta(days=30)).isoformat(), (TODAY - dt.timedelta(days=60)).isoformat()
    last = [f for f in F if f.get("createdDate", "")[:10] >= d30]
    prev = [f for f in F if d60 <= f.get("createdDate", "")[:10] < d30]
    jul = [f for f in F if f.get("createdDate", "")[:7] == "2026-07"]
    neg = [f for f in last if (f.get("productValuation") or 5) <= 3]
    rip = sum(1 for f in neg if RIP.search(" ".join(str(f.get(k) or "") for k in ("text", "cons")).lower()))
    vals = [f.get("productValuation") for f in last if f.get("productValuation")]
    return {"r30": len(last), "r_prev30": len(prev), "r_jul": len(jul), "neg30": len(neg), "rip30": rip,
            "rating30": round(st.mean(vals), 2) if vals else None, "capped": len(F) >= 1000}


def collect(niche: int) -> str:
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch
    out = f"data/raw/monitor/{niche}/{TODAY.isoformat()}"
    os.makedirs(out, exist_ok=True)
    W = watchlist(niche)
    with ThreadPoolExecutor(8) as ex:                                # свежие отзывы в папку снимка, не общий кэш
        revs = list(ex.map(lambda r: reviews_window(r["itemid"], f"{out}/feedbacks"), W))
    c = Client()
    d1 = (TODAY - dt.timedelta(days=36)).isoformat()
    for r in W:
        p = f"{out}/daily_{r['id']}.json"
        if os.path.exists(p):
            continue
        try:
            json.dump(fetch(c, "wb_sku", {"sku": r["id"], "report": "by_period", "d1": d1, "d2": D2}), open(p, "w", encoding="utf8"), ensure_ascii=False)
        except Exception as e:                                           # noqa: BLE001
            print("  by_period не получен:", r["id"], str(e)[:80]); c = Client()
    for i, q in enumerate(PRESETS[niche]["queries"]):
        p = f"{out}/search_{i}.json"
        if not os.path.exists(p):
            try:
                json.dump(fetch(c, "wb_check_rates", {"query": q, "region": "Москва", "limit": 100}), open(p, "w", encoding="utf8"), ensure_ascii=False)
            except Exception as e:                                       # noqa: BLE001
                print("  выдача не получена:", q, str(e)[:80]); c = Client()
    snap = [{"id": r["id"], "itemid": r.get("itemid"), "name": r["name"][:60], "seller": r.get("seller"),
             "sales_jul_day": round(r["sales"] / 31, 1), **v} for r, v in zip(W, revs)]
    json.dump(snap, open(f"{out}/watchlist.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    return out


def daily_stats(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    d = json.load(open(path, encoding="utf8"))
    rows = sorted([r for r in (d if isinstance(d, list) else d.get("data", [])) if r.get("data")], key=lambda r: r["data"])[-30:]
    if not rows:
        return {}
    pr = [r.get("final_price") for r in rows if r.get("final_price")]
    pos = [r.get("search_position_avg") for r in rows if r.get("search_position_avg")]
    return {"price_now": pr[-1] if pr else None, "price_30d_ago": pr[0] if pr else None,
            "ads_pct": round(sum(1 for r in rows if r.get("in_ads")) / len(rows) * 100),
            "promo_pct": round(sum(1 for r in rows if r.get("in_action")) / len(rows) * 100),
            "pos_med": round(st.median(pos)) if pos else None}


def report(niche: int, out: str) -> str:
    snap = json.load(open(f"{out}/watchlist.json", encoding="utf8"))
    prev_dirs = sorted(d for d in glob.glob(f"data/raw/monitor/{niche}/*") if d.replace("\\", "/") != out.replace("\\", "/"))
    prev_search = set()
    if prev_dirs:
        for f in glob.glob(f"{prev_dirs[-1]}/search_*.json"):
            prev_search |= {x["id"] for x in (json.load(open(f, encoding="utf8")).get("data") or [])}
    rows = []
    for s in snap:
        k = (s["sales_jul_day"] / (s["r_jul"] / 31)) if s["r_jul"] else None      # продаж на 1 отзыв (июль)
        est = round(s["r30"] / 30 * k, 1) if k and s["r30"] else None
        dyn = round((s["r30"] / s["r_prev30"] - 1) * 100) if s["r_prev30"] else None
        rows.append({**s, **daily_stats(f"{out}/daily_{s['id']}.json"), "est_sales_day": est, "dyn_pct": dyn})
    rows.sort(key=lambda r: -(r["est_sales_day"] or 0))
    L = [f"# Монитор конкурентов {niche} — {TODAY.isoformat()}", "",
         "Продажи/день — оценка по отзывам за 30 дней (калибровка июль-2026), работает и для FBO. "
         "Цена, реклама, акции, позиция — Saleflow by_period за 30 дней. «Отз. Δ» — отзывы последних 30 дней к предыдущим 30.", "",
         "| SKU | Товар | Продаж/д (оценка) | Июль/д | Отз. 30д | Отз. Δ | Рейтинг 30д | Негатив 30д | «порвалась» | Цена ₽ (30д назад) | Реклама | Акция | Позиция |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|"]
    for r in rows:
        pc = f"{r.get('price_now') or '—'} ({r.get('price_30d_ago') or '—'})"
        L.append(f"| {r['id']} | {r['name'][:38]} | {r['est_sales_day'] if r['est_sales_day'] is not None else '—'} | {r['sales_jul_day']} | {r['r30']} | "
                 f"{'' if r['dyn_pct'] is None else ('+' if r['dyn_pct'] > 0 else '')}{r['dyn_pct'] if r['dyn_pct'] is not None else '—'}% | {r['rating30'] or '—'} | "
                 f"{r['neg30']} | {r['rip30']} | {pc} | {r.get('ads_pct', '—')}% | {r.get('promo_pct', '—')}% | {r.get('pos_med') or '—'} |")
    sig = []
    for r in rows:
        if r["dyn_pct"] is not None and r["dyn_pct"] >= 50 and r["r30"] >= 10:
            sig.append(f"📈 {r['id']} растёт: отзывы {r['r_prev30']} → {r['r30']} (+{r['dyn_pct']}%)")
        if r["dyn_pct"] is not None and r["dyn_pct"] <= -40 and r["r_prev30"] >= 10:
            sig.append(f"📉 {r['id']} падает: отзывы {r['r_prev30']} → {r['r30']} ({r['dyn_pct']}%)")
        if r.get("price_now") and r.get("price_30d_ago") and r["price_now"] <= r["price_30d_ago"] * 0.9:
            sig.append(f"💸 {r['id']} снизил цену {r['price_30d_ago']} → {r['price_now']} ₽")
        if r["neg30"] >= 5 and r["rip30"] / max(r["neg30"], 1) >= 0.3:
            sig.append(f"⚠️ {r['id']} жалобы «порвалась»: {r['rip30']} из {r['neg30']} негативных")
    known = {r["id"] for r in snap}
    for i, q in enumerate(PRESETS[niche]["queries"]):
        f = f"{out}/search_{i}.json"
        if not os.path.exists(f):
            continue
        data = json.load(open(f, encoding="utf8")).get("data") or []
        top = data[:100]
        new = [x for x in top if prev_search and x["id"] not in prev_search]
        unknown = [x for x in top[:30] if x["id"] not in known]
        L += ["", f"## Выдача «{q}» (Москва, сейчас): реклама {sum(1 for x in top if x.get('promoted'))}/100"]
        if new:
            L.append("Новые в топ-100 с прошлого снимка: " + ", ".join(f"{x['id']} ({x.get('final_price')} ₽, поз. {x['position_general']})" for x in new[:15]))
        if unknown:
            L.append("В топ-30, но не в списке наблюдения: " + ", ".join(f"{x['id']} {x.get('name','')[:25]} ({x.get('final_price')} ₽)" for x in unknown[:10]))
    L += ["", "## Сигналы", *(sig or ["— без резких изменений"]), "",
          "Источники: WB отзывы (feedbacks1.wb.ru), Saleflow by_period / wb_check_rates, products500 2026-07 (калибровка). "
          "Отзывы WB отдаёт до 1 000 последних — для очень больших карточек окно 60 дней полное."]
    os.makedirs("reports/monitor", exist_ok=True)
    p = f"reports/monitor/{niche}_{TODAY.isoformat()}.md"
    open(p, "w", encoding="utf8").write("\n".join(L))
    print("\n".join(L[:12 + len(rows)])); print(*sig, sep="\n")
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, default=249)
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    out = f"data/raw/monitor/{a.niche}/{TODAY.isoformat()}" if a.report_only else collect(a.niche)
    print("отчёт:", report(a.niche, out))


if __name__ == "__main__":
    main()
