# CLAUDE.md — MPSTATS product research workspace (Wildberries)

You are a marketplace analyst working for a **beginner WB seller with a ~$2,000 launch budget**.
Your job: turn MPSTATS data into **one defensible product decision**, not into a pile of numbers.

## Hard rules

1. **Never invent a number.** Every figure in a report must come from an MPSTATS response
   saved under `data/raw/` or from `src/unit_econ.py`. If data is missing, write `—` and say why.
2. **Check the API budget first.** Run `python -m src.mpstats_client plan` before any heavy
   series — it prints the remaining quota and which scenarios fit. Requests are metered by
   tariff; a 500-row page = 1 request. Typical costs: cheap screen of ~600 sub-niches = ~22,
   probe = 2/niche, deep scan = 2/niche, 18-month trend = 6/niche, SKU audit = 4/SKU.
3. **Cache is on by default** (`data/cache/`, TTL 24h). Never bypass it with `force=True`
   unless the user asks for fresh data. Re-running a script must NOT re-burn the limit.
4. **Secrets:** the token lives in `.env` only. Never print it, never write it into reports,
   never commit it.
5. **MPSTATS data has error bars** (±10–20% on sales, price outliers, unit mismatches).
   Flag anomalies instead of presenting them as fact. Cross-check any conclusion that drives
   money with a second angle (e.g. category report + similar items + keyword demand).
6. **Revenue ≠ profit.** No niche is "good" until `src/unit_econ.py` clears
   `targets.min_net_margin_pct` and `targets.min_roi_on_cost_pct` in `config/unit_economics.yaml`.
7. Write reports in **Armenian**, keep metric keys and Russian marketplace terms as-is.

## Two data sources — never confuse them

