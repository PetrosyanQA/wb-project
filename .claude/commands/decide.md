---
description: Final go/no-go with unit economics and a launch plan for the $2,000 budget
---

Make the final decision for: **$ARGUMENTS**

1. Take the median price of the niche from the scan report (NOT an optimistic price).
2. Ask the user for supplier cost and parcel size if unknown; otherwise use their stated numbers.
   Compute volume in liters as `L × W × H (cm) / 1000` including packaging.
3. Run `python -m src.unit_econ --price <median> --cost <cost> --volume <liters> --buyout <%> --drr 15`.
   Run it again at price −15% (promo/price war scenario) and at buyout −15 p.p. (pessimistic).
4. Compare against `config/unit_economics.yaml` targets. State pass/fail for each scenario.
5. Compute the launch plan from `config/scoring.yaml` budget block:
   units affordable, expected days to sell out at the niche's median daily sales per card,
   ad budget, reserve, and the break-even number of units.
6. Check the non-data risks and say them out loud:
   certification / Честный знак marking, seasonality window, 18+ or restricted goods,
   fragile or oversized item, long supplier lead time, patent/brand risk.
7. Deliver in Armenian:
   - **ՈՐՈՇՈՒՄ:** 🟢 գնում ենք / 🟡 ստուգել ևս մեկ բան / 🔴 մերժում
   - unit economics table, batch plan, 3 risks with mitigation,
   - **Kill criteria:** the metrics that, if not reached in 30 days, mean we stop buying.
   - First 14 days action list (photos, SEO keywords from the audit, price, ad start).
