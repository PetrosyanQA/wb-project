"""Каталог всех сохранённых данных по нишам (2026-10-08). Файлы НЕ перемещаются — только индекс. 0 запросов.

    python -m src.catalog            # → data/CATALOG.json + docs/DATA_CATALOG.md + docs/DATA_CLEANUP.md

Для каждого файла в data/raw/saleflow/** определяется:
  ниша  — subject_id из пути (dna/777, newcomer/249, launch/777, strategy777, xborder/2486, products_2264_…, subject511_…)
          или из содержимого первого products/items-файла папки-«слага» (termos, chasy-naruchnye …);
  тип   — products500 / products / top100 / daily (by_period) / keywords / comments / card / trends / price_seg / sellers / …;
  месяц — YYYY-MM из имени файла, если есть.
DATA_CLEANUP.md — список подозрительных файлов (пустые, ответы-ошибки, точные дубликаты). Ничего не удаляется.
"""
from __future__ import annotations

import collections
import glob
import hashlib
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
RAW = "data/raw/saleflow"
OUT_JSON = "data/CATALOG.json"
OUT_MD = "docs/DATA_CATALOG.md"
OUT_CLEAN = "docs/DATA_CLEANUP.md"

KINDS = [  # (тип, regex по относительному пути) — порядок важен
    ("daily", r"/(daily|daily_long|winners)/|/launch/\d+/\d+\.json$|_by_period\.json$|by_period"),
    ("card", r"/cards?/|card_content|cards_dims|cards_specs"),
    ("comments", r"comments"),
    ("keywords", r"keywords|/seo/"),
    ("top100", r"top100_products|top100_trajectories"),
    ("products500", r"products500"),
    ("products", r"products|items"),
    ("trends", r"trends|/monthly/|yoy|season"),
    ("price_seg", r"price_seg"),
    ("sellers", r"sellers"),
    ("subjects_list", r"subjects_all|subjects_mid|subjects_small|page_\d+\.json|screen"),
    ("analysis", r"econ|reg\.|summary|segments|eval|\.md$"),
]
NICHE_PATTERNS = [r"/(?:dna|newcomer|launch|xborder|fresh2kg)/(\d+)(?:/|$)", r"strategy(\d+)", r"products_(\d+)_", r"subject(\d+)_",
                  r"/(\d+)_(?:\d{4}-\d\d|products|comments)", r"ids_(\d+)"]


def kind_of(rel: str) -> str:
    for k, rx in KINDS:
        if re.search(rx, rel, re.I):
            return k
    return "other"


def subject_names() -> dict[int, str]:
    names = {}
    for f in glob.glob(f"{RAW}/2026-10-04/subjects_all/page_*.json"):
        try:
            for r in json.load(open(f, encoding="utf-8")).get("data", []):
                names[int(r["id"])] = r["name"].split(" / ")[-1]
        except Exception:                                    # noqa: BLE001 — каталог не должен падать на одном файле
            pass
    return names


