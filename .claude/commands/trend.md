---
description: 12–18 month dynamics for a niche: trend, YoY, seasonality, saturation, entry window
---

Analyse the long-term dynamics of: **$ARGUMENTS**

1. Resolve the exact path first (`mpstats_client categories`), then preview the cost:
   `python -m src.trend_scan --path "<path>" --days 540 --snapshots 4 --dry-run`
   (~2 requests for the daily series + 1 per snapshot). Ask before spending quota.
2. Run it and read `reports/trend_*.md`.
3. Interpret in Armenian, in this exact order — do not reorder, each gate kills the next:

   **Gate 1 — Direction.** Trend %/month + YoY. If YoY < −10% → stop, recommend dropping the niche.
   Warn explicitly when R² < 0.2: the trend line is noise, not signal.

   **Gate 2 — Saturation.** The decisive number is `₽ per selling card` across snapshots.
   Revenue up + per-card down >15% = the niche is filling with sellers faster than with money.
   Say plainly whether a beginner still fits.

   **Gate 3 — Timing.** Seasonality amplitude and the entry window. If `too_late` is true,
   give the next viable order date instead of pretending it still works.

   **Gate 4 — Stock risk.** Volatility (CV). Above 60% recommend a larger safety stock and
   a smaller first batch.

4. Finish with one line: **«Մտնո՞ւմ ենք — այո / ոչ / այո, բայց <ամիս>-ից»** and the single
   number that would change the answer.
5. Remind the user this run was stored in `data/history.db`; suggest re-running weekly so the
   project accumulates its own time series.
