"""Cross-border экономика ниш по логистическим сценариям (config/scenarios.yaml). Только чтение.

    python -m src.xborder screen [--date 2026-10-04] [--top 40]     # 0 запросов: «вес-бюджет» по сценариям
    python -m src.xborder refine --weights weights.json              # уточнение по реальным габаритам/весу
    python -m src.xborder selftest                                   # регрессия против decision_2026-10-04

Главная идея: при доставке из Китая цену товара определяет вес. Поэтому для каждой ниши считаем
  ceiling  — потолок себестоимости с доставкой (маржа/ROI по unit_economics.yaml) в худшем из
             трёх сценариев: база, цена −15%, выкуп −15 п.п.;
  W_max    — максимальный оплачиваемый вес (кг), при котором товар с заводской ценой
             «медианная цена / k_good» ещё укладывается в ceiling;
  max ¥    — (refine) максимальная заводская цена при известном весе, и k = цена / (max ¥ × курс).
Для AM_MADE (армянское производство) вместо ¥ — потолок местной закупочной цены ₽.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from pathlib import Path

import yaml

from .landed_cost import landed_cost, load_config as load_lc, max_cny
from .unit_econ import _deep_merge, cost_ceiling, load_config as load_ue

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "saleflow"
SCEN = ROOT / "config" / "scenarios.yaml"
ELECTRONICS = ("усилител", "пылесос", "скалер", "видеоглаз", "алкотест", "насос", "камер", "датчик",
               "регистратор", "фен", "плойк", "машинк", "триммер", "эпилятор", "массажер", "весы")


def load_scenarios(path: Path = SCEN) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def scenario_cfgs(name: str, sc: dict) -> tuple[dict, dict]:
    """→ (unit_econ cfg, landed_cost cfg) для сценария."""
    s = sc["scenarios"][name]
    tariffs = ROOT / s["tariffs_file"] if s.get("tariffs_file") else Path("/nonexistent")
    ue = load_ue(auto=tariffs)
    if s.get("tariffs"):
        ue = _deep_merge(ue, copy.deepcopy(s["tariffs"]))
    lc = _deep_merge(load_lc(), copy.deepcopy(s.get("landed") or {}))
    return ue, lc


def stress_ceiling(price: float, volume_l: float, commission: float, buyout: float,
                   ue: dict, st: dict) -> dict:
    """Потолок себестоимости в трёх сценариях; binding = минимальный."""
    kw = dict(commission_pct=commission, ad_share_of_revenue_pct=st["drr_pct"])
    base = cost_ceiling(price, volume_l, ue, buyout_pct=buyout, **kw)
    cheap = cost_ceiling(price * (1 - st["price_drop_pct"] / 100), volume_l, ue, buyout_pct=buyout, **kw)
    low_b = cost_ceiling(price, volume_l, ue, buyout_pct=max(buyout - st["buyout_drop_pp"], 1), **kw)
    return {"base": base, "price_drop": cheap, "buyout_drop": low_b, "binding": min(base, cheap, low_b)}


def max_weight(ceiling: float, cny: float, units: int, lc: dict) -> float | None:
    """Максимальный оплачиваемый вес (кг), при котором landed(cny, W) ≤ ceiling."""
    if landed_cost(cny, 0.0, units, None, None, lc)["landed_cost_rub"] > ceiling:
        return None
    lo, hi = 0.0, 20.0
    for _ in range(40):
        mid = (lo + hi) / 2
        ok = landed_cost(cny, mid, units, None, None, lc)["landed_cost_rub"] <= ceiling
        lo, hi = (mid, hi) if ok else (lo, mid)
    return round(lo, 2)


def cabinet_commissions() -> dict[int, dict]:
    """ՓԱՍՏ՝ քո (AM) կաբինետի կոմիսիաները՝ WB API /api/v1/tariffs/commission (քեշ 24 ժ)."""
    from .wb_seller import WBSellerClient
    data = WBSellerClient(quiet=True).tariffs_commission()
    rows = data.get("report", data.get("data", []))
    return {int(r["subjectID"]): {"fbo": r.get("paidStorageKgvp"), "fbs": r.get("kgvpMarketplace")} for r in rows}


def commission_for(s: dict, row: dict, cabinet: dict) -> float | None:
    kind = s["commission"]
    if s.get("commission_source") == "cabinet":
        return (cabinet.get(row["id"]) or {}).get(kind)
    return row.get(f"commission_{kind}")


def subject_rows(date: str) -> dict[int, dict]:
    rows = {}
    for f in glob.glob(str(RAW / date / "subjects_*" / "page_*.json")):
        for x in json.load(open(f, encoding="utf-8"))["data"]:
            rows[x["id"]] = x
    return rows


def candidates(date: str) -> list[dict]:
    out = {}
    for f in glob.glob(str(RAW / date / "subjects_*" / "screen_xborder*.json")):
        for r in json.load(open(f, encoding="utf-8")):
            out[r["id"]] = r
    return list(out.values())


def screen(date: str, top: int) -> list[dict]:
    sc = load_scenarios()
    st, units, k_good = sc["stress"], sc["units_per_batch"], sc["k_good"]
    dump = subject_rows(date)
    cfgs = {n: scenario_cfgs(n, sc) for n in sc["scenarios"]}
    cabinet = cabinet_commissions()
    res = []
    for c in candidates(date):
        x = dump.get(c["id"], {})
        price = x.get("median_price_final") or c["aov"]
        buyout = c.get("buyout") or 65
        row = {"id": c["id"], "name": c["name"], "revenue_m": c["revenue_m"], "price": round(price),
               "aov": c["aov"], "sellers": c["sellers"], "buyout": buyout, "rating": c["rating"],
               "fresh_pct": c["fresh_pct"], "pre_score": c["score"], "checked": c.get("checked"),
               "electronics": any(w in c["name"].lower() for w in ELECTRONICS),
               "commission_fbo": c.get("commission_fbo"), "commission_fbs": c.get("commission_fbs"),
               "scen": {}}
        for n, s in sc["scenarios"].items():
            ue, lc = cfgs[n]
            comm = commission_for(s, row, cabinet)
            if comm is None:
                continue
            ceil = stress_ceiling(price, 1.0, comm, buyout, ue, st)
            entry = {"commission": comm, "ceiling": ceil["binding"]}
            if s.get("local_cost"):
                entry["max_local_rub"] = ceil["binding"]
                entry["local_share_pct"] = round(ceil["binding"] / price * 100, 1) if price else None
            else:
                cny = price / k_good / float(lc["fx"]["cny_to_rub"])
                entry["cny_at_k"] = round(cny, 1)
                entry["w_max_kg"] = max_weight(ceil["binding"], cny, units, lc)
            row["scen"][n] = entry
        res.append(row)
    res.sort(key=lambda r: -((r["scen"].get("AM") or {}).get("w_max_kg") or -1))
    out = RAW / date / "xborder_screen.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"кандидатов: {len(res)}; k_good={k_good} (заводская цена = медианная / {k_good}); объём 1 л; "
          f"стресс: цена −{st['price_drop_pct']}%, выкуп −{st['buyout_drop_pp']} п.п.\n")
    print("| id | Предмет | M ₽ | цена | ком. AM / РФ | выкуп | ¥ при k | W max AM | W max RU_FBO | W max RU_FBS | "
          "AM_MADE: потолок ₽ (% цены) | ⚡ |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in res[:top]:
        s = r["scen"]
        w = lambda n: "—" if (s.get(n) or {}).get("w_max_kg") is None else f"{s[n]['w_max_kg']:.2f}"
        am = s.get("AM_MADE") or {}
        print(f"| {r['id']} | {r['name']} | {r['revenue_m']} | {r['price']} | "
              f"{(s.get('AM') or {}).get('commission', '—')} / {r['commission_fbo']} | {r['buyout']} | "
              f"{(s.get('AM') or {}).get('cny_at_k', '—')} | {w('AM')} | {w('RU_FBO')} | {w('RU_FBS')} | "
              f"{am.get('max_local_rub', '—')} ({am.get('local_share_pct', '—')}%) | {'⚡' if r['electronics'] else ''} |")
    print(f"\n✔ {out}")
    return res


def refine(date: str, weights_path: str) -> list[dict]:
    """weights.json: {subject_id: {"weight_kg": .., "dims_cm": [l,w,h], "price": .., "source": ".."}}"""
    sc = load_scenarios()
    st, units = sc["stress"], sc["units_per_batch"]
    w_in = json.load(open(weights_path, encoding="utf-8"))
    base = {r["id"]: r for r in json.load(open(RAW / date / "xborder_screen.json", encoding="utf-8"))}
    cfgs = {n: scenario_cfgs(n, sc) for n in sc["scenarios"]}
    cabinet = cabinet_commissions()
    res = []
    dump = subject_rows(date)
    for sid, w in w_in.items():
        sid_i = int(sid)
        if sid_i in base:
            r = copy.deepcopy(base[sid_i])
        else:                                   # не прошёл screen (напр. выкуп < 65%) — берём из выгрузки
            x = dump[sid_i]
            r = {"id": sid_i, "name": x["name"], "revenue_m": round(x["revenue"] / 1e6, 1),
                 "price": x.get("median_price_final"), "sellers": x.get("sellers"),
                 "buyout": x.get("purchase_after_return"), "commission_fbo": x.get("commision_fbo"),
                 "commission_fbs": x.get("commision_fbs"), "electronics": False, "not_screened": True}
        m_path = RAW / date / "xborder" / str(sid_i) / "metrics.json"
        metrics = json.load(open(m_path, encoding="utf-8")) if m_path.exists() else {}
        r["metrics"] = {k: metrics.get(k) for k in ("median_price", "top1_pct", "top10_pct", "armenia_pct",
                                                     "country_pct", "fresh_top20", "median_comments_top20", "sellers")}
        price = w.get("price") or metrics.get("median_price") or r["price"]
        dims = tuple(w["dims_cm"]) if w.get("dims_cm") else None
        vol = (dims[0] * dims[1] * dims[2] / 1000) if dims else w.get("volume_l", 1.0)
        r.update(price=round(price), weight_kg=w["weight_kg"], dims_cm=dims, volume_l=round(vol, 2),
                 weight_source=w.get("source", "—"), scen={})
        for n, s in sc["scenarios"].items():
            ue, lc = cfgs[n]
            comm = commission_for(s, r, cabinet)
            ceil = stress_ceiling(price, vol, comm, r["buyout"], ue, st)
            e = {"commission": comm, **{f"ceil_{k}": v for k, v in ceil.items()}}
            if s.get("local_cost"):
                e["max_local_rub"] = ceil["binding"]
            else:
                mc = max_cny(ceil["binding"], w["weight_kg"], units, dims, None, lc)
                mc_base = max_cny(ceil["base"], w["weight_kg"], units, dims, None, lc)
                e["max_cny"] = mc
                e["max_cny_base"] = mc_base
                e["k"] = round(price / (mc * float(lc["fx"]["cny_to_rub"])), 1) if mc else None
                lc0 = landed_cost(0.0, w["weight_kg"], units, dims, None, lc)
                e["freight_rub"] = lc0["freight_rub"]
            r["scen"][n] = e
        res.append(r)
    out = RAW / date / "xborder_refined.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✔ {out} ({len(res)} ниш)")
    return res


def products(date: str, files: list[str]) -> list[dict]:
    """MCP wb_subject products (сохранённые харнессом файлы) → data/raw/.../xborder/<id>/products.json + метрики.
    Читает ВСЕ строки каждого файла (не превью)."""
    import shutil
    from collections import Counter, defaultdict
    from statistics import median
    from .saleflow_eval import clean_items, load_strategy, volume_l
    s = load_strategy()
    today = __import__("datetime").date.fromisoformat(date)
    out = []
    for f in files:
        data = json.load(open(f, encoding="utf-8"))["data"]
        if not data:
            continue
        sid = Counter(r.get("subject_id") for r in data).most_common(1)[0][0]
        dst = RAW / date / "xborder" / str(sid)
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst / "products.json")
        kept, dropped = clean_items(data, sid, s)
        rev = sum(r.get("revenue") or 0 for r in kept) or 1
        by_seller = defaultdict(float)
        for r in kept:
            if r.get("seller"):
                by_seller[r["seller"]] += r.get("revenue") or 0
        shares = sorted(by_seller.values(), reverse=True)
        country = Counter()
        for r in kept:
            country[(r.get("country") or "—").strip() or "—"] += r.get("revenue") or 0
        dims = [(r["package_length"], r["package_width"], r["package_height"]) for r in kept
                if all((r.get(k) or 0) > 0 for k in ("package_length", "package_width", "package_height"))]
        vols = [v for v in (volume_l(r) for r in kept) if v]
        top20 = sorted(kept, key=lambda r: -(r.get("revenue") or 0))[:20]
        fresh = sum(1 for r in top20 if r.get("sku_first_date")
                    and (today - __import__("datetime").date.fromisoformat(r["sku_first_date"][:10])).days <= 365)
        med_dims = [round(median(d[i] for d in dims), 1) for i in range(3)] if dims else None
        row = {"id": sid, "name": data[0].get("subject"), "rows": len(data), "kept": len(kept), "dropped": len(dropped),
               "median_price": round(median(r["final_price"] for r in kept if r.get("final_price"))),
               "dims_known": len(dims), "median_dims_cm": med_dims,
               "median_volume_l": round(median(vols), 2) if vols else None,
               "volumetric_kg": round(median(vols) / 6, 2) if vols else None,
               "sellers": len(by_seller),
               "top1_pct": round(shares[0] / rev * 100, 1) if shares else None,
               "top10_pct": round(sum(shares[:10]) / rev * 100, 1) if shares else None,
               "country_pct": {k: round(v / rev * 100, 1) for k, v in country.most_common(5)},
               "armenia_pct": round(country.get("Армения", 0) / rev * 100, 1),
               "fresh_top20": fresh,
               "median_comments_top20": round(median(r.get("comments") or 0 for r in top20)),
               "leaders": [{"id": r["id"], "name": r["name"][:60], "price": r.get("final_price"),
                            "revenue": r.get("revenue"), "seller": r.get("seller"), "country": r.get("country"),
                            "comments": r.get("comments"), "rating": r.get("rating")} for r in top20[:5]]}
        (dst / "metrics.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        out.append(row)
    print("| id | Предмет | строк (чисто) | мед. цена | габариты, см (известно) | объём л | объёмный кг | продавцов | "
          "top-1 % | top-10 % | Армения % | страны | свежих в топ-20 | мед. отзывов топ-20 |")
    print("|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|")
    for r in out:
        cc = ", ".join(f"{k} {v}" for k, v in list(r["country_pct"].items())[:3])
        print(f"| {r['id']} | {r['name']} | {r['rows']} ({r['kept']}) | {r['median_price']} | {r['median_dims_cm']} ({r['dims_known']}) | "
              f"{r['median_volume_l']} | {r['volumetric_kg']} | {r['sellers']} | {r['top1_pct']} | {r['top10_pct']} | "
              f"{r['armenia_pct']} | {cc} | {r['fresh_top20']} | {r['median_comments_top20']} |")
    return out


def selftest() -> None:
    """Часы, AM, 0.3 кг, 12×12×7, 200 шт: при старом курсе ¥ = 11.5 должно совпасть с decision_2026-10-04."""
    sc = load_scenarios()
    ue, lc = scenario_cfgs("AM", sc)
    lc["fx"]["cny_to_rub"], lc["fx"]["usd_to_rub"] = 11.5, 83.0
    base = cost_ceiling(2008, 1.0, ue, commission_pct=24.5, buyout_pct=65, ad_share_of_revenue_pct=15)
    cheap = cost_ceiling(round(2008 * 0.85), 1.0, ue, commission_pct=24.5, buyout_pct=65, ad_share_of_revenue_pct=15)
    m_base = max_cny(base, 0.3, 200, (12, 12, 7), None, lc)
    m_cheap = max_cny(cheap, 0.3, 200, (12, 12, 7), None, lc)
    print(f"ceiling base {base:.0f} (ожид. 533), price−15% {cheap:.0f} (ожид. 427); "
          f"max ¥ {m_base} (ожид. 21.9) / {m_cheap} (ожид. 15.0)")
    assert abs(base - 533) <= 2 and abs(cheap - 427) <= 2, "ceiling drift"
    assert abs(m_base - 21.9) <= 0.3 and abs(m_cheap - 15.0) <= 0.3, "max_cny drift"
    print("selftest OK")


def main() -> None:
    ap = argparse.ArgumentParser(description="cross-border экономика ниш")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("screen"); p.add_argument("--date", default="2026-10-04"); p.add_argument("--top", type=int, default=40)
    p = sub.add_parser("refine"); p.add_argument("--date", default="2026-10-04"); p.add_argument("--weights", required=True)
    p = sub.add_parser("products"); p.add_argument("--date", default="2026-10-04"); p.add_argument("files", nargs="+")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "products":
        products(a.date, a.files)
    elif a.cmd == "screen":
        screen(a.date, a.top)
    elif a.cmd == "refine":
        refine(a.date, a.weights)
    else:
        selftest()


if __name__ == "__main__":
    main()
