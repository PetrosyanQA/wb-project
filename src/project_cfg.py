"""Чтение config/project.yaml — даты, пороги, бюджеты и планка цикла анализа (одно место на весь проект)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parents[1] / "config" / "project.yaml"


@lru_cache(maxsize=1)
def cfg() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


def get(dotted: str, default=None):
    cur = cfg()
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur
