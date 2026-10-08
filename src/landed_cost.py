"""Չինաստան → Հայաստան ներկրման իրական ինքնարժեք (landed cost).

1688/Alibaba-ի գինը ԵՐԲԵՔ չէ քո ինքնարժեքը։ Ավելանում են՝
բեռնափոխադրում (քաշային կամ ծավալային), ԵԱՏՄ մաքսատուրք, ՀՀ ԱԱՀ 20%,
բրոքեր, նմուշներ, բրակ։ Այս մոդուլը հաշվում է միավորի լրիվ ինքնարժեքը ₽-ով,
որն ուղղակի մտնում է `unit_econ --cost`-ի մեջ։

    python3 -m src.landed_cost --cny 18 --weight-kg 0.35 --units 300
    python3 -m src.landed_cost --cny 18 --weight-kg 0.35 --dims 20x14x9 --mode air
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:                                        # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "landed_cost.yaml"


def load_config(path: Path | str = CONFIG) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    if yaml is None:
        raise RuntimeError("pyyaml պետք է՝ pip install pyyaml")
    return yaml.safe_load(text)


def chargeable_weight(weight_kg: float, dims_cm: tuple[float, float, float] | None,
                      divisor: float) -> tuple[float, str]:
    """Փոխադրողը վերցնում է ՄԵԾԸ՝ իրական կամ ծավալային քաշից."""
    if not dims_cm:
        return weight_kg, "իրական"
    volumetric = (dims_cm[0] * dims_cm[1] * dims_cm[2]) / divisor
    if volumetric > weight_kg:
        return volumetric, f"ծավալային ({volumetric:.2f} > {weight_kg:.2f} կգ)"
    return weight_kg, "իրական"


def landed_cost(cny: float, weight_kg: float, units: int | None = None,
                dims_cm: tuple[float, float, float] | None = None,
                mode: str | None = None, cfg: dict | None = None) -> dict:
    """→ միավորի լրիվ ինքնարժեքը ₽-ով + ծախսերի քայքայում."""
    cfg = cfg or load_config()
    fx, fr, cu, ba = cfg["fx"], cfg["freight"], cfg["customs"], cfg["batch"]
    units = int(units or ba["units"])
    mode = mode or fr["mode"]
    usd = float(fx["usd_to_rub"])

    # 1. Ապրանքի գինը գործարանում
    goods_rub = cny * float(fx["cny_to_rub"])

    # 2. Բեռնափոխադրում — քաշային կամ ծավալային
    cw, cw_kind = chargeable_weight(weight_kg, dims_cm, float(fr["volumetric_divisor"]))
    rate = float(fr["rates_usd_per_kg"][mode])
    freight_batch_usd = max(cw * units * rate, float(fr["min_charge_usd"]))
    freight_rub = freight_batch_usd * usd / units

    # 3. Մաքս — տուրքը հաշվվում է ապրանք+բեռնափոխադրում բազայի վրա (CIF)
    cif_rub = goods_rub + freight_rub
    duty_rub = cif_rub * float(cu["duty_pct"]) / 100.0
    vat_base = cif_rub + duty_rub
    vat_rub = vat_base * float(cu["vat_pct"]) / 100.0
    if cu.get("vat_recoverable"):
        vat_rub = 0.0

    # 4. Խմբաքանակի ֆիքսված ծախսերը՝ բաշխված միավորի վրա
    fixed_usd = (float(cu["broker_fee_usd"]) + float(cu["customs_fee_usd"])
                 + float(ba["samples_usd"]) + float(ba["inspection_usd"]))
    fixed_rub = fixed_usd * usd / units

    # 4b. Плечо ПОСЛЕ растаможки (напр. Ереван → Москва внутри ЕАЭС): без пошлины и НДС сверху
    pc = cfg.get("post_customs") or {}
    post_rub = 0.0
    if pc.get("usd_per_kg"):
        post_usd = max(cw * units * float(pc["usd_per_kg"]), float(pc.get("min_charge_usd", 0)))
        post_rub = post_usd * usd / units

    subtotal = goods_rub + freight_rub + duty_rub + vat_rub + fixed_rub + post_rub

    # 5. Բրակ — պիտանի միավորների թիվը պակաս է, ինքնարժեքը բարձրանում է
    defect = float(ba["defect_rate_pct"]) / 100.0
    total = subtotal / (1.0 - defect) if defect < 1 else subtotal

    return {
        "units": units, "mode": mode,
        "chargeable_kg": round(cw, 3), "chargeable_kind": cw_kind,
        "goods_rub": round(goods_rub, 2),
        "freight_rub": round(freight_rub, 2),
        "duty_rub": round(duty_rub, 2),
        "vat_rub": round(vat_rub, 2),
        "fixed_rub": round(fixed_rub, 2),
        "post_customs_rub": round(post_rub, 2),
        "defect_uplift_rub": round(total - subtotal, 2),
        "landed_cost_rub": round(total, 2),
        "markup_vs_factory_pct": round((total / goods_rub - 1) * 100, 1) if goods_rub else 0.0,
        "batch_total_rub": round(total * units, 2),
        "batch_total_usd": round(total * units / usd, 2),
    }


def max_cny(ceiling_rub: float, weight_kg: float, units: int | None = None,
            dims_cm: tuple[float, float, float] | None = None,
            mode: str | None = None, cfg: dict | None = None) -> float | None:
    """Գործարանի ամենաբարձր գինը ¥-ով, որի landed cost-ը ≤ ceiling_rub (բիսեկցիա).
    None = նույնիսկ ¥0-ի դեպքում բեռը + մաքսը արդեն գերազանցում են սահմանը."""
    cfg = cfg or load_config()

    def cost(c: float) -> float:
        return landed_cost(c, weight_kg, units, dims_cm, mode, cfg)["landed_cost_rub"]

    if cost(0.0) > ceiling_rub:
        return None
    lo, hi = 0.0, ceiling_rub / float(cfg["fx"]["cny_to_rub"])
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cost(mid) <= ceiling_rub else (lo, mid)
    return round(lo, 1)


def main() -> None:
    p = argparse.ArgumentParser(description="Չինաստան → Հայաստան landed cost")
    p.add_argument("--cny", type=float, required=True, help="գործարանի գինը ¥")
    p.add_argument("--weight-kg", type=float, required=True, help="միավորի քաշը կգ (փաթեթով)")
    p.add_argument("--dims", help="ծավալային քաշի համար՝ ԵxԼxԲ սմ, օր. 20x14x9")
    p.add_argument("--units", type=int, help="խմբաքանակի չափ (default՝ config-ից)")
    p.add_argument("--mode", choices=["air", "truck", "rail"], help="փոխադրման եղանակ")
    p.add_argument("--budget-usd", type=float, help="եթե տրված է՝ հաշվում է max խմբաքանակը")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    dims = None
    if a.dims:
        dims = tuple(float(x) for x in a.dims.lower().replace(",", "x").split("x"))  # type: ignore
        if len(dims) != 3:
            p.error("--dims ֆորմատը՝ 20x14x9")

    cfg = load_config()
    res = landed_cost(a.cny, a.weight_kg, a.units, dims, a.mode, cfg)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print(f"\nLanded cost՝ Չինաստան → Երևան   ({res['mode']}, {res['units']} հատ)")
    print("─" * 62)
    rows = [("Գործարանի գին", "goods_rub"), ("Բեռնափոխադրում", "freight_rub"),
            ("ԵԱՏՄ մաքսատուրք", "duty_rub"), ("ՀՀ ԱԱՀ", "vat_rub"),
            ("Բրոքեր/նմուշ/QC", "fixed_rub"), ("Բրակի հավելում", "defect_uplift_rub")]
    for label, key in rows:
        share = res[key] / res["landed_cost_rub"] * 100 if res["landed_cost_rub"] else 0
        print(f"  {label:<22}{res[key]:>10.2f} ₽   {share:>5.1f}%")
    print("─" * 62)
    print(f"  {'ԻՆՔՆԱՐԺԵՔ 1 հատ':<22}{res['landed_cost_rub']:>10.2f} ₽"
          f"   (+{res['markup_vs_factory_pct']}% գործարանի գնից)")
    print(f"  {'Վճարվող քաշ':<22}{res['chargeable_kg']:>10.3f} կգ  ({res['chargeable_kind']})")
    print(f"  {'Խմբաքանակը ընդամենը':<22}{res['batch_total_rub']:>10.2f} ₽"
          f"   = ${res['batch_total_usd']:,.0f}")

    if a.budget_usd:
        per_unit_usd = res["landed_cost_rub"] / cfg["fx"]["usd_to_rub"]
        max_units = int(a.budget_usd // per_unit_usd)
        print(f"\n  ${a.budget_usd:,.0f} բյուջեով → **{max_units} հատ** "
              f"(${per_unit_usd:.2f}/հատ)")
        if max_units < 100:
            print("  ⚠️ <100 հատ՝ WB-ում ալգորիթմը չի հասցնի բարձրացնել քարտը")

    print(f"\n  → unit_econ-ի մեջ՝  --cost {res['landed_cost_rub']:.0f}\n")


if __name__ == "__main__":
    main()
