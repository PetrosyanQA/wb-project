"""Карточка 249 «Эспандеры» (3 артикула в склейке) → WB Content/Prices/Marketplace API.

    python -m src.wb_card payload                 # показать JSON карточки, 0 запросов
    python -m src.wb_card sandbox                 # весь цикл в песочнице (WB_TOKEN_TEST): баркоды → карточка → цены → склад/остатки
    python -m src.wb_card sandbox --step status   # только проверить карточки/ошибки в песочнице
    python -m src.wb_card prod ...                # реальный кабинет — ТОЛЬКО после явного «да» пользователя (токен с правом записи)

Значения характеристик — reports/product_spec_249_2026-10-18.md, card_content_249_2026-10-18.md, forwarder_spec_249_2026-10-18.md.
Вес/габариты упаковки — [допущение] до образца. Ответы API пишутся в data/raw/wb_sandbox/ (или data/raw/wb_prod/).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from src.wb_seller import load_env, token_bits

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
SUBJECT = 249
TITLE = "Резинка для подтягивания на турник"
DESCRIPTION = (
    "Резинка для подтягивания на турник из ТПЭ (термопластичный эластомер, без латекса и без запаха) — помогает сделать "
    "первые подтягивания и увеличить количество повторов. Петля длиной 208 см, толщина 4,5 мм. Каждую партию проверяем "
    "растяжением в 3 раза и 100 циклами, отдельно — место соединения кольца. Нагрузка указана честно: усилие при "
    "растяжении на 50 см и на 150 см. Подходит для подтягиваний "
    "и отжиманий с поддержкой, растяжки, кроссфита, тренировок дома, на улице и в зале, реабилитации. Как выбрать: если вы "
    "не подтягиваетесь ни разу — берите резинку, которая снимает 30–40 % вашего веса; когда получится 8 повторов — переходите "
    "на уровень ниже. Красная 13 мм — 6–16 кг, чёрная 22 мм — 11–29 кг, фиолетовая 32 мм — 15–39 кг. В комплекте мешок для "
    "хранения и карточка с QR-кодом — программа подтягиваний на 8 недель с видео. Храните вдали от солнца и острых предметов, "
    "перед тренировкой проверяйте целостность резинки. Резинка для фитнеса, эспандер ленточный, жгут для тренировок."
)
# (vendorCode, цвет, ширина см, нагрузка кг, кол-во, вес г, упаковка Д×Ш×В см ≤ 1 л, комплектация, цена ₽) — цены и габариты по аудиту 2026-10-22
VARIANTS = [
    ("RP-22-BLK", "черный", 2.2, 29, 1, 230, (16, 16, 3), ["резинка — 1 шт.", "мешок для хранения — 1 шт.", "карточка с программой тренировок — 1 шт."], 1100),
    ("RP-32-VIO", "фиолетовый", 3.2, 39, 1, 330, (16, 15, 4), ["резинка — 1 шт.", "мешок для хранения — 1 шт.", "карточка с программой тренировок — 1 шт."], 1250),
    ("RP-1322-SET", "красный", 2.2, 29, 2, 380, (16, 15, 4), ["резинка красная 13 мм — 1 шт.", "резинка черная 22 мм — 1 шт.", "мешок для хранения — 1 шт.", "карточка с программой тренировок — 1 шт."], 1290),
]
HOSTS = {"sandbox": {"content": "content-api-sandbox", "prices": "discounts-prices-api-sandbox", "mp": "marketplace-api-sandbox"},
         "prod": {"content": "content-api", "prices": "discounts-prices-api", "mp": "marketplace-api"}}


def build(barcodes: list[str]) -> list[dict]:
    variants = []
    for (vc, color, width, load, qty, weight, (L, W, H), kit, _), bc in zip(VARIANTS, barcodes):
        ch = [
            {"id": 640, "value": ["фитнес", "кроссфит", "подтягивания"]},
            {"id": 15679, "value": qty},
            {"id": 15988, "value": ["для подтягиваний", "для растяжки", "для фитнеса"]},
            {"id": 15994, "value": ["ленточный"]},
            {"id": 17596, "value": ["термопластичный эластомер (ТПЭ)"]},
            {"id": 90661, "value": load},
            {"id": 90673, "value": width},
            {"id": 90675, "value": 208},
            {"id": 378533, "value": kit},
            {"id": 7594054, "value": 4.5},
            {"id": 14177449, "value": [color] if qty == 1 else ["красный", "черный"]},
            {"id": 14177451, "value": ["Китай"]},
        ]
        variants.append({"vendorCode": vc, "title": TITLE, "description": DESCRIPTION,
                         "dimensions": {"length": L, "width": W, "height": H, "weightBrutto": round(weight / 1000, 3)},
                         "characteristics": ch, "sizes": [{"skus": [bc]}]})
    return [{"subjectID": SUBJECT, "variants": variants}]


class API:
    def __init__(self, mode: str):
        load_env()
        key = "WB_TOKEN_TEST" if mode == "sandbox" else os.environ.get("WB_CARD_TOKEN_VAR", "WB_TOKEN_CARDS")
        tok = (os.environ.get(key) or "").strip()
        if not tok:
            raise SystemExit(f"нет {key} в .env")
        info = token_bits(tok)
        if mode == "prod" and (info["sandbox"] or info["readonly"]):
            raise SystemExit(f"{key}: для prod нужен Personal-токен с правом записи")
        self.h, self.mode = {"Authorization": tok, "Content-Type": "application/json"}, mode
        self.raw = ROOT / "data" / "raw" / ("wb_sandbox" if mode == "sandbox" else "wb_prod")
        self.raw.mkdir(parents=True, exist_ok=True)

    def call(self, method: str, host: str, path: str, body=None, save: str | None = None):
        url = f"https://{HOSTS[self.mode][host]}.wildberries.ru{path}"
        for _ in range(4):
            r = requests.request(method, url, headers=self.h, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None, timeout=60)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("X-Ratelimit-Retry", 2)) + 0.5); continue
            break
        time.sleep(1.1)                                         # песочница: ≤ 1 запрос/сек
        try:
            data = r.json()
        except ValueError:
            data = {"_text": r.text[:500]}
        if save:
            json.dump({"status": r.status_code, "data": data}, open(self.raw / save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return r.status_code, data


def cycle(api: API, step: str) -> None:
    if step in ("all", "card"):
        st, d = api.call("POST", "content", "/content/v2/barcodes", {"count": len(VARIANTS)}, "barcodes.json")
        barcodes = d.get("data") or []
        print("баркоды:", st, len(barcodes))
        if len(barcodes) < len(VARIANTS):
            raise SystemExit(f"баркоды не получены: {d}")
        cards = build(barcodes)
        json.dump(cards, open(api.raw / "card_payload.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        st, d = api.call("POST", "content", "/content/v2/cards/upload", cards, "upload.json")
        print("создание карточки:", st, d.get("errorText") or "ok", d.get("additionalErrors") or "")
        time.sleep(5)
    st, d = api.call("POST", "content", "/content/v2/cards/error/list", {}, "errors.json")
    errs = d.get("data") or []
    print("ошибки карточек:", st, len(errs) if isinstance(errs, list) else errs)
    for e in (errs if isinstance(errs, list) else [])[:10]:
        print("   ", e.get("vendorCode") or e.get("vendorCodes"), e.get("errors"))
    st, d = api.call("POST", "content", "/content/v2/get/cards/list",
                     {"settings": {"cursor": {"limit": 100}, "filter": {"withPhoto": -1}}}, "cards_list.json")
    cards = [c for c in (d.get("cards") or []) if c.get("subjectID") == SUBJECT]
    print("карточек 249:", len(cards), "| склейка imtID:", sorted({c.get("imtID") for c in cards}))
    nm = {c["vendorCode"]: c["nmID"] for c in cards}
    for c in cards:
        print("   ", c["vendorCode"], "nmID", c["nmID"], "| характеристик", len(c.get("characteristics") or []), "| баркод", c["sizes"][0]["skus"])
    if step in ("all", "price") and nm:
        body = {"data": [{"nmID": nm[v[0]], "price": v[8], "discount": 0} for v in VARIANTS if v[0] in nm]}
        st, d = api.call("POST", "prices", "/api/v2/upload/task", body, "price_task.json")
        print("цены:", st, d.get("errorText") or d.get("data"))
        time.sleep(3)
        st, d = api.call("GET", "prices", "/api/v2/list/goods/filter?limit=10", None, "prices_list.json")
        for g in ((d.get("data") or {}).get("listGoods") or []):
            print("   ", g.get("vendorCode"), g.get("nmID"), [(s.get("price"), s.get("discountedPrice")) for s in g.get("sizes", [])])
    if step in ("all", "stock") and nm:
        st, d = api.call("GET", "mp", "/api/v3/warehouses", None, "warehouses.json")
        wh = d if isinstance(d, list) else []
        print("склады продавца:", st, [(w.get("id"), w.get("name")) for w in wh][:5])
        if wh:
            qty = {"RP-22-BLK": 150, "RP-32-VIO": 100, "RP-1322-SET": 50}   # API 2026: остатки по chrtId, не по баркоду
            body = {"stocks": [{"chrtId": c["sizes"][0]["chrtID"], "amount": qty.get(c["vendorCode"], 10)} for c in cards]}
            bcs = [x["chrtId"] for x in body["stocks"]]
            st, d = api.call("PUT", "mp", f"/api/v3/stocks/{wh[0]['id']}", body, "stocks_put.json")
            print("остатки записаны:", st, d if st != 204 else "")
            st, d = api.call("POST", "mp", f"/api/v3/stocks/{wh[0]['id']}", {"chrtIds": bcs}, "stocks_get.json")
            print("остатки:", st, d)
        st, d = api.call("GET", "mp", "/api/v3/orders/new", None, "orders_new.json")
        print("новые FBS-задания:", st, len((d or {}).get("orders") or []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["payload", "sandbox", "prod"])
    ap.add_argument("--step", default="all", choices=["all", "card", "status", "price", "stock"])
    a = ap.parse_args()
    if a.mode == "payload":
        print(json.dumps(build([f"200000000000{i}" for i in range(len(VARIANTS))]), ensure_ascii=False, indent=1)); return
    cycle(API(a.mode), a.step)


if __name__ == "__main__":
    main()
