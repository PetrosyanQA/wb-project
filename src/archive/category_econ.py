"""Ո՞ր WB կատեգորիաներում է Չինաստան→Երևան մոդելը կենսունակ.

Օգտագործում է **միայն քո սեփական WB API-ն** (`/api/v1/tariffs/commission`, 7000+
կատեգորիա իրական կոմիսիաներով) + Երևանի իրական տարիֆները + landed cost մոդելը։
Ոչ MPStats, ոչ Saleflow — այսինքն աշխատում է նույնիսկ երբ դրանք հասանելի չեն։

Ի՞նչ է հաշվում. ամեն կատեգորիայի համար գտնում է **առավելագույն գործարանային ¥ գինը**,
որի դեպքում ապրանքը դեռ տալիս է թիրախային մարժան և ROI-ն տվյալ վաճառքի գնով։
Սա նեղացնում է որոնման դաշտը ՄԻՆՉԵՎ նիշայի տվյալ ունենալը։

    python3 -m src.category_econ --price 1900 --volume 0.5
    python3 -m src.category_econ --price 1900 --volume 0.5 --parent "Дом"
    python3 -m src.category_econ --price 1900 --volume 0.5 --top 40 --md reports/cat.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .landed_cost import landed_cost, load_config as lc_config
from .unit_econ import load_config as ue_config, unit_economics
from .wb_seller import WBSellerClient

ROOT = Path(__file__).resolve().parent.parent
# Կոմիսիայի դաշտը ըստ վաճառքի մոդելի
MODEL_FIELD = {
    "fbw": "kgvpBooking",          # WB-ի պահեստ (СЦ Ереван) — մեր հիմնական սցենարը
    "fbw_paid": "paidStorageKgvp",  # WB-ի պահեստ վճարովի պահեստավորմամբ
    "fbs": "kgvpMarketplace",       # վաճառողի պահեստից
    "dbs": "kgvpSupplier",          # առաքումը վաճառողի ուժերով
}


def max_affordable_cost(price: float, volume_l: float, commission_pct: float,
                        ue_cfg: dict, lo: float = 1.0, hi: float | None = None) -> float:
    """Առավելագույն ինքնարժեքը (₽), որի դեպքում ԵՐԿՈՒ թիրախն էլ բավարարվում են."""
    t = ue_cfg["targets"]
    min_margin = float(t["min_net_margin_pct"])
    min_roi = float(t["min_roi_on_cost_pct"])
    hi = hi if hi is not None else price

    def ok(cost: float) -> bool:
        e = unit_economics(price, cost, volume_l, ue_cfg, with_breakeven=False,
                           commission_pct=commission_pct)
        return e["net_margin_pct"] >= min_margin and e["roi_on_goods_pct"] >= min_roi

    if not ok(lo):
        return 0.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def cost_to_cny(target_cost_rub: float, weight_kg: float, units: int,
                dims, mode: str, lc_cfg: dict) -> float:
    """Հակադարձ՝ ինքնարժեքից → գործարանի ¥ գին (բիսեկցիա landed_cost-ի վրա)."""
    lo, hi = 0.0, 500.0
    if landed_cost(lo, weight_kg, units, dims, mode, lc_cfg)["landed_cost_rub"] > target_cost_rub:
        return 0.0
    for _ in range(45):
        mid = (lo + hi) / 2
        if landed_cost(mid, weight_kg, units, dims, mode, lc_cfg)["landed_cost_rub"] <= target_cost_rub:
            lo = mid
        else:
            hi = mid
    return lo


def min_viable_price(cost_rub: float, volume_l: float, commission_pct: float,
                     ue_cfg: dict) -> float:
    """Նվազագույն վաճառքի գինը, որի դեպքում ԵՐԿՈՒ թիրախն էլ բավարարվում են."""
    t = ue_cfg["targets"]
    mm, mr = float(t["min_net_margin_pct"]), float(t["min_roi_on_cost_pct"])

    def ok(price: float) -> bool:
        e = unit_economics(price, cost_rub, volume_l, ue_cfg, with_breakeven=False,
                           commission_pct=commission_pct)
        return e["net_margin_pct"] >= mm and e["roi_on_goods_pct"] >= mr

    lo, hi = cost_rub, cost_rub * 30 + 5000
    if not ok(hi):
        return float("inf")
    for _ in range(55):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi


def analyse(price: float, volume_l: float, weight_kg: float, units: int,
            dims, mode: str, model: str = "fbw",
            parent_filter: str = "", cny: float | None = None) -> list[dict]:
    ue_cfg, lc_cfg = ue_config(), lc_config()
    field = MODEL_FIELD[model]

    client = WBSellerClient()
    report = (client.tariffs_commission() or {}).get("report") or []

    # Խմբավորում ըստ parentName — subject-ները նույն ծնողի ներքո նույն կոմիսիան ունեն
    groups: dict[str, dict] = {}
    for row in report:
        parent = (row.get("parentName") or "").strip()
        if not parent:
            continue
        if parent_filter and parent_filter.lower() not in parent.lower():
            continue
        comm = row.get(field)
        if comm is None:
            continue
        g = groups.setdefault(parent, {"parent": parent, "commission": float(comm),
                                       "subjects": 0, "parentID": row.get("parentID")})
        g["subjects"] += 1
        g["commission"] = max(g["commission"], float(comm))   # ՊԱՀՊԱՆՈՂԱԿԱՆ՝ վատագույնը ծնողի ներքո

    cost_fixed = None
    if cny is not None:
        cost_fixed = landed_cost(cny, weight_kg, units, dims, mode, lc_cfg)["landed_cost_rub"]

    out = []
    for g in groups.values():
        if cost_fixed is not None:
            mvp = min_viable_price(cost_fixed, volume_l, g["commission"], ue_cfg)
            e2 = unit_economics(max(mvp, 1.0), cost_fixed, volume_l, ue_cfg,
                                with_breakeven=False, commission_pct=g["commission"])
            out.append({**g, "cost_rub": round(cost_fixed, 0),
                        "min_price": round(mvp, 0) if mvp != float("inf") else None,
                        "mult_vs_cny": round(mvp / (cny * lc_cfg["fx"]["cny_to_rub"]), 1)
                                       if mvp != float("inf") and cny else None,
                        "commission_rub": round(e2["commission"], 0)})
            continue
        max_cost = max_affordable_cost(price, volume_l, g["commission"], ue_cfg)
        max_cny = cost_to_cny(max_cost, weight_kg, units, dims, mode, lc_cfg) if max_cost else 0.0
        e = unit_economics(price, max(max_cost, 1.0), volume_l, ue_cfg,
                           with_breakeven=False, commission_pct=g["commission"])
        out.append({**g, "max_cost_rub": round(max_cost, 0), "max_cny": round(max_cny, 1),
                    "commission_rub": round(e["commission"], 0),
                    "logistics_rub": round(e["logistics_with_returns"], 0)})
    if cny is not None:
        out.sort(key=lambda x: (x["min_price"] is None, x["min_price"] or 0))
    else:
        out.sort(key=lambda x: -x["max_cny"])
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="WB կատեգորիաների էկոնոմիկական կենսունակությունը")
    p.add_argument("--price", type=float, help="պլանավորվող վաճառքի գին ₽ (→ максимум ¥)")
    p.add_argument("--cny", type=float, help="գործարանի ¥ գին (→ минимум վաճառքի գին)")
    p.add_argument("--volume", type=float, default=0.5, help="ծավալ, լ")
    p.add_argument("--weight-kg", type=float, default=0.35)
    p.add_argument("--dims", default="20x14x9")
    p.add_argument("--units", type=int, default=300)
    p.add_argument("--mode", default="truck", choices=["air", "truck", "rail"])
    p.add_argument("--model", default="fbw", choices=list(MODEL_FIELD))
    p.add_argument("--parent", default="", help="ֆիլտր ծնող-կատեգորիայով")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--md", help="պահել markdown հաշվետվություն")
    a = p.parse_args()

    if not a.price and not a.cny:
        p.error("պետք է --price կամ --cny")
    dims = tuple(float(x) for x in a.dims.lower().split("x")) if a.dims else None
    rows = analyse(a.price or 0.0, a.volume, a.weight_kg, a.units, dims, a.mode,
                   a.model, a.parent, a.cny)
    ue_cfg = ue_config()
    t = ue_cfg["targets"]

    ue_cfg = ue_config()
    t = ue_cfg["targets"]
    tgt = f"մարժա ≥{t['min_net_margin_pct']}% ԵՎ ROI ≥{t['min_roi_on_cost_pct']}%"

    if a.cny:
        c0 = rows[0]["cost_rub"] if rows else 0
        head = (f"Գործարան ¥{a.cny:.0f} → ինքնարժեք **{c0:.0f} ₽** "
                f"({a.volume} լ · {a.weight_kg} կգ · {a.units} հատ · {a.mode})\n"
                f"Թիրախ՝ {tgt} | Երևան | մոդել {a.model.upper()}")
        print("\n" + head + "\n")
        print(f"{'Կատեգորիա':<40}{'Коми%':>7}{'мин. գին':>11}{'×¥':>7}{'subj':>6}")
        print("─" * 73)
        for r in rows[:a.top]:
            mp = r["min_price"]
            mark = "🟢" if mp and mp <= 1800 else "🟡" if mp and mp <= 2400 else "🔴"
            price_s = f"{mp:.0f}₽" if mp else "անհնար"
            print(f"{mark} {r['parent'][:38]:<38}{r['commission']:>7.1f}{price_s:>11}"
                  f"{(r['mult_vs_cny'] or 0):>7.1f}{r['subjects']:>6}")
        print(f"\n  Ամենաթանկ մուտքը (վատ կատեգորիաներ)՝")
        for r in rows[-6:]:
            mp = r["min_price"]
            print(f"  🔴 {r['parent'][:38]:<38}{r['commission']:>7.1f}"
                  f"{(f'{mp:.0f}₽' if mp else 'անհնար'):>11}")
        band = [r for r in rows if r["min_price"] and r["min_price"] <= 2600]
        print(f"\n  ≤2600₽ գոտում տեղավորվում է՝ {len(band)} / {len(rows)} կատեգորիա")
    else:
        head = (f"Գին {a.price:.0f} ₽ · {a.volume} լ · {a.weight_kg} կգ · {a.units} հատ · "
                f"{a.mode} · մոդել {a.model.upper()}\nԹիրախ՝ {tgt} | Երևանի տարիֆներ")
        print("\n" + head + "\n")
        viable = [r for r in rows if r["max_cny"] > 0]
        print(f"Կատեգորիաներ՝ {len(rows)}  |  կենսունակ՝ {len(viable)}\n")
        print(f"{'Կատեգորիա':<40}{'Коми%':>7}{'макс ինքնարժ':>14}{'макс ¥':>9}{'subj':>6}")
        print("─" * 78)
        for r in rows[:a.top]:
            mark = "🟢" if r["max_cny"] >= 25 else "🟡" if r["max_cny"] >= 12 else "🔴"
            print(f"{mark} {r['parent'][:38]:<38}{r['commission']:>7.1f}"
                  f"{r['max_cost_rub']:>13.0f}₽{r['max_cny']:>9.1f}{r['subjects']:>6}")

    if a.md:
        if a.cny:
            lines = [f"# Նվազագույն վաճառքի գինը ըստ կատեգորիայի — գործարան ¥{a.cny:.0f}", "",
                     head.replace("\n", "  \n"), "",
                     "| | Կատեգորիա | Комиссия % | Մին. գին ₽ | ×¥ | Subj |",
                     "|---|---|---:|---:|---:|---:|"]
            for r in rows:
                mp = r["min_price"]
                mark = "🟢" if mp and mp <= 1800 else "🟡" if mp and mp <= 2400 else "🔴"
                lines.append(f"| {mark} | {r['parent']} | {r['commission']:.1f} | "
                             f"{(f'{mp:.0f}' if mp else '—')} | "
                             f"{(f'{r["mult_vs_cny"]:.1f}' if r.get('mult_vs_cny') else '—')} | "
                             f"{r['subjects']} |")
        else:
            lines = [f"# WB կատեգորիաների էկոնոմիկա — {a.price:.0f} ₽", "",
                     head.replace("\n", "  \n"), "",
                     "| | Կատեգորիա | Комиссия % | Макс ինքնարժեք ₽ | Макс ¥ | Subj |",
                     "|---|---|---:|---:|---:|---:|"]
            for r in rows:
                mark = "🟢" if r["max_cny"] >= 25 else "🟡" if r["max_cny"] >= 12 else "🔴"
                lines.append(f"| {mark} | {r['parent']} | {r['commission']:.1f} | "
                             f"{r['max_cost_rub']:.0f} | {r['max_cny']:.1f} | {r['subjects']} |")
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n✔ {a.md}")

    print()


if __name__ == "__main__":
    main()
