# Առաջին գործարկում — 10 րոպե

Հերթականությունը կարևոր է. ամեն քայլը փակում է մի ռիսկ։

## 1. Միջավայր (3 րոպե)
```
setup.bat          ← Windows (կրկնակի սեղմում)
bash setup.sh      ← macOS / Linux
```
Ստեղծում է `.venv`, տեղադրում գրադարանները, պատրաստում `.env`-ը։

## 2. Թոքեններ (2 րոպե)
`.env` ֆայլում՝
```
MPSTATS_TOKEN=...          ← MPStats → Профиль → API
WB_SELLER_TOKEN=...        ← WB Partners → Настройки → Доступ к API («Только на чтение»)
```

## 3. ⚠️ Doctor — ԱՄԵՆԱԿԱՐԵՎՈՐ ՔԱՅԼԸ (2 րոպե, ~6 հարցում)
```
mps.bat src.doctor --path "Дом/Кухня"
```
Ստուգում է՝ կապ, իրավունքներ, և արդյոք դաշտերի անունները համընկնում են։

**Եթե տեսնում ես ❌ → պատճենիր «Իրական բանալիները» բաժինը և ուղարկիր ինձ։**
Դա 1-2 րոպեի ուղղում է `src/fields.py`-ում։ Առանց դրա կստանաս զրոներ։

## 4. Բյուջե (10 վրկ)
```
mps.bat src.mpstats_client plan
```

## 5. Որոնում
```
mps.bat src.discover --depth 2 --probe 25 --growth-top 10 --dry-run
mps.bat src.discover --depth 2 --probe 25 --growth-top 10
```
→ `reports/discovery_<date>.html` — բաց արա բրաուզերով։

## 6. Խորացում
```
mps.bat src.niche_scan --from-csv reports/discovery_<date>.csv --tiers A,B --limit-niches 10
mps.bat src.trend_scan --path "<տոպ նիշա>" --days 540 --snapshots 4
mps.bat src.sync_tariffs --apply
mps.bat src.sku_audit --sku <id> --sku <id>
```

## Ի՞նչ անել, եթե ինչ-որ բան չաշխատի

| Ախտանիշ | Պատճառ | Լուծում |
|---|---|---|
| `401 / 403` | թոքենի իրավունքներ | ստուգիր կատեգորիաները WB-ում / MPStats տարիֆը |
| `429` | լիմիտ | սպասիր, կամ իջեցրու `--max-requests` |
| Ամեն ինչ 0 է | դաշտերի անուններ | **doctor** → ուղարկիր ինձ ելքը |
| Դատարկ արդյունք | սխալ path | `mps.bat src.mpstats_client categories "<բառ>"` |
| `~` նշան աղյուսակում | ագրեգատ հաշվետվությունը տարիֆում չկա | նորմալ է, թվերը մոտարկված են |
| `ModuleNotFoundError` | venv-ը շրջանցված է | օգտագործիր `mps.bat`, ոչ թե `python` |