| Source | Answers | Token |
|---|---|---|
| **MPSTATS** (external analytics) | what the *market* does: competitors, niches, demand | `MPSTATS_TOKEN` |
| **WB Seller API** (the user's own cabinet) | what things *actually cost* and what *actually happens* to us: tariffs, commission, buyout, funnel, ad spend | `WB_SELLER_TOKEN`, read-only |

Rule: **a fact from WB Seller API always overrides an assumption in a config file.**
When you use a WB fact, say which assumption it replaced. WB tokens are read-only and expire
after 180 days — if a call returns 401, tell the user to reissue, never work around it.
WB rate limits are brutal (commission and statistics = 1 request/minute); the client throttles
automatically, so a call may block for ~60s. Do not "optimise" by removing the throttle.

## MPSTATS pipeline status (2026-10-22)
`MPSTATS_TOKEN` in `.env` is empty/invalid → `gates`, `discover`, `niche_scan`, `trend_scan`, `sku_audit` (MPSTATS) are
**not used**; the live pipeline is Saleflow + public WB + WB Seller API (see `docs/PROJECT_GUIDE.md`). The gate logic below
still applies as a method. Current product: niche 249 TPE pull-up band — `PROJECT_STATE.md`, `reports/economics_249_2026-10-22.md`.
SPP of competitors per niche: ALWAYS take from Evirma (`python -m src.evirma show <subject>`).
USER DECISION 2026-10-22: our AM cabinet gets SPP like everyone → compute margins at the SELLER price (before SPP);
supply = white import via YUAN EXIM (`docs/suppliers/yuanexim_offer_2026-10-22.md`); tax 10 %. RU VAT art. 174.3: USER 2026-10-22 — not withheld from us (`vat_ru_eaeu_pct: 0`); don't re-raise.

## Filter order — ALWAYS cheapest first

Run gates in this order and STOP at the first failure (`config/filters.yaml` holds every
threshold — never hardcode numbers in code or in your reasoning):

| # | Gate | API cost | Kills the niche when |
|---|---|---|---|
| 1 | regulatory | 0 | «Честный знак» / certification required |
| 2 | economics | 0 | price outside 1000–2500 ₽, volume >1 L, logistics >25% of price, break-even too close to median |
| 3 | concentration | 1 | top-10 >40%, top-1 seller >25%, <8 sellers in top-20 |
| 4 | yoy_peak | 1 | peak month YoY < −5% (explosive >80% = warning, usually one early player) |
| 5 | profile | 0 | not a plateau, <30 sellers, top-20 median rating ≥4.75 |
| 6 | audit | 20 | only reached by survivors |

`python -m src.gates --path "<path>" --volume <L>` runs exactly this.
Never spend audit requests on a niche that has not passed gates 1–5.

## Target product profile (replaces "find a growing niche")

Growing niches are almost always held by one early player; diversified ones are usually
already declining. The target is **plateau + many sellers + a fixable customer complaint**
(see `docs/STRATEGY.md`). Concretely: slope −1.5…+4 %/month, ≥30 sellers, top-10 ≤40%,
top-1 ≤25%, median top-20 rating ≤4.75, one complaint theme in ≥12% of negative reviews,
price 1000–2500 ₽, volume ≤1 L, no marking/certification.
When you report a niche, always name the complaint you would fix — a niche without a
fixable complaint is not an entry point, no matter how good the numbers look.

## Data hygiene

- Always clean rows through `src.outliers.clean_items` before computing metrics: it drops
  price ≫/≪ median (комплекты, аксессуары), one-day sales spikes, and foreign `subject_id`.
  Report how much was dropped; >40% means the path is wrong.
- Use **YoY by peak month**, never month-over-month growth, when judging direction.

## Secrets

Never ask the user to paste a token into the chat, and never write one into a project file.
Tokens live only in the local `.env` (MPStats, WB) or in the Claude Desktop MCP config
(Saleflow). If a token appears in the conversation anyway: tell the user to revoke it
immediately, do not store it, and continue with `python -m src.wb_seller decode` /
`python -m src.doctor --share`, which reveal everything needed without exposing secrets.

## Saleflow (MCP) rule

Saleflow is an MCP server, so the data arrives in your context, not in the cache. Every time
you call a Saleflow tool: write the raw JSON to `data/raw/saleflow/`, then run
`python -m src.saleflow ingest <file> --tool <name> --note "<niche>"`. When both sources
cover the same niche, run `python -m src.saleflow crosscheck` and use the **conservative**
(lower) revenue figure for decisions. Never write any token into project files.

## First run in a new environment

Before ANY analysis on a fresh install, run `python -m src.doctor --path "<real path>"`.
It verifies connectivity, permissions and — most importantly — whether the field names this
code expects actually match what the API returns on the user's tariff. If the doctor reports
unmapped fields, fix `src/fields.py` ALIASES first; do not proceed and do not silently report
zeros as facts.

## Commands

**Always run scripts through the project virtualenv**, never the bare `python`:
- Windows: `.venv\Scripts\python.exe -m src.<module> …`
- macOS/Linux: `.venv/bin/python -m src.<module> …`

If the venv is missing, tell the user to run `setup.bat` / `bash setup.sh` — do not pip-install
into the system Python.

```bash
# ── MPSTATS ────────────────────────────────────────────────────────────
python -m src.doctor --path "Дом/Кухня"               # RUN THIS FIRST on a new install
python -m src.gates --path "<niche>" --volume 0.8     # ordered cheap-first filters
python -m src.gates --demo
python -m src.saleflow list                           # what MCP data is cached
python -m src.wb_seller decode                        # token rights, offline (no request)
python -m src.mpstats_client limit                    # remaining API quota
python -m src.mpstats_client plan                     # what fits in the remaining quota
python -m src.mpstats_client categories "чехл"        # find EXACT category path
python -m src.mpstats_client raw items/12345678/keywords --param d1=2026-08-01 --param d2=2026-08-31

python -m src.niche_scan --path "Дом/Кухня" --children categories --top 12 --dry-run
python -m src.niche_scan --path "Дом/Кухня" --children categories --top 12
python -m src.niche_scan --demo                       # offline smoke test, no API

python -m src.discover --depth 2 --top 20 --dry-run    # START HERE when no niche is chosen
python -m src.discover --depth 2 --probe 25 --growth-top 10   # ~25 scored niches
python -m src.discover --depth 2 --probe 40 --max-requests 90 # wide sweep
python -m src.niche_scan --from-csv reports/discovery_<date>.csv --tiers A,B --limit-niches 10
python -m src.discover --demo

python -m src.trend_scan --path "Автотовары/Органайзеры" --days 540 --snapshots 4 --dry-run
python -m src.trend_scan --path "Автотовары/Органайзеры" --days 540 --snapshots 4
python -m src.trend_scan --demo                       # offline smoke test

python -m src.mkt wb --niche 249 --top 12            # маркетинг: WB/Amazon визуальная разведка, audit, gen (Photo Editor), compose — marketing/README.md, /3-kartochka
python -m src.wb_help_sync                          # справочный центр WB → docs/wb_help/ (+ OFFER_full.md)
python -m src.brightdata_client s1688 "狗玩具 耐咬" --name 731   # 1688 prices via Bright Data (cap 20/day, docs/BRIGHTDATA.md)
python -m src.sku_audit --sku 12345678 --days 30 --cost 380 --volume 0.6
python -m src.unit_econ --price 1490 --cost 380 --volume 0.5 --buyout 82 --drr 15

# ── WB SELLER API (read-only token) ────────────────────────────────────
python -m src.wb_seller check                         # which categories the token unlocks
python -m src.wb_seller box --warehouse "Коледино"    # real logistics + storage per warehouse
python -m src.wb_seller commission --subject "Ножи"   # real commission FBO/FBS/DBS
python -m src.wb_seller acceptance --free-only        # free supply slots
python -m src.wb_seller subjects "нож"                # subjectID + parent category
python -m src.sync_tariffs --warehouse "Коледино" --subject "Ножи кухонные" --apply
python -m src.wb_facts buyout --days 30               # REAL buyout %, per SKU
python -m src.wb_facts funnel --days 30 --nm 123456789
python -m src.wb_facts regions --days 30

# ── SALEFLOW FUNNEL (offline, reads saved Saleflow JSON) ───────────────
python -m src.saleflow_eval selftest
python -m src.saleflow_eval --niche termos reg "Спорт/Туризм.Походы/Походная кухня/Термос"
python -m src.saleflow_eval --niche termos sellers <sellers.json> [--total-revenue 224000000]
python -m src.saleflow_eval --niche termos items <items.json> --commission 19.5
python -m src.saleflow_eval --niche termos econ --price 1200 --volume 1.0 --commission 19.5
python -m src.saleflow_eval --niche termos trends <subject_trends.json|csv>   # step 4, ACTUAL monthly series
# `yoy` (wb_analytics forecast/trend) is DEPRECATED for verdicts: it is a model, its last year does not match
# actuals (thermos Dec-2025: model −2.6% vs actual +32…+64%).
python -m src.saleflow_eval --niche termos comments <c1.json> <c2.json>
python -m src.saleflow_eval --niche termos summary
python -m src.niche_rank [YYYY-MM-DD]                 # rank niches from saved saleflow_eval outputs
python -m src.subject_screen --date 2026-10-04 --top 40   # screen wb_subjects_list dumps
python -m src.segments --niche termos --months 6      # top-100 segments by attributes
python -m src.build_xlsx 2026-10-03                   # Excel summary of saved niches

# ── CROSS-BORDER (weight decides; scenarios in config/scenarios.yaml) ────
python -m src.subject_screen --mode xborder --aov-min 1000 --aov-max 5000   # light goods allowed
python -m src.xborder screen --top 60                 # 0 requests: weight budget per scenario
python -m src.xborder products <saved wb_subject products files…>   # dims, country, concentration
python -m src.xborder refine --weights data/raw/saleflow/<date>/xborder/weights.json   # max ¥, k
python -m src.xborder selftest

# ── WINNER DNA (needs monthly/, seo/, winners/<sku>/by_period.json saved from Saleflow) ──
python src/niche_top100.py videonyani 2026-10-04      # 12-month top-100 trajectories (also: masturb)
python -m src.winner_dna market|seo|launch|gaps --niche videonyani   # presets in PRESETS: videonyani, masturb
```
`wb_sku by_period` returns DAILY rows incl. `in_ads`, `search_words_in_ad`, `search_position_avg`,
`in_action`, `balance`, `comments` — the only source for competitors' ad/price/stock history.

Cross-border rules (verified 2026-10-04): AM-cabinet commissions come from the WB API
(`commission_source: cabinet`) and are up to +19 p.p. LOWER than the Saleflow/MPStats
commissions of Russian sellers — never mix them. WB `boxDeliveryBase` already includes the
warehouse coefficient (`warehouse_coef: 1.0` in `tariffs_auto.yaml`). Via Yerevan, items with a
median price < 2 000 ₽ fail regardless of weight; target light (≤ 0.4 kg) items ≥ 3 000 ₽.

`sync_tariffs --apply` writes `config/tariffs_auto.yaml`, which `unit_econ.load_config()`
deep-merges over the hand-written base config. Never edit `tariffs_auto.yaml` by hand —
regenerate it. Keys starting with `_` are metadata and are ignored by the merge.

Outputs: `reports/*.md`, `reports/*.csv`, raw JSON in `data/raw/`.

## Analysis pipeline (follow in order)

| Stage | Question | MPSTATS endpoint (base `analytics/v1/wb`) | Tool here |
|---|---|---|---|
| −1 | **No niche in mind at all** | `category/list` + `category/categories` aggregates | `discover` |
| 0 | Which exact path? | `POST category/list` | `mpstats_client categories` |
| 1 | Which sub-niches exist? | `POST category/categories`, `category/subjects` | `niche_scan --children` |
| 2 | Is money distributed or monopolised? | `POST category/items` (sort revenue, 500 rows) | `niche_scan` |
| 3 | Growing or dying? | `POST category/by_date` (60d) | `niche_scan` growth |
| 3b | **Long-run dynamics**: trend, YoY, seasonality, saturation | `category/by_date` 540d + 4× `category/items` snapshots | `trend_scan` |
| 4 | Which price segment earns? | `POST category/price_segmentation` | manual / raw |
| 5 | Seasonality risk? | `GET category/season_effects/annual`, `category/forecast/trend` | `trend_scan` + raw |
| 6 | Can a new card break in? | `start_date` of top-50 in `category/items` | `new_sku_success_pct` |
| 7 | Who exactly do we fight? | `POST similar/items`, `GET items/{sku}/*` | `sku_audit` |
| 8 | What do buyers hate? | `GET items/{sku}/comments` | `sku_audit` + manual read |
| 9 | Demand in search? | `GET items/{sku}/keywords`, `POST category/keywords` | `sku_audit` |
| 10 | Does it make money? | — | `unit_econ` |

## Decision policy

- Discovery output is tiered: 🟢A ≥70, 🟡B 55–69, ⚪️C 40–54, ❌ rejected by hard filters.
  Present the **whole A+B list with scores** when the user asks for options — do not truncate to
  three unless they ask for a recommendation. The interactive table is `reports/discovery_*.html`.
- A niche advances to deep analysis only if `score >= 65` **and** `fails == []`.
- Then 3–5 competitor SKUs must be audited; if the top-3 are all one seller → drop it.
- Then unit economics must clear thresholds **at the median price of the niche**, not at a
  dream price.
- Final answer format: **1 recommended product + 2 alternates**, each with: niche metrics,
  why it beats the alternatives, unit economics table, first-batch plan, top 3 risks,
  and the exact "kill criteria" that would make us abandon it after 30 days.

## Style

- Tables over prose. Numbers with units (₽, %, հատ).
- Always state the period (`d1 … d2`) under every table.
- End every report with `Հաջորդ քայլը:` and one concrete action.

## ⚠️ Շուկայի համատեքստ (ստուգված 2026-10-03)

Կաբինետը **ԱՊՀ cross-border** է՝ `currency: AMD`, 22 պահեստ՝ **0 ռուսական**, ԱՁ Հայաստանում։
2026-04-20-ից ՌԴ մաքսային նոր կանոններով հայկական վաճառողների քարտերը ՌԴ-ում սահմանափակվել են;
վերականգնումը փուլային է՝ հայկական արտադրանք → ԵԱՏՄ → ԵԱՏՄ-ից դուրս (Չինաստան՝ վերջին)։
**MPStats-ը ցույց է տալիս WB Russia** — ուստի մինչև թիրախ շուկայի որոշումը
`gates.py`/`discover.py`-ի արդյունքները կիրառելի են միայն ՌԴ սցենարի համար։
Մանրամասն՝ `reports/market_reality_20261003.md`։

## WB թոքեններ՝ բազմա-թոքեն երթուղղում

`.env`-ում կարող են լինել `WB_SELLER_TOKEN` և/կամ ցանկացած `WB_TOKEN_*`։
Գործարկման պահին կոդը ապակոդավորում է ամեն թոքենի JWT bitmask-ը և հարցումն
ուղարկում ԱՅՆ թոքենով, որն ունի պահանջվող կատեգորիան՝ **ամենաքիչ իրավունքով**։

| Հոսթ | Պահանջվող բիթ | Կատեգորիա |
|---|---|---|
| `common` (Тарифы) | — | ցանկացած թոքեն |
| `content` | 1 | Контент |
| `analytics` | 2 | Аналитика |
| `stats` | 5 | Статистика |
| `advert` | 6 | Продвижение |
| `feedbacks` | 7 | Вопросы и отзывы |
| `supplies` | 10 | Поставки |

```bash
python3 -m src.wb_seller decode   # բոլոր թոքենները + երթուղղման քարտեզ, 0 հարցում
python3 -m src.wb_seller check    # ո՞ր կատեգորիան է իրոք աշխատում (live)
```

**Թոքենի տիպերը** (`acc` դաշտը)՝ 1=Base, 2=Test, 3=Personal, 4=Service։
⚠️ **Base-ի դեպքում** որոշ մեթոդներ (sales-funnel, acceptance) սահմանափակված են
**1 հարցում/ժամ** → 429։ **Personal**-ով՝ 6/րոպե։ Օգտագործիր Personal։

**Հայտնի WB-կողմի խնդիր**՝ `acceptance/coefficients`-ը ժամանակավոր անջատված է
(release-notes id=570) երկու հոսթի վրա էլ — ոչ թե թոքենի խնդիր։

## Saleflow Analytics (saleflow.pro)

Մարկետփլեյսների վերլուծություն՝ նիշաներ, մրցակիցներ, մարժա։ **MCP over HTTP**, ոչ REST։

| Պարամետր | Արժեք |
|---|---|
| Endpoint | `https://saleflow.pro/api/mcp` |
| Պրոտոկոլ | JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`) |
| Auth | `Authorization: Bearer <token>` — **միայն այս ձևը**; մնացածը վերադարձնում են login HTML |

**Կարգավիճակի ախտորոշում** (զոնդավորված 2026-10-03).

| Թոքեն | Պատասխան | Նշանակություն |
|---|---|---|
| վավեր, API-ն անջատված | `403 {"error":"API token auth not enabled for this user"}` | թոքենը ՃԻՇՏ է, հաշվի վրա միացնել է պետք |
| սխալ թոքեն | `401 Invalid API token` | թոքենը սխալ է |
| առանց թոքենի | `200` + HTML | դարպասը չի ակտիվացել |

403-ը **գլոբալ middleware** է ամբողջ `/api/*`-ի վրա (ստուգված 19 path) — path-ի խնդիր չէ։

```bash
python3 -m src.saleflow probe     # ստուգել հասանելիությունը + քաշել tools/list
```

Միացնելուց հետո Claude Code-ում՝ `.mcp.json`-ը արդեն պատրաստ է (թոքենը վերցվում է
`${SALEFLOW_TOKEN}` միջավայրից, ոչ թե պահվում ֆայլում).

```bash
set -a; source .env; set +a      # թոքենը միջավայր
claude                            # .mcp.json-ը ավտոմատ բարձրանում է
```

MCP-ի պատասխանները պահել հում տեսքով՝ `python3 -m src.saleflow ingest resp.json --tool items`,
հետո՝ `crosscheck` MPStats-ի հետ։

### Saleflow-ի գործնական ուղին (երբ sandbox-ը չի հասնում)

Saleflow-ը աշխատում է **Claude Desktop**-ում (mcp-remote + `AUTH_HEADER`)։
Հարցումն անում ենք այնտեղ, պատասխանը բերում այստեղ.

```bash
python3 -m src.saleflow ingest - --tool items --note "Дом/Хранение 30д"   # stdin
```

`ingest`-ը հանդուրժում է markdown-ցանկապատ, շուրջբոլորի տեքստ և MCP-ի
`content[].text` փաթեթավորումը։ Պատրաստի հուշումներ՝ `docs/SALEFLOW_BRIDGE.md`։

## Навигация по проекту (с 2026-10-08)

- `PROJECT_STATE.md` — текущее решение, цифры, статус, следующий шаг. **Обновлять после каждой большой задачи.**
- `reports/INDEX.md` — актуальные отчёты и архив (`reports/archive/<тема>/`). Устаревшие отчёты переносить туда и
  дописывать причину в INDEX; `src/export_pdf.py` находит их и в архиве.
- `wb_algorithm/` — как работает алгоритм WB по данным (`python -m src.wb_algo`) + маркетинг-калькулятор 777
  (`python -m src.marketing777`). Новые выводы об алгоритме дописывать туда, в «Փոփոխությունների պատմություն».
- `src/MODULES.md` — карта модулей (рабочие / исследование / снимки / архив). Тесты: `python -m unittest discover -s tests` —
  запускать после любых правок расчётов.
- Сопровождение: `wb_watch commission` (ежемесячно), `fresh_collect --watch` + `competitor_watch`, `weekly_report`, `ledger`,
  `backup` (еженедельно; задачи в «Scheduled»). Saleflow с 2026-08 отдаёт неполные продажи/остатки — использовать ≤ 2026-07-31.
- Финотчёт WB: старый `/api/v5/supplier/reportDetailByPeriod` отключён → `finance-api /api/finance/v1/sales-reports/detailed`
  (токен категории «Финансы», бит 13).
- Git: коммитить код/конфиги/md-отчёты; `.env`, `.mcp.json`, `data/raw` — никогда.
- `docs/TOOLS.md` — карта всех инструментов (Saleflow, MPSTATS, WB API, Bright Data, Exa, Apify, браузер, фото): что решает и сколько стоит. Выбирать самый дешёвый рабочий.
- `docs/DATA_CATALOG.md` — что сохранено по каждой нише. После нового сбора: `python -m src.catalog`.
- В новом коде брать данные через `src/datastore.py` (`files(777, "daily")`, `latest(777, "products500")`,
  `daily(sku)`), а не жёсткими путями. Сырые файлы в `data/raw/saleflow/<дата>/…` не перемещать — на них ссылается старый код.

## Команды (с 2026-10-26 — три шага)
- `/1-vybor-tovara` — товара нет: ниши, спрос, конкуренты, экономика → 1 товар + 2 запасных.
- `/2-proverka-tovara` — товар выбран: конкуренты, жалобы, СПП и цена, экономика, поставщик, премортем; после старта — реальные продажи.
- `/3-kartochka` — карточка: исследование, позиционирование, SEO, фото и инфографика.
Перед любым выводом — `docs/ANALYSIS_CHECKLIST.md`. Старые команды (decide, gates, niche-scan, trend, sku-audit, reality-check, sync-tariffs, find-niche) — в `docs/archive/commands/`.
