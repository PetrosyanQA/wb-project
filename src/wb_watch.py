"""Сторож кабинета WB: комиссия (раз в месяц) и проверка базы удержаний — от цены до СПП или от цены покупателя.

    python -m src.wb_watch commission         # комиссия кабинета по нашим предметам vs базовая → тревога при росте
    python -m src.wb_watch spp-basis --days 14 # по реализации (reportDetailByPeriod): от какой цены WB считает комиссию

commission: WB API /api/v1/tariffs/commission (1 запрос/мин, кэш 24 ч). FBS = kgvpMarketplace, FBO = paidStorageKgvp,
  DBS = kgvpSupplier (см. memory wb-commission-fields). Базовая линия — config/commission_baseline.json (создаётся при
  первом запуске), история — data/processed/commission_history.csv. При изменении пересчитывает маржу через marketing777.
spp-basis: строки «Продажа» из детализации реализации (finance-api, токен «Финансы»). Сравнивает фактическое вознаграждение WB с двумя гипотезами:
  A) комиссия% × цена до СПП (retailPriceWithDisc), B) комиссия% × цена покупателя (retailAmount).
  Поля — по документации WB [справка]; вердикт эвристический, сверить с еженедельным отчётом в кабинете.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import statistics as st
import sys

from src.wb_seller import WBError, WBSellerClient, rub

sys.stdout.reconfigure(encoding="utf-8")
WATCH = {249: "Эспандеры", 777: "Держатели в авто", 2486: "Катушки рыболовные"}   # 249 — наш товар; 777/2486 — для истории
BASE = "config/commission_baseline.json"
HIST = "data/processed/commission_history.csv"
FIELDS = {"FBS": "kgvpMarketplace", "FBO": "paidStorageKgvp", "DBS": "kgvpSupplier"}


def commission() -> int:
    c = WBSellerClient(quiet=True)
    data = c.tariffs_commission()
    rep = data.get("report", data.get("data", {}).get("report", [])) if isinstance(data, dict) else data
    now = {sid: {k: r.get(f) for k, f in FIELDS.items()} for r in rep for sid in WATCH if r.get("subjectID") == sid}
    base = json.load(open(BASE, encoding="utf-8")) if os.path.exists(BASE) else None
    today = dt.date.today().isoformat()
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    new_file = not os.path.exists(HIST)
    with open(HIST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "subject_id", "subject", "FBS", "FBO", "DBS"])
        for sid, v in now.items():
            w.writerow([today, sid, WATCH[sid], v["FBS"], v["FBO"], v["DBS"]])
    if base is None:
        json.dump({"date": today, "commission": {str(k): v for k, v in now.items()}}, open(BASE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"базовая линия создана ({today}):", now)
        return 0
    alarm = 0
    for sid, v in now.items():
        b = base["commission"].get(str(sid), {})
        for k in FIELDS:
            if b.get(k) is not None and v[k] is not None and v[k] != b[k]:
                alarm = 1
                print(f"⚠️ {sid} {WATCH[sid]} {k}: было {b[k]}% ({base['date']}) → стало {v[k]}%")
        print(f"{sid} {WATCH[sid]}: FBS {v['FBS']}% | FBO {v['FBO']}% | DBS {v['DBS']}%")
    if alarm and now.get(249, {}).get("FBS") is not None:
        from src.unit_econ import load_scheme, unit_economics
        from src.cargo import per_unit
        cfg = load_scheme("am_fbs")
        for name, price, yuan, kg, vol in (("чёрная 22 мм", 1100, 5.7, 0.23, 0.77), ("фиолетовая 32 мм", 1250, 7.8, 0.33, 0.96)):
            e = unit_economics(price, per_unit(yuan, kg, vol)["landed_rub"], vol, cfg, with_breakeven=False, buyout_pct=82,
                               commission_pct=now[249]["FBS"], ad_share_of_revenue_pct=15, packaging_rub=15)
            print(f"→ 249 {name} {price} ₽ при комиссии FBS {now[249]['FBS']}% (¥{yuan}, ДРР 15%): прибыль {e['net_profit']} ₽, "
                  f"маржа {e['net_margin_pct']}% (порог 18%)")
    else:
        print("✅ комиссия не изменилась с", base["date"])
    return alarm


def spp_basis(days: int) -> None:
    c = WBSellerClient(quiet=True)
    d2 = dt.date.today()
    d1 = d2 - dt.timedelta(days=days)
    rows = c.report_detail_by_period(d1.isoformat(), d2.isoformat()) or []
    sales = [r for r in rows if isinstance(r, dict) and str(r.get("docTypeName", "")).lower().startswith("продаж")
             and rub(r.get("retailAmount")) > 0]
    print(f"реализация {d1} … {d2}: строк {len(rows)}, продаж {len(sales)}")
    if not sales:
        print("Продаж ещё нет → проверку повторить после первой недели продаж (python -m src.wb_watch spp-basis --days 14).")
        return
    errA, errB, out = [], [], []
    for r in sales:
        pct = rub(r.get("commissionPercent"))
        before = rub(r.get("retailPriceWithDisc"))             # цена с учётом скидки продавца = до СПП
        buyer = rub(r.get("retailAmount"))                     # фактически оплачено покупателем
        fact = rub(r.get("ppvzSalesCommission")) + rub(r.get("vw")) + rub(r.get("vwNds"))
        if not pct or not before or not buyer:
            continue
        a, b = before * pct / 100, buyer * pct / 100
        errA.append(abs(fact - a) / a); errB.append(abs(fact - b) / b)
        out.append((r.get("nmId"), before, buyer, rub(r.get("spp")), pct, fact, rub(r.get("forPay"))))
    for o in out[:10]:
        print(f"  nm {o[0]}: до СПП {o[1]:.0f} | покупатель {o[2]:.0f} | СПП {o[3]}% | КВВ {o[4]}% | удержано WB {o[5]:.0f} | к перечислению {o[6]:.0f}")
    if errA and errB:
        mA, mB = st.median(errA), st.median(errB)
        verdict = "A — от цены ДО СПП (как в нашей модели) ✅" if mA < mB else "B — от цены ПОКУПАТЕЛЯ ⚠️ (маржа ≈ 10%, см. marketing_strategy §3)"
        print(f"отклонение гипотезы A {mA:.1%}, B {mB:.1%} → база удержаний: {verdict}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["commission", "spp-basis"])
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    try:
        sys.exit(commission() if a.cmd == "commission" else spp_basis(a.days))
    except WBError as e:
        print("WB API:", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
