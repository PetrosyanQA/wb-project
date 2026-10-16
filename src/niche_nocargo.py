"""Поиск ниши «v1 без карго» (2026-10-16): одна воронка, объединяющая методы всех волн v1–v6, БЕЗ карго-фильтров. 0 запросов.

    python -m src.niche_nocargo          # → data/processed/niche_nocargo_<дата>.json, reports/niche_nocargo_<дата>.md/.xlsx

Снято (карго): «чувств. груз» (v1/v2), запрет по названию магнит/аккумулятор/батарейки/электроника/жидкости (v1, v5),
отсев карточек electro (v5). Оставлено: Честный знак, регистрация/оружие/еда/18+, габарит-корни (список src.niche_v6).
Этапы:
  0. universe  — все предметы июля ≥ 5 млн ₽, ≥ 30 продавцов, медиана ≥ 400 ₽, выкуп ≥ 55 % (как v5/v6, без карго-запретов);
  1. новички   — products500 июля (кэш любой волны): ценовые полосы v5 (+4 000–6 000), новичок 2025-08…2026-05,
                 P50 ≥ 4/день, ≥ 5 новичков, ≥ 3 продавцов-победителей, top-1 полосы ≤ 35 % (v4/v5);
  2. сезон     — индекс 2026 (all_niches_season), июль < 50 % среднего → июль не пересчитываем (отсев);
  3. экономика — max ¥ при марже ≥ 18 % и ROI ≥ 60 % (схема am_fbs + карго), ДРР 10/15 %; габарит из карточек, иначе 0,8 л / 0,35 кг;
                 маржа ДРР 15 % при закупке = 9 % цены покупателя [допущение, как v5];
  4. Китай     — доля Китая в полосе (v2: < 50 % — флаг, не отсев);
  5. история   — статусы ниши во всех прошлых волнах (niche_merge), отметка «карго мешал раньше».
Статус: ✅ полоса прошла и маржа ≥ 18 % · 🟡 полоса прошла, маржа 0–18 % · ❌ причина · ⏳ products500 не собран (ждёт квоты v6).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys

from src import niche_v6  # noqa: F401  — подменяет запреты/полосы niche_v5 на «без карго»
from src import niche_v5 as V
from src.screen_v4 import max_yuan
from src.strategy import econ_config

sys.stdout.reconfigure(encoding="utf-8")
P = "data/processed"
TODAY = dt.date.today().isoformat()
OUT_J = f"{P}/niche_nocargo_{TODAY}.json"
OUT_MD = f"reports/niche_nocargo_{TODAY}.md"
OUT_X = f"reports/niche_nocargo_{TODAY}.xlsx"
CARGO = re.compile(r"чувств|магнит|карго|electro|аккум|батаре|жидк", re.I)
KIZ = re.compile(r"косметик|пилинг|депиляц|красота / пенки", re.I)   # ЧЗ-косметика, которую пропускает BAN_NAME v6 («косметич»)
KIZ_CHECK = re.compile(r"туалетн|пеленк|подгузн", re.I)   # возможен ЧЗ — проверить need_kiz по карточке
SHARE = 0.09                                           # закупка = 9 % цены покупателя [допущение v5]
WAVES = ["v1", "v2", "v3", "v4", "v5", "v6", "итог"]


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def history() -> dict[int, dict]:
    fs = sorted(f for f in glob.glob(f"{P}/niche_merge_*.json"))
    return {r["id"]: r["waves"] for r in (load(fs[-1]) if fs else [])}


def dims_for(ids) -> tuple[float, float, str]:
    d = [V.card_dims(load(f"{V.CARDS}/{s}.json")) for s in ids[:2] if os.path.exists(f"{V.CARDS}/{s}.json")]
    vols = [x["vol_l"] for x in d if x["vol_l"]]
    kgs = [x["kg"] for x in d if x["kg"]]
    if vols and kgs:
        return round(sorted(vols)[len(vols) // 2], 2), round(sorted(kgs)[len(kgs) // 2], 2), "карточки"
    return 0.8, 0.35, "допущение"


def band_fail(b) -> list[str]:
    f = []
    if b["newcomers"] < 5:
        f.append(f"новичков {b['newcomers']} < 5")
    if b["p50"] < 4:
        f.append(f"новичок P50 {b['p50']} < 4/день")
    if b["winner_sellers"] < 3:
        f.append(f"продавцов-победителей {b['winner_sellers']} < 3")
    if (b["top1_pct"] or 100) > 35:
        f.append(f"top-1 полосы {b['top1_pct']}% > 35")
    return f


def evaluate(u: dict, seas: dict, cny: float) -> dict:
    r = {k: u.get(k) for k in ("id", "name", "rev_mln", "price_med", "buyout", "sellers_ws", "com")}
    s = seas.get(u["id"]) or {}
    r["season"] = {"peak": s.get("peak_month"), "type": s.get("type")}
    if KIZ.search(u["name"]):
        return {**r, "status": "❌ Честный знак (косметика)", "fails": ["ЧЗ"]}
    p = V.p500(u["id"])
    if not p:
        return {**r, "status": "⏳ products500 не собран", "fails": []}
    R = [x for x in V.rows(p) if x.get("sales") and x.get("revenue")]
    if len(R) < 50:
        return {**r, "status": f"❌ мало карточек с продажами ({len(R)})", "fails": ["< 50 карточек"]}
    k = V.season_k(u["id"])
    if k < 0.5:
        return {**r, "status": f"❌ июль {round(k * 100)}% среднего — сезон не летом", "fails": ["сезон"]}
    bands = [V.band_stats(R, lo, hi, k) for lo, hi in V.BANDS]
    ok = [b for b in bands if not band_fail(b)]
    if not ok:
        b = max(bands, key=lambda b: (b["p50"], b["newcomers"]))
        return {**r, "status": "❌ " + "; ".join(band_fail(b))[:80], "fails": band_fail(b), "best": b}
    comm = u.get("com") or 25.0
    for b in ok:
        b["max_yuan_drr10"] = max_yuan(b["seller_price_med"], 0.8, 0.35, u["buyout"], comm, 10, 0)
        b["score"] = round(b["p50"] * b["max_yuan_drr10"], 1)
    b = max(ok, key=lambda b: b["score"])
    vol, kg, src = dims_for(b["top_ids"])
    price = b["seller_price_med"]
    y = round(b["buyer_med"] * SHARE / cny, 1)
    m15 = round(V.margin_at(price, y, kg, vol, u["buyout"], comm, 15), 1)
    r.update(best=b, vol_l=vol, kg=kg, dims_src=src, yuan_assumed=y, margin_drr15=m15,
             max_yuan_drr10=max_yuan(price, vol, kg, u["buyout"], comm, 10, 0), max_yuan_drr15=max_yuan(price, vol, kg, u["buyout"], comm, 15, 0))
    flags = []
    if (b["china_pct"] or 0) < 50:
        flags.append(f"Китай {b['china_pct']}%")
    if s.get("type") and s["type"] != "круглый год":
        flags.append(f"{s['type']}, пик {s.get('peak_month')}")
    if src != "карточки":
        flags.append("габарит —")
    if KIZ_CHECK.search(u["name"]):
        flags.append("ЧЗ? проверить")
    r["flags"] = flags
    mk = "✅" if m15 >= 18 else "🟡" if m15 > 0 else "❌"
    r["status"] = f"{mk} полоса {b['band'][0]}–{b['band'][1]} ₽, P50 {b['p50']}/день, маржа ДРР15 {m15}%"
    r["fails"] = [] if mk != "❌" else [f"маржа ДРР15 {m15}%"]
    return r


def main():
    cny = econ_config()["cargo"]["cny_to_rub"]
    seas = {r["id"]: r for r in load(f"{P}/all_niches_season_2026-10-11.json") or []}
    hist = history()
    v5u = {u["id"] for u in load(f"{P}/niche_v5_universe.json") or []}
    U = load(V.UNIVERSE) or V.universe()               # niche_v6_universe.json (без карго-запретов)
    out = []
    for u in U:
        r = evaluate(u, seas, cny)
        h = hist.get(u["id"], {})
        r["history"] = {w: x["status"] for w, x in h.items()}
        r["cargo_blocked_before"] = (u["id"] not in v5u) or any(CARGO.search(x["status"]) for x in h.values())
        out.append(r)
    rank = {"✅": 0, "🟡": 1, "❌": 2, "⏳": 3}
    out.sort(key=lambda r: (rank[r["status"][0]], -((r.get("best") or {}).get("score") or 0) if r["status"][0] in "✅🟡" else 0, -r["rev_mln"]))
    json.dump(out, open(OUT_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cnt = {k: sum(1 for r in out if r["status"][0] == k) for k in rank}
    good = [r for r in out if r["status"][0] in "✅🟡"]
    L = [f"# Поиск ниши «v1 без карго» — все волны в одной воронке ({TODAY})", "",
         "Код: `src/niche_nocargo.py`, 0 запросов. Данные: Saleflow products500 июль 2026 (2026-07-01…2026-07-31), предметы июля 2026,",
         "сезонность 2026 (all_niches_season), карточки лидеров (кэш v5). Снято: чувств. груз, магниты/батарейки/электроника/жидкости.", "",
         "| Этап | Ниш |", "|---|---:|", f"| universe (без карго-запретов) | {len(out)} |",
         f"| products500 есть | {len(out) - cnt['⏳']} |", f"| ✅ | {cnt['✅']} |", f"| 🟡 | {cnt['🟡']} |", f"| ❌ | {cnt['❌']} |",
         f"| ⏳ ждёт сбора | {cnt['⏳']} |", "",
         "## Прошли (✅/🟡)", "",
         "| # | Ниша | Полоса ₽ | Нов. | P50/день | Поб. прод. | top-1 % | Цена прод. ₽ | Выкуп % | Ком. % | max ¥ ДРР10 | max ¥ ДРР15 | ¥ доп. | Маржа ДРР15 % | Габарит | Карго мешал | Флаги | Ст. |",
         "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|"]
    for i, r in enumerate(good, 1):
        b = r["best"]
        L.append(f"| {i} | {r['id']} {r['name'].split(' / ')[-1][:32]} | {b['band'][0]}–{b['band'][1]} | {b['newcomers']} | {b['p50']} | {b['winner_sellers']} | "
                 f"{b['top1_pct']} | {b['seller_price_med']} | {r['buyout']} | {r['com']} | {r['max_yuan_drr10']} | {r['max_yuan_drr15']} | {r['yuan_assumed']} | "
                 f"{r['margin_drr15']} | {r['vol_l']} л / {r['kg']} кг ({'карт.' if r['dims_src'] == 'карточки' else 'доп.'}) | "
                 f"{'да' if r['cargo_blocked_before'] else 'нет'} | {'; '.join(r['flags'])} | {r['status'][0]} |")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "без карго"
        ws.append(["id", "ниша", "статус", "выручка млн ₽", "медиана ₽", "выкуп %", "продавцов", "ком. %", "полоса", "новичков", "P50/день",
                   "поб. продавцов", "top-1 %", "цена прод. ₽", "Китай %", "объём л", "кг", "габарит", "max ¥ ДРР10", "max ¥ ДРР15", "¥ доп.",
                   "маржа ДРР15 %", "карго мешал раньше", "флаги", *WAVES])
        for r in out:
            b = r.get("best") or {}
            ws.append([r["id"], r["name"], r["status"], r["rev_mln"], r["price_med"], r["buyout"], r["sellers_ws"], r["com"],
                       f"{b['band'][0]}–{b['band'][1]}" if b else None, b.get("newcomers"), b.get("p50"), b.get("winner_sellers"), b.get("top1_pct"),
                       b.get("seller_price_med"), b.get("china_pct"), r.get("vol_l"), r.get("kg"), r.get("dims_src"), r.get("max_yuan_drr10"),
                       r.get("max_yuan_drr15"), r.get("yuan_assumed"), r.get("margin_drr15"), "да" if r["cargo_blocked_before"] else "нет",
                       "; ".join(r.get("flags") or []), *[r["history"].get(w, "·") for w in WAVES]])
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(OUT_X)
    except Exception as e:                             # noqa: BLE001
        print("xlsx:", e)
    print(f"universe {len(out)} | ✅ {cnt['✅']} 🟡 {cnt['🟡']} ❌ {cnt['❌']} ⏳ {cnt['⏳']} → {OUT_MD}")


if __name__ == "__main__":
    main()
