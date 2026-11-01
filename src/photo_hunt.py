"""Найти КАРТИНКИ товара по ОПИСАНИЮ (без фото пользователя): Китай + международные площадки + Pinterest → лист-сравнение →
выбор → поиск той же модели по картинке (/poisk-po-foto).

    python -m src.photo_hunt plan    --spec tote     # ссылки Яндекс Картинок по источникам (открывает Claude во встроенном браузере)
    python -m src.photo_hunt yandex  --spec tote     # Яндекс Картинки по тексту × площадки (Pinterest, AliExpress, WB, Ozon, Маркет, все) — напрямую, 0 кредитов
    python -m src.photo_hunt collect --spec tote     # 1688 (офферы + фото) и Amazon (поиск) через Bright Data, ≈ 2–4 кредита
    python -m src.photo_hunt sheet   --spec tote     # скачать картинки, баллы по описанию, листы 6×5 с номерами → смотреть глазами
    python -m src.photo_hunt pick    --spec tote 3 17 # выбранные номера → ссылки «поиск по картинке» (Яндекс → Сайты) + оффер/ASIN

Источники и как берём (проверено 27.10.2026):
  Яндекс Картинки по тексту + `site:` — pinterest.com, aliexpress.ru, wildberries.ru, ozon.ru, market.yandex.ru, без фильтра —
      встроенный браузер, Claude снимает [{img, alt}] JS-ом и пишет в data/raw/photo_hunt/<spec>/yandex_<источник>.json
  1688 — Bright Data s1688 (фото оффера cbu01.alicdn.com + цена + id), Amazon — Bright Data поиск (фото + ASIN + цена).
  Bright Data не пускает на Pinterest/AliExpress (robots.txt без KYC) — не обходим, идём через Яндекс.
Описание (ключевые слова RU/EN/CN, плюсы и минусы) — SPECS ниже; китайская часть общая с src/spec_find.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import io
import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
FONT = "C:/Windows/Fonts/msyh.ttc"          # с кириллицей и китайским (arial рисует квадраты)

SPECS = {
    "kbag": {   # тип сумки Kenguluna 21737 (Я.Маркет): каркасная деловая А4, молния сверху, чёрный корпус + серые бока/ручки — без логотипа
        "ru": "сумка женская деловая А4 каркасная молния экокожа двухцветная",
        "en": "women structured work handbag A4 zipper two tone black grey",
        "cn_files": ["k_gongwen", "k_zip", "k_pinse", "t_a4", "t_dding"],
        "sites": ["wildberries.ru", "ozon.ru", ""],
        "keep": r"сумк|bag|handbag|包|çanta|sac|bolsa",
        "plus": r"делов|офис|a4|а4|каркас|structured|молни|zip|拉链|撞色|拼色|two.?tone|эко.?кож|pu|皮|公文|手提|通勤|work|business|черн|black|黑|сер|grey|gray|灰",
        "minus": r"ткан|canvas|帆布|牛津|oxford|nylon|尼龙|детск|童|принт|印花|рюкзак|双肩|клатч|мини|小号|电脑包男|男",
    },
    "tote": {
        "ru": "сумка тоут экокожа молния А4",
        "en": "black vegan leather tote bag zipper laptop",
        "cn_files": ["wv_tote", "tote_zip", "tote_pu", "t_zimu", "t_dding", "t_a4", "t_tongqin"],
        "keep": r"сумк|тоут|шоппер|bag|tote|purse|handbag|包|çanta|sac|bolsa|borsa",
        "sites": ["pinterest.com", "aliexpress.ru", "wildberries.ru", "ozon.ru", "market.yandex.ru", ""],
        "plus": r"тоут|шоппер|tote|托特|молни|zip|拉链|эко.?кож|кожзам|pu\b|vegan|leather|皮|а4|a4|laptop|ноутбук|电脑|"
                r"черн|black|黑|коричн|шокол|brown|coffee|咖啡|棕|косметич|pouch|子母|ножк|feet|底钉|работ|office|work|通勤",
        "minus": r"магнит|magnet|磁|ткан|canvas|帆布|вязан|knit|детск|kid|童|принт|print|印花|мини|mini|小号|рюкзак|backpack|双肩|"
                 r"клатч|clutch|кошел|wallet|пляж|beach|соломен|straw",
    },
}


def d(spec: str) -> Path:
    p = ROOT / "data" / "raw" / "photo_hunt" / spec
    (p / "img").mkdir(parents=True, exist_ok=True)
    return p


def plan(spec: str) -> None:
    S = SPECS[spec]
    print("Открыть каждую ссылку во встроенном браузере, подождать 4 с и выполнить JS (снимает картинки и подписи):")
    print("  [...document.querySelectorAll('a[href*=\"img_url=\"]')].map(a=>({img:new URL(a.href).searchParams.get('img_url'),"
          " alt:(a.querySelector('img')||{}).alt||''}))")
    print(f"Результат каждой ссылки → data/raw/photo_hunt/{spec}/yandex_<источник>.json\n")
    for lang in ("ru", "en"):
        for site in S["sites"]:
            q = S[lang] + (f" site:{site}" if site else "")
            name = f"{lang}_{site.split('.')[0] or 'all'}"
            print(f"{name}: https://yandex.ru/images/search?text={urllib.parse.quote(q)}")


def yandex(spec: str) -> None:
    """Яндекс Картинки по тексту (ru/en × площадки) напрямую: в HTML есть JSON entities — origUrl, alt, snippet (страница, домен)."""
    import html as H
    import time
    S, n_all = SPECS[spec], 0
    rx = re.compile(r'"alt":"((?:[^"\\]|\\.)*)".{0,300}?"origUrl":"([^"]+)","snippet":\{"title":"((?:[^"\\]|\\.)*)","domain":"([^"]*)","url":"([^"]*)"')
    for lang in ("ru", "en"):
        for site in S["sites"]:
            name = f"{lang}_{site.split('.')[0] or 'all'}"
            p = d(spec) / f"yandex_{name}.json"
            if p.exists():
                continue
            q = S[lang] + (f" site:{site}" if site else "")
            r = requests.get("https://yandex.ru/images/search?text=" + urllib.parse.quote(q), timeout=25,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                                      "Accept-Language": "ru"})
            if "showcaptcha" in r.url or "captcha" in r.text[:5000].lower():
                print(f"{name}: Яндекс просит капчу — стоп (не обходим); открыть ссылку во встроенном браузере вручную")
                break
            t = H.unescape(r.text)
            rows = [dict(src="Я:" + (dom or site or "all"), img=img, alt=(alt + " | " + title)[:200], url=url, price="")
                    for alt, img, title, dom, url in rx.findall(t)]
            json.dump(rows, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            n_all += len(rows)
            print(f"{name}: {len(rows)} картинок")
            time.sleep(3)
    print(f"Яндекс: {n_all} новых картинок")


def collect(spec: str) -> None:
    from src.brightdata_client import BudgetStop, fetch, offers_1688
    S, out = SPECS[spec], []
    for name in S["cn_files"]:
        for p in sorted(glob.glob(str(ROOT / f"data/raw/brightdata/*/1688_{name}.html")))[-1:]:
            for r in offers_1688(open(p, encoding="utf-8", errors="ignore").read()):
                if r.get("img"):
                    out.append(dict(src="1688", img=r["img"], alt=r["title"], price=f"¥{r['price_cny']}", id=r["offer_id"],
                                    url=f"https://detail.1688.com/offer/{r['offer_id']}.html" if r["offer_id"] else ""))
    try:
        h = fetch(f"https://www.amazon.com/s?k={urllib.parse.quote(S['en'])}", f"amz_s_hunt_{spec}")
        for b in h.split('data-component-type="s-search-result"')[1:]:
            g = lambda rx: (re.findall(rx, b) or [None])[0]        # noqa: E731
            asin, img = g(r'data-asin="(\w+)"'), g(r'class="s-image"[^>]+src="([^"]+)"')
            if asin and img:
                out.append(dict(src="Amazon", img=img, alt=g(r'<h2[^>]*aria-label="([^"]+)"') or "", price=g(r'a-offscreen">(\$[\d.,]+)<') or "",
                                id=asin, url=f"https://www.amazon.com/dp/{asin}"))
    except BudgetStop:
        raise
    except SystemExit as e:
        print("Amazon:", e)
    json.dump(out, open(d(spec) / "bright.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"1688 + Amazon: {len(out)} картинок → data/raw/photo_hunt/{spec}/bright.json")


def items(spec: str) -> list[dict]:
    rows = []
    for p in sorted(d(spec).glob("*.json")):
        if p.name == "sheet.json":
            continue
        for r in json.load(open(p, encoding="utf-8")):
            if not r.get("img"):
                continue
            src = r.get("src") or p.stem.replace("yandex_", "Я:")
            host = urllib.parse.urlparse(r["img"]).netloc
            src = {"i.pinimg.com": "Pinterest"}.get(host, src)
            if "wbbasket" in host:
                src = "WB"
            if "alicdn" in host and src.startswith("Я"):
                src = "AliExpress/1688"
            if "media-amazon" in r["img"]:                         # превью 218 px → большое фото (иначе поиск по картинке шумит)
                r["img"] = re.sub(r"\._AC_[^.]+_\.", "._AC_SL1000_.", r["img"])
            rows.append({**r, "src": src})
    seen, out = set(), []
    for r in rows:
        k = re.sub(r"[?#].*$", "", r["img"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def score(r: dict, S: dict) -> int:
    t = (r.get("alt") or "").lower()
    return 2 * len(set(re.findall(S["plus"], t, re.I))) - 4 * len(set(re.findall(S["minus"], t, re.I)))


def sheet(spec: str, per: int = 30) -> None:
    S = SPECS[spec]
    rows = items(spec)
    for r in rows:
        r["score"] = score(r, S)
    rows.sort(key=lambda r: -r["score"])
    rows = [r for r in rows if r["score"] > 0][:120]
    f = ImageFont.truetype(FONT, 15)
    ok = []
    for r in rows:
        fp = d(spec) / "img" / (hashlib.md5(r["img"].encode()).hexdigest()[:12] + ".jpg")
        if not fp.exists():
            try:
                x = requests.get(r["img"], headers={"User-Agent": "Mozilla/5.0", "Referer": "https://yandex.ru/"}, timeout=15)
                Image.open(io.BytesIO(x.content)).convert("RGB").save(fp, quality=85)
            except Exception:                                            # noqa: BLE001 — битые/закрытые картинки пропускаем
                continue
        r["file"] = str(fp)
        ok.append(r)
    for n, r in enumerate(ok, 1):
        r["n"] = n
    json.dump(ok, open(d(spec) / "sheet.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tw, th, cols = 220, 260, 6
    for s in range(0, len(ok), per):
        part = ok[s:s + per]
        im = Image.new("RGB", (tw * cols, th * ((len(part) + cols - 1) // cols)), "white")
        dr = ImageDraw.Draw(im)
        for i, r in enumerate(part):
            x, y = (i % cols) * tw, (i // cols) * th
            try:
                t = Image.open(r["file"]); t.thumbnail((tw - 8, th - 46)); im.paste(t, (x + 4, y + 4))
            except OSError:
                pass
            dr.rectangle([x, y + th - 42, x + tw, y + th], fill="white")
            dr.text((x + 4, y + th - 40), f"#{r['n']} {r['src'][:12]} {r.get('price') or ''}", font=f, fill="black")
            dr.text((x + 4, y + th - 21), (r.get("alt") or "")[:30], font=f, fill=(90, 90, 90))
        out = d(spec) / f"sheet_{s // per + 1}.jpg"
        im.save(out, quality=82)
        print("лист:", out.relative_to(ROOT))
    by = {}
    for r in ok:
        by[r["src"]] = by.get(r["src"], 0) + 1
    print(f"картинок с баллом > 0: {len(ok)} — " + ", ".join(f"{k} {v}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])))


def pick(spec: str, nums: list[int]) -> None:
    """Выбранные номера → поиск той же модели по картинке (Яндекс «Сайты», без браузера) → reports/image_find_<spec>_<n>_<дата>.md."""
    from src.image_find import auto, enrich, report, yandex_url
    S = SPECS[spec]
    rows = {r["n"]: r for r in json.load(open(d(spec) / "sheet.json", encoding="utf-8"))}
    for n in nums:
        r = rows.get(n)
        if not r:
            continue
        print(f"#{n} {r['src']} {r.get('price') or ''} {r.get('url') or ''}\n   {r.get('alt', '')[:90]}\n   поиск той же модели: {yandex_url(r['img'])}")
        try:
            found = [x for x in enrich(auto(r["img"])) if re.search(S["keep"], x["title"], re.I)]   # только тот же тип товара
        except SystemExit as e:
            print("  ", e)
            continue
        out = ROOT / "reports" / f"image_find_{spec}_{n}_{dt.date.today()}.md"
        out.write_text(report(f"{spec} #{n}", found), encoding="utf-8")
        for x in found[:12]:
            print(f"   {x['site']:<12} {x['price'] or '—':>9}  {x['id'] or '':<12} {x['title'][:70]}")
        print(f"   всего совпадений: {len(found)} → {out.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "yandex", "collect", "sheet", "pick"])
    ap.add_argument("nums", nargs="*", type=int)
    ap.add_argument("--spec", default="tote")
    a = ap.parse_args()
    {"plan": lambda: plan(a.spec), "yandex": lambda: yandex(a.spec), "collect": lambda: collect(a.spec), "sheet": lambda: sheet(a.spec),
     "pick": lambda: pick(a.spec, a.nums)}[a.cmd]()


if __name__ == "__main__":
    main()
