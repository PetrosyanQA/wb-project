"""Параметры белого ввоза YUAN EXIM из config/landed_cost.yaml → white_import (одно место для всех расчётов)."""
from __future__ import annotations

from pathlib import Path

import yaml

_W = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "landed_cost.yaml").read_text(encoding="utf-8"))["white_import"]
CNY, USD, K, CUSTOMS, USD_PER_KG = _W["cny_rub"], _W["usd_rub"], _W["k"], _W["customs_per_batch_rub"], _W["usd_per_kg"]


def landed(yuan: float, kg: float, batch: int) -> float:
    """Себестоимость «под ключ» за 1 шт, ₽."""
    return K * yuan * CNY + USD_PER_KG * USD * kg + CUSTOMS / batch


def yuan_from_cost(cost: float, kg: float, batch: int) -> float:
    """Обратная задача: какой ¥ у фабрики даёт эту себестоимость."""
    return (cost - CUSTOMS / batch - USD_PER_KG * USD * kg) / (K * CNY)
