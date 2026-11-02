# WB-проект: поиск и запуск товара (Wildberries, AM-кабинет, FBS, белый ввоз)

Одна страница: как устроен проект и как им пользоваться. Правила — `CLAUDE.md`, сценарий анализа — `/analiz`,
текущее решение — `PROJECT_STATE.md` и `python -m src.wb decide`.

## 7 команд (всё остальное — внутри них)
```bash
.venv/Scripts/python.exe -m src.wb status        # все источники: работает ли, сколько осталось, свежесть данных
.venv/Scripts/python.exe -m src.wb fbs-check     # полный ли свежий месяц в Saleflow (fbs=1) — 2 запроса
.venv/Scripts/python.exe -m src.wb collect       # докачать ниши из очереди (стоп при запасе Saleflow 50)
.venv/Scripts/python.exe -m src.wb screen        # все ниши → сегменты → копилка → мастер-список (0 запросов)
.venv/Scripts/python.exe -m src.wb check "запрос" --sid 1142   # живая выдача + ниша изнутри + строка мастер-списка
.venv/Scripts/python.exe -m src.wb decide        # решение по товару + срок цикла поиска (go/no-go)
.venv/Scripts/python.exe -m src.wb daily         # самообучение: СПП, новички, прогнозы против факта
```

## Как идёт работа
1. `status` → если Saleflow ❌ 401 — перевыпустить токен (saleflow.pro → в конфиг Claude Desktop и `.env`, не в чат).
2. `collect` → `screen` → `reports/niche_master_<дата>.md` (все ниши со статусами) и `reports/niche_pool_<дата>.md` (сегменты).
3. По кандидатам — `/analiz` (уникальность через Exa → живая выдача → ¥ 1688 → экономика → решение).
4. Решение только через `src.decision`; цикл поиска кончается датой `discovery_until` в `config/decision_current.yaml`.
5. Дальше: КП → образец → тестовая партия 50–100 → живая карточка → kill-критерии (`config/launch.yaml`).

## Источники (выбор инструмента — таблица в `CLAUDE.md`)
| Что | Чем | Лимит |
|---|---|---|
| Рынок WB, ниши, карточки, живая выдача | Saleflow (данные MPSTATS), `src/saleflow_stdio.py`: fbs=1, кэш 24 ч, сырой JSON в `data/raw/saleflow/` | 500/день, резерв 50 |
| Наши комиссии, тарифы, выкуп, воронка | WB Seller API (`src/wb_seller.py`, `src/wb_facts.py`), только чтение | 1 запрос/мин |
| СПП конкурентов | Evirma (`src/evirma.py`) | бесплатно |
| Цены 1688, Amazon | Bright Data (`src/brightdata_client.py`) | стоп при 100 |
| Тренды, законы, ЧЗ | Exa | бесплатно |

## Ядро кода (`src/`)
| Группа | Модули |
|---|---|
| Вход | `wb` |
| Данные | `saleflow_stdio`, `datastore`, `catalog`, `outliers`, `niche_requirements` |
| Отбор | `niche_all` (все ниши), `screen_white` (сегменты), `niche_pool` (копилка), `niche_inside`, `niche_deep` |
| Проверка идеи | `radar` (живая выдача), `product_deep` (жалобы), `brightdata_client`, `spec_find`, `global_variants` |
| Экономика | `unit_econ` (am_fbs), `white_import`, `commission`, `evirma`, `monte_carlo`, `budget_sim` |
| Решение и обучение | `decision`, `learning` |
| Запуск и слежка | `brush_report`, `brush_watch`, `tg`, `bot_actions`, `wb_seller`, `wb_facts`, `mkt`, `gallery_research`, `wb_card` |
Остальное в `src/` — вспомогательное для старых сценариев; `src/archive/` — снимки по старым моделям (не для решений).
Тесты: `python -m unittest discover -s tests` (после любых правок расчётов).

## Правила, которые не меняются
Запрет — только магниты (ЧЗ, документы, электроника — с пометкой «оформить»). Экономика — при СПП 18 / 10 / 0 %.
Цифра без источника — «—». Деньги, письма, цены в кабинете, публикации — только после «да» пользователя.
Ключи — только в `.env`; никогда в чат, отчёты и git.
