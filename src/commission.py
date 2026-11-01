"""Комиссия WB нашего AM-кабинета — единственный источник (аудит 2026-11-01).

Берётся из самого свежего дампа WB API `data/raw/wb_seller/commission_<дата>.json`
(обновить: `python -m src.wb_seller commission --subject "<предмет>"`). Поле FBS — `kgvpMarketplace`.
Комиссии Saleflow/MPStats (у продавцов РФ выше до +19 п.п.) сюда не подмешиваются: нет данных → ошибка.
"""
from __future__ import annotations

import glob
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELD = {"fbs": "kgvpMarketplace", "dbs": "kgvpSupplier", "fbo": "paidStorageKgvp"}


@lru_cache(maxsize=1)
def table() -> tuple[str, dict[int, dict]]:
    files = sorted(glob.glob(str(ROOT / "data/raw/wb_seller/commission_*.json")))
    if not files:
        raise FileNotFoundError("нет дампа комиссий WB API: python -m src.wb_seller commission --subject …")
    d = json.load(open(files[-1], encoding="utf-8"))
    return Path(files[-1]).stem.split("_", 1)[1], {r["subjectID"]: r for r in d["report"]}


def commission(subject_id: int, scheme: str = "fbs") -> float:
    """Комиссия % по предмету WB для схемы (fbs по умолчанию). Нет предмета в дампе → KeyError (не подставляем)."""
    _, t = table()
    if subject_id not in t:
        raise KeyError(f"предмета {subject_id} нет в дампе комиссий WB API — обновите дамп, не подставляйте Saleflow")
    return float(t[subject_id][FIELD[scheme]])


def all_fbs() -> dict[int, float]:
    return {sid: float(r[FIELD["fbs"]]) for sid, r in table()[1].items()}
