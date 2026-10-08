"""WB Seller API → config/tariffs_auto.yaml (իրական տարիֆներ գուշակածների փոխարեն).

  python -m src.sync_tariffs --warehouse "Коледино" --subject "Ножи кухонные" --apply

Գրում է ԱՌԱՆՁԻՆ ֆայլ՝ config/tariffs_auto.yaml, որը unit_econ-ը merge է անում
բազային config/unit_economics.yaml-ի վրա։ Այսպես ձեռքով դրած մեկնաբանությունները չեն կորչում,
և միշտ երևում է՝ որ թիվն է WB-ից, որը՝ քո ենթադրությունը։
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import yaml

from .wb_seller import WBSellerClient, rub

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / "config" / "tariffs_auto.yaml"


def _num(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def cheapest_warehouse(warehouses: list[dict]) -> dict:
    """Եթե պահեստ նշված չէ՝ վերցնում ենք ամենաէժան լոգիստիկայով գործողը."""
    usable = [w for w in warehouses if _num(w.get("boxDeliveryBase")) is not None]
    return min(usable, key=lambda w: _num(w["boxDeliveryBase"])) if usable else warehouses[0]


def pick_warehouse(client: WBSellerClient, name: str) -> dict:
    data = client.tariffs_box()
    warehouses = data.get("response", {}).get("data", {}).get("warehouseList", [])
    if not warehouses:
        raise SystemExit("WB-ն դատարկ warehouseList վերադարձրեց — ստուգիր թոքենի «Тарифы» իրավունքը.")
    if not name:
        return cheapest_warehouse(warehouses)
    hits = [w for w in warehouses if name.lower() in str(w.get("warehouseName", "")).lower()]
    if not hits:
        available = ", ".join(sorted(str(w.get("warehouseName")) for w in warehouses)[:25])
        raise SystemExit(f"«{name}» պահեստը չգտնվեց։ Հասանելի են՝ {available} …")
    return hits[0]


def pick_commission(client: WBSellerClient, subject: str) -> list[dict]:
    data = client.tariffs_commission()
    rowset = data.get("report", data.get("data", []))
    needle = subject.lower()
    return [r for r in rowset if needle in str(r.get("subjectName", "")).lower()][:10]


def main() -> None:
    p = argparse.ArgumentParser(description="Sync WB tariffs into config")
    p.add_argument("--warehouse", default="", help="պահեստ (դատարկ = ավտոմատ ամենաէժանը քո կաբինետում)")
    p.add_argument("--subject", default="", help="предмет կոմիսիայի համար")
    p.add_argument("--volume", type=float, default=0.5, help="ստուգման ծավալ, լ")
    p.add_argument("--apply", action="store_true", help="գրել config/tariffs_auto.yaml")
    args = p.parse_args()

    client = WBSellerClient()
    wh = pick_warehouse(client, args.warehouse)

    delivery_base = rub(wh.get("boxDeliveryBase"))
    delivery_liter = rub(wh.get("boxDeliveryLiter"))
    delivery_coef = rub(wh.get("boxDeliveryCoefExpr"), 100.0) / 100.0
    storage_base = rub(wh.get("boxStorageBase"))
    storage_liter = rub(wh.get("boxStorageLiter"))
    storage_coef = rub(wh.get("boxStorageCoefExpr"), 100.0) / 100.0

    print(f"\nՊԱՀԵՍՏ: {wh.get('warehouseName')}   ({date.today()})")
    print("─" * 64)
    print(f"Առաքում՝ 1-ին լիտր {delivery_base:.1f} ₽ | +1 լ {delivery_liter:.1f} ₽ | коэф {delivery_coef*100:.0f}%")
    print(f"Պահեստավորում՝ բազա {storage_base:.3f} ₽/օր | +1 լ {storage_liter:.3f} ₽/օր | коэф {storage_coef*100:.0f}%")
    v = args.volume
    logi = (delivery_base + max(0.0, v - 1) * delivery_liter)
    print(f"\nՍտուգում {v} լ-ի համար՝ լոգիստիկա ≈ {logi:.1f} ₽ (коэф {delivery_coef*100:.0f}%-ը արդեն ներառված է)")
    print("⚠️  Համեմատիր WB կաբինետի կալկուլյատորի հետ։")

    commissions = []
    if args.subject:
        commissions = pick_commission(client, args.subject)
        print(f"\nԿՈՄԻՍԻԱ «{args.subject}»")
        print("─" * 64)
        print(f"{'Предмет':<34}{'FBO%':>7}{'FBS%':>7}{'DBS%':>7}")
        for r in commissions:
            print(f"{str(r.get('subjectName'))[:33]:<34}{rub(r.get('paidStorageKgvp')):>7.1f}"
                  f"{rub(r.get('kgvpMarketplace')):>7.1f}{rub(r.get('kgvpSupplier')):>7.1f}")

    # boxDeliveryBase/Liter-ը ԱՐԴԵՆ բազմապատկված են коэф-ով. Ташкент (100%) = 46.0 / 14.0,
    # Ереван (155%) = 71.3 / 21.7 = 46 × 1.55 / 14 × 1.55 (cache_wb, 2026-10-03)։
    # Կրկին բազմապատկելը լոգիստիկան ×1.55 էր ուռճացնում → warehouse_coef = 1.0։
    payload = {
        "_source": "WB Seller API /api/v1/tariffs/box + /commission",
        "_synced_at": str(date.today()),
        "_warehouse": wh.get("warehouseName"),
        "_delivery_coef_included_pct": round(delivery_coef * 100),
        "_storage_coef_included_pct": round(storage_coef * 100),
        "logistics": {
            # WB-ի API-ն տալիս է ՄԵԿ բազային գին ≤1 լ-ի համար (boxDeliveryBase),
            # ոչ թե ենթալիտրային աստիճաններ → լրացնում ենք բոլոր աստիճանները նույն թվով,
            # որ merge-ից հետո հին ՌԴ-ի ենթադրությունները չմնան։
            "tiers_under_1l": {k: delivery_base for k in (0.200, 0.400, 0.600, 0.800, 1.000)},
            "first_liter_over_1l": delivery_base,
            "extra_liter": delivery_liter,
            "warehouse_coef": 1.0,
        },
        "storage": {
            "per_liter_per_day": round(storage_liter or storage_base, 4),
            "warehouse_coef": 1.0,
        },
    }
    if commissions:
        best = commissions[0]
        payload["commission_pct"] = round(rub(best.get("paidStorageKgvp")), 2)
        payload["_commission_subject"] = best.get("subjectName")

    if args.apply:
        AUTO.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"\n✔ գրվեց {AUTO}")
        print("   unit_econ-ը այսուհետ կվերցնի այս թվերը (merge բազային config-ի վրա)։")
    else:
        print("\n(--apply չկա → ֆայլը չի գրվել)")
    print(f"[wb api_calls={client.api_calls} cache_hits={client.cache_hits}]")


if __name__ == "__main__":
    main()
