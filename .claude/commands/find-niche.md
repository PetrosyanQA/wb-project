---
description: Start from ZERO — search the whole WB catalogue and shortlist niches for the budget
---

The user has **no niche in mind**. Find one for: **$ARGUMENTS** (constraints, if any).

Never ask "which category?" — that is the whole point of this command. Ask only about
constraints the data cannot know (see step 2).

1. `python -m src.mpstats_client limit` → report remaining quota. The full funnel costs ~30–40
   requests; if fewer remain, reduce `--max-requests` and say so.
2. Confirm the beginner constraints in one short message (default to `config/scoring.yaml`
   if the user does not care): budget, price band, and categories to exclude
   (clothing/shoes = sizes and 30–45% buyout; food/cosmetics = certification;
   electronics = warranty). Do not turn this into an interview — one message, then proceed.
3. Preview: `python -m src.discover --depth 2 --top 20 --dry-run`, then run it for real.
   Stage 1 screens hundreds of sub-categories on **aggregates only** (revenue, SKU count,
   average price). Stage 2 ("probe", automatic for the top 10) pulls just the top-20 cards of
   each survivor — 1–2 requests each — and that is where **monopoly, growth, review barrier and
   fresh-card success** become visible. The final score is 40% cheap + 60% probe.
   Never report the cheap score alone: a niche can look excellent on aggregates and collapse
   once the probe shows the top-10 holding 83% of revenue.
4. Take the top 5 and run the deep pass: `python -m src.discover --depth 2 --deep 5`
   (or `niche_scan` on each path if the user wants more control).
5. For the surviving top 3, run `python -m src.trend_scan --path "<path>" --days 540 --snapshots 4`
   and apply the four gates from `/trend`: direction → saturation → timing → stock risk.
6. Deliver in Armenian:
   - **3 նիշա** ranked, each with: why it survived, the killer number, and the main risk;
   - what was rejected and why (one line each) — the user learns the filter logic;
   - the ONE niche you would personally take with $2,000 and the reason;
   - the exact next command to run.

Never present the cheap screening score as a final verdict — it is a funnel stage, not a decision.
