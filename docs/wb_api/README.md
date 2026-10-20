# WB API — карта методов (dev.wildberries.ru, 2026-10-20)

Источник: https://dev.wildberries.ru/en/docs/openapi/api-information (12 разделов + тарифы).
Полную документацию (Redoc) сайт отдаёт только браузеру, поэтому здесь краткая карта; детали метода — по ссылке раздела.
Токен: заголовок `Authorization: <token>`, действует 180 дней. В проекте токены лежат только в `.env`; `src/wb_seller.py` сам выбирает токен с нужной категорией.

## Типы токенов

| Тип | acc | Для чего | Лимиты |
|---|---|---|---|
| Personal | 3 | свои программы (наш случай); нельзя передавать третьим лицам и облачным сервисам | максимальные |
| Service | 4 | сервис из каталога «Решения для бизнеса» | как Personal |
| Base | 1 | ограниченный набор данных | у части методов 1 запрос/час |
| **Test** | 2 | **песочница**: тестовые данные, без риска | 1 запрос/сек |

Биты поля `s` (категории): 1 Контент, 2 Аналитика, 3 Цены и скидки, 4 Маркетплейс, 5 Статистика, 6 Продвижение, 7 Отзывы и вопросы,
9 Чат с покупателями, 10 Поставки, 11 Возвраты, 12 Документы, 13 Финансы, 16 Пользователи, 30 = только чтение.
Ответ 4XX в категории Маркетплейс считается за 10 запросов.

## Песочница (Test token)

| Что можно отрепетировать | Хост |
|---|---|
| Создание карточек, медиа, теги | content-api-sandbox.wildberries.ru |
| Цены и скидки созданных карточек | discounts-prices-api-sandbox.wildberries.ru |
| FBS: сборочные задания, поставки, склады, остатки (стикеры cross-border — пустой ответ) | marketplace-api-sandbox.wildberries.ru |
| Реклама: кампании, ставки, кластеры, тестовое пополнение баланса | advert-api-sandbox.wildberries.ru |
| Отзывы и вопросы (тестовые) | feedbacks-api-sandbox.wildberries.ru |
| Основные отчёты (4 месяца назад) | statistics-api-sandbox.wildberries.ru |
| FBW поставки | supplies-api-sandbox.wildberries.ru |

## Разделы и методы

