"""Маркетинговый модуль: визуальная разведка конкурентов (WB + Amazon) и генерация фото/инфографики.

    python -m src.mkt wb --niche 249 --top 12                 # top-N по выручке (products500 июля) → галереи + rich + характеристики
    python -m src.mkt wb --niche 249 --skus 150000713 24257910
    python -m src.mkt amazon --niche 249 --query "pull up assistance bands" [--detail 6]   # Bright Data: выдача + галереи топ-N
    python -m src.mkt audit --niche 249                       # таблица «карточка ↔ продажи» + контакт-листы → marketing/<niche>/
    python -m src.mkt gen --niche 249 --mode infographics --image <файл|URL|wb:sku> --brief marketing/249/brief_slide1.txt [--count 4]
    python -m src.mkt gen --niche 249 --mode photoshoot|freeform|remove-bg|upscale --image ... [--brief ...]
    python -m src.mkt compose marketing/249/slides/s1.json [...]   # слайд 900×1200: фото + точный русский текст (ИИ искажает кириллицу)

Данные: data/raw/mkt/<niche>/{wb,amazon}/ (сырые, не в git); результаты и брифы: marketing/<niche>/ (в git, кроме *_raw).
Генерация — Saleflow Photo Editor (pe_*) через src.saleflow_stdio. Чужие фото — только для анализа; публикуем только
кадры НАШЕГО товара (образец / наша съёмка). Методика и чек-листы — marketing/README.md.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
FONT = "C:/Windows/Fonts/arial.ttf"
FONT_B = "C:/Windows/Fonts/arialbd.ttf"


def raw_dir(niche: int, src: str) -> Path:
    p = ROOT / "data" / "raw" / "mkt" / str(niche) / src
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_dir(niche: int) -> Path:
    p = ROOT / "marketing" / str(niche)
    p.mkdir(parents=True, exist_ok=True)
    return p


def font(sz: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_B if bold else FONT, sz)
    except OSError:
        return ImageFont.load_default()


def get_img(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, headers=UA, timeout=25)
        return Image.open(io.BytesIO(r.content)).convert("RGB") if r.status_code == 200 else None
    except Exception:                                           # noqa: BLE001
        return None


# ── WB ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def top_skus(niche: int, top: int) -> list[dict]:
    from src import datastore as D
    data, meta = D.products(niche, "2026-10")             # свежий список конкурентов (для выбора карточек, не для продаж)
    if not data:
        data, meta = D.products(niche, "2026-07")
    if not data:
        raise SystemExit(f"нет products500 для {niche}: соберите Saleflow products (src.strategy_collect --step core)")
    rows = [r for r in data if r.get("sales")]
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: -r["revenue"]):
        imt = r.get("itemid")
        if imt in seen:
            continue
        seen.add(imt); out.append(r)
        if len(out) >= top:
            break
    return out


def wb_collect(niche: int, skus: list[int], meta: dict[int, dict]) -> list[dict]:
    from src.wb_cdn_card import fetch as cdn
    d = raw_dir(niche, "wb")
    res = []
    for nm in skus:
        cp = d / f"{nm}.json"
        card = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else cdn(nm)
        if not card:
            print("  нет card.json:", nm); continue
        n = card.get("_basket")
        base = f"https://basket-{n:02d}.wbbasket.ru/vol{nm // 100000}/part{nm // 1000}/{nm}"
        if "_rich" not in card:
            try:
                r = requests.get(f"{base}/info/ru/rich.json", headers=UA, timeout=20)
                card["_rich"] = r.json() if r.status_code == 200 else None
            except Exception:                                   # noqa: BLE001
                card["_rich"] = None
        cp.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        cnt = (card.get("media") or {}).get("photo_count") or 0
        imgs = [f"{base}/images/big/{i}.webp" for i in range(1, min(cnt, 15) + 1)]
        rich = [b["img"]["src"] for blk in ((card.get("_rich") or {}).get("content") or []) for b in blk.get("blocks", []) if b.get("img")]
        gd = d / str(nm)
        gd.mkdir(exist_ok=True)
        with ThreadPoolExecutor(8) as ex:
            for i, im in enumerate(ex.map(get_img, imgs + rich)):
                if im:
                    im.save(gd / (f"{i + 1:02d}.jpg" if i < len(imgs) else f"rich_{i - len(imgs) + 1:02d}.jpg"), quality=85)
        opts = {o["name"]: o["value"] for g in card.get("grouped_options", []) for o in g.get("options", [])} or \
               {o["name"]: o["value"] for o in card.get("options", [])}
        m = meta.get(nm, {})
        res.append({"nm": nm, "name": card.get("imt_name"), "photos": cnt, "video": bool((card.get("media") or {}).get("has_video")),
                    "rich_blocks": len(rich), "chars": len(opts), "desc_len": len(card.get("description") or ""),
                    "price": round(m["revenue"] / m["sales"]) if m.get("sales") else None,
                    "sales_day": round(m["sales"] / 31, 1) if m.get("sales") else None,
                    "reviews": m.get("comments"), "rating": m.get("rating"), "options": opts})
        print(f"  {nm}: фото {cnt}, rich {len(rich)}, характеристик {len(opts)}")
    (d / "_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def sheet(rows: list[tuple[str, list[Path]]], path: Path, tw: int = 165, th: int = 220, nmax: int = 10, label_w: int = 260) -> None:
    W = label_w + tw * nmax
    img = Image.new("RGB", (W, th * len(rows)), "white")
    d = ImageDraw.Draw(img)
    for r, (label, files) in enumerate(rows):
        y = r * th
        for k, line in enumerate(label.split("\n")[:6]):
            d.text((6, y + 8 + k * 22), line[:30], font=font(15, k == 0), fill="black" if k == 0 else (70, 70, 70))
        for i, f in enumerate(files[:nmax]):
            try:
                im = Image.open(f).convert("RGB"); im.thumbnail((tw - 4, th - 4)); img.paste(im, (label_w + i * tw, y + 2))
            except Exception:                                   # noqa: BLE001
                pass
    img.save(path, quality=85)


# ── Amazon ──────────────────────────────────────────────────────────────────────────────────────────────────────
def amazon(niche: int, query: str, detail: int) -> list[dict]:
    from src.brightdata_client import BudgetStop, fetch
    d = raw_dir(niche, "amazon")
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:40]
    html = fetch(f"https://www.amazon.com/s?k={requests.utils.quote(query)}", f"amz_s_{slug}")
    items = []
    for b in html.split('data-component-type="s-search-result"')[1:]:
        g = lambda rx: (re.findall(rx, b) or [None])[0]               # noqa: E731
        asin = g(r'data-asin="(\w+)"') or g(r'/dp/(\w{10})')
        items.append({"asin": asin, "title": g(r'<h2[^>]*aria-label="([^"]+)"') or g(r'<span class="a-size-[^"]*a-text-normal"[^>]*>([^<]+)<'),
                      "price": g(r'a-offscreen">\$?([\d.,]+)<'), "rating": g(r'([\d.]+) out of 5 stars'),
                      "reviews": g(r'aria-label="([\d,]+) ratings?"'), "bought_month": g(r'([\d.,]+K?\+?) bought in past month'),
                      "sponsored": "Sponsored" in b[:3000], "img": g(r'class="s-image"[^>]+src="([^"]+)"') or g(r'src="(https://m\.media-amazon[^"]+)"')})
    uniq = {}
    for i in items:
        if i["asin"] and i["asin"] not in uniq:
            i["title"] = re.sub(r"^Sponsored Ad - ", "", i["title"] or "")
            uniq[i["asin"]] = i
    items = list(uniq.values())

    def bought(i):
        s = (i.get("bought_month") or "0").replace("+", "").replace(",", "")
        return float(s[:-1]) * 1000 if s.endswith("K") else float(s or 0)
    items.sort(key=lambda i: -bought(i))
    (d / f"search_{slug}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in items[:24]:
        p = d / f"{i['asin']}_s.jpg"
        if not p.exists() and i.get("img"):
            im = get_img(i["img"])
            if im: im.save(p, quality=85)
    for i in items[:detail]:                                    # галерея товара: 1 кредит Bright Data на ASIN
        h = ""
        for attempt in range(3):                                # Bright Data: «adaptive rate limit» → пауза и повтор
            try:
                h = fetch(f"https://www.amazon.com/dp/{i['asin']}", f"amz_dp_{i['asin']}"); break
            except BudgetStop:
                raise
            except BaseException as e:                          # noqa: BLE001 — fetch может вызвать SystemExit
                print("   повтор", i["asin"], str(e)[:80]); time.sleep(8 * (attempt + 1))
        urls = list(dict.fromkeys(re.findall(r'"hiRes":"(https://m\.media-amazon\.com/images/I/[^"]+)"', h)))[:10]
        i["gallery"] = len(urls)
        with ThreadPoolExecutor(6) as ex:
            for k, im in enumerate(ex.map(get_img, urls)):
                if im: im.save(d / f"{i['asin']}_{k + 1:02d}.jpg", quality=85)
    (d / f"search_{slug}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Amazon «{query}»: {len(items)} товаров, галерей {min(detail, len(items))}")
    return items


# ── аудит ───────────────────────────────────────────────────────────────────────────────────────────────────────
def audit(niche: int) -> None:
    wd, ad, od = raw_dir(niche, "wb"), raw_dir(niche, "amazon"), out_dir(niche)
    wb = json.loads((wd / "_summary.json").read_text(encoding="utf-8")) if (wd / "_summary.json").exists() else []
    if wb:
        rows = []
        for c in wb:
            files = sorted((wd / str(c["nm"])).glob("[0-9][0-9].jpg"))
            rows.append((f"{c['nm']}\n{(c['name'] or '')[:28]}\n{c['price'] or '—'} ₽ · {c['sales_day'] or '—'}/д\n"
                         f"фото {c['photos']} · rich {c['rich_blocks']}\nхар-к {c['chars']} · отз {c['reviews'] or '—'}", files))
        sheet(rows, od / "wb_galleries.jpg")
        rich = [(f"{c['nm']} rich", sorted((wd / str(c["nm"])).glob("rich_*.jpg"))) for c in wb if c["rich_blocks"]]
        if rich:
            sheet(rich, od / "wb_rich.jpg", tw=300, th=190, nmax=6, label_w=150)
    amz = sorted(ad.glob("search_*.json"))
    if amz:
        items = json.loads(amz[-1].read_text(encoding="utf-8"))
        rows = []
        for i in items[:12]:
            files = sorted(ad.glob(f"{i['asin']}_[0-9][0-9].jpg")) or sorted(ad.glob(f"{i['asin']}_s.jpg"))
            rows.append((f"{i['asin']}\n${i.get('price') or '—'} · {i.get('bought_month') or '—'}/мес\nрейтинг {i.get('rating') or '—'} · {i.get('reviews') or '—'} отз.\n{(i.get('title') or '')[:28]}", files))
        sheet(rows, od / "amazon_galleries.jpg")
    md = [f"# Визуальный аудит {niche} (автоматическая часть)", "",
          "| SKU | Цена ₽ | Продажи/д | Отзывы | Фото | Видео | Rich-блоков | Характеристик | Описание, симв. |", "|---|---:|---:|---:|---:|---|---:|---:|---:|"]
    for c in wb:
        md.append(f"| {c['nm']} | {c['price'] or '—'} | {c['sales_day'] or '—'} | {c['reviews'] or '—'} | {c['photos']} | {'да' if c['video'] else 'нет'} | {c['rich_blocks']} | {c['chars']} | {c['desc_len']} |")
    md += ["", "Источник: WB CDN (карточки), Saleflow products500 (цена/продажи, июль). Картинки: wb_galleries.jpg, wb_rich.jpg, amazon_galleries.jpg.",
           "Разбор слайдов, позиционирование и бриф пишет аналитик по marketing/README.md (шаги 3–5)."]
    (od / "audit_auto.md").write_text("\n".join(md), encoding="utf-8")
    print("готово:", od)


# ── генерация (Saleflow Photo Editor) ───────────────────────────────────────────────────────────────────────────
def as_input(src: str) -> str:
    if src.startswith(("http://", "https://", "wb:", "data:")):
        return src
    im = Image.open(src).convert("RGB")                        # Photo Editor падает на больших base64 → ≤ 1200 px JPEG
    im.thumbnail((1200, 1200))
    b = io.BytesIO(); im.save(b, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def collect_images(obj) -> list[str]:
    out = []
    if isinstance(obj, str):
        if obj.startswith(("http://", "https://")) and re.search(r"\.(png|jpe?g|webp)(\?|$)", obj, re.I):
            out.append(obj)
        elif obj.startswith("data:image") or (len(obj) > 2000 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", obj[:200])):
            out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values(): out += collect_images(v)
    elif isinstance(obj, list):
        for v in obj: out += collect_images(v)
    return out


def gen(niche: int, mode: str, image: str, brief: str | None, count: int, aspect: str, refs: list[str]) -> None:
    from src.saleflow_stdio import Client
    from src.strategy_collect import fetch as sf
    prompt = " ".join(Path(brief).read_text(encoding="utf-8").split()) if brief and Path(brief).exists() else (brief or "")
    tool, args = {
        "infographics": ("pe_infographics_auto", {"prompt": prompt, "image_count": count, "aspect_ratio": aspect}),
        "photoshoot": ("pe_photoshoot_auto", {"prompt": prompt, "image_count": count, "aspect_ratio": aspect}),
        "freeform": ("pe_freeform", {"prompt": prompt, "aspect_ratio": aspect}),
        "remove-bg": ("pe_remove_background", {}),
        "upscale": ("pe_upscale", {}),
    }[mode]
    args["image"] = as_input(image)
    if mode in ("infographics", "photoshoot", "freeform"):
        args["model"] = "model_2" if mode == "infographics" else "model_1"   # «auto» бэкенд не принимает
    if refs and mode in ("infographics", "photoshoot", "freeform"):
        args["references"] = [as_input(r) for r in refs[:5]]
    od = out_dir(niche) / "generated" / time.strftime("%Y%m%d_%H%M%S")
    od.mkdir(parents=True, exist_ok=True)
    (od / "request.json").write_text(json.dumps({"tool": tool, "mode": mode, "prompt": prompt, "image": image, "refs": refs,
                                                 "count": count, "aspect": aspect}, ensure_ascii=False, indent=1), encoding="utf-8")
    res = sf(Client(), tool, args, timeout=900)
    (od / "response_meta.json").write_text(json.dumps(res, ensure_ascii=False)[:20000], encoding="utf-8")
    imgs = collect_images(res)
    for k, s in enumerate(imgs, 1):
        if s.startswith("http"):
            im = get_img(s)
            if im: im.save(od / f"frame_{k}.png")
        else:
            b = s.split(",", 1)[1] if s.startswith("data:") else s
            (od / f"frame_{k}.png").write_bytes(base64.b64decode(b))
    print(f"{tool}: кадров {len(imgs)} → {od}")


# ── сборка слайда: точный кириллический текст поверх фото ───────────────────────────────────────────────────────────
THEMES = {"dark": {"bg": (24, 26, 30), "fg": (255, 255, 255), "accent": (198, 241, 53), "sub": (215, 218, 222), "shade": 165},
          "light": {"bg": (243, 244, 240), "fg": (22, 24, 28), "accent": (120, 160, 0), "sub": (60, 64, 70), "shade": 0}}


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    out, line = [], ""
    for w in text.split():
        t = (line + " " + w).strip()
        if d.textlength(t, font=f) <= width:
            line = t
        else:
            out.append(line); line = w
    return out + ([line] if line else [])


def compose(spec_path: str) -> Path:
    """spec JSON: {"out", "bg" (фото), "theme": dark|light, "headline", "sub", "bullets": [..], "tag", "photo_box": [x,y,w,h]}"""
    sp = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    th = THEMES[sp.get("theme", "dark")]
    W, H = 900, 1200
    img = Image.new("RGB", (W, H), th["bg"])
    if sp.get("bg"):
        ph = Image.open(sp["bg"]).convert("RGB")
        x, y, w, h = sp.get("photo_box", [0, 0, W, H])
        r = max(w / ph.width, h / ph.height)
        ph = ph.resize((int(ph.width * r), int(ph.height * r)))
        ph = ph.crop(((ph.width - w) // 2, (ph.height - h) // 2, (ph.width - w) // 2 + w, (ph.height - h) // 2 + h))
        img.paste(ph, (x, y))
        if th["shade"]:                                          # затемнение сверху под текст
            ov = Image.new("L", (W, H), 0); od = ImageDraw.Draw(ov)
            for yy in range(0, 520):
                od.line([(0, yy), (W, yy)], fill=int(th["shade"] * (1 - yy / 520)))
            img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, ov)
    d = ImageDraw.Draw(img)
    y = 56
    if sp.get("tag"):
        f = font(26, True); tw = d.textlength(sp["tag"], font=f)
        d.rounded_rectangle((48, y, 48 + tw + 32, y + 46), 10, fill=th["accent"]); d.text((64, y + 8), sp["tag"], font=f, fill=(20, 20, 20)); y += 74
    hf = font(sp.get("headline_size", 112), True)
    for ln in wrap(d, sp.get("headline", ""), hf, W - 96):
        d.text((48, y), ln, font=hf, fill=th["accent"] if sp.get("accent_headline", True) else th["fg"]); y += int(hf.size * 1.08)
    sf = font(38, True)
    for ln in wrap(d, sp.get("sub", ""), sf, W - 96):
        d.text((48, y + 6), ln, font=sf, fill=th["fg"]); y += 50
    bf = font(32)
    by = sp.get("bullets_y", H - 70 - 58 * len(sp.get("bullets", [])))
    for b in sp.get("bullets", []):
        d.rounded_rectangle((40, by - 8, W - 40, by + 46), 14, fill=(0, 0, 0) if sp.get("theme", "dark") == "dark" else (255, 255, 255))
        d.ellipse((60, by + 10, 78, by + 28), fill=th["accent"]); d.text((96, by + 2), b, font=bf, fill=th["fg"]); by += 58
    out = Path(sp.get("out") or Path(spec_path).with_suffix(".png"))
    out.parent.mkdir(parents=True, exist_ok=True); img.save(out)
    print("слайд:", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wb"); w.add_argument("--niche", type=int, required=True); w.add_argument("--top", type=int, default=12)
    w.add_argument("--skus", type=int, nargs="*")
    a = sub.add_parser("amazon"); a.add_argument("--niche", type=int, required=True); a.add_argument("--query", required=True)
    a.add_argument("--detail", type=int, default=6)
    u = sub.add_parser("audit"); u.add_argument("--niche", type=int, required=True)
    g = sub.add_parser("gen"); g.add_argument("--niche", type=int, required=True)
    g.add_argument("--mode", required=True, choices=["infographics", "photoshoot", "freeform", "remove-bg", "upscale"])
    g.add_argument("--image", required=True); g.add_argument("--brief"); g.add_argument("--count", type=int, default=4)
    g.add_argument("--aspect", default="3:4"); g.add_argument("--refs", nargs="*", default=[])
    c = sub.add_parser("compose"); c.add_argument("spec", nargs="+")
    x = ap.parse_args()
    if x.cmd == "wb":
        meta = {r["id"]: r for r in top_skus(x.niche, max(x.top, 50))}
        skus = x.skus or [r["id"] for r in top_skus(x.niche, x.top)]
        wb_collect(x.niche, skus, meta)
    elif x.cmd == "amazon":
        amazon(x.niche, x.query, x.detail)
    elif x.cmd == "audit":
        audit(x.niche)
    elif x.cmd == "compose":
        for sp in x.spec: compose(sp)
    elif x.cmd == "gen":
        gen(x.niche, x.mode, x.image, x.brief, x.count, x.aspect, x.refs)


if __name__ == "__main__":
    main()
