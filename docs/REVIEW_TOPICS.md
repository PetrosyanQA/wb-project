# Поиск повторяющихся жалоб в отзывах

`src.review_topics` — офлайн-инструмент для первичного поиска повторяющихся формулировок в негативных отзывах. Он дополняет словари тем из `src.saleflow_eval` и `src.dna_reviews`, не меняя существующие правила скоринга.

Анализатор строит частотные сочетания из 1–3 слов, считает количество отзывов и SKU, где они встречаются, и среднюю оценку. В отчёт намеренно не записываются цитаты или полные тексты отзывов, чтобы не распространять пользовательские данные. Это лексический поиск, а не ML-кластеризация: близкие по смыслу формулировки могут не объединиться, поэтому найденные темы нужно проверить по исходным данным.

Запуск на сохранённых JSON Saleflow:

```bash
python -m src.review_topics data/raw/saleflow/<дата>/dna/<subject>/comments/*.json
```

Сохранить Markdown и JSON:

```bash
python -m src.review_topics \
  --min-reviews 3 --min-skus 2 --since-days 365 \
  --out reports/review_topics.md \
  --json-out reports/review_topics.json \
  data/raw/saleflow/<дата>/dna/<subject>/comments/*.json
```

Для `--since-days` у отзывов должна быть дата в `date`, `createdAt` или `created_at`; отзывы без распознаваемой даты исключаются. По умолчанию учитываются только отзывы с оценкой 1–3 и без временного фильтра.

Проверить регрессию без сети и API-токенов:

```bash
python -m unittest tests.test_review_topics -v
```

Реализация вдохновлена подходом к поиску тем в отзывах из [Wildberries-Analytics-Platform](https://github.com/phmilover/Wildberries-Analytics-Platform), но использует только стандартную библиотеку Python и не переносит его ML-модели или код.
