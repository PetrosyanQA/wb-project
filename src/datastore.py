"""Единая точка доступа к сохранённым данным по нише/SKU — вместо жёстких путей в новых скриптах. 0 запросов.

    from src.datastore import files, latest, daily, rows
    files(777, "daily")            # все дневные ряды ниши (dict-и каталога)
    latest(777, "products500")     # путь к самому свежему products500 ниши
    daily(494403950)               # самый длинный дневной ряд SKU (list[dict], отсортирован по дате)
    rows(path)                     # строки ответа Saleflow из файла (data/items/... или список)

    python -m src.datastore 777            # что есть по нише
    python -m src.datastore sku 494403950  # где лежат ряды SKU и какой период

Каталог: data/CATALOG.json (строится `python -m src.catalog`; если его нет — строится автоматически).
"""
from __future__ import annotations

import collections
import json
import os
import sys

from src.catalog import OUT_JSON, build, rows_of

_CAT: list[dict] | None = None


def catalog(refresh: bool = False) -> list[dict]:
    global _CAT
    if refresh or (_CAT is None and not os.path.exists(OUT_JSON)):
        from src.catalog import main as rebuild
        rebuild()
    if _CAT is None or refresh:
        _CAT = json.load(open(OUT_JSON, encoding="utf-8"))
    return _CAT


def files(niche: int, kind: str | None = None) -> list[dict]:
    return [c for c in catalog() if c["niche"] == niche and (kind is None or c["kind"] == kind)]


def latest(niche: int, kind: str) -> str | None:
    """Самый свежий файл: по дате сбора, затем по месяцу в имени."""
    F = files(niche, kind)
    return max(F, key=lambda c: (c["date"], c["month"] or "", c["bytes"]))["path"] if F else None


def rows(path: str) -> list:
    return rows_of(path)


def daily_files(sku: int) -> list[str]:
    return [c["path"] for c in catalog() if c["sku"] == sku and c["kind"] == "daily"]


def daily(sku: int) -> list[dict]:
    """Самый длинный ряд by_period для SKU (несколько сборов → берём покрывающий больше дней)."""
    best: list[dict] = []
    for p in daily_files(sku):
        d = rows_of(p)
        if len(d) > len(best):
            best = d
    return sorted([r for r in best if isinstance(r, dict) and r.get("data")], key=lambda r: r["data"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "sku":
        sku = int(a[1])
        for p in daily_files(sku):
            d = sorted(r["data"] for r in rows_of(p) if isinstance(r, dict) and r.get("data"))
            print(f"{p}: {len(d)} дн. {d[0] if d else ''} … {d[-1] if d else ''}")
        return
    n = int(a[0])
    F = files(n)
    if not F:
        raise SystemExit(f"по нише {n} данных нет")
    print(f"{n} {F[0]['niche_name'] or ''}: {len(F)} файлов")
    for kind, G in sorted(collections.defaultdict(list, {k: [c for c in F if c["kind"] == k] for k in {c["kind"] for c in F}}).items()):
        extra = f", SKU: {len({c['sku'] for c in G if c['sku']})}" if kind in ("daily", "card", "comments") else ""
        print(f"  {kind:12} {len(G):4} файлов{extra} | свежий: {latest(n, kind)}")


if __name__ == "__main__":
    main()
