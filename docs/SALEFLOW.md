# Saleflow (MCP) + MPStats (API) — երկու աղբյուր մեկ շղթայում

## ⚠️ Նախ՝ անվտանգություն

Եթե թոքենը երբևէ հայտնվել է չատում, մեսենջերում կամ սքրինշոթում — **այն այլևս գաղտնի չէ**։
Saleflow-ում ստեղծիր նորը և նորից գործարկիր installer-ը («Установить / заменить токен»)։
Հին թոքենը անվավեր դարձրու։

Saleflow-ի թոքենը պահվում է **Claude Desktop-ի կոնֆիգում**՝
`mcpServers.saleflow.env.AUTH_HEADER` — ոչ թե այս պրոյեկտի `.env`-ում։
Այս repo-ի ոչ մի ֆայլում թոքեն չկա և չպետք է լինի։

## Երկու աղբյուրի տարբերությունը

| | MPStats | Saleflow |
|---|---|---|
| Ինտերֆեյս | REST API (token `.env`-ում) | **MCP սերվեր** (Claude-ն է կանչում) |
| Ո՞վ է հարցում անում | Python սկրիպտները | ինքը՝ Claude-ը |
| Քեշ | `data/cache/` 24ժ | ✋ չկա — դրա համար է ադապտերը |
| Հում տվյալ | պահվում է | պահվում է **միայն եթե Claude-ը գրի ֆայլ** |

MCP-ի թույլ կողմը. պատասխանը ապրում է զրույցի մեջ և անհետանում։ Հաջորդ օրը նույն
հարցումը նորից է գնում, իսկ թվերը չես կարող վերստուգել։ Ադապտերը դա ուղղում է։

## Կամուրջը

```
Claude (MCP tool call saleflow)
        ↓  պատասխանը գրում է ֆայլ՝ ԱՆՓՈՓՈԽ
data/raw/saleflow/<tool>_<sha1>.json
        ↓  python -m src.saleflow ingest
նորմալացված տողեր (նույն սխեման, ինչ MPStats items)
        ↓
niche_metrics / gates / unit_econ / crosscheck
```

### Կանոնը Claude-ի համար

> Երբ կանչում ես Saleflow MCP գործիք, **միշտ** պահիր հում JSON պատասխանը
> `data/raw/saleflow/`-ում և գործարկիր `python -m src.saleflow ingest <ֆայլ> --tool <անուն>
> --note "<նիշա>"`։ Առանց դրա տվյալը չի քեշավորվում և չի վերստուգվում։

Այս կանոնը գրված է նաև `CLAUDE.md`-ում, որ Claude-ը ավտոմատ հետևի դրան։

## Հրամանները

```bash
python -m src.saleflow ingest data/raw/saleflow/resp.json --tool items --note "Дом/Хранение"
python -m src.saleflow list                      # ինչ է պահված, որքան թարմ
python -m src.saleflow show <sha1> --limit 10    # նորմալացված տողեր
python -m src.saleflow crosscheck --mpstats <file.json> --saleflow <sha1>
```

## Խաչաստուգումը — ամենաարժեքավոր մասը

Երկու անկախ աղբյուր նույն նիշայի վրա.

```
mpstats_rows              20
saleflow_rows             20
matched                   20
median_revenue_diff_pct   9.5
total_revenue_mpstats     2,538,458
total_revenue_saleflow    2,380,823
verdict                   🟢 աղբյուրները համաձայն են
conservative_revenue      2,380,823   ← որոշման համար վերցրու ՍԱ
```

Կանոնը.

| Տարբերություն | Վերդիկտ | Ինչ անել |
|---|---|---|
| < 15% | 🟢 համաձայն են | աշխատիր միջինով |
| 15–35% | 🟡 նկատելի | վերցրու **ավելի պահպանողական** թիվը |
| > 35% | 🔴 հակասում են | մի՛ վստահիր ոչ մեկին. ստուգիր WB-ի իրական քարտով |

Երկու աղբյուրն էլ **գնահատում** են վաճառքը (WB-ն չի հրապարակում ուրիշների փաստը)։
Երբ դրանք համաձայն են՝ վստահությունը մեծանում է։ Երբ ոչ՝ դա ազդանշան է, ոչ թե աղմուկ։

## Եթե դաշտերը չեն ճանաչվում

`ingest`-ը ցույց է տալիս.

```
✔ պահված՝ data/raw/saleflow/items_cd7704ba962f.json
  տողեր՝ 20
  ճանաչված դաշտեր՝ id, name, brand, seller, revenue, sales, price, rating, comments
  ⚠️ չճանաչված՝ start_date, category → ավելացրու ալիաս src/fields.py-ում
```

Ավելացրու պակասող անունը `src/fields.py`-ի `_EXTRA_ALIASES`-ում — 1 տող, և բոլոր
մոդուլները անմիջապես սկսում են տեսնել այդ դաշտը։

## Claude Code-ում Saleflow MCP միացնելը (ոչ պարտադիր)

Installer-ը սարքում է **Claude Desktop**-ը։ Claude Code-ում նույն սերվերը ավելացվում է ձեռքով.

```bash
claude mcp add saleflow --transport http <SALEFLOW_MCP_URL> \
  --header "Authorization: Bearer <քո նոր թոքենը>"
claude mcp list        # ստուգում
```

URL-ը վերցրու Claude Desktop-ի կոնֆիգից՝ `mcpServers.saleflow` բաժնից
(Windows՝ `%APPDATA%\Claude\claude_desktop_config.json`,
macOS՝ `~/Library/Application Support/Claude/claude_desktop_config.json`)։
Թոքենը **մի՛ գրիր** պրոյեկտի ֆայլերում — այն մնում է միայն MCP-ի կոնֆիգում։
