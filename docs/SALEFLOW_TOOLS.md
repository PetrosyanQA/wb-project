# Saleflow (данные MPSTATS): что используем и что не пробовали — 2026-11-02

Клиент — `src/saleflow_stdio.py` (fbs=1 по умолчанию, кэш 24 ч, сырой JSON в `data/raw/saleflow/<дата>/<инструмент>/`, стоп при
остатке < 50). Важно из описаний инструментов: **fbs=0 с августа 2026 почти пуст** (WB скрыл остатки FBO) → всегда fbs=1.
Гипотеза к проверке (`python -m src.wb fbs-check`): «август+ неполный (0,61×)» мог быть артефактом — тогда доступны свежие месяцы.

## Используем
`wb_subject` (products, keywords, trends) · `wb_subjects_list` · `wb_sku` (by_period) · `wb_check_rates` (живая выдача) ·
`wb_similar` · `wb_shelves` · `wb_seller` · `wb_card_content` · `ozon_queries` · `pe_*` (фото) · `account_limits`.

## Не пробовали — и зачем
| Инструмент | Что даёт | Зачем нам |
|---|---|---|
| `wb_subject` report=price_segmentation / geography / warehouses / brands / sellers | сегменты, регионы, склады, бренды ниши за 1 запрос | сегменты без 500 карточек; склады FBS конкурентов |
| `wb_category_stats` (subcategories, price_segmentation, trends) | целая категория | сравнить подкатегории за 1 запрос |
| `wb_compare` scope=subject | период к периоду по каждой карточке | растущие модели и новички без by_period |
| `wb_analytics` season_effects/annual | сезонные коэффициенты ниши | закрыть «сезон ?» у ~1 600 ниш |
| `wb_brand`, `wb_warehouses` | товары/склады бренда или продавца | разбор лидера (UniPlush и др.) |
| `wbbidder_*` (clusters: CPC, CPM, ставки) | реклама нашего кабинета | после запуска — ДРР по факту |
| `lk_wb_*` | наш кабинет через Saleflow | после запуска (дублирует WB Seller API) |
| `wb_shelves_project` | ⚠️ меняет аккаунт MPSTATS | только с «да» пользователя |
