---
description: Deep-dive the leaders of a niche and extract a product improvement brief
---

Audit the competitors for: **$ARGUMENTS**

1. From the latest `reports/niche_scan_*.md` (or the user's input) pick the **5 SKUs that matter**:
   top-2 by revenue, 1 mid-table card that sells well with few reviews, and 2 cards younger
   than 120 days that already sell. Explain the choice.
2. Run `python -m src.sku_audit --sku <id>` for each (one call per SKU, mind the quota).
3. Pull reviews for the top-2: `python -m src.mpstats_client raw items/<id>/comments`.
   Extract the recurring complaints — these are the product requirements for our version.
4. Build a comparison table: price, 30-day revenue, sales, reviews, rating, stock,
   days in stock, estimated revenue per review.
5. Answer explicitly:
   - What is the **price anchor** of the niche (where the volume actually sits)?
   - What is the **review barrier** (median reviews of cards that sell daily)?
   - Can a card with 0 reviews get sales here? Evidence from the fresh SKUs.
   - What exact product improvement would win (from complaints), and does it raise cost?
6. Output: `reports/sku_audit_<date>.md` plus an Armenian summary with a
   "Ի՞նչ ապրանք ենք պատվիրում" spec: materials, size, packaging, what to fix vs leaders.