| Раздел (ссылка) | Хост | Ключевые методы |
|---|---|---|
| [General](https://dev.wildberries.ru/en/docs/openapi/api-information) | common-api | `/ping`, новости портала, `/api/v1/seller-info`, рейтинг продавца, подписка Джем, **`/api/common/v1/tariff-constructor/options`** (опции и их цена), пользователи |
| [Тарифы](https://dev.wildberries.ru/en/docs/openapi/wb-tariffs) | common-api | `/api/v1/tariffs/commission`, `/api/v1/tariffs/box`, `/pallet`, **`/api/v1/tariffs/return`**, коэффициенты приёмки |
| [Товары](https://dev.wildberries.ru/en/docs/openapi/item-management) | content-api, discounts-prices-api, marketplace-api | предметы и характеристики (`/content/v2/object/all`, `/content/v2/object/charcs/{id}`), справочники (цвета, страны, ТН ВЭД), **`/content/v2/barcodes`**, **`/content/v2/cards/upload`**, `/cards/upload/add` (склейка), `/cards/update`, `/cards/moveNm`, ошибки `/cards/error/list`, **медиа `/content/v3/media/file|save`**, теги; **цены `/api/v2/upload/task`**, история, **карантин `/api/v2/quarantine/goods`**, склады продавца `/api/v3/warehouses`, остатки |
| [Аналитика](https://dev.wildberries.ru/en/docs/openapi/analytics) | seller-analytics-api | **воронка `/api/analytics/v3/sales-funnel/products`** (+history), лента заказов, **поисковые запросы `/api/v2/search-report/*`** (позиции, тексты запросов по товару), остатки, рейтинг товара |
| [Отчёты](https://dev.wildberries.ru/en/docs/openapi/reports) | statistics-api, seller-analytics-api | заказы `/api/v1/supplier/orders`, продажи `/api/v1/supplier/sales`, штрафы за габариты, удержания `/api/analytics/v1/deductions`, платное хранение, продажи по регионам, возвраты, заблокированные товары |
| [Продвижение](https://dev.wildberries.ru/en/docs/openapi/promotion) | advert-api, dp-calendar-api | кампании (создать `/adv/v2/seacat/save-ad`, старт/пауза/стоп), **ставки и рекомендации ставок**, мин. ставка, кластеры запросов и минус-фразы, баланс и бюджет, **статистика `/adv/v3/fullstats`**, календарь акций и участие |
| [FBS](https://dev.wildberries.ru/en/docs/openapi/orders-fbs) | marketplace-api | **новые задания `/api/v3/orders/new`**, статусы, отмена, **стикеры** (в т.ч. **`/api/v3/orders/stickers/cross-border`** и история статусов cross-border), поставки, точки отгрузки, пропуска, автовозвраты |
| [Общение](https://dev.wildberries.ru/en/docs/openapi/customer-communication) | feedbacks-api, buyer-chat-api, returns-api | **вопросы и отзывы** (новые, неотвеченные, ответить), закреплённые отзывы, чат с покупателем, **заявки на возврат `/api/v1/claims`** |
| [Финансы и документы](https://dev.wildberries.ru/en/docs/openapi/documents-and-accounting) | finance-api, documents-api | **баланс**, **еженедельный отчёт реализации `/api/finance/v1/sales-reports/detailed`**, эквайринг, документы (скачать) |
| DBS / DBW / C&C / FBW | marketplace-api, supplies-api | нам не нужны (наша модель — FBS со своего склада ФФ) |

## Каталог «Решения для бизнеса»

https://dev.wildberries.ru/en/business-solutions — более 125 сервисов, подключаются Service-токеном в один клик
(MPSpace, Torgstat, MarketGuru, Wildbox, Otveto, Mpstats и др.). Платные; у нас аналитика и биддер уже есть (MPSTATS, Saleflow `wbbidder_*`), поэтому сейчас не нужны.

## Проверено в песочнице 2026-10-20 (WB_TOKEN_TEST, `src/wb_card.py` + ручные вызовы)

| Шаг | Метод | Результат / особенность |
|---|---|---|
| Баркоды | POST `/content/v2/barcodes` `{"count":3}` | ✅ |
| Карточка 3 варианта (склейка) | POST `/content/v2/cards/upload` | ✅ один imtID; **вес только в `dimensions.weightBrutto` (кг)** — характеристики «Вес с упаковкой», «Д/Ш/В упаковки» отклоняются |
| Цены | POST `/api/v2/upload/task` `{"data":[{"nmID","price","discount"}]}` | ✅ |
| Склад продавца | GET `/api/v3/offices` → POST `/api/v3/warehouses` `{"name","officeId"}` | ✅ |
| Остатки | PUT `/api/v3/stocks/{warehouseId}` `{"stocks":[{"chrtId","amount"}]}` | ✅ **по `chrtId`, не по баркоду** (по sku → 400) |
| Тест-заказы FBS | POST `/api/v3/test/fbs/orders/make` `{"orders":[{"sku":"<баркод>","amount":n}]}` | ✅ amount ≤ 10 |
| Новые задания | GET `/api/v3/orders/new` | ✅ цена в копейках (110000 = 1 100 ₽) |
| Поставка | POST `/api/v3/supplies` → PATCH `/api/v3/supplies/{id}/orders/{orderId}` → PATCH `.../deliver` | ✅ |
| Стикеры | POST `/api/v3/orders/stickers?type=png&width=58&height=40` | ✅ PNG base64, partA/partB (пример: reports/assets/wb_fbs_sticker_sandbox.png) |
| Действия покупателя (тест) | PATCH `/api/v3/test/fbs/orders/{id}/deliver|receive|reject|defect`, `/api/v3/test/fbs/supplies/{id}/close` | ✅ статусы sold / canceled_by_client / defect |
| Тест-отзывы/вопросы | POST `/api/v1/test/make/feedbacks/batch`, `/questions/batch` `{"feedbacks":[{"nmId","texts":[…]}]}` | ✅ |
| Ответ на отзыв | POST `/api/v1/feedbacks/answer` `{"id","text"}` | ✅ 204 |
| Ответ на вопрос | PATCH `/api/v1/questions` `{"id","answer":{"text"},"state":"wbRu"}` | ✅ |
| Тест-баланс рекламы | POST `/adv/v1/test/update/balance` `{"balance","net","bonus"}` | ✅ каждое поле ≥ 100 |
| Кампания | POST `/adv/v2/seacat/save-ad` `{"name","nms":[…]}` → бюджет POST `/adv/v1/budget/deposit?id=` → GET `/adv/v0/start?id=` | ✅ тип 9, статус 9 (идут показы). `/api/advert/v2/adverts`, `/api/advert/v1/bids/min`, `/adv/v1/promotion/adverts` в песочнице → 404 |
