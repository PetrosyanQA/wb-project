---
description: Marketing for a niche/product — competitor & international visual research, positioning, card brief, professional photos and infographic slides
---

Do the full marketing cycle for: **$ARGUMENTS** (niche id and product; e.g. `249 латексная петля 22 мм`).
Follow `marketing/README.md` step by step. Report in Armenian, full text in chat, files as backup.

1. **Data first.** Make sure products500 for the niche exists (`src.datastore.latest(<niche>, "products500")`); if not, collect it
   with Saleflow (`src.strategy_collect --step core`). Buyer complaints: `data/processed/complaints_*` or WB feedbacks (`src.niche_final_rank.feedbacks`).
2. **WB visual research:** `python -m src.mkt wb --niche <id> --top 12` (0 paid requests, WB CDN).
3. **International research:** `python -m src.mkt amazon --niche <id> --query "<english query>" --detail 6` (Bright Data, ≈ 7 credits;
   stop and tell the user if fewer than 100 credits remain).
4. **Audit:** `python -m src.mkt audit --niche <id>` → open `marketing/<id>/wb_galleries.jpg`, `wb_rich.jpg`, `amazon_galleries.jpg`
   with Read and describe slide by slide: what the leaders show, visual code, numbers on slide 1, what nobody shows (gap).
   Relate to sales/day and reviews from `audit_auto.md`. Use WB rules from `docs/wb_help` (photo ≥ 700×900, 3:4, no foreign logos, плашки).
5. **Positioning:** one sentence = the fixable complaint + the buyer's result. Never claim what the product can't prove
   (no «до 400 кг»). Every number on a slide must come from the spec / supplier table / our test — tag [факт]/[допущение].
6. **Brief:** 10 gallery slides + video + 5–6 rich blocks (800×500 / 700×700 / 700×900) + title ≤ 60 chars + all characteristics
   (`data/raw/wb_sandbox/charcs_<id>.json` or content API) + description with keywords from Saleflow keywords.
7. **Visuals:**
   - photos: `python -m src.mkt gen --niche <id> --mode freeform|photoshoot --image <our photo> --brief <txt>` (Saleflow Photo Editor);
   - text slides: write a JSON spec and `python -m src.mkt compose marketing/<id>/slides/<n>.json` — text is drawn by code,
     never by the AI model (it misspells Cyrillic). `infographics` mode of Photo Editor may be unavailable — fall back to compose.
   - Before showing: QA every frame with Read — product identity (color/width/shape), physically correct use (band on the bar,
     loop under knee/foot), no extra logos, readable on a phone. Reject and regenerate wrong frames.
   - Supplier/competitor photos = concept only, label «КОНЦЕПТ». Published frames must show OUR sample.
8. **Deliver:** `marketing/<id>/brief_<date>.md` + slides; send with SendUserFile; end with `Հաջորդ քայլը:`.
