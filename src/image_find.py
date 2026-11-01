"""Поиск товара по картинке: разбор выдачи «Яндекс Картинки → Сайты» (скилл /poisk-po-foto).

    python -m src.image_find auto 949363603 --photo 7 --name x   # всё сразу без браузера: поиск по картинке + разбор + WB-данные
    python -m src.image_find url 949363603 [--photo 7]            # ссылка для Яндекса по фото карточки WB (.webp — с .jpg Яндекс «ничего не нашёл»)
    python -m src.image_find parse <yandex_sites.txt> --name tote # текст страницы «Сайты» → таблица совпадений + WB-артикулы
    python -m src.image_find enrich --name tote                   # WB-артикулы → карточка CDN (продавец, материал, размер) + продажи из products500

Текст страницы сохраняет Claude из встроенного браузера (get_page_text) в data/raw/image_find/<name>_sites.txt — 0 запросов Saleflow,
0 кредитов Bright Data (Bright Data не поддерживает Яндекс, Google Lens отдаёт капчу; поиск 1688 по URL картинки не работает — нужна загрузка).
Итог: reports/image_find_<name>_<дата>.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "raw" / "image_find"
SITES = {"wildberries": "WB", "ozon": "Ozon", "market.yandex": "Я.Маркет", "aliexpress": "AliExpress", "joom": "Joom",
         "dhgate": "DHgate", "1688": "1688", "alibaba": "Alibaba", "taobao": "Taobao", "temu": "Temu", "lamoda": "Lamoda"}


def wb_image(sku: int, photo: int = 1) -> str:
    from src.wb_cdn_card import fetch
    card = fetch(sku) or {}
    b = int(card.get("_basket") or 1)
    return f"https://basket-{b:02d}.wbbasket.ru/vol{sku // 100000}/part{sku // 1000}/{sku}/images/big/{photo}.webp"


def yandex_url(img: str) -> str:
    return "https://yandex.ru/images/search?rpt=imageview&cbir_page=sites&url=" + urllib.parse.quote(img, safe="")


def auto(img: str) -> list[dict]:
    """Поиск по картинке без браузера: Яндекс «Сайты» отдаёт в HTML JSON "sites":[{title,url,domain,originalImage}]."""
    import html as H
    import requests
    r = requests.get(yandex_url(img), timeout=30, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                                                         "Chrome/124 Safari/537.36", "Accept-Language": "ru"})
    if "showcaptcha" in r.url:
        raise SystemExit("Яндекс просит капчу — не обходим; открыть ссылку во встроенном браузере (шаги 2–4 скилла)")
    t, out = H.unescape(r.text), []
    for m in re.finditer(r'"sites":\[', t):
        depth, i = 0, m.end() - 1
        for j in range(i, min(len(t), i + 200000)):
            depth += {"[": 1, "]": -1}.get(t[j], 0)
            if depth == 0:
                try:
                    out += json.loads(t[i:j + 1])
                except ValueError:
                    pass
                break
    rows, seen = [], set()
    for s in out:
        if s.get("url") in seen:
            continue
        seen.add(s.get("url"))
        title, host = s.get("title") or "", s.get("domain") or ""
        site = next((v for k, v in SITES.items() if k in host.lower()), host)
        m = re.search(r"за ([\d\s]+) (₽|тг|руб)", title) or re.search(r"[Оо]т ([\d\s,]+) (руб|€|\$)", title)
        sku = re.search(r"/catalog/(\d+)/|\b(\d{6,12})\b", (s.get("url") or "") + " " + title)
        dims = re.search(r"длина:\s*(\d+)\s*см\s*Ширина:\s*(\d+)\s*см\s*Высота:\s*(\d+)", s.get("description") or "", re.I)
        rows.append(dict(site=site, host=host, title=title[:110], price=f"{m.group(1).strip()} {m.group(2)}" if m else "",
                         id=(sku.group(1) or sku.group(2)) if sku else "", global_wb="global.wildberries" in host,
                         dims="×".join(dims.groups()) if dims else "", desc=(s.get("description") or "")[:140], url=s.get("url")))
    return rows


def parse(text: str) -> list[dict]:
    """Блоки выдачи начинаются строкой «ШИРИНА×ВЫСОТА», затем заголовок, затем домен, затем описание."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    out = []
    for i, ln in enumerate(lines):
        if not re.fullmatch(r"\d{3,4}×\d{3,4}", ln) or i + 2 >= len(lines):
            continue
        title, host = lines[i + 1], lines[i + 2]
        desc = lines[i + 3] if i + 3 < len(lines) and not re.fullmatch(r"\d{3,4}×\d{3,4}", lines[i + 3]) else ""
        site = next((v for k, v in SITES.items() if k in host.lower()), host)
        m = re.search(r"за ([\d\s]+) (₽|тг|руб)", title) or re.search(r"[Оо]т ([\d\s,]+) (руб|€|\$)", title)
        price = f"{m.group(1).strip()} {m.group(2)}" if m else ""
        sku = re.search(r"\b(\d{6,12})\b", title)
        dims = re.search(r"длина:\s*(\d+)\s*см\s*Ширина:\s*(\d+)\s*см\s*Высота:\s*(\d+)", desc, re.I)
        out.append(dict(site=site, host=host, title=title[:110], price=price, id=sku.group(1) if sku else "",
                        global_wb="global.wildberries" in host, dims="×".join(dims.groups()) if dims else "",
                        desc=desc[:140]))
    return out


