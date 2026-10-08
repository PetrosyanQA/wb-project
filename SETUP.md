# Տեղադրում համակարգչի վրա — քայլ առ քայլ

**Կարճ պատասխան.** այո, պետք է ներբեռնես պանակը քո համակարգիչ։ Ամեն ինչ աշխատում է լոկալ՝
քո թոքենները մնում են քո մեքենայի վրա, ոչ մի տեղ չեն ուղարկվում։

Ընդհանուր ժամանակը՝ **15–20 րոպե**։

---

## 0. Ի՞նչ է պետք

| Բաղադրիչ | Ինչի համար | Պարտադի՞ր |
|---|---|---|
| **Python 3.10+** | սկրիպտները | ✅ այո |
| **MPStats թոքեն** | շուկայի տվյալներ | ✅ այո |
| **Claude Code** (Node.js 18+) | AI շերտը | 🟡 առանց դրա էլ սկրիպտներն աշխատում են |
| **WB Seller թոքեն** | իրական տարիֆներ/выкуп | 🟡 խորհուրդ է տրվում |

---

## 1. Ներբեռնիր պրոյեկտը

Այս զրույցի ֆայլերի պանակում կա **`mpstats-research.zip`** — ներբեռնիր և բացիր (unzip)
հարմար տեղում, օրինակ.

- Windows՝ `C:\Users\<քո անունը>\mpstats-research`
- macOS՝ `/Users/<քո անունը>/mpstats-research`

> ⚠️ Խուսափիր ռուսերեն/հայերեն տառերով և բացատներով ուղիներից (OneDrive-ի «Рабочий стол»
> երբեմն խնդիր է ստեղծում Python-ի հետ)։

---

## 2. Տեղադրիր Python-ը

### Windows
1. https://www.python.org/downloads/ → **Download Python 3.12**
2. Տեղադրիչում **անպայման նշիր ☑️ «Add python.exe to PATH»** (ամենահաճախ սխալը սա է)
3. Ստուգիր՝ բացիր **PowerShell** և գրիր `python --version` → պետք է տա `Python 3.12.x`

### macOS
```bash
# եթե Homebrew կա
brew install python
# ստուգում
python3 --version
```

---

## 3. Գործարկիր տեղադրման սկրիպտը

### Windows
Բացիր պանակը Explorer-ում → կրկնակի սեղմիր **`setup.bat`**
(կամ PowerShell-ում՝ `cd C:\Users\<անուն>\mpstats-research` հետո `.\setup.bat`)

### macOS / Linux
```bash
cd ~/mpstats-research
bash setup.sh
```

Սկրիպտը ինքը՝ ստեղծում է `.venv` միջավայրը, տեղադրում փաթեթները, պատրաստում `.env`-ը
և գործարկում demo-սքանը։ Եթե վերջում տեսնում ես `reports/niche_scan_....md` — ամեն ինչ կարգին է։

---

## 4. Դիր թոքենները

Բաց արա `.env` ֆայլը (Windows՝ Notepad, macOS՝ TextEdit) և լրացրու.

```
MPSTATS_TOKEN=քո_թոքենը_այստեղ
WB_SELLER_TOKEN=քո_wb_թոքենը_այստեղ
```

- **MPStats թոքեն.** mpstats.io → մտիր → `mpstats.io/userpanel` → բլոկ «API token» → պատճենիր
- **WB թոքեն.** WB Partners → Настройки → Доступ к API → Создать новый токен →
  ☑️ «Только на чтение», ❌ «Тестовый контур», կատեգորիաներ՝ Тарифы, Контент, Статистика, Аналитика

Պահպանիր ֆայլը։ **Թոքենները ոչ մեկին մի ուղարկիր, այդ թվում՝ ինձ չաթում։**

Ստուգում — **պարտադիր առաջին քայլը**.
```powershell
mps.bat src.doctor --path "Дом/Кухня"    REM Windows
```
Սա ստուգում է կապը, իրավունքները և դաշտերի անունները։ Եթե ինչ-որ բան չի համընկնում —
պատճենիր արդյունքը և ուղարկիր ինձ, կուղղեմ 1 րոպեում։

