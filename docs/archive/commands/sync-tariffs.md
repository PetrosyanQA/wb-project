---
description: Replace guessed WB tariffs with real ones from the seller's WB API
---

Sync real WB tariffs for: **$ARGUMENTS** (warehouse and/or subject name)

1. Verify access first: `python -m src.wb_seller check`. If «Тарифы» is not available, stop and
   tell the user which token category is missing — do not guess numbers instead.
2. If the user did not name a warehouse, show the cheapest realistic options:
   `python -m src.wb_seller box` and pick by `boxDeliveryBase × coefficient`, not by name.
3. If a subject is known, get the exact commission: `python -m src.wb_seller commission --subject "<name>"`.
   Show FBO / FBS / DBS side by side — the difference often decides the fulfilment model.
4. Run `python -m src.sync_tariffs --warehouse "<wh>" --subject "<subj>" --apply`.
5. **Sanity-check the result**: recompute the unit economics before and after
   (`python -m src.unit_econ ...` with the same price/cost/volume) and report the delta in ₽ and %.
   If logistics moved by more than ±40%, warn that the warehouse coefficient may be double-counted
   and tell the user to compare with the WB cabinet calculator.
6. Also check acceptance: `python -m src.wb_seller acceptance --free-only` — list the nearest dates
   with coefficient 0 or 1 for that warehouse, since paid acceptance can eat the whole first margin.

Report in Armenian: old vs new numbers in one table, and whether the product still clears
`targets.min_net_margin_pct`.