def enrich(rows: list[dict]) -> list[dict]:
    from src.wb_cdn_card import fetch
    sold = {}
    for p in glob.glob(str(ROOT / "data/raw/saleflow/v3_products*/*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in (d.get("data") if isinstance(d, dict) else d) or []:
            sold[str(r.get("id"))] = r
    for x in rows:
        if x["site"] != "WB" or not x["id"]:
            continue
        c = fetch(int(x["id"])) or {}
        opts = {o.get("name", "").lower(): o.get("value") for o in c.get("options") or []}
        x["material"] = next((v for k, v in opts.items() if "материал" in k or "состав" in k), "")
        x["size"] = next((v for k, v in opts.items() if k.startswith(("размер", "длина", "ширина", "высота"))), "")
        x["country"] = next((v for k, v in opts.items() if "страна" in k), "")
        s = sold.get(x["id"])
        if s:
            x.update(sales_jul=s.get("sales"), price_jul=round(s.get("final_price_average") or s.get("final_price") or 0),
                     seller=s.get("seller"), start=(s.get("sku_first_date") or "")[:7])
    return rows


def report(name: str, rows: list[dict]) -> str:
    L = [f"# Поиск по картинке: {name} — {dt.date.today()}", "",
         "Источник: Яндекс Картинки → «Сайты» (одинаковое фото = та же модель с той же фабрики).", "",
         "| Площадка | Цена | Артикул | Название | Продаж/мес (07.2026) | Продавец | Материал | Размер |",
         "|---|---:|---|---|---:|---|---|---|"]
    for x in rows:
        link = f"[{x['id']}](https://www.wildberries.ru/catalog/{x['id']}/detail.aspx)" if x["site"] == "WB" and x["id"] else (x["id"] or "—")
        site = x["site"] + (" (кросс-бордер)" if x.get("global_wb") else "")
        L.append(f"| {site} | {x['price'] or x.get('price_jul') or '—'} | {link} | {x['title'][:60]} | {x.get('sales_jul', '—')} | "
                 f"{str(x.get('seller') or '—')[:16]} | {str(x.get('material') or '—')[:25]} | {x.get('size') or x.get('dims') or '—'} |")
    wb = [x for x in rows if x["site"] == "WB"]
    other = sorted({x["site"] for x in rows if x["site"] not in ("WB",)})
    L += ["", f"Итого: {len(rows)} совпадений; на WB — {len(wb)} (кросс-бордер из Китая — {sum(1 for x in wb if x.get('global_wb'))}); "
          f"другие площадки: {', '.join(other) or '—'}.",
          "", "**Как читать:** та же модель на WB у других продавцов = конкуренты по этому товару и их цена; кросс-бордер (global.wildberries) = "
          "продают напрямую из Китая, обычно дешевле; AliExpress / DHgate / Joom = розничная цена Китая (потолок; цена фабрики на 1688 ниже в 2–4 раза).",
          "", "**Фабрика на 1688:** поиск по фото на 1688 работает только с загрузкой файла — открыть приложение 1688 / s.1688.com → иконка камеры → "
          "загрузить фото (пользователь сам; капчу не обходим). Или: `python -m src.brightdata_client s1688 \"<китайский запрос>\"` "
          "по названию и размерам из таблицы."]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["url", "auto", "parse", "enrich"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--photo", type=int, default=1)
    ap.add_argument("--name", default="item")
    a = ap.parse_args()
    DIR.mkdir(parents=True, exist_ok=True)
    if a.cmd == "url":
        img = wb_image(int(a.arg), a.photo) if a.arg.isdigit() else a.arg
        print("фото:", img)
        print("Яндекс:", yandex_url(img))
        return
    jp = DIR / f"{a.name}.json"
    if a.cmd == "auto":
        img = wb_image(int(a.arg), a.photo) if a.arg.isdigit() else a.arg
        rows = enrich(auto(img))
        json.dump(rows, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"совпадений: {len(rows)}")
    if a.cmd == "parse":
        rows = parse(open(a.arg, encoding="utf-8").read())
        json.dump(rows, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"совпадений: {len(rows)} → {jp.relative_to(ROOT)}")
    rows = json.load(open(jp, encoding="utf-8"))
    if a.cmd == "enrich":
        rows = enrich(rows)
        json.dump(rows, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    text = report(a.name, rows)
    out = ROOT / "reports" / f"image_find_{a.name}_{dt.date.today()}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
