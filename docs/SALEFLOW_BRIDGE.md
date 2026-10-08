# Saleflow → վերլուծության կամուրջ

## Ինչու՞ այս ուղին

Saleflow-ը **MCP սերվեր** է։ MCP-ի հարցումն անում է ոչ թե Python-ը, այլ ինքը՝ Claude-ը։
Քեզ մոտ Saleflow-ը աշխատում է **Claude Desktop**-ում → այնտեղ էլ անում ենք հարցումը,
իսկ պատասխանը մտնում է վերլուծության խողովակաշար մեկ հրամանով։

```
Claude Desktop  ──MCP──▶  Saleflow            ← այստեղ կապը արդեն աշխատում է
        │
        │ պատճենում ես պատասխանը
        ▼
  src.saleflow ingest -  ──▶  data/raw/saleflow/*.json   ← հում ապացույց
        │
        ▼
  normalize → gates / niche_metrics / unit_econ / scoring
```

Այս ուղին **կախված չէ** նրանից, թե sandbox-ը հասնո՞ւմ է saleflow.pro-ին։

---

## Քայլ 1 — հարցումը Claude Desktop-ում

Նոր չատ → **+ → Connectors → saleflow** միացված → պատճենիր պատրաստի հուշումը։

### Հուշում A — նիշայի ապրանքների ցանկ

> Օգտագործիր saleflow MCP-ն և բեր **Дом / Хранение вещей** կատեգորիայի ապրանքները
> վերջին 30 օրվա համար։ Պետք են՝ id, name, brand, seller, price, revenue, sales,
> rating, comments, balance, start_date։ Գին՝ 1400–2600 ₽։
> **Պատասխանը տուր ՄԻԱՅՆ որպես JSON, առանց բացատրության**, մեկ ```json բլոկում։

### Հուշում B — նիշաների համեմատություն

> saleflow MCP-ով բեր 10 ենթակատեգորիա **Автотовары**-ի տակից՝ ամսական ընդհանուր
> выручка, վաճառողների թիվ, տոպ-10-ի մասնաբաժին, միջին գին, YoY դինամիկա։
> **Միայն JSON**, մեկ բլոկում։

### Հուշում C — մրցակիցների խորացում

> saleflow MCP-ով տուր այս 20 nmID-ի օրական վաճառքները 90 օրվա կտրվածքով
> + պահեստային մնացորդները։ **Միայն JSON**։

> 💡 «**Միայն JSON**» բառերը կարևոր են — առանց դրանց Claude-ը կգրի նաև տեքստ,
> թեև `ingest`-ը ամեն դեպքում կքաղի JSON-ը շուրջբոլորի տեքստից։

---

## Քայլ 2 — ներմուծում

Պատճենիր պատասխանը և.

```bash
cd mpstats-research
python3 -m src.saleflow ingest - --tool items --note "Дом/Хранение 30д"
# ապա տեղադրիր պատասխանը և սեղմիր Ctrl-D (macOS/Linux) կամ Ctrl-Z Enter (Windows)
```

Կամ պահիր ֆայլ և՝

```bash
python3 -m src.saleflow ingest resp.json --tool items --note "Дом/Хранение 30д"
```

`ingest`-ը հանդուրժում է՝
- ```` ```json ```` ցանկապատերը
- JSON-ի շուրջ ցանկացած տեքստ («Вот результат: …»)
- MCP-ի `{"content":[{"type":"text","text":"{…}"}]}` փաթեթավորումը
- ներդրված `data` / `items` / `rows` / `products` / `results` բանալիները

Ելքը ցույց է տալիս, թե **որ դաշտերն են ճանաչվել**.

```
✔ պահված՝ data/raw/saleflow/items_1751bbe7b60f.json
  տողեր՝ 1
  ճանաչված դաշտեր՝ id, name, seller, revenue, sales, price, rating, comments, category
  ⚠️ չճանաչված՝ brand, balance, start_date → ավելացրու ալիաս src/fields.py-ում
```

Չճանաչված դաշտ տեսնելու դեպքում՝ բաց արա `src/fields.py` և ավելացրու Saleflow-ի
իրական բանալին համապատասխան `ALIASES`-ի մեջ։ Մեկ անգամ՝ ընդմիշտ։

---

## Քայլ 3 — վերլուծություն

```bash
python3 -m src.saleflow list                  # ինչ է պահված
python3 -m src.saleflow show <sha1> --limit 20 # նորմալացված տողեր
```

Հում ֆայլերը մնում են `data/raw/saleflow/`-ում՝ կարող ես վերագործարկել
վերլուծությունը առանց նոր հարցման։

### Խաչաստուգում MPStats-ի հետ

```bash
python3 -m src.saleflow crosscheck --mpstats data/raw/mps_items.json --saleflow <sha1>
```

Ցույց է տալիս մեդիան выручка-ի շեղումը երկու աղբյուրի միջև՝
🟢 <15% · 🟡 15–35% · 🔴 >35%։ Երկու աղբյուրի համաձայնությունը շատ ավելի
հուսալի է, քան մեկի թիվը։

---

## Եթե ուզում ես Saleflow-ը **Claude Code**-ում (ոչ միայն Desktop-ում)

`.mcp.json`-ն արդեն պատրաստ է `mcp-remote` ձևաչափով։ Թոքենը ֆայլում չէ.

```bash
set -a; source .env; set +a
export AUTH_HEADER="Bearer $SALEFLOW_TOKEN"
claude          # saleflow-ը բարձրանում է ավտոմատ
```

⚠️ Եթե Claude Code-ում 403 ստանաս, բայց Desktop-ում աշխատում է — ուրեմն URL-ը
տարբերվում է։ Վերցրու ճշգրիտ URL-ը աշխատող կոնֆիգից.

| ՕՀ | Ուղի |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

և փոխարինիր `.mcp.json`-ի `args`-ում եղած հասցեն։
