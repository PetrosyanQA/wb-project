"""Слежение за карточками конкурентов: главное фото, число фото, видео, название — и помогло ли изменение.

    from src.card_watch import check, effects
    ch = check(skus)            # → список изменений с прошлой проверки (+ новые главные фото для Telegram)
    ev = effects(bp)            # → оценка эффекта прошлых смен фото по by_period (продажи/день, место, видимость)

Источник — публичный CDN WB (card.json и images/big/1.webp), 0 запросов Saleflow. Главное фото сравниваем по «отпечатку»
(среднее 16×16 в оттенках серого), чтобы пересжатие той же картинки не считалось сменой.
CTR конкурентов WB не публикует (ни MPSTATS, ни Saleflow) — эффект меряем по продажам в день, среднему месту в поиске
и видимости карточки за 7 дней до и после смены. Наш CTR — из WB Seller API, когда будет товар.
Состояние — data/processed/watch_437/cards_state.json, события — photo_events.json, картинки — photos/.
"""
from __future__ import annotations

import datetime as dt
import io
import json

import requests

from src.brush_watch import BASE

UA = {"User-Agent": "Mozilla/5.0"}
STATE = BASE / "cards_state.json"
EVENTS = BASE / "photo_events.json"
PHOTOS = BASE / "photos"


def _base(sku: int) -> str | None:
    from src.wb_cdn_card import fetch
    c = fetch(sku) or {}
    n = c.get("_basket")
    return f"https://basket-{n:02d}.wbbasket.ru/vol{sku // 100000}/part{sku // 1000}/{sku}" if n else None


def _fingerprint(img: bytes) -> tuple[str, bytes]:
    from PIL import Image
    im = Image.open(io.BytesIO(img)).convert("RGB")
    g = im.convert("L").resize((16, 16))
    px = list(g.getdata())
    avg = sum(px) / len(px)
    bits = "".join("1" if p > avg else "0" for p in px)
    im.thumbnail((800, 800))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return f"{int(bits, 2):064x}", out.getvalue()


def _diff(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def snapshot(sku: int) -> dict | None:
    base = _base(sku)
    if not base:
        return None
    try:
        card = requests.get(f"{base}/info/ru/card.json", headers=UA, timeout=15).json()
        img = requests.get(f"{base}/images/big/1.webp", headers=UA, timeout=20).content
        fp, jpg = _fingerprint(img)
    except Exception:                                                     # noqa: BLE001
        return None
    media = card.get("media") or {}
    return {"fp": fp, "jpg": jpg, "photos": media.get("photo_count"), "video": bool(media.get("has_video")),
            "title": card.get("imt_name") or "", "rich": bool(card.get("has_rich"))}


def check(skus: list[int], names: dict[int, str]) -> list[dict]:
    st = json.load(open(STATE, encoding="utf-8")) if STATE.exists() else {}
    ev = json.load(open(EVENTS, encoding="utf-8")) if EVENTS.exists() else []
    PHOTOS.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    out = []
    for sku in skus:
        s = snapshot(sku)
        if not s:
            continue
        p = st.get(str(sku))
        nm = names.get(sku, str(sku))
        if p:
            if _diff(p["fp"], s["fp"]) > 40:                              # из 256 бит — заметно другая картинка
                f = PHOTOS / f"{sku}_{today}.jpg"
                f.write_bytes(s["jpg"])
                out.append({"sku": sku, "kind": "photo", "text": f"🖼 {nm}: СМЕНИЛ ГЛАВНОЕ ФОТО", "jpg": s["jpg"],
                            "old": str(PHOTOS / f"{sku}_last.jpg")})
                ev.append({"sku": sku, "date": today, "name": nm, "evaluated": False})
            if p.get("photos") != s["photos"] and s["photos"] is not None and p.get("photos") is not None:
                out.append({"sku": sku, "kind": "count", "text": f"🖼 {nm}: фото в карточке {p['photos']} → {s['photos']}"})
            if p.get("video") != s["video"]:
                out.append({"sku": sku, "kind": "video", "text": f"🎬 {nm}: {'ДОБАВИЛ видео' if s['video'] else 'убрал видео'}"})
            if p.get("title") and p["title"] != s["title"]:
                out.append({"sku": sku, "kind": "title", "text": f"✏️ {nm}: сменил название\n     было: «{p['title'][:70]}»\n     стало: «{s['title'][:70]}»"})
            if not p.get("rich") and s["rich"]:
                out.append({"sku": sku, "kind": "rich", "text": f"📄 {nm}: добавил rich-контент (расширенное описание)"})
        (PHOTOS / f"{sku}_last.jpg").write_bytes(s["jpg"])
        st[str(sku)] = {k: v for k, v in s.items() if k != "jpg"} | {"checked": today}
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(ev, open(EVENTS, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def effects(bp: dict[int, list[dict]], min_days: int = 3) -> list[str]:
    """Для смен фото старше min_days дней: продажи/день, место и видимость 7 дн до → после (из by_period)."""
    ev = json.load(open(EVENTS, encoding="utf-8")) if EVENTS.exists() else []
    out = []
    today = dt.date.today()
    for e in ev:
        if e.get("evaluated"):
            continue
        d0 = dt.date.fromisoformat(e["date"])
        if (today - d0).days < min_days:
            continue
        r = bp.get(int(e["sku"])) or []
        before = [x for x in r if d0 - dt.timedelta(days=7) <= dt.date.fromisoformat(x["data"]) < d0]
        after = [x for x in r if dt.date.fromisoformat(x["data"]) >= d0]
        if len(before) < 3 or len(after) < 3:
            continue
        avg = lambda L, k: sum((x.get(k) or 0) for x in L) / len(L)        # noqa: E731
        s0, s1 = avg(before, "sales"), avg(after, "sales")
        p0, p1 = avg(before, "search_position_avg"), avg(after, "search_position_avg")
        v0, v1 = avg(before, "search_visibility"), avg(after, "search_visibility")
        ads0, ads1 = sum(1 for x in before if x.get("in_ads")), sum(1 for x in after if x.get("in_ads"))
        ch = (s1 / s0 - 1) * 100 if s0 else 0
        verdict = "✅ фото СРАБОТАЛО" if ch >= 15 else ("❌ фото НЕ помогло" if ch <= -15 else "➖ эффекта почти нет")
        note = " (но реклама менялась — вывод неточный)" if abs(ads1 / len(after) - ads0 / len(before)) > 0.3 else ""
        out.append(f"🖼 {e['name']}: сменил фото {d0:%d.%m} → {verdict}{note}\n"
                   f"     продажи в день {s0:.1f} → {s1:.1f} ({ch:+.0f} %), место в поиске {p0:.0f} → {p1:.0f}, видимость {v0:.0f} → {v1:.0f}")
        e["evaluated"] = True
    json.dump(ev, open(EVENTS, "w", encoding="utf-8"), ensure_ascii=False)
    return out
