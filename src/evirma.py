"""СПП (скидка WB для покупателя) по категориям — Evirma (evirma.ru/spp, публичные данные без входа, Москва).

    python -m src.evirma show 249 654          # текущая СПП по ценовым полосам (FBO / FBS) + 30 дней истории
    python -m src.evirma snapshot              # все ≈ 5 900 категорий → data/processed/evirma_spp_<дата>.csv (≈ 60 запросов)

Зачем: у кабинета из Армении СПП ≈ 0, у конкурентов из РФ — скидка WB. Чем она выше в нише, тем сильнее конкурентов
субсидирует WB и тем ниже их цена для покупателя при той же выручке. Значения API — в сотых долях процента (1700 = 17 %), границы цен — в копейках (переводим в ₽).
Правило проекта: при анализе ниш СПП брать отсюда (обязательно), а не из оценок.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
API = "https://evirma.ru/api/server/wb/spp"
H = {"User-Agent": "Mozilla/5.0", "content-type": "application/json", "Referer": "https://evirma.ru/spp"}
RAW = "data/raw/evirma"


def _post(ep: str, ids: list[int], retries: int = 6) -> list[dict]:
    out = []
    for i in range(0, len(ids), 100):                                     # API принимает ≤ 100 категорий за запрос
        for attempt in range(retries):
            r = requests.post(f"{API}/{ep}", headers=H, json={"subjects": ids[i:i + 100]}, timeout=60)
            if r.status_code != 429:
                break
            time.sleep(int(r.headers.get("Retry-After") or 0) or 20 * (attempt + 1))   # сервис ограничивает частоту
        r.raise_for_status()
        out += r.json().get("data") or []
        time.sleep(3)                                                     # бережно к чужому сервису
    return out


def subjects() -> dict[int, str]:
    r = requests.get(f"{API}/subjects", headers=H, timeout=60)
    r.raise_for_status()
    return {s["subject_wb_id"]: s["name"] for s in r.json()["data"]["subjects"]}


def ranges(ids: list[int], retries: int = 6) -> dict[int, dict]:
    """→ {subject: {"date", "fbo": [полосы], "fbs": [полосы]}}; полоса: price_from, price_to, spp (%), spp_max, articles, zero_pct."""
    res = {}
    for d in _post("subject-ranges", ids, retries):
        dims = d.get("dimensions") or {}
        pct = lambda v: v / 100 if v is not None else None                                                # noqa: E731
        rub = lambda v: v // 100 if v is not None else None                                               # noqa: E731
        conv = lambda L: [{"price_from": rub(b["price_from"]), "price_to": rub(b["price_to"]), "spp": pct(b["spp_mode"]),   # noqa: E731
                           "spp_max": pct(b["spp_max"]), "articles": b["articles"], "zero_pct": b.get("zero_articles_percent")}
                          for b in L or []]
        res[d["subject_wb_id"]] = {"date": d.get("date"), "stale": d.get("is_stale"), "fbo": conv(dims.get("fbo")), "fbs": conv(dims.get("fbs"))}
    return res


def history(ids: list[int]) -> dict[int, list[dict]]:
    return {d["subject_wb_id"]: [{k: (v / 100 if k.startswith("spp") and v is not None else v) for k, v in it.items()} for it in d.get("items") or []]
            for d in _post("subject-history", ids)}


def spp_at(r: dict, price: float, model: str = "fbs") -> float | None:
    """СПП конкурентов модели model (fbo/fbs) в полосе, куда попадает цена ДО СПП."""
    for b in r.get(model) or []:
        if price >= b["price_from"] and (b["price_to"] is None or price < b["price_to"]):
            return b["spp"]
    return None


def snapshot() -> str:
    names = subjects()
    rg = ranges(list(names))
    today = dt.date.today().isoformat()
    os.makedirs(f"{RAW}/{today}", exist_ok=True)
    json.dump(rg, open(f"{RAW}/{today}/ranges.json", "w", encoding="utf-8"), ensure_ascii=False)
    out = f"data/processed/evirma_spp_{today}.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject", "name", "date", "fbo_spp", "fbo_spp_max", "fbo_articles", "fbs_bands", "fbs_spp_low", "fbs_spp_high", "fbs_zero_pct"])
        for sid, r in sorted(rg.items()):
            fbo = (r["fbo"] or [{}])[0]
            fbs = r["fbs"] or []
            bands = "; ".join(f"{b['price_from']}–{b['price_to'] or '∞'}: {b['spp']}%" for b in fbs)
            w.writerow([sid, names.get(sid, ""), r["date"], fbo.get("spp"), fbo.get("spp_max"), fbo.get("articles"), bands,
                        fbs[0]["spp"] if fbs else None, fbs[-1]["spp"] if fbs else None, fbs[0]["zero_pct"] if fbs else None])
    print(f"категорий: {len(rg)} → {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "snapshot"])
    ap.add_argument("ids", nargs="*", type=int)
    a = ap.parse_args()
    if a.cmd == "snapshot":
        snapshot()
        return
    rg, hi = ranges(a.ids), history(a.ids)
    for sid in a.ids:
        r = rg.get(sid, {})
        print(f"\n{sid} ({r.get('date')}):")
        for m in ("fbo", "fbs"):
            print(f"  {m.upper()}: " + "; ".join(f"{b['price_from']}–{b['price_to'] or '∞'} ₽ → {b['spp']} % (до {b['spp_max']} %, {b['articles']} карт.)"
                                              for b in r.get(m, [])))
        h = hi.get(sid, [])
        if h:
            print(f"  30 дней FBO: {h[0]['spp_fbo']} → {h[-1]['spp_fbo']} %, FBS: {h[0]['spp_fbs']} → {h[-1]['spp_fbs']} %")


if __name__ == "__main__":
    main()
