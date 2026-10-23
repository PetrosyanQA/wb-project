"""Глубокая проверка ниши из сохранённого products500 (Saleflow) + отзывы WB + СПП Evirma. 0 запросов Saleflow.

    python -m src.deep_check 3018 374 6370 8163 --dir data/raw/saleflow/2026-10-23/deep4    # → reports/deep_check_<дата>.md

По каждой нише: концентрация (top-10 карточек, top-1 продавец, продавцов в top-20), медиана рейтинга top-20, новички top-100
(с 2025-08), доля Китая, медиана цены/продаж top-100, отзывы 10 лидеров (feedbacks1.wb.ru, кэш) → доля негатива и темы жалоб,
СПП конкурентов FBS (Evirma). Пороги — из CLAUDE.md «Target product profile» (top-10 ≤ 40 %, top-1 ≤ 25 %, ≥ 8 продавцов в top-20,
медиана рейтинга ≤ 4,75, жалоба ≥ 12 % негатива).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date.today().isoformat()
THEMES = {
    "брак / сломалось": r"брак|сломал|слома|трещ|разбит|отвалил|оторвал|не работ|развалил|лопнул|порвал",
    "качество / хлипкое": r"качеств|хлипк|тонк|дешев|ненадеж|непрочн|кривой|криво",
    "не соответствует описанию / фото": r"не соответств|не как на фото|отличается|другой цвет|не тот|описани",
    "размер": r"размер|маленьк|большой|мелк|не подош|не подход",
    "запах": r"запах|воня",
    "упаковка / доставка": r"упаков|доставк|помят|вскрыт|коробк",
    "некомплект": r"некомплект|не хватает|нет в комплекте|не положили",
    "неудобно": r"неудоб|скольз|не держ|падает|шата",
}


def load(path: Path) -> list[dict]:
    d = json.load(open(path, encoding="utf-8"))
    return d.get("data", d) if isinstance(d, dict) else d


def complaints(skus: list[int]) -> dict:
    from src.niche_monitor import feedbacks                     # niche_final_rank читает sys.argv при импорте — не годится
    from src.wb_cdn_card import fetch
    fb_dir = str(ROOT / "data" / "raw" / "wb_feedbacks")
    tot, neg, texts, seen = 0, 0, [], set()
    for sku in skus:
        imt = (fetch(sku) or {}).get("imt_id")
        if not imt or imt in seen:
            continue
        seen.add(imt)
        F = feedbacks(imt, fb_dir)
        N = [f for f in F if (f.get("productValuation") or 5) <= 3]
        tot += len(F); neg += len(N)
        texts += [((f.get("text") or "") + " " + (f.get("cons") or "")).lower() for f in N]
    th = sorted(((t, sum(1 for x in texts if re.search(p, x))) for t, p in THEMES.items()), key=lambda z: -z[1])
    return {"cards": len(seen), "total": tot, "neg": neg, "neg_pct": round(neg / tot * 100, 1) if tot else None,
            "themes": [(t, n, round(n / len(texts) * 100) if texts else 0) for t, n in th]}


def check(sid: int, base: Path) -> tuple[dict, list[str]]:
    f = base / str(sid) / "products500_2026-07.json"
    if not f.exists():                                          # ниша могла собираться в другой папке того же дня
        f = next(iter(sorted(base.parent.glob(f"*/{sid}/products500_2026-07.json"))), f)
    if not f.exists():
        return {}, [f"## {sid}", "— нет products500 (не собран)"]
    rows = sorted(load(f), key=lambda r: -(r.get("revenue") or 0))
    tot = sum(r.get("revenue") or 0 for r in rows) or 1
    sel = collections.Counter()
    for r in rows:
        sel[r.get("seller")] += r.get("revenue") or 0
    t100 = rows[:100]
    m = {"subject": rows[0].get("subject") if rows else sid,
         "top10": round(sum(r.get("revenue") or 0 for r in rows[:10]) / tot * 100),
         "top1_seller": round(sel.most_common(1)[0][1] / tot * 100) if sel else None,
         "sellers_top20": len({r.get("seller") for r in rows[:20]}),
         "rating_top20": st.median([r.get("rating") or 0 for r in rows[:20]]) if rows else None,
         "new_top100": sum(1 for r in t100 if (r.get("sku_first_date") or "") >= "2025-08"),
         "china": round(sum(r.get("revenue") or 0 for r in t100 if (r.get("country") or "") == "Китай")
                        / (sum(r.get("revenue") or 0 for r in t100) or 1) * 100),
         "price_med": st.median([r.get("final_price") or 0 for r in t100]) if t100 else None,
         "sales_med": st.median([r.get("sales") or 0 for r in t100]) if t100 else None,
         "spp_avg": st.median([r.get("spp_avg") or 0 for r in t100]) if t100 else None}
    m["fb"] = complaints([r["id"] for r in rows[:10]])
    try:
        from src import evirma as E
        rg = E.ranges([sid], retries=1).get(sid)
        m["evirma_fbs"] = "; ".join(f"{b['price_from']}–{b['price_to'] or '∞'} → {b['spp']:g} %" for b in rg["fbs"]) if rg else None
    except Exception:                                           # noqa: BLE001
        m["evirma_fbs"] = None
    ok = lambda c: "✅" if c else "❌"                           # noqa: E731
    fb = m["fb"]
    top_theme = fb["themes"][0] if fb["themes"] else ("—", 0, 0)
    L = [f"## {sid} {m['subject']}",
         "| Ցուցանիշ | Արժեք | Շեմ |", "|---|---|---|",
         f"| Top-10 քարտերի բաժին | {m['top10']} % | {ok(m['top10'] <= 40)} ≤ 40 % |",
         f"| Top-1 վաճառող | {m['top1_seller']} % | {ok((m['top1_seller'] or 0) <= 25)} ≤ 25 % |",
         f"| Վաճառողներ top-20-ում | {m['sellers_top20']} | {ok(m['sellers_top20'] >= 8)} ≥ 8 |",
         f"| Top-20 մեդիանա վարկանիշ | {m['rating_top20']} | {ok((m['rating_top20'] or 5) <= 4.75)} ≤ 4,75 |",
         f"| Նորեկներ top-100-ում (2025-08-ից) | {m['new_top100']} | — |",
         f"| Չինաստանի բաժին top-100-ում | {m['china']} % | — |",
         f"| Մեդիանա գին / վաճառք top-100 | {m['price_med']:.0f} ₽ / {m['sales_med']:.0f} հատ/ամիս | — |",
         f"| Կարծիքներ (10 լիդեր, {fb['cards']} քարտ) | {fb['total']}, բացասական {fb['neg_pct']} % | — |",
         f"| Գլխավոր բողոք | {top_theme[0]} — {top_theme[2]} % բացասականի | {ok(top_theme[2] >= 12)} ≥ 12 % |",
         f"| СПП FBS (Evirma) | {m['evirma_fbs'] or '—'} | — |",
         "", "Բողոքների թեմաներ՝ " + ", ".join(f"{t} {p} %" for t, n, p in fb["themes"][:5]),
         "", "Լիդերներ՝"]
    for r in rows[:8]:
        L.append(f"- {r['id']} {r['name'][:50]} — {r.get('final_price')} ₽, {r.get('sales')} հատ, ★{r.get('rating')}, {r.get('country') or '—'}")
    return m, L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("subjects", nargs="+", type=int)
    ap.add_argument("--dir", default="data/raw/saleflow/2026-10-23/deep4")
    a = ap.parse_args()
    base = ROOT / a.dir
    out, M = [f"# Խորը ստուգում — {TODAY}", "Աղբյուր՝ Saleflow products500 (2026-07-01 … 2026-07-31), WB feedbacks, Evirma. [факт], սխալ ±10–20 %.", ""], {}
    for s in a.subjects:
        m, L = check(s, base)
        M[s] = m
        out += L + [""]
    rep = ROOT / "reports" / f"deep_check_{TODAY}.md"
    rep.write_text("\n".join(out), encoding="utf-8")
    json.dump(M, open(ROOT / "data" / "processed" / f"deep_check_{TODAY}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n".join(out)); print("→", rep.relative_to(ROOT))


if __name__ == "__main__":
    main()
