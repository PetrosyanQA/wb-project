"""WB unit-economics: 1 միավորի շահույթ, ROI, break-even, բյուջեի ստուգում."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _deep_merge(base: dict, patch: dict) -> dict:
    """patch-ի արժեքները վերագրում են base-ին (ներդրված dict-երը՝ ռեկուրսիվ)."""
    for key, value in patch.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: Path | str = ROOT / "config" / "unit_economics.yaml",
                auto: Path | str = ROOT / "config" / "tariffs_auto.yaml") -> dict:
    """Բազային կոնֆիգ + (եթե կա) WB Seller API-ից սինքրոնացված իրական տարիֆներ."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    auto_path = Path(auto)
    if auto_path.exists():
        patch = yaml.safe_load(auto_path.read_text(encoding="utf-8")) or {}
        cfg = _deep_merge(cfg, patch)
        cfg["_tariffs_source"] = f"WB API, {patch.get('_synced_at', '?')} ({patch.get('_warehouse', '?')})"
    return cfg


def load_scheme(name: str = "am_fbs", path: Path | str = ROOT / "config" / "unit_economics.yaml") -> dict:
    """Բազային կոնֆիգ + բիզնեսի ընթացիկ սխեման (config/scheme_<name>.yaml), առանց tariffs_auto.yaml-ի (СЦ Ереван)։
    Սխեմայում՝ FBS «Свой склад РФ», հարկ, эквайринг, ДРР-ի հիմքը (պատվերներից), ֆիքսված ФФ."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    patch = yaml.safe_load((ROOT / "config" / f"scheme_{name}.yaml").read_text(encoding="utf-8")) or {}
    cfg = _deep_merge(cfg, patch)
    lg = cfg["logistics"]
    cfg["_tariffs_source"] = (f"scheme {name}: WB FBS {lg['first_liter_over_1l']} + {lg['extra_liter']} ₽/л + ФФ "
                              f"{lg.get('ff_per_order_rub', 0)} ₽/отправка; налог {cfg['tax']['rate_pct']}%; "
                              f"эквайринг {cfg.get('acquiring_pct', 0)}%; ДРР от {cfg['operations'].get('ad_basis', 'sales')}")
    return cfg


def wb_logistics(volume_l: float, cfg: dict) -> float:
    """Ուղիղ լոգիստիկա 1 պատվերի համար՝ ըստ WB 2026 բազային ցանցի (կամ սխեմայի ֆիքսված FBS-ի ≤ 1 լ ապրանքի համար)."""
    log = cfg["logistics"]
    if log.get("flat_rub") is not None and volume_l <= float(log.get("flat_max_l", 1.0)):
        return float(log["flat_rub"]) * float(log["warehouse_coef"]) * float(log["localization_index"])
    if volume_l <= 1.0:
        base = None
        for limit, price in sorted(((float(k), v) for k, v in log["tiers_under_1l"].items())):
            if volume_l <= limit:
                base = float(price)
                break
        base = base if base is not None else float(log["first_liter_over_1l"])
    else:
        extra = volume_l - 1.0
        base = float(log["first_liter_over_1l"]) + extra * float(log["extra_liter"])
    return base * float(log["warehouse_coef"]) * float(log["localization_index"])


def unit_economics(price: float, cost: float, volume_l: float, cfg: dict | None = None,
                   with_breakeven: bool = True, **overrides) -> dict:
    """price — գնորդի վճարած գին (₽), cost — ինքնարժեք առանց first mile-ի.
    overrides: buyout_pct, ad_share_of_revenue_pct, … + commission_pct, fixed_per_unit_rub (ФФ-ի ֆիքսված մասը 1 վաճառքի վրա)։
    operations.ad_basis = "orders" → ДРР-ը WB-ի պես պատվերներից է, 1 վաճառքի վրա՝ ДРР × գին / выкуп."""
    cfg = cfg or load_config()
    ops = dict(cfg["operations"]); ops.update({k: v for k, v in overrides.items() if k in ops})
    commission_pct = overrides.get("commission_pct", cfg["commission_pct"])
    fixed = float(overrides.get("fixed_per_unit_rub", 0.0))
    buyout = max(1.0, float(ops["buyout_pct"])) / 100.0

    commission = price * float(commission_pct) / 100.0
    acquiring = price * float(cfg.get("acquiring_pct", 0)) / 100.0

    ship = wb_logistics(volume_l, cfg) + float(cfg["logistics"].get("ff_per_order_rub", 0))   # + ФФ до пункта приёма WB
    # 1 վաճառքի հաշվով՝ բոլոր չգնված պատվերների լոգիստիկան նույնպես մերն է
    logistics = ship / buyout
    returns = float(cfg["logistics"]["return_cost_rub"]) * (1.0 / buyout - 1.0)

    st = cfg["storage"]
    storage = (float(st["per_liter_per_day"]) * max(volume_l, 1.0)
               * float(st["warehouse_coef"]) * float(st["avg_days_on_stock"]))
    acceptance = float(cfg.get("acceptance_per_liter", 0)) * volume_l * float(st["warehouse_coef"])

    ads = price * float(ops["ad_share_of_revenue_pct"]) / 100.0
    if ops.get("ad_basis") == "orders":
        ads /= buyout
    goods = (cost + float(ops["packaging_rub"]) + float(ops["first_mile_rub"]))
    goods *= 1.0 + float(ops["defect_loss_pct"]) / 100.0

    marketplace_costs = commission + acquiring + logistics + returns + storage + acceptance
    payout = price - marketplace_costs
    gross = payout - goods - ads

    tax_cfg = cfg["tax"]
    tax = (price * float(tax_cfg["rate_pct"]) / 100.0 if tax_cfg["mode"] == "revenue"
           else max(0.0, gross - fixed) * float(tax_cfg["rate_pct"]) / 100.0)
    net = gross - tax - fixed

    return {
        "price": round(price, 2),
        "commission": round(commission, 2),
        "acquiring": round(acquiring, 2),
        "logistics_with_returns": round(logistics + returns, 2),
        "storage": round(storage, 2),
        "acceptance": round(acceptance, 2),
        "wb_costs_total": round(marketplace_costs, 2),
        "payout_from_wb": round(payout, 2),
        "goods_cost_full": round(goods, 2),
        "ads": round(ads, 2),
        "tax": round(tax, 2),
        "fixed_per_unit": round(fixed, 2),
        "net_profit": round(net, 2),
        "net_margin_pct": round(net / price * 100, 1) if price else 0.0,
        "roi_on_goods_pct": round(net / goods * 100, 1) if goods else 0.0,
        "breakeven_price": round(_breakeven(price, cost, volume_l, cfg, ops, commission_pct, fixed), 2)
        if with_breakeven else None,
    }


def _breakeven(price: float, cost: float, volume_l: float, cfg: dict, ops: dict,
               commission_pct: float, fixed: float = 0.0) -> float:
    """Նվազագույն գինը, որի դեպքում net = 0 (պարզ բիսեկցիա)."""
    lo, hi = 1.0, max(price * 5, 100.0)
    for _ in range(60):
        mid = (lo + hi) / 2
        res = unit_economics(mid, cost, volume_l, cfg, with_breakeven=False,
                             commission_pct=commission_pct, fixed_per_unit_rub=fixed, **ops)
        if res["net_profit"] >= 0:
            hi = mid
        else:
            lo = mid
    return hi


def cost_ceiling(price: float, volume_l: float, cfg: dict | None = None, **overrides) -> float:
    """Ամենաբարձր ինքնարժեքը (₽, առանց first mile-ի), որի դեպքում դեռ բավարարվում են
    targets.min_net_margin_pct ԵՎ targets.min_roi_on_cost_pct (բիսեկցիա). 0 = չի անցնում նույնիսկ անվճար."""
    cfg = cfg or load_config()
    t = cfg["targets"]

    def ok(cost: float) -> bool:
        e = unit_economics(price, cost, volume_l, cfg, with_breakeven=False, **overrides)
        return (e["net_margin_pct"] >= t["min_net_margin_pct"]
                and e["roi_on_goods_pct"] >= t["min_roi_on_cost_pct"])

    if not ok(0.0):
        return 0.0
    lo, hi = 0.0, float(price)
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return round(lo, 2)


def batch_plan(econ: dict, cost: float, budget_usd: float, fx: float,
               goods_share: float = 0.55, min_units: int = 80) -> dict:
    """Որքան միավոր կարող ենք գնել բյուջեով և ինչ է դա տալիս."""
    budget_rub = budget_usd * fx
    goods_budget = budget_rub * goods_share
    units = int(goods_budget // max(econ["goods_cost_full"], 1))
    return {
        "budget_rub": round(budget_rub),
        "goods_budget_rub": round(goods_budget),
        "units_affordable": units,
        "enough_for_launch": units >= min_units,
        "batch_profit_rub": round(units * econ["net_profit"]),
        "revenue_if_sold_out_rub": round(units * econ["price"]),
        "payback_units": int(goods_budget // max(econ["net_profit"], 1)) if econ["net_profit"] > 0 else None,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="WB unit economics")
    p.add_argument("--price", type=float, required=True, help="վաճառքի գին, ₽")
    p.add_argument("--cost", type=float, required=True, help="ինքնարժեք, ₽")
    p.add_argument("--volume", type=float, required=True, help="ծավալ, լիտր (Դ×Լ×Բ см / 1000)")
    p.add_argument("--commission", type=float, help="WB կոմիսիա %%")
    p.add_argument("--buyout", type=float, help="выкуп %%")
    p.add_argument("--drr", type=float, help="գովազդի բաժինը շրջանառությունից %%")
    p.add_argument("--budget-usd", type=float, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cfg = load_config()
    overrides = {}
    if args.commission is not None:
        overrides["commission_pct"] = args.commission
    if args.buyout is not None:
        overrides["buyout_pct"] = args.buyout
    if args.drr is not None:
        overrides["ad_share_of_revenue_pct"] = args.drr

    econ = unit_economics(args.price, args.cost, args.volume, cfg, **overrides)
    scoring = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))
    budget = scoring["budget"]
    plan = batch_plan(econ, args.cost, args.budget_usd or budget["total_usd"],
                      budget["fx_rub_per_usd"], budget["goods_share"],
                      budget["min_first_batch_units"])

    if args.json:
        print(json.dumps({"economics": econ, "batch": plan}, ensure_ascii=False, indent=2))
        return

    t = cfg["targets"]
    print(f"\n{'ՅՈՒՆԻՏ-ԷԿՈՆՈՄԻԿԱ (1 վաճառք)':<38}")
    print("─" * 52)
    for label, key in [("Գին", "price"), ("WB կոմիսիա", "commission"),
                       ("Լոգիստիկա + վերադարձ", "logistics_with_returns"),
                       ("Պահեստավորում", "storage"), ("Приёмка", "acceptance"),
                       ("→ WB-ի վճարումը", "payout_from_wb"),
                       ("Ինքնարժեք (full)", "goods_cost_full"), ("Գովազդ", "ads"),
                       ("Հարկ", "tax"), ("= ԶՈՒՏ ՇԱՀՈՒՅԹ", "net_profit")]:
        print(f"{label:<28} {econ[key]:>10,.0f} ₽")
    print("─" * 52)
    print(f"{'Մարժա':<28} {econ['net_margin_pct']:>10} %   (թիրախ ≥ {t['min_net_margin_pct']}%)")
    print(f"{'ROI ինքնարժեքի վրա':<28} {econ['roi_on_goods_pct']:>10} %   (թիրախ ≥ {t['min_roi_on_cost_pct']}%)")
    print(f"{'Break-even գին':<28} {econ['breakeven_price']:>10,.0f} ₽")
    print(f"\n{'ԱՌԱՋԻՆ ԽՄԲԱՔԱՆԱԿ':<38}")
    print("─" * 52)
    print(f"{'Բյուջե ապրանքի վրա':<28} {plan['goods_budget_rub']:>10,.0f} ₽")
    print(f"{'Միավոր':<28} {plan['units_affordable']:>10}")
    print(f"{'Շահույթ խմբաքանակից':<28} {plan['batch_profit_rub']:>10,.0f} ₽")
    ok = (econ["net_margin_pct"] >= t["min_net_margin_pct"]
          and econ["roi_on_goods_pct"] >= t["min_roi_on_cost_pct"]
          and plan["enough_for_launch"])
    print(f"\nՎԵՐԴԻԿՏ: {'🟢 անցնում է' if ok else '🔴 չի անցնում շեմերը'}")


if __name__ == "__main__":
    main()
