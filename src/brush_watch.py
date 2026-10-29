"""Мониторинг конкурентов по кистям (437): каждый час — живая выдача, раз в день — продажи по дням. Сообщения в Telegram.

Данные Saleflow приходят через MCP в сессии Claude (stdio-мост сломан), поэтому скрипт читает уже сохранённые JSON:

    python -m src.brush_watch status --ok | --down "<текст ошибки>"      # доступ к данным WB: сообщает только при смене
    python -m src.brush_watch hourly <check_rates_1.json> [<check_rates_2.json> …]   # каждый час
    python -m src.brush_watch daily <by_period_<sku>.json …>              # раз в день (имя файла = SKU)
    python -m src.brush_watch hourly --dry …                               # без отправки в Telegram

Каждый час (по живой выдаче WB, Москва): место в поиске, цена, реклама да/нет, остаток → продано за час (по снижению остатка),
новые карточки в топ-10. Раз в день (by_period): продажи вчера, цена вчера/позавчера, реклама, продажи 7 дней к прошлым 7.
Список SKU и пороги — config/watch_437.yaml. История — data/processed/watch_437/. Telegram — как в src.competitor_pulse.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

import os

import requests
import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config" / "watch_437.yaml").read_text(encoding="utf-8"))
BASE = Path(os.environ.get("WATCH_STATE_DIR") or ROOT / "data" / "processed" / f"watch_{CFG['niche']}")   # в облаке — cloud_state/
BASE.mkdir(parents=True, exist_ok=True)
NOW = dt.datetime.now()
WATCH = {int(k): v for k, v in (CFG.get("competitors") or {}).items()}
OUR = {int(k) for k in (CFG.get("our_skus") or [])}
TH = CFG.get("thresholds") or {}


def rows(p: str) -> list[dict]:
    d = json.load(open(p, encoding="utf-8"))
    return (d.get("data") if isinstance(d, dict) else d) or []


def telegram(text: str) -> bool:
    """В облаке — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID из секретов GitHub; на компьютере — как в src.competitor_pulse."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        from src.competitor_pulse import telegram as local
        return local(text)
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text[:4000]}, timeout=20)
        return r.ok
    except requests.RequestException:
        return False


def send(text: str, dry: bool) -> None:
    print(text)
    if not dry:
        print("Telegram:", "отправлено" if telegram(text) else "не отправлено (нет токена / chat_id)")


def name(sku: int, fallback: str = "") -> str:
    return ("⭐ НАШ: " if sku in OUR else "") + (WATCH.get(sku) or fallback or str(sku))[:60]


