"""Бот-команды: отчёт предлагает действие кнопками → пользователь жмёт «Да» → действие выполняется в WB.

    python -m src.bot_actions poll          # забрать нажатия и команды из Telegram и выполнить (каждые 5–15 мин)
    python -m src.bot_actions poll --dry    # показать, что было бы сделано

Кнопки (callback_data, без состояния — работает и в облаке):
  price:<nmID>:<цена для покупателя>   — поставить цену (nmID 0 = тест-режим, товара ещё нет)
  ads:<nmID>:<₽ в день>                — включить рекламу (пока только подтверждение и запись; кампания — вручную)
  no:<любое>                           — отказ, просто отмечаем
Команды текстом: /status — что бот умеет и в каком режиме; /price <₽> — предложить новую цену с кнопкой подтверждения.

Безопасность: принимаются ТОЛЬКО нажатия из нашего чата (TELEGRAM_CHAT_ID / config/notify.yaml); реальное изменение
цены — только если в config/watch_437.yaml actions_enabled: true, артикул есть в our_skus и есть WB-токен с правом
«Цены и скидки». Иначе — тест: бот отвечает, что сделал бы. Все решения пишутся в data/processed/watch_437/actions.csv.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys

from src.brush_watch import BASE, CFG
from src.tg import api, creds, h, send

sys.stdout.reconfigure(encoding="utf-8")
OUR = {int(x) for x in (CFG.get("our_skus") or [])}
ENABLED = bool(CFG.get("actions_enabled"))
SPP_F = BASE / "spp.json"


def log(row: list) -> None:
    with open(BASE / "actions.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([dt.datetime.now().isoformat(timespec="seconds")] + row)


def set_price(nm: int, buyer: int) -> str:
    """Цена для покупателя → цена продавца через текущую СПП → цена до скидки при нашей скидке в кабинете."""
    from src.wb_seller import WBSellerClient
    spp = None
    try:
        spp = json.load(open(SPP_F, encoding="utf-8")).get("spp")
    except Exception:                                                     # noqa: BLE001
        pass
    seller = round(buyer / (1 - (spp or 21) / 100))
    c = WBSellerClient()
    goods = c.request("GET", "discounts", "/api/v2/list/goods/filter", params={"limit": 10, "filterNmID": nm})
    lst = ((goods or {}).get("data") or {}).get("listGoods") or []
    disc = (lst[0].get("discount") if lst else 0) or 0
    price = round(seller / (1 - disc / 100))
    c.request("POST", "discounts", "/api/v2/upload/task", json={"data": [{"nmID": nm, "price": price, "discount": disc}]})
    return f"цена до скидки {price} ₽, скидка {disc} % → цена продавца {seller} ₽ → покупатель ≈ {buyer} ₽ (СПП {spp} %)"


def handle_callback(q: dict, dry: bool) -> None:
    data = q.get("data") or ""
    kind, nm, val = (data.split(":") + ["", "", ""])[:3]
    nm = int(nm or 0)
    user_msg = q.get("message") or {}
    if kind == "no":
        reply, row = "❌ Понял, ничего не меняем.", ["отказ", data]
    elif kind == "price":
        if nm and nm in OUR and ENABLED:
            try:
                res = "🧪 (dry) " if dry else ""
                res += set_price(nm, int(val)) if not dry else f"поставил бы {val} ₽"
                reply, row = f"✅ Цена изменена: арт. {nm} → {h(res)}", ["цена", nm, val, "выполнено"]
            except Exception as e:                                        # noqa: BLE001
                reply, row = f"⚠️ Не получилось изменить цену: {h(str(e)[:200])}", ["цена", nm, val, "ошибка"]
        else:
            why = "товара ещё нет" if not nm else ("артикул не наш" if nm not in OUR else "действия выключены (actions_enabled: false)")
            reply, row = f"🧪 Тест: поставил бы цену <b>{h(val)} ₽</b> — сейчас не меняю ({why}).", ["цена", nm, val, "тест"]
    elif kind == "ads":
        reply = (f"📣 Принято: реклама ≈ {h(val)} ₽/день. Пока запускаю вручную — автоматический запуск кампаний добавим, "
                 f"когда будет товар и токен «Продвижение».")
        row = ["реклама", nm, val, "принято"]
    else:
        reply, row = "Не понял кнопку.", ["?", data]
    print(reply)
    log(row)
    if not dry:
        api("answerCallbackQuery", callback_query_id=q["id"], text="Принято")
        if user_msg.get("message_id"):                                   # убрать кнопки с исходного сообщения
            api("editMessageReplyMarkup", chat_id=user_msg["chat"]["id"], message_id=user_msg["message_id"], reply_markup={"inline_keyboard": []})
        send(reply)


def handle_text(m: dict, dry: bool) -> None:
    txt = (m.get("text") or "").strip()
    if txt.startswith("/status"):
        mode = "РАБОТАЕТ (меняю цены по кнопке)" if ENABLED and OUR else "ТЕСТ (товара ещё нет — только показываю, что сделал бы)"
        msg = (f"<b>🤖 Бот кистей 437</b>\nРежим: <b>{mode}</b>\nНаши артикулы: {', '.join(map(str, OUR)) or 'нет'}\n"
               f"Отчёты: 10:00 и 20:00. Команды: /status, /price 1490")
    elif txt.startswith("/price"):
        try:
            val = int("".join(ch for ch in txt.split(maxsplit=1)[1] if ch.isdigit()))
        except Exception:                                                 # noqa: BLE001
            val = None
        if not val:
            msg = "Напишите так: /price 1490"
        else:
            nm = next(iter(OUR), 0)
            if not dry:
                send(f"Поставить цену <b>{val} ₽</b> для покупателя" + (f" на арт. {nm}?" if nm else " (тест — товара ещё нет)?"),
                     buttons=[[{"text": f"✅ Да, {val} ₽", "callback_data": f"price:{nm}:{val}"}, {"text": "❌ Нет", "callback_data": "no:price"}]])
            return
    else:
        return
    print(msg)
    if not dry:
        send(msg)


def poll(dry: bool) -> None:
    _, chat = creds()
    off_f = BASE / "bot_offset.json"
    off = json.load(open(off_f, encoding="utf-8")).get("offset", 0) if off_f.exists() else 0
    res = api("getUpdates", offset=off, timeout=0, allowed_updates=["callback_query", "message"]) or {}
    ups = res.get("result") or []
    for u in ups:
        off = max(off, u["update_id"] + 1)
        q, m = u.get("callback_query"), u.get("message")
        src_chat = str(((q or {}).get("message") or {}).get("chat", {}).get("id") or (m or {}).get("chat", {}).get("id") or "")
        if src_chat != str(chat):                                          # чужие чаты игнорируем
            continue
        if q:
            handle_callback(q, dry)
        elif m:
            handle_text(m, dry)
    if not dry:
        json.dump({"offset": off}, open(off_f, "w", encoding="utf-8"))
    print(f"обработано обновлений: {len(ups)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["poll"])
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    poll(a.dry)