def rows_of(path: str) -> list:
    try:
        if os.path.getsize(path) > 30_000_000:
            return []
        d = json.load(open(path, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return []
    if isinstance(d, dict):
        for k in ("data", "items", "products", "result"):
            if isinstance(d.get(k), list):
                return d[k]
        return []
    return d if isinstance(d, list) else []


def slug_subject(folder: str) -> int | None:
    """subject_id папки-«слага»: самый частый `"subject_id": N` в первых 3 МБ её файлов (json/txt/csv)."""
    cnt = collections.Counter()
    for f in sorted(glob.glob(f"{folder}/**/*", recursive=True))[:120]:
        if os.path.isfile(f) and f.endswith((".json", ".txt", ".csv")):
            head = open(f, encoding="utf-8", errors="ignore").read(3_000_000)
            cnt.update(int(x) for x in re.findall(r'"?subject_?[iI][dD]"?\s*[:=]\s*"?(\d{1,5})(?!\d)', head))
    return cnt.most_common(1)[0][0] if cnt else None


def names_from_products(cat: list[dict]) -> dict[int, str]:
    """Названия предметов из самих выгрузок (поле subject у товаров)."""
    names = {}
    for c in cat:
        if c["kind"] in ("products500", "products", "top100") and c["bytes"] < 30_000_000:
            for r in rows_of(c["path"])[:5]:
                if isinstance(r, dict) and r.get("subject_id") and r.get("subject"):
                    names[int(r["subject_id"])] = str(r["subject"]).split(" / ")[-1]
                    break
    return names


def niche_of(rel: str, slug_ids: dict[str, int | None]) -> tuple[int | None, str | None]:
    for rx in NICHE_PATTERNS:
        m = re.search(rx, "/" + rel)
        if m:
            return int(m.group(1)), None
    parts = rel.split("/")
    if len(parts) >= 3 and re.match(r"\d{4}-\d\d-\d\d$", parts[0]):
        slug = parts[1]
        return slug_ids.get(f"{parts[0]}/{slug}"), slug
    return None, None


def build() -> list[dict]:
    names = subject_names()
    slug_ids = {}
    for d in glob.glob(f"{RAW}/2026-*/*/"):
        rel = os.path.relpath(d, RAW).replace("\\", "/").rstrip("/")
        slug_ids[rel] = slug_subject(d)
    cat = []
    for path in glob.glob(f"{RAW}/**/*", recursive=True):
        if os.path.isdir(path):
            continue
        rel = os.path.relpath(path, RAW).replace("\\", "/")
        if rel == "_index.json":
            continue
        nid, slug = niche_of(rel, slug_ids)
        m = re.search(r"(20\d\d-\d\d)(?:-\d\d)?", os.path.basename(rel))
        sku = re.search(r"(?:^|/)(\d{6,11})(?:_by_period)?(?:/by_period)?\.json$", rel) or re.search(r"/(\d{6,11})/", rel)
        cat.append({"path": f"{RAW}/{rel}", "date": rel.split("/")[0] if re.match(r"\d{4}-", rel) else "ingest",
                    "niche": nid, "niche_name": names.get(nid) if nid else None, "slug": slug, "kind": kind_of(rel),
                    "month": m.group(1) if m else None, "sku": int(sku.group(1)) if sku and kind_of(rel) in ("daily", "card", "comments") else None,
                    "bytes": os.path.getsize(path)})
    extra = names_from_products(cat)
    for c in cat:
        if c["niche"] and not c["niche_name"]:
            c["niche_name"] = extra.get(c["niche"])
    # ingest-файлы из корня: ниша из _index.json note
    idx = json.load(open(f"{RAW}/_index.json", encoding="utf-8")) if os.path.exists(f"{RAW}/_index.json") else {}
    for v in idx.values():
        for c in cat:
            if c["path"].endswith("/" + v.get("file", "~")):
                m = re.search(r"(?:subject\s*|\b)(\d{2,5})\b", v.get("note", ""))
                if m and not c["niche"]:
                    c["niche"] = int(m.group(1)); c["niche_name"] = names.get(c["niche"]) or extra.get(c["niche"])
                c["note"] = v.get("note")
    return cat


def write_md(cat: list[dict]) -> None:
    by = collections.defaultdict(list)
    for c in cat:
        by[c["niche"] if c["niche"] else f"slug:{c['slug']}" if c["slug"] else "без ниши"].append(c)
    order = sorted(by, key=lambda k: (k not in (777, 2486), -len(by[k])))
    L = ["# Каталог данных проекта по нишам", "",
         "Автоматически: `python -m src.catalog` (перезапускать после нового сбора). Файлы лежат там, где их сохранил сбор —",
         "этот каталог только показывает, **что есть по каждой нише**. В коде используйте `src/datastore.py` "
         "(`files(777, 'daily')`, `latest(777, 'products500')`, `daily(494403950)`).", "",
         "Типы: products500 = top-500 товаров ниши за месяц; top100 = top-100 + траектории; daily = дневной ряд карточки (wb_sku by_period); "
         "keywords = поисковые запросы; comments = отзывы; card = карточка WB (характеристики, габариты); trends = помесячная динамика ниши.", "",
         f"Всего файлов: {len(cat)}, ниш/папок: {len(by)}, объём {sum(c['bytes'] for c in cat) / 1e9:.2f} ГБ.", "",
         "## Сводка", "", "| Ниша | Файлов | products500 | daily (SKU) | keywords | comments | card | trends | Даты сбора |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for k in order:
        C = by[k]; kc = collections.Counter(c["kind"] for c in C)
        slugs = sorted({c["slug"] for c in C if c["slug"]})
        name = (f"{k} {C[0]['niche_name'] or ''}" if isinstance(k, int) else k).strip() + (f" ({', '.join(slugs[:3])})" if slugs and isinstance(k, int) else "")
        L.append(f"| {name} | {len(C)} | {kc['products500']} | {len({c['sku'] for c in C if c['kind'] == 'daily'})} | {kc['keywords']} | "
                 f"{kc['comments']} | {kc['card']} | {kc['trends']} | {', '.join(sorted({c['date'] for c in C}))} |")
    L += ["", "## Детально (ниши с ≥ 10 файлами)", ""]
    for k in order:
        C = by[k]
        if len(C) < 10:
            continue
        name = (f"{k} {C[0]['niche_name'] or ''}" if isinstance(k, int) else k).strip()
        L += [f"### {name}", "", "| Тип | Файлов | Месяцы | Папки |", "|---|---:|---|---|"]
        for kind, G in sorted(collections.defaultdict(list, {kk: [c for c in C if c["kind"] == kk] for kk in {c["kind"] for c in C}}).items()):
            months = sorted({c["month"] for c in G if c["month"]})
            mtxt = f"{months[0]} … {months[-1]} ({len(months)})" if months else "—"
            dirs = sorted({os.path.dirname(c["path"]).replace(RAW + "/", "") for c in G})
            L.append(f"| {kind} | {len(G)} | {mtxt} | {'<br>'.join(dirs[:6])}{' …' if len(dirs) > 6 else ''} |")
        L.append("")
    os.makedirs("docs", exist_ok=True)
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")


def cleanup(cat: list[dict]) -> None:
    bad, dup, seen = [], collections.defaultdict(list), {}
    for c in cat:
        p = c["path"]
        if c["bytes"] < 20_000:
            txt = open(p, encoding="utf-8", errors="ignore").read(2000).strip()
            empty = txt in ("", "[]", "{}", "null") or re.fullmatch(r'\{\s*"data"\s*:\s*\[\s*\]\s*\}', txt)
            err = re.search(r"request failed|timed out|Missing session|Internal Server Error|\"error\"", txt, re.I)
            if empty or (err and not txt.startswith("[{")):
                bad.append((p, c["bytes"], txt[:80].replace("|", "/").replace("\n", " ")))
                continue
        if c["bytes"] < 50_000_000:
            h = hashlib.md5(open(p, "rb").read()).hexdigest()
            dup[h].append(p)
    dups = [v for v in dup.values() if len(v) > 1]
    waste = sum(os.path.getsize(v[0]) * (len(v) - 1) for v in dups)
    L = ["# Подозрительные файлы данных (ничего не удалено)", "",
         "Сгенерировано `python -m src.catalog`. Решение об удалении — за владельцем проекта.", "",
         "**Рекомендация:** дубликаты не удалять — это намеренные копии (разные скрипты читают разные пути), "
         "экономия была бы ~1% объёма.", "",
         f"## Пустые / ответы-ошибки: {len(bad)}", "", "| Файл | Байт | Начало |", "|---|---:|---|"]
    L += [f"| `{p}` | {b} | {t} |" for p, b, t in sorted(bad)]
    L += ["", f"## Точные дубликаты: {len(dups)} групп, лишнее место {waste / 1e6:.1f} МБ", ""]
    for v in sorted(dups, key=lambda v: -os.path.getsize(v[0]))[:200]:
        L.append(f"- {os.path.getsize(v[0]) / 1e6:.2f} МБ × {len(v)}: " + " = ".join(f"`{x}`" for x in sorted(v)))
    open(OUT_CLEAN, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"подозрительных: {len(bad)}, групп дубликатов: {len(dups)} ({waste / 1e6:.1f} МБ)")


def main() -> None:
    cat = build()
    json.dump(cat, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False)
    write_md(cat)
    cleanup(cat)
    print(f"файлов {len(cat)}; без ниши {sum(1 for c in cat if not c['niche'])} → {OUT_JSON}, {OUT_MD}, {OUT_CLEAN}")


if __name__ == "__main__":
    main()
