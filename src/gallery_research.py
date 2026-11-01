"""Исследование галерей конкурентов: список конкурентов → скачать галереи WB и Amazon → листы-сравнения.

    python -m src.gallery_research list   --niche 249 --price 900 2600 --include "петл|лент|резинк" --exclude "ткан|мини" --top 18
    python -m src.gallery_research fetch  --niche 249                    # галереи WB по списку (CDN WB, 0 запросов Saleflow)
    python -m src.gallery_research amazon --niche 249 --query "pull up assistance bands set" --detail 8   # Bright Data ≈ 9 кредитов
    python -m src.gallery_research sheets --niche 249                    # листы: 1 строка = 1 карточка

Список конкурентов: marketing/<id>/research/competitors.json; листы: marketing/<id>/research/wb_sheet_N.jpg, amazon_sheet.jpg.
Дальше Claude смотрит листы и пишет разбор слайдов (что показывает каждая карточка) → бриф → дизайн (/foto-dizain).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
FONT = "C:/Windows/Fonts/arial.ttf"


def research_dir(niche: int) -> Path:
    d = ROOT / "marketing" / str(niche) / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def products(niche: int) -> dict[int, dict]:
    from src.datastore import latest
    p = latest(niche, "products500")
    for alt in (ROOT / "data/raw/saleflow/2026-11-01/p500" / f"{niche}.json",           # свежий октябрь (niche_v7_collect)
                ROOT / "data/raw/saleflow/v3_products500" / f"{niche}.json", ROOT / "data/raw/saleflow/v3_products100" / f"{niche}.json"):
        if not p and alt.exists():                       # выгрузки screen_white / niche_deep scan
            p = str(alt)
    if not p:
        sys.exit(f"нет products500 для ниши {niche}: собрать `python -m src.strategy_collect --niche {niche} --step core`")
    d = json.load(open(p, encoding="utf-8"))
    return {r["id"]: r for r in (d["data"] if isinstance(d, dict) else d)}


def cmd_list(a) -> None:
    rows = products(a.niche).values()
    inc = re.compile(a.include, re.I) if a.include else None
    exc = re.compile(a.exclude, re.I) if a.exclude else None
    sel = [r for r in rows if a.price[0] <= (r.get("final_price") or 0) <= a.price[1]
           and (not inc or inc.search(r["name"])) and (not exc or not exc.search(r["name"]))]
    sel.sort(key=lambda r: -(r.get("revenue") or 0))
    top = sel[:a.top]
    out = [{"id": r["id"], "price": r["final_price"], "sales": r["sales"], "reviews": r.get("comments"),
            "start": (r.get("sku_first_date") or "")[:7], "seller": r.get("seller"), "name": r["name"]} for r in top]
    json.dump(out, open(research_dir(a.niche) / "competitors.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"подходят {len(sel)}, в список {len(out)} → marketing/{a.niche}/research/competitors.json")
    for i, r in enumerate(out, 1):
        print(f"{i:>2}. {r['id']} | {r['price']} ₽ | {r['sales']} шт/мес | {r['reviews']} отз. | {r['start']} | {r['name'][:60]}")


def cmd_fetch(a) -> None:
    ids = [str(r["id"]) for r in json.load(open(research_dir(a.niche) / "competitors.json", encoding="utf-8"))]
    subprocess.run([sys.executable, "-m", "src.mkt", "wb", "--niche", str(a.niche), "--skus", *ids], check=True)


def cmd_amazon(a) -> None:
    subprocess.run([sys.executable, "-m", "src.mkt", "amazon", "--niche", str(a.niche), "--query", a.query, "--detail", str(a.detail)], check=True)


def sheet(items: list[tuple[str, list[str]]], out: Path, n: int = 10, tw: int = 150, th: int = 200) -> None:
    f = ImageFont.truetype(FONT, 18)
    im = Image.new("RGB", (220 + tw * n, th * max(1, len(items))), "white")
    d = ImageDraw.Draw(im)
    for i, (label, files) in enumerate(items):
        y = i * th
        d.multiline_text((6, y + 8), label, font=f, fill="black", spacing=4)
        for j, fp in enumerate(files[:n]):
            try:
                t = Image.open(fp).convert("RGB"); t.thumbnail((tw - 4, th - 4)); im.paste(t, (220 + j * tw, y + 2))
            except OSError:
                pass
        d.line([(0, y + th - 1), (im.width, y + th - 1)], fill=(200, 200, 200))
    im.save(out, quality=82)
    print("лист:", out.relative_to(ROOT))


def cmd_sheets(a) -> None:
    rd = research_dir(a.niche)
    wb = ROOT / "data" / "raw" / "mkt" / str(a.niche) / "wb"
    comp = json.load(open(rd / "competitors.json", encoding="utf-8"))
    items = [(f"{k}. {r['id']}\n{r['price']} ₽\n{r['sales']} шт/мес\n{r['reviews']} отз.", sorted(glob.glob(str(wb / str(r["id"]) / "[0-9][0-9].jpg"))))
             for k, r in enumerate(comp, 1)]
    for s in range(0, len(items), 6):
        sheet(items[s:s + 6], rd / f"wb_sheet_{s // 6 + 1}.jpg")
    am = ROOT / "data" / "raw" / "mkt" / str(a.niche) / "amazon"
    g = collections.defaultdict(list)
    for fp in sorted(glob.glob(str(am / "*_[0-9][0-9].jpg"))):
        g[os.path.basename(fp).split("_")[0]].append(fp)
    if g:
        sheet([(f"A{k}. {asin}", fs) for k, (asin, fs) in enumerate(g.items(), 1)], rd / "amazon_sheet.jpg")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list"); l.add_argument("--niche", type=int, required=True); l.add_argument("--price", type=int, nargs=2, default=[0, 10 ** 6])
    l.add_argument("--include"); l.add_argument("--exclude"); l.add_argument("--top", type=int, default=18)
    f = sub.add_parser("fetch"); f.add_argument("--niche", type=int, required=True)
    m = sub.add_parser("amazon"); m.add_argument("--niche", type=int, required=True); m.add_argument("--query", required=True); m.add_argument("--detail", type=int, default=8)
    s = sub.add_parser("sheets"); s.add_argument("--niche", type=int, required=True)
    a = ap.parse_args()
    {"list": cmd_list, "fetch": cmd_fetch, "amazon": cmd_amazon, "sheets": cmd_sheets}[a.cmd](a)


if __name__ == "__main__":
    main()
