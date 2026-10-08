---
description: Scan a WB category branch and rank sub-niches by opportunity score
---

Scan and rank sub-niches for: **$ARGUMENTS**

Steps:

1. Run `python -m src.mpstats_client limit` and report the remaining quota. If fewer than
   30 requests remain, stop and ask the user before continuing.
2. Resolve the exact category path with `python -m src.mpstats_client categories "<keyword>"`.
   Never guess a path — MPSTATS matches it literally.
3. Preview the plan: `python -m src.niche_scan --path "<path>" --children categories --top 12 --dry-run`.
   Show the user the niche list and the estimated request count.
4. Execute the scan without `--dry-run`.
5. Read `reports/niche_scan_<date>.md` and write a short Armenian summary:
   - top 3 niches with score, revenue per selling card, top-10 share, growth, median price;
   - for each: 1 sentence on why it ranks there;
   - every niche rejected by a hard filter, with the reason;
   - the single biggest data caveat you noticed (outliers, thin samples, missing dates).
6. Recommend which ONE niche to take to `/sku-audit` next and why.

Do not propose a product yet — this stage only narrows the field.
