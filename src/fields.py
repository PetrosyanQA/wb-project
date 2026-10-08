"""Нормализация полей MPSTATS: имена колонок отличаются между отчётами."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

ALIASES: dict[str, tuple[str, ...]] = {
    "id":       ("id", "sku", "nmId", "nm_id", "item_id"),
    "name":     ("name", "title", "item_name"),
    "brand":    ("brand", "brand_name"),
    "seller":   ("seller", "supplier", "seller_name", "supplier_name"),
    "revenue":  ("revenue", "sales_rub", "revenue_total", "proceeds"),
    "sales":    ("sales", "orders", "sales_count"),
    "price":    ("final_price", "price", "avg_price", "median_price"),
    "rating":   ("rating", "reviewRating", "valuation"),
    "comments": ("comments", "feedbacks", "reviews", "comments_count"),
    "balance":  ("balance", "stocks", "quantity"),
    "days_in_stock": ("days_in_stock", "days", "days_on_site"),
    "start_date": ("start_date", "sku_first_date", "first_date", "firstdate", "date_created", "createdAt", "created_at", "firstSaleDate"),
    "purchase": ("purchase", "buyout", "buyout_percent"),
    "turnover": ("turnover", "oborachivaemost"),
    "lost_profit": ("lost_profit", "lost_revenue"),
    "date":     ("date", "day", "dt"),
    "is_fbs":   ("is_fbs", "fbs"),
    "category": ("category", "path", "subject", "name"),
}

# ── Saleflow / camelCase / այլ աղբյուրների ալիասներ ──────────────────────────
# Ավելացվում են վերջում, որ հիմնական քարտեզը կարդացվի հեշտ։
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "id":        ("nmID", "article", "vendorCode", "productId"),
    "name":      ("productName", "product_name", "subject_name"),
    "brand":     ("brandName",),
    "seller":    ("supplierName", "sellerName", "merchant", "ownerName"),
    "revenue":   ("revenueRub", "revenue_rub", "turnover_rub", "sum_revenue", "revenues",
                  "salesSum", "sum"),
    "sales":     ("ordersCount", "orders_count", "sold", "sales_quantity",
                  "quantity_sold", "ordersQty"),
    "price":     ("priceRub", "price_rub", "salePrice", "sale_price",
                  "price_with_discount", "currentPrice"),
    "rating":    ("rating_value", "ratingValue", "stars"),
    "comments":  ("feedbacksCount", "reviewsCount", "feedback_count"),
    "balance":   ("stock", "stocks_wb", "quantity_full", "stocksCount"),
    "days_with_sales": ("days_with_sales", "sales_days", "days_sales", "days_on_sale"),
    "subject_id": ("subject_id", "subjectId", "subjectID", "subject"),
}
for _key, _extra in _EXTRA_ALIASES.items():
    ALIASES[_key] = tuple(dict.fromkeys(ALIASES.get(_key, ()) + _extra))


def pick(row: dict, key: str, default: Any = None) -> Any:
    """Достаёт значение по логическому имени поля, перебирая известные алиасы."""
    for alias in ALIASES.get(key, (key,)):
        if alias in row and row[alias] is not None:
            return row[alias]
    return default


def num(value: Any, default: float = 0.0) -> float:
    """Безопасное приведение к float (API отдаёт '1 234,5', None, '' и т.п.)."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def fnum(row: dict, key: str, default: float = 0.0) -> float:
    return num(pick(row, key), default)


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def percentile(values: Iterable[float], q: float) -> float:
    data = sorted(v for v in values if v is not None)
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q
    low, high = int(pos), min(int(pos) + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (pos - low)


def median(values: Iterable[float]) -> float:
    return percentile(values, 0.5)