```powershell
mps.bat src.mpstats_client limit        REM լիմիտի մնացորդ
```
```bash
.venv/bin/python -m src.mpstats_client limit     # macOS
```

---

## 5. Տեղադրիր Claude Code-ը

Պետք է Node.js 18+ → https://nodejs.org (LTS տարբերակը)

```bash
npm install -g @anthropic-ai/claude-code
```

Հետո պանակի ներսում.
```bash
cd mpstats-research
claude
```
Առաջին անգամ կխնդրի մուտք գործել (`/login`, Anthropic հաշիվ)։ Claude-ն ինքնաբերաբար կկարդա
`CLAUDE.md`-ը և կիմանա կանոնները։

Փորձիր.
```
/niche-scan Дом/Кухня
```

> Windows-ում Claude Code-ը աշխատում է և՛ նատիվ, և՛ WSL-ի տակ։ Եթե նատիվում խնդիր լինի՝
> տեղադրիր WSL (`wsl --install`) և կրկնիր քայլերը Ubuntu-ի ներսում։

---

## 6. Ամենօրյա աշխատանքի ցիկլ

```bash
# 1. Որքան լիմիտ կա
mps.bat src.mpstats_client limit

# 2. Գտիր ճշգրիտ path
mps.bat src.mpstats_client categories "чехл"

# 3. Սքան (նախ dry-run)
mps.bat src.niche_scan --path "Электроника/Аксессуары" --top 12 --dry-run
mps.bat src.niche_scan --path "Электроника/Аксессуары" --top 12

# 4. Կարդա reports/niche_scan_<ամսաթիվ>.md (Claude-ը կբացատրի)

# 5. Մրցակիցներ
mps.bat src.sku_audit --sku 123456789

# 6. Իրական տարիֆներ + էկոնոմիկա
mps.bat src.sync_tariffs --warehouse "Коледино" --subject "Чехлы" --apply
mps.bat src.unit_econ --price 1490 --cost 380 --volume 0.4
```

macOS-ում `mps.bat X` → `.venv/bin/python -m X`

---

## 7. Հաճախակի խնդիրներ

| Սխալ | Պատճառ | Լուծում |
|---|---|---|
| `python : The term 'python' is not recognized` | PATH-ում չկա | Վերատեղադրիր Python-ը ☑️ «Add to PATH»-ով |
| `cannot be loaded because running scripts is disabled` | PowerShell policy | Օգտագործիր `mps.bat`-ը (activate պետք չէ) կամ `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Հայերենը կրակոզյաբրա է cmd-ում | կոդավորում | `mps.bat`-ն արդեն դնում է UTF-8, կամ ձեռքով՝ `chcp 65001` |
| `401 — неверный токен` | սխալ/ժամկետանց թոքեն | MPStats՝ նոր թոքեն; WB՝ 180 օր հետո վերաթողարկել |
| `403` WB-ում | թոքենին պակասում է կատեգորիա | Նոր թոքեն՝ Тарифы + Статистика + Аналитика |
| `429` | լիմիտ սպառված | Սկրիպտը ինքը սպասում է; կրճատիր `--top`-ը կամ սպասիր |
| Դատարկ պատասխան նիշայի համար | սխալ `path` | `mpstats_client categories "<բառ>"` → պատճենիր ամբողջ path-ը |
| `ModuleNotFoundError: yaml` | venv-ը չի օգտագործվում | Գործարկիր `mps.bat`-ով կամ `.venv/bin/python`-ով |

---

## 8. Անվտանգության հիշեցում 🔒

1. `.env`-ը երբեք մի ուղարկիր, մի հրապարակիր, մի դիր git-ում (արդեն `.gitignore`-ում է)
2. WB թոքենը՝ **միայն «Только на чтение»**
3. Եթե թոքենը պատահաբար ինչ-որ տեղ հայտնվեց՝ անմիջապես վերաթողարկիր կաբինետում
4. `data/cache/`-ը պարունակում է API պատասխաններ — եթե կիսվում ես պանակով, ջնջիր այն
