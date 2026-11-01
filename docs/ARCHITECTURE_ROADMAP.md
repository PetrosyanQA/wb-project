# Архитектура: план внедрения (по повторному аудиту 2026-11-02)

Принцип: не добавлять функции поверх старой логики, пока нет единых статусов, доказательств и ворот. `/analiz` — оркестратор, считают модули.

| Этап | Что | Статус |
|---|---|---|
| 1 | Запуск в чистом окружении: `setup.sh/.bat`, `requirements.txt` (+pillow), `requirements-lock.txt`, `scripts/check.sh`, CI `.github/workflows/tests.yml` | ✅ 2026-11-02 |
| 4* | Режимы DISCOVERY / VALIDATION / FROZEN_TEST — `config/decision_current.yaml`, `/analiz` 0.0 | ✅ 2026-11-02 |
| 5 | Монте-Карло: диапазоны в `config/monte_carlo.yaml`, `--seed`, `--sensitivity`, источник диапазона | ✅ 2026-11-02 |
| 6 | Learning: `calibration_factor` (≥ 5 фактов, взвешенная медиана, полураспад 180 дн.), `learning adjust` | ✅ 2026-11-02 |
| 11 | Единые ворота и решение: `src/decision.py` (ESTIMATE → WATCHLIST, нет образца → нельзя SOURCE, нет продаж → нельзя SCALE) | ✅ 2026-11-02 |
| 2 | `src/evidence.py` + `src/quality.py`: паспорт каждого ответа (источник, запрос, период, SHA-256, полнота, свежесть) | ⏳ следующий |
| 3 | Адаптеры (Saleflow, WB, Apify, Bright Data) → `{data, evidence, quality}` | ⏳ после этапа 2 |
| 5b | `src/product_identity.py` + `src/uniqueness.py` (SIGNAL_ONLY / SUPPORTED / VERIFIED с причинами) | ⏳ |
| 8 | `supplier_evidence.py`: экономика VERIFIED только с КП (комплектация, MOQ, вес, объём) | ⏳ при получении КП |
| 7 | `external_trends.py`: Amazon / Etsy / Pinterest со статусами FOUND / NOT_FOUND / BLOCKED / NOT_CHECKED | ⏳ (Etsy/Pinterest — по желанию, дизайн; спрос доказывают Amazon + WB) |
| 12 | `product_validation.py` + план-факт по финотчёту WB | ⏳ после старта карточки |

Расхождение с аудитом (решение проекта): обязательный HOLD при отсутствии Pinterest/Etsy не вводим — они не дают продаж;
в отчётах пишем честно «External triangulation: PARTIAL (Amazon + WB; Pinterest/Etsy: NOT_CHECKED)».
