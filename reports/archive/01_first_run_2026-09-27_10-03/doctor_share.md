# Doctor — 2026-10-03

Ստուգման path՝ `Дом/Кухня`

_DEMO ռեժիմ՝ սինթետիկ պատասխաններով_

## 1. Կապ և իրավունքներ

| Էնդփոյնթ | Կարգավիճակ | Տողեր |
|---|---|---|
| `api_limit` | ✅ | — |
| `category/list` | ✅ | 1 |
| `category/categories` | ✅ | 1 |
| `category/items` | ✅ | 1 |
| `category/by_date` | ✅ | 1 |

## 2. Դաշտերի քարտեզագրում (ամենակարևոր մասը)

### `category/items`

- ✅ Գտնված՝ `id`, `name`, `revenue`, `sales`, `price`, `comments`, `rating`, `seller`, `brand`, `balance`
- ❌ **Չգտնված՝ `start_date`**
  - `start_date` — առանց սրա չի աշխատի «թարմ քարտերի հաջողություն» ցուցանիշը

<details><summary>Իրական բանալիները</summary>

```
balance, brand, comments, final_price, id, name, rating, revenue, sales, supplier_name
```
</details>

### `category/categories`

- ✅ Գտնված՝ `name`, `revenue`, `sales`

<details><summary>Իրական բանալիները</summary>

```
name, revenue, sales
```
</details>

### `category/by_date`

- ✅ Գտնված՝ `date`, `revenue`

<details><summary>Իրական բանալիները</summary>

```
date, revenue, sales
```
</details>

## 3. WB Seller API

_(demo ռեժիմում չի ստուգվում)_

## 4. Եզրակացություն

🟠 **Գտնվել է 1 խնդիր.**

1. `category/items` → չգտնված դաշտ `start_date` (ալիասներ՝ start_date, sku_first_date, first_date, firstdate, date_created, createdAt, created_at, firstSaleDate)

### Ինչ անել
1. Եթե խնդիրը **դաշտի անունն** է — պատճենիր «Իրական բանալիները» բաժինը և ուղարկիր ինձ, ես կուղղեմ `src/fields.py`-ի `ALIASES`-ը (1 րոպե)։
2. Եթե խնդիրը **403/401** է — թոքենի իրավունքներն են պակասում։
3. Եթե **դատարկ պատասխան** է — path-ը սխալ է. `python -m src.mpstats_client categories "<բառ>"`։

_Ծախսվեց ~0 API հարցում_