def cmd_status(a) -> None:
    f = BASE / "status.json"
    prev = json.load(open(f, encoding="utf-8")) if f.exists() else {"ok": None}
    ok = bool(a.ok)
    json.dump({"ok": ok, "ts": NOW.isoformat(timespec="minutes"), "error": a.down or ""}, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    if prev.get("ok") == ok:
        print("статус не изменился:", "работает" if ok else "нет доступа"); return
    if ok:
        send(f"✅ Кисти 437, {NOW:%d.%m %H:%M}: Saleflow снова отдаёт данные WB — мониторинг включён, отчёты каждый час.", a.dry)
    else:
        send(f"⛔ Кисти 437, {NOW:%d.%m %H:%M}: Saleflow не отдаёт данные WB ({(a.down or '')[:120]}). "
             "Проверьте модуль «Внешняя аналитика WB» в MPSTATS. Сообщу, когда заработает.", a.dry)


def cmd_hourly(a) -> None:
    cur: dict[int, dict] = {}
    for qi, p in enumerate(a.files):
        for x in rows(p):
            sku = x["id"]
            s = cur.setdefault(sku, {"name": (x.get("name") or "")[:40], "pos": x["position_general"], "price": x.get("final_price"),
                                     "ads": bool(x.get("promoted")), "balance": x.get("balance"), "rating": x.get("rating"),
                                     "comments": x.get("comments"), "q": qi})
            if x["position_general"] < s["pos"]:
                s.update(pos=x["position_general"], q=qi)
    if not cur:
        print("выдача пустая — пропуск"); return
    lf = BASE / "last_hour.json"
    prev = {int(k): v for k, v in json.load(open(lf, encoding="utf-8")).items()} if lf.exists() else {}
    pp, pos_th, low = TH.get("price_pct", 3), TH.get("position", 10), TH.get("low_stock", 10)
    first = not prev
    L, S, ACT = [], [], []
    gone = []
    for sku in list(WATCH) + sorted(OUR - set(WATCH)):
        b, p0 = cur.get(sku), prev.get(sku)
        if not b:
            gone.append(name(sku)); continue
        lines = [f"{len(L) + 1}. {name(sku)}", f"   https://www.wildberries.ru/catalog/{sku}/detail.aspx"]
        # место в поиске
        if p0 and p0["pos"] != b["pos"]:
            arrow = "⬆️ поднялся" if b["pos"] < p0["pos"] else "⬇️ опустился"
            lines.append(f"   Место в поиске: {b['pos']} (было {p0['pos']}, {arrow})")
            if abs(b["pos"] - p0["pos"]) >= pos_th:
                S.append(f"{arrow[:2]} {name(sku)}: место {p0['pos']} → {b['pos']}")
        else:
            lines.append(f"   Место в поиске: {b['pos']}" + ("" if first else " (без изменений)"))
        # цена
        if p0 and p0.get("price") and b.get("price") and b["price"] != p0["price"]:
            ch = (b["price"] / p0["price"] - 1) * 100
            lines.append(f"   Цена: {b['price']} ₽ (было {p0['price']} ₽, {ch:+.0f} %)")
            if abs(ch) >= pp:
                if -ch >= TH.get("price_drop_alert", 10):
                    S.append(f"⚠️ {name(sku)} снизил цену на {-ch:.0f} %: {p0['price']} → {b['price']} ₽")
                    ACT.append(f"• {name(sku)} резко снизил цену — следим, не теряем ли мы заказы; свою цену пока не трогаем")
                else:
                    S.append(f"💸 {name(sku)}: цена {p0['price']} → {b['price']} ₽ ({ch:+.0f} %)")
        else:
            lines.append(f"   Цена: {b['price']} ₽" + ("" if first else " (не менялась)"))
        # реклама
        if p0 and p0.get("ads") != b["ads"]:
            lines.append(f"   Реклама: {'включил 📣' if b['ads'] else 'выключил 📴'}")
            S.append(f"{'📣 включил' if b['ads'] else '📴 выключил'} рекламу: {name(sku)}")
        else:
            lines.append(f"   Реклама: {'есть 📣' if b['ads'] else 'нет'}")
        # остаток и продажи за час
        if b.get("balance") is not None:
            sold = (p0["balance"] - b["balance"]) if p0 and p0.get("balance") is not None else None
            tail = ""
            if sold is not None and sold > 0:
                tail = f" (−{sold} за час ≈ {sold} продаж)"
            elif sold is not None and sold < 0:
                tail = f" (+{-sold}, пришла поставка)"
            lines.append(f"   Остаток: {b['balance']} шт{tail}")
            if b["balance"] <= low and (not p0 or (p0.get("balance") or 0) > low):
                S.append(f"📦 {name(sku)}: остаток {b['balance']} шт — скоро закончится")
        # отзывы
        if b.get("comments") is not None:
            dc = (b["comments"] - p0["comments"]) if p0 and p0.get("comments") is not None else 0
            lines.append(f"   Отзывов: {b['comments']}" + (f" (+{dc} новых)" if dc > 0 else "") + (f", рейтинг {b['rating']}" if b.get("rating") else ""))
        L.append("\n".join(lines))
    short = [sku for sku in WATCH if cur.get(sku) and cur[sku].get("balance") is not None and cur[sku]["balance"] <= low]
    if len(short) >= TH.get("raise_price_min", 2):
        S.append(f"💡 у {len(short)} конкурентов заканчивается товар")
        ACT.append("• У нескольких конкурентов кончается товар — можно поднять нашу цену на 5–10 %")
    top10_prev = {k for k, v in prev.items() if v["pos"] <= 10}
    for sku, v in sorted(cur.items(), key=lambda kv: kv[1]["pos"]):
        if v["pos"] <= 10 and prev and sku not in top10_prev and sku not in WATCH:
            S.append(f"🆕 новый в топ-10: «{v['name']}» {v['price']} ₽, реклама {'да' if v['ads'] else 'нет'} — "
                     f"https://www.wildberries.ru/catalog/{sku}/detail.aspx")
    top = sorted(cur.values(), key=lambda v: v["pos"])[:10]
    avg = round(sum(v["price"] or 0 for v in top) / len(top)) if top else 0
    promo = sum(1 for v in top if v["ads"])
    with open(BASE / "hourly.csv", "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for sku, v in cur.items():
            if v["pos"] <= 30 or sku in WATCH or sku in OUR:
                w.writerow([NOW.isoformat(timespec="minutes"), sku, v["pos"], v["price"], int(v["ads"]), v["balance"], v["rating"], v["comments"]])
    json.dump({str(k): v for k, v in cur.items()}, open(lf, "w", encoding="utf-8"), ensure_ascii=False)
    our_price = CFG.get("our_price_buyer") or 1390
    head = (f"🖌 КИСТИ ДЛЯ МАКИЯЖА — отчёт за час\n{NOW:%d.%m.%Y %H:%M}, поиск WB «{CFG['queries'][0]}», Москва\n\n"
            f"📊 РЫНОК (первые 10 мест поиска)\n"
            f"• Средняя цена: {avg} ₽ (наша плановая — {our_price} ₽)\n"
            f"• С рекламой: {promo} из {len(top)} — без рекламы наверх не попасть")
    if first:
        chg = "\n\n🔔 ЧТО ИЗМЕНИЛОСЬ\nЭто первый замер — сравнение «было → стало» будет со следующего часа."
    else:
        chg = "\n\n🔔 ЧТО ИЗМЕНИЛОСЬ ЗА ЧАС\n" + ("\n".join(S[:12]) if S else "Ничего важного: цены, реклама и места почти те же.")
    act = ("\n\n✅ ЧТО ДЕЛАТЬ НАМ\n" + "\n".join(ACT)) if ACT else ""
    comp = "\n\n👥 КОНКУРЕНТЫ (наши ориентиры)\n\n" + "\n\n".join(L)
    if gone:
        comp += "\n\n❔ Не найдены в поиске (нет в первых 500 — возможно, кончился товар):\n" + "\n".join(f"• {g}" for g in gone)
    send(head + chg + act + comp, a.dry)


def cmd_daily(a) -> None:
    yday = (NOW.date() - dt.timedelta(days=1)).isoformat()
    L, tot = [], []
    for p in a.files:
        sku = int(Path(p).stem.split("_")[-1])
        r = sorted((x for x in rows(p) if x.get("data")), key=lambda x: x["data"])
        if not r:
            continue
        last, prev = r[-1], (r[-2] if len(r) > 1 else None)
        s7 = sum(x.get("sales") or 0 for x in r[-7:])
        s7p = sum(x.get("sales") or 0 for x in r[-14:-7])
        dif = f"{(s7 / s7p - 1) * 100:+.0f} %" if s7p else "—"
        pr = last.get("final_price") or last.get("price")
        pr0 = (prev or {}).get("final_price") or (prev or {}).get("price")
        pch = "=" if not pr0 or pr == pr0 else f"{pr0}→{pr} {'⬆️' if pr > pr0 else '⬇️'}"
        ads_days = sum(1 for x in r[-7:] if x.get("in_ads"))
        ch_txt = f"{(s7 / s7p - 1) * 100:+.0f} %" if s7p else "нет данных"
        pr_txt = f"{pr} ₽" + ("" if not pr0 or pr == pr0 else f" (позавчера {pr0} ₽, {'выросла ⬆️' if pr > pr0 else 'снизилась ⬇️'})")
        L.append("\n".join([
            f"{len(L) + 1}. {name(sku)}",
            f"   https://www.wildberries.ru/catalog/{sku}/detail.aspx",
            f"   Продано вчера: {last.get('sales') or 0} шт",
            f"   За 7 дней: {s7} шт (прошлые 7 дней: {s7p} шт, {ch_txt})",
            f"   Цена: {pr_txt}",
            f"   Реклама: {'есть 📣' if last.get('in_ads') else 'нет'} (была {ads_days} из 7 дней)",
            f"   Остаток: {last.get('balance')} шт, отзывов: {last.get('comments')}"]))
        tot.append((s7, s7p, sku))
        with open(BASE / "daily.csv", "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([last["data"], sku, last.get("sales"), pr, int(bool(last.get("in_ads"))), last.get("balance"), last.get("comments"), s7, s7p])
    if not L:
        print("нет данных by_period"); return
    extra = spp_line() + reviews_lines(yday) + (weekly_lines() if NOW.weekday() == 0 else [])
    a7, b7 = sum(x for x, _, _ in tot), sum(y for _, y, _ in tot)
    best = max(tot, key=lambda x: x[0])
    mkt = f"{(a7 / b7 - 1) * 100:+.0f} %" if b7 else "нет данных"
    head = (f"📊 КИСТИ ДЛЯ МАКИЯЖА — итоги дня за {yday[8:]}.{yday[5:7]}.{yday[:4]}\n\n"
            f"📈 РЫНОК (наши {len(tot)} конкурентов вместе)\n"
            f"• За 7 дней продали {a7} шт, за прошлые 7 дней — {b7} шт ({mkt})\n"
            f"• Больше всех продаёт: {name(best[2])} — {best[0]} шт за неделю")
    more = ("\n\n🔎 ДОПОЛНИТЕЛЬНО\n" + "\n".join(extra)) if extra else ""
    body = head + more + "\n\n👥 ПО КАЖДОМУ КОНКУРЕНТУ\n\n" + "\n\n".join(L)
    rep = ROOT / "reports" / "monitor" / "watch437" / f"{NOW:%Y-%m-%d}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(body + "\n", encoding="utf-8")
    send(body + "\n\n(продажи — данные Saleflow, это оценка)", a.dry)


def spp_line() -> list[str]:
    """СПП Evirma (FBS) в полосе нашей цены продавца; сравнение с прошлым днём."""
    try:
        from src.evirma import ranges, spp_at
        r = ranges([CFG["niche"]]).get(CFG["niche"]) or {}
    except Exception as e:                                                # noqa: BLE001
        return [f"💳 СПП: Evirma не ответил ({str(e)[:60]})"]
    buyer = CFG.get("our_price_buyer") or 1390
    spp = spp_at(r, buyer / 0.79, "fbs")
    f = BASE / "spp.json"
    prev = json.load(open(f, encoding="utf-8")).get("spp") if f.exists() else None
    json.dump({"spp": spp, "date": r.get("date")}, open(f, "w", encoding="utf-8"))
    ch = "" if prev is None or prev == spp else f" (было {prev} %)"
    return [f"💳 СПП FBS при цене {buyer} ₽ для покупателя: {spp} %{ch} [Evirma {r.get('date')}]"]


def reviews_lines(yday: str) -> list[str]:
    """Новые отзывы конкурентов за вчера (публичный API отзывов WB): сколько плохих и о чём — темы для нашей карточки."""
    import collections
    import re
    from src.niche_monitor import feedbacks
    from src.product_deep import THEMES
    from src.wb_cdn_card import fetch
    rx = {k: re.compile(v, re.I) for k, v in {**THEMES["common"], **THEMES["brush"]}.items()}
    fb_dir = str(BASE / "fb" / NOW.strftime("%Y-%m-%d"))                 # свежая выгрузка раз в день
    n_new = n_neg = 0
    th, quotes = collections.Counter(), []
    for sku in WATCH:
        imt = (fetch(sku) or {}).get("imt_id")
        if not imt:
            continue
        for f in feedbacks(imt, fb_dir):
            if (f.get("createdDate") or "")[:10] != yday:
                continue
            n_new += 1
            if (f.get("productValuation") or 5) <= 3:
                n_neg += 1
                txt = " ".join(str(f.get(k) or "") for k in ("text", "cons")).strip()
                hit = [k for k, x in rx.items() if x.search(txt)]
                th.update(hit)
                if hit and len(quotes) < 2 and 15 <= len(txt) <= 140:
                    quotes.append(f"   «{txt}» — {name(sku)}")
    if not n_new:
        return ["💬 Отзывы конкурентов за вчера: новых нет (или WB не отдал)"]
    top = ", ".join(f"{k} {v}" for k, v in th.most_common(3))
    return [f"💬 Отзывы конкурентов за вчера: {n_new} новых, плохих (≤3★) {n_neg}" + (f" — {top}" if top else "")] + quotes


def weekly_lines() -> list[str]:
    """Понедельник: кто вырос и кто упал за неделю (продажи 7 дн к прошлым 7 дн, из daily.csv)."""
    f = BASE / "daily.csv"
    if not f.exists():
        return []
    last = {}
    for r in csv.reader(open(f, encoding="utf-8")):
        last[int(r[1])] = (int(r[7] or 0), int(r[8] or 0))
    ch = sorted(((s7 / p7 - 1) * 100, sku) for sku, (s7, p7) in last.items() if p7)
    if not ch:
        return []
    up = ", ".join(f"{name(s)} {d:+.0f} %" for d, s in reversed(ch[-2:]))
    dn = ", ".join(f"{name(s)} {d:+.0f} %" for d, s in ch[:2])
    return ["📅 Неделя: выросли — " + up, "📅 Неделя: упали — " + dn]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--ok", action="store_true"); g.add_argument("--down")
    h = sub.add_parser("hourly"); h.add_argument("files", nargs="+")
    d = sub.add_parser("daily"); d.add_argument("files", nargs="+")
    for x in (s, h, d):
        x.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    {"status": cmd_status, "hourly": cmd_hourly, "daily": cmd_daily}[a.cmd](a)


if __name__ == "__main__":
    main()
