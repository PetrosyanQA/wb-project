# Մեր գործիքների քարտեզը (2026-10-18)

Կանոն. ամեն խնդրի համար սկզբում ընտրել **ամենաէժան աշխատող** գործիքը, հետո՝ ավելի թանկը։
Գաղտնաբառեր/ключ-եր՝ միայն `.env`-ում (APIFY_TOKEN, BRIGHTDATA_TOKEN, MPSTATS_TOKEN, SALEFLOW_TOKEN, WB_SELLER_TOKEN)։

## 1. Գործիքներ և սահմանաչափեր

| Գործիք | Ինչ է տալիս | Արժեք / լիմիտ | Կարգավիճակ |
|---|---|---|---|
| **Saleflow MCP** (`saleflow_universal`) | WB/Ozon/YM նիշաներ, products, SKU by_period (գովազդ, դիրք, մնացորդ), քարտեր, վաճառողներ, բրենդներ, `lk_wb_*` (մեր կաբինետ), `pe_*` (ֆոտո), repricer, wbbidder | 500 հարցում/օր; տվյալները վստահելի ≤ 2026-07-31 | ✅ (products-ը երբեմն ընկնում է) |
| **MPSTATS API** | կատեգորիաներ, items, by_date, keywords, comments | սակագնով; `mpstats_client plan` | ✅ |
| **WB Seller API** | իրական комиссия, тарифы, выкуп, воронка, финотчет | 1 հարցում/րոպե (throttle) | ✅ read-only |
| **WB հրապարակային** (CDN քարտեր, отзывы) | քարտի չափեր, կազմ, կարծիքներ | անվճար | ✅ `wb_cdn_card` |
| **Bright Data** Web Unlocker | ցանկացած հրապարակային էջ | 5 000 կրեդիտ/ամիս անվճար, մեր սահմանը 20/օր | ✅ 1688; ⚠️ Amazon (ցանկը JS-ով); ❌ Ozon (KYC/robots) |
| **Exa MCP** `web_search_exa` / `web_fetch_exa` | իմաստային որոնում թարմ հոդվածներում, օրենքներում, ամբողջ էջի ընթերցում | ըստ Exa պլանի | ✅ փորձարկված (ЧЗ, շուկայի թրենդներ) |
| **Exa** `agent_run` | բազմաքայլ հետազոտություն, աղյուսակ | **վճարովի** ($5 լռելյայն) → միայն օգտատիրոջ «այո»-ով և `budget`-ով | չօգտագործված |
| **Apify** | Amazon / TikTok / Google Trends ակտորներ, 1688 | $5/ամիս, կրեդիտը 0 մինչև 2026-11-01 | ⏸ |
| **WebSearch / WebFetch** (ներկառուցված) | արագ որոնում / էջ | անվճար | ✅ |
| **Բրաուզեր** (ներկառուցված / Claude in Chrome) | էջեր, որտեղ պետք է մարդու մուտք (1688 login — մուտքը անում է օգտատերը) | անվճար | ✅ |
| **Photo editor** (MPSTATS skill + Saleflow `pe_*`) | ֆոն, ինֆոգրաֆիկա, ֆոտոշուտ քարտի համար | սակագնով | ✅ |
| **Scheduled tasks** | ավտոմատ վերահսկում (комиссия, մրցակիցներ, backup) | անվճար | ✅ ակտիվ |
| **Telegram plugin** | ծանուցումներ օգտատիրոջը հեռախոսին | անվճար | միացված է |
| **Artifacts / Docs** | ինտերակտիվ դաշբորդ, համատեղ փաստաթուղթ | անվճար | ✅ |
| **Skills** | find-niche, gates, decide, sku-audit, trend, wb-forecast, wb-winner-dna, trend-hunter | — | ✅ |

## 2. Խնդիր → գործիք

| Խնդիր | 1-ին ընտրություն | Պահուստային |
|---|---|---|
| Նիշաների սքրին | Saleflow subjects/products | MPSTATS |
| Մատակարարի ¥ | **Bright Data `s1688`** | Chrome (օգտատիրոջ մուտքով), Apify (11/01-ից) |
| Մատակարարի MOQ, չափեր | Bright Data 1688 detail (պարսեր գրելու է) | Chrome |
| Մրցակիցների կարծիքներ WB | WB հրապարակային feedbacks | Saleflow / MPSTATS comments |
| Կարծիքներ Ozon | Saleflow `ozon_sku` | — (Bright Data-ն արգելափակված է) |
| ЧЗ / сертификация / ТН ВЭД | **Exa web_search** (КонсультантПлюс, Честный знак) | WebSearch |
| Շուկայի նորություններ, թրենդներ RU | **Exa web_search** | WebSearch |
| Միջազգային թրենդներ | Apify (Amazon/TikTok) | Bright Data Amazon (պետք է պարսեր) |
| Իրական ծախսեր և выкуп | WB Seller API | config-ի ենթադրություններ |
| Քարտի ֆոտո | Photo editor | — |
| Մշտական վերահսկում | Scheduled tasks + Telegram | — |

## 3. Փորձարկումներ 2026-10-18

| Փորձ | Արդյունք |
|---|---|
| Bright Data 1688 (731 / 249 / 722) | ¥ P50 4,05 / 4,18 / 29,8 [факт] |
| Bright Data Amazon Movers & Shakers Pet | էջը բեռնվում է, բայց ցանկը JS-ով է → պարսեր կամ Apify |
| Bright Data Ozon որոնում | ❌ «not available … no KYC … robots.txt» |
| Exa՝ реле напряжения ЧЗ? | **Այո**՝ 8536 49 000 0 «реле на напряжение ≤ 1000 В» ПП 1954-ում, արգելք 01.12.2026-ից → 4536 դուրս [факт, КонсультантПлюс] |
| Exa՝ կենդանիների խաղալիքների շուկա | Ozon՝ խաղալիքներ ×2,3 (2026 H1), WB zootovary +44 %; ամենաարագ աճողը՝ ինտերակտիվ/puzzle; գնորդի հիմնական պահանջը՝ դիմացկունություն [факт, logistics.ru 2026-10-06, IndexBox 2026-05] |
