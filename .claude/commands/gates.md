---
description: Run the cost-ordered filter gates on a niche (cheapest filter first)
---

Evaluate **$ARGUMENTS** through `config/filters.yaml` gates, cheapest first.

1. Ask the user ONLY for the product volume in litres if it is not obvious (it drives
   logistics and the economics gate). Default to 0.8 L if they do not know.
2. `python -m src.gates --path "<path>" --volume <L>` — it stops at the first failed gate,
   so a rejected niche costs 0–2 API requests instead of 20.
3. Report in Armenian, in gate order, and state **which gate killed it and at what cost**.
   Do not soften a FAIL: a niche that needs «Честный знак» is out, full stop.
4. If all gates pass, the next step is review mining — the entry wedge is the complaint:
   `python -m src.sku_audit --sku <id> --sku <id>` on 2 leaders + 1 mid + 2 fresh cards.
   Extract complaint themes from 1–3 star reviews, keep only themes that appear across
   ≥3 different sellers and ≥12% of negatives, and that can be fixed at supplier level
   without raising cost by more than 15%.
5. End with: the complaint you would fix, the first-screen infographic claim it produces,
   and the kill criteria from `docs/STRATEGY.md`.
