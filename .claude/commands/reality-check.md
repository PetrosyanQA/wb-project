---
description: Compare the plan against real WB seller data (buyout, funnel, costs)
---

Reality-check the launch for: **$ARGUMENTS**

Run only what the token allows; skip silently what it does not, and say so at the end.

1. `python -m src.wb_facts buyout --days 30` → real выкуп %.
   Compare with `operations.buyout_pct` in `config/unit_economics.yaml`.
   If the gap is ≥10 p.p., **recompute unit economics with the real number** and show the new margin.
2. `python -m src.wb_facts funnel --days 30 --nm <ids>` → diagnose the bottleneck:
   views → cart → order → buyout. Name ONE bottleneck, not four.
3. `python -m src.wb_facts regions --days 30` → check whether the warehouse choice still makes sense.
4. Pull the financial truth if available:
   `python -m src.mpstats_client raw` is NOT for this — use
   `WBSellerClient.report_detail_by_period()` via a short script, and compare the actual payout
   per unit with `unit_econ`'s predicted `payout_from_wb`. Explain every deviation > 5%.
5. Update `config/unit_economics.yaml` (or `tariffs_auto.yaml`) with the confirmed real values and
   say exactly which assumption was replaced by which fact.

Finish with: **«Ի՞նչ ենք անում հաջորդ 7 օրում»** — max 3 actions, ranked by money impact.
