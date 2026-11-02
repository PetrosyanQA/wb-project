# Карта модулей `src/` (обновлено 2026-11-01, аудит)

## ✅ Рабочие сейчас (товар — кисти 437)
| Группа | Модули |
|---|---|
| Экономика | `unit_econ` (схема am_fbs по умолчанию), `white_import` (себестоимость — единственный источник), `commission` (комиссия кабинета из WB API), `screen_white`, `monte_carlo`, `budget_sim`, `finplan`, `strategy.cost_rub` |
| Данные | `datastore` (`products(sid, month)` — единый поиск карточек, июль по умолчанию), `catalog`, `saleflow_stdio`, `evirma` (СПП, `latest_snapshot`), `wb_cdn_card`, `wb_seller`, `wb_facts` |
| Анализ ниши / товара | `niche_deep`, `niche_inside`, `product_deep`, `niche_requirements` (запрет только магниты), `niche_v7`, `niche_v7_cards`, `wb_risers`, `global_variants` (только идеи — пробел подтверждать `wb_check_rates`) |
| Поставщики | `brightdata_client` (стоп на резерве — `BudgetStop`), `apify_client` (стоп < 0,5 USD), `spec_find`, `photo_hunt`, `image_find` |
| Карточка / маркетинг | `mkt`, `gallery_research`, `wb_card` |
| Мониторинг | `brush_report` + `brush_watch` (`config/watch_437.yaml`, Telegram 10:00), `tg`, `bot_actions` (цена — только при известной СПП), `competitor_pulse`, `weekly_report` (`config/launch.yaml`), `ledger` |

## 🗄 Снимки (цифры по СТАРОЙ модели — не использовать для решений)
`marketing777`, `strategy777`, `finplan777`, `best_product_report`, `fresh_screen`, `dna_rank`, `niche_dna_xlsx`, `xborder`, `deep_731_249`, `holder777_full`, `knife_*`, `cloud_daily` (249).

---
# История: карта от 2026-10-08

Запуск всегда через venv: `.venv\Scripts\python.exe -m src.<модуль>`. Тесты: `.venv\Scripts\python.exe -m unittest discover -s tests`.

## ✅ Рабочие — запуск и сопровождение товара 777
| Модуль | Зачем | Расписание |
|---|---|---|
| `weekly_report` | Еженедельная сводка по НАШЕЙ карточке + решение по правилам (стоп/держать/поднять цену/дозаказ) | понедельник (после старта) |
| `competitor_watch` | 5 главных конкурентов: цена, реклама, акции, остаток, позиции → сигналы | понедельник |
| `fresh_collect` | Сбор для слежки (`--watch`) и свежих отзывов/позиций конкурентов | по запросу / понедельник |
| `wb_watch` | `commission` — комиссия кабинета vs базовая; `spp-basis` — от какой цены WB считает удержания (нужен токен «Финансы») | 1-е число месяца / после 1-й недели продаж |
| `ledger` | Партии, деньги, остаток, «на сколько дней хватит», когда дозаказать (`ledger/*.csv`) | после каждой поставки/недели |
| `marketing777` | Цена × ДРР → маржа, СПП ниши, чувствительность к комиссии | при смене цены/закупки/комиссии |
| `mkt_analyze` | Маркетинговый анализ из данных проекта: SEO-ядро, боли→УТП, реклама в выдаче, реклама конкурентов, СПП (Evirma), бюджет ДРР → `reports/marketing/` | еженедельно / перед карточкой |
| `product_screen` | Сначала товар: все сохранённые карточки Saleflow → лёгкие китайские дженерики 1 200–3 500 ₽, ≥ 300 продаж, без ЧЗ/электроники → `reports/product_screen_*.md` | при поиске товара |
| `deep_check` | Глубокая проверка ниш из сохранённого products500: концентрация, новички, Китай, жалобы 10 лидеров (отзывы WB), СПП Evirma → `reports/deep_check_*.md` | после сбора products500 |
| `niche_requirements` | Для КАЖДОГО предмета WB: ЧЗ, документы (декларация/сертификат/отказное), электроника/батарея/магнит, габарит, запрет → `reports/niche_requirements_*.xlsx` + Google Sheets «WB: что нужно для каждой ниши» | при смене правил / раз в квартал |
| `sheets_export` | Строки для Google Sheets «WB 249 мониторинг» (новое с прошлой выгрузки; пишет Claude коннектором, затем `--commit`) | ежедневно в задаче daily-249 |
| `unit_econ`, `landed_cost` | Юнит-экономика и себестоимость с доставкой | по запросу |
| `backup` | Zip-копия данных вне OneDrive (инкрементально) | понедельник |

## 🔧 Данные и инфраструктура
| Модуль | Зачем |
|---|---|
| `catalog`, `datastore` | Каталог всех данных по нишам и единый доступ (`files`, `latest`, `daily`) — в новом коде только через них |
| `saleflow_stdio`, `strategy_collect`, `launch_collect`, `mcp_dump`, `saleflow` | Сбор Saleflow (по одному запросу, пропуск скачанного, стоп после 3 сбоев) |
| `wb_seller`, `wb_facts`, `sync_tariffs`, `doctor` | WB Seller API (read-only), тарифы, проверка окружения |
| `mpstats_client`, `fields`, `outliers` | Клиент MPSTATS (исходный конвейер) и очистка данных |
| `export_pdf`, `html_report`, `build_xlsx` | Выгрузка отчётов в PDF/HTML/Excel |

## 🔬 Исследование (переиспользуемые)
| Модуль | Зачем |
|---|---|
| `wb_algo` | «Алгоритм WB»: драйверы позиции/продаж, кривые реакции, изменения по месяцам → `wb_algorithm/` |
| `launch_patterns`, `launch_summary` | Как заходили победители vs середняки vs слабые |
| `winner_decisions` | Что видели новички-победители до T0 и что сделали в нед. 1–8: правила с проверкой по времени, leave-one-niche-out и «честной зоне» цены; `apply` — checklist v2 к кандидатам (`config/filters.yaml → newcomer_rules`) |
| `strategy`, `finplan`, `compare_niches`, `newcomer_screen` | Стратегия ниши по шаблону, финплан, сравнение ниш (единая методика 07.10) |
| `discover`, `niche_scan`, `gates`, `trend_scan`, `sku_audit`, `scoring` | Исходный конвейер поиска ниш (CLAUDE.md) |
| `subject_screen`, `fresh_screen`, `category_econ`, `niche_dna*`, `dna_*`, `saleflow_eval`, `niche_rank`, `segments` | Скрины и ДНК ниш (цена — с исправлением СПП от 07.10) |

## 📌 Снимки (пути с датой закреплены намеренно — воспроизводят отчёт на конкретный день)
`top100_777` (05.10), `best_product_report` (05.10), `strategy777` + `finplan777` (06.10; заменены `strategy` + `finplan`).

## 🗄 Архив (направления закрыты, код оставлен для истории)
| Модуль | Направление |
|---|---|
| `build_final_docx` | Обоснование по ножам (04–05.10) |
| `winner_dna`, `niche_top100` | Видеоняни и мастурбаторы (04.10) |
| `vacuum_segments` | Вакууматоры (03.10) |
| `season_niches` | Декабрьский сезонный скрин (05.10) |
| `xborder` | Схема через склад в Ереване — заменена на FBS из РФ |
