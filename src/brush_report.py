"""Глубокий отчёт по нише кистей (437) два раза в день → Telegram (утро 10:00, вечер 20:00).

    python -m src.brush_report morning        # выдача 3 запросов + by_period по ≈ 40 карточкам + СПП + отзывы → Telegram
    python -m src.brush_report evening        # свежая выдача (цена, реклама, остаток, места) + утренний by_period → Telegram
    python -m src.brush_report morning --dry  # без отправки

Данные Saleflow скрипт берёт сам: сначала HTTP API (SALEFLOW_TOKEN, облако), иначе локальный мост Saleflow MCP
(src.saleflow_stdio). Утро ≈ 3 + 40 запросов, вечер 3 запроса (лимит 500/день).
Что в отчёте: рынок (продажи 7 дн к прошлым 7, прогноз на 7 дней с учётом сезона, цены, доля рекламы), что изменилось
с прошлого отчёта, у кого и когда закончится товар, СПП, новые отзывы и жалобы, по каждой карточке — продажи, цена,
реклама, остаток, дней до конца остатка; и что делать нам: цена, реклама, партия (пока товара нет — тест-режим).
Конфиг — config/watch_437.yaml; состояние — data/processed/watch_437/report_*.json; отчёты — reports/monitor/watch437/.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

from src.brush_watch import BASE, CFG, ROOT, send

sys.stdout.reconfigure(encoding="utf-8")
NOW = dt.datetime.now()
YDAY = NOW.date() - dt.timedelta(days=1)
U = CFG.get("universe") or {}
WATCH = {int(k): v for k, v in (CFG.get("competitors") or {}).items()}
OUR = [int(x) for x in (CFG.get("our_skus") or [])]


# ── данные ──────────────────────────────────────────────────────────────────────────────────────────────────
class Data:
    def __init__(self) -> None:
        self.http = self.stdio = None
        try:
            from src.brush_watch_cloud import Saleflow
            self.http = Saleflow()
        except Exception:                                                 # noqa: BLE001 — API не включён → локальный мост
            from src.saleflow_stdio import Client
            self.stdio = Client()

    def tool(self, name: str, args: dict, tries: int = 3):
        import time
        for i in range(tries):                                            # мост иногда отвечает «request failed» — повторяем
            try:
                if self.http:
                    return self.http.tool(name, args)
                from src.strategy_collect import fetch
                return fetch(self.stdio, name, args)
            except Exception as e:                                        # noqa: BLE001
                if i == tries - 1 or "не куплен" in str(e) or "403" in str(e):
                    raise
                time.sleep(5 * (i + 1))
                if self.stdio:
                    from src.saleflow_stdio import Client
                    self.stdio = Client()


def raw_dir() -> Path:
    p = ROOT / "data" / "raw" / "saleflow" / "watch437" / NOW.strftime("%Y-%m-%d")
    p.mkdir(parents=True, exist_ok=True)
    return p


def search(D: Data) -> tuple[dict[int, dict], dict]:
    cur, meta = {}, {}
    errs = []
    for i, q in enumerate(CFG["queries"]):
        try:
            d = D.tool("wb_check_rates", {"query": q, "region": "Москва", "limit": 100}, tries=2)
        except Exception as e:                                            # noqa: BLE001 — один запрос упал → остальные
            errs.append(str(e)); print("выдача не получена:", q, str(e)[:80]); continue
        json.dump(d, open(raw_dir() / f"{NOW:%H%M}_q{i}.json", "w", encoding="utf-8"), ensure_ascii=False)
        rows_ = d.get("data") or []
        meta[q] = {"total": d.get("total"), "promoted_total": d.get("promoted_total"),
                   "top30_promo": sum(1 for x in rows_ if x["position_general"] <= 30 and x.get("promoted")),
                   "top30": sum(1 for x in rows_ if x["position_general"] <= 30)}
        for x in d.get("data") or []:
            s = cur.setdefault(x["id"], {"name": (x.get("name") or "")[:60], "brand": x.get("brand") or "", "pos": x["position_general"],
                                         "price": x.get("final_price"), "ads": bool(x.get("promoted")), "balance": x.get("balance"),
                                         "rating": x.get("rating"), "comments": x.get("comments"), "fbs": x.get("is_fbs"), "q": i})
            s["pos"] = min(s["pos"], x["position_general"])
    if not cur:
        raise RuntimeError(errs[0] if errs else "выдача пустая")
    meta["_failed"] = len(errs)
    if WATCH or OUR:                                                       # наши ориентиры, даже если ниже 100-го места
        d = D.tool("wb_check_rates", {"query": CFG["queries"][0], "region": "Москва", "limit": 100, "skus": list(WATCH) + OUR})
        for x in d.get("data") or []:
            cur.setdefault(x["id"], {"name": (x.get("name") or "")[:60], "brand": x.get("brand") or "", "pos": x["position_general"],
                                     "price": x.get("final_price"), "ads": bool(x.get("promoted")), "balance": x.get("balance"),
                                     "rating": x.get("rating"), "comments": x.get("comments"), "fbs": x.get("is_fbs"), "q": 0})
        meta["_not_found"] = d.get("not_found") or []
    return cur, meta


def universe(cur: dict[int, dict]) -> list[int]:
    inc = re.compile(U.get("name_include", "набор"), re.I)
    exc = re.compile(U.get("name_exclude", "$^"), re.I)
    lo, hi, top = U.get("price_min", 0), U.get("price_max", 10 ** 6), U.get("top_positions", 60)
    pick = [k for k, v in sorted(cur.items(), key=lambda kv: kv[1]["pos"])
            if v["pos"] <= top and lo <= (v["price"] or 0) <= hi and inc.search(v["name"]) and not exc.search(v["name"])]
    keep = OUR + [k for k in WATCH if k in cur] + [k for k in pick if k not in WATCH and k not in OUR]
    return list(dict.fromkeys(keep))[: U.get("max_skus", 40)]


def by_period(D: Data, skus: list[int]) -> dict[int, list[dict]]:
    out = {}
    for sku in skus:
        try:
            r = D.tool("wb_sku", {"report": "by_period", "sku": sku, "d1": str(YDAY - dt.timedelta(days=14)), "d2": str(YDAY)})
        except Exception as e:                                            # noqa: BLE001
            print("by_period", sku, str(e)[:80]); continue
        r = r.get("data") if isinstance(r, dict) else r
        out[sku] = sorted((x for x in r or [] if x.get("data")), key=lambda x: x["data"])
    json.dump({str(k): v for k, v in out.items()}, open(BASE / "report_bp.json", "w", encoding="utf-8"), ensure_ascii=False)
    return out


# ── расчёты ─────────────────────────────────────────────────────────────────────────────────────────────────
def season_factor() -> tuple[float, str]:
    """Следующие 7 дней к текущим: отношение продаж следующего месяца к текущему год назад (trends ниши)."""
    p = ROOT / "data" / "raw" / "saleflow" / "niche_deep" / f"trends_{CFG['niche']}.json"
    try:
        m = {r["label_date"][:7]: r["sales"] for r in json.load(open(p, encoding="utf-8"))["data"]}
        y = NOW.year - 1
        a, b = m.get(f"{y}-{NOW.month:02d}"), m.get(f"{y if NOW.month < 12 else y + 1}-{NOW.month % 12 + 1:02d}")
        if a and b:
            f = b / a
            return 1 + (f - 1) * 7 / 30, f"сезон: {['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'][NOW.month % 12]} к текущему месяцу год назад ×{f:.2f}"
    except Exception:                                                     # noqa: BLE001
        pass
    return 1.0, "сезон: нет данных"


def card(sku: int, s: dict | None, r: list[dict], prev: dict | None) -> dict:
    last7 = r[-7:]
    a7 = sum(x.get("sales") or 0 for x in last7)
    p7 = sum(x.get("sales") or 0 for x in r[-14:-7])
    per_day = a7 / max(1, len(last7))
    bal = (s or {}).get("balance") if s else (r[-1].get("balance") if r else None)
    days_left = round(bal / per_day, 1) if bal is not None and per_day > 0 else None
    return dict(sku=sku, name=(WATCH.get(sku) or (s or {}).get("name") or str(sku)), pos=(s or {}).get("pos"),
                price=(s or {}).get("price") or (r[-1].get("final_price") if r else None),
                price_y=r[-1].get("final_price") if r else None, price_2=r[-2].get("final_price") if len(r) > 1 else None,
                ads=(s or {}).get("ads", bool(r and r[-1].get("in_ads"))), ads_days=sum(1 for x in last7 if x.get("in_ads")),
                ad_words=r[-1].get("search_words_in_ad") if r else None,
                sales_y=r[-1].get("sales") if r else None, a7=a7, p7=p7, per_day=round(per_day, 1), balance=bal, days_left=days_left,
                comments=(s or {}).get("comments") or (r[-1].get("comments") if r else None),
                rating=r[-1].get("avg_latest_rating") if r else (s or {}).get("rating"),
                neg=r[-1].get("latest_negative_comments_percent") if r else None, in_action=bool(r and r[-1].get("in_action")),
                prev=prev or {}, our=sku in OUR)


def spp_now() -> tuple[float | None, str]:
    try:
        from src.evirma import ranges, spp_at
        r = ranges([CFG["niche"]]).get(CFG["niche"]) or {}
        buyer = CFG.get("our_price_buyer") or 1390
        return spp_at(r, buyer / 0.79, "fbs"), str(r.get("date"))
    except Exception as e:                                                # noqa: BLE001
        return None, f"Evirma не ответил ({str(e)[:40]})"


def reviews(skus: list[int], since: str) -> dict[int, dict]:
    from src.niche_monitor import feedbacks
    from src.product_deep import THEMES
    from src.wb_cdn_card import fetch
    rx = {k: re.compile(v, re.I) for k, v in {**THEMES["common"], **THEMES["brush"]}.items()}
    fb_dir = str(BASE / "fb" / NOW.strftime("%Y-%m-%d_%H"))
    out = {}
    for sku in skus:
        imt = (fetch(sku) or {}).get("imt_id")
        if not imt:
            continue
        new = [f for f in feedbacks(imt, fb_dir) if (f.get("createdDate") or "") > since]
        neg = [f for f in new if (f.get("productValuation") or 5) <= 3]
        th = collections.Counter(k for f in neg for k, x in rx.items() if x.search(" ".join(str(f.get(z) or "") for z in ("text", "cons"))))
        q = [s for s in (" ".join(str(f.get(z) or "") for z in ("text", "cons")).strip()[:120] for f in neg) if len(s) >= 10][:1]
        out[sku] = {"new": len(new), "neg": len(neg), "themes": th, "quote": q}
    return out


def econ(buyer: float, spp: float | None) -> dict:
    try:
        return _econ(buyer, spp)
    except Exception:                                                     # noqa: BLE001 — в облаке нет локальных таблиц тарифов
        return {"seller": round(buyer / (1 - (spp or 21) / 100)), "start": "—", "norm": "—", "margin": None}


def _econ(buyer: float, spp: float | None) -> dict:
    from src.screen_white import COM, econ as E
    s = (spp or 21) / 100
    seller = round(buyer / (1 - s))
    cost = CFG.get("our_cost_landed") or 345
    y = (cost - 15800 / (CFG.get("our_batch") or 300) - 1.5 * 0.25 * 92.37) / (1.446 * 13.29)   # ¥ из себестоимости
    com = COM.get(CFG["niche"]) or 26
    st_, nm = E(seller, y, 1.0, 0.25, com, 83, 15, CFG.get("our_batch") or 300), E(seller, y, 1.0, 0.25, com, 83, 8, CFG.get("our_batch") or 300)
    return {"seller": seller, "start": round(st_["net_profit"]), "norm": round(nm["net_profit"]), "margin": nm["net_margin_pct"]}


# ── отчёт ───────────────────────────────────────────────────────────────────────────────────────────────────
def fmt_card(c: dict, i: int, rv: dict | None) -> str:
    p = c["prev"]
    L = [f"{i}. {'⭐ НАШ: ' if c['our'] else ''}{c['name'][:60]}", f"   https://www.wildberries.ru/catalog/{c['sku']}/detail.aspx"]
    pos = f"{c['pos']}" if c["pos"] else "нет в первых 100"
    if p.get("pos") and c["pos"] and p["pos"] != c["pos"]:
        pos += f" (было {p['pos']} {'⬆️' if c['pos'] < p['pos'] else '⬇️'})"
    L.append(f"   Место в поиске: {pos}")
    pr = f"{c['price']} ₽"
    if p.get("price") and c["price"] and p["price"] != c["price"]:
        pr += f" (в прошлом отчёте {p['price']} ₽, {(c['price'] / p['price'] - 1) * 100:+.0f} %)"
    elif c["price_2"] and c["price_y"] and c["price_2"] != c["price_y"]:
        pr += f" (позавчера {c['price_2']} ₽ → вчера {c['price_y']} ₽)"
    L.append(f"   Цена: {pr}" + (" · акция WB" if c["in_action"] else ""))
    ad = "есть 📣" if c["ads"] else "нет"
    if p and p.get("ads") is not None and p.get("ads") != c["ads"]:
        ad = "ВКЛЮЧИЛ 📣" if c["ads"] else "ВЫКЛЮЧИЛ 📴"
    L.append(f"   Реклама: {ad} · {c['ads_days']} из 7 дней" + (f" · слов в рекламе {c['ad_words']}" if c["ad_words"] else ""))
    ch = f"{(c['a7'] / c['p7'] - 1) * 100:+.0f} %" if c["p7"] else "—"
    L.append(f"   Продажи: вчера {c['sales_y'] if c['sales_y'] is not None else '—'} шт · 7 дн {c['a7']} шт ({ch} к прошлым 7) · ≈{c['per_day']}/день")
    if c["balance"] is not None:
        dl = c["days_left"]
        end = f" → хватит на ≈{dl} дн (до {(NOW + dt.timedelta(days=dl)):%d.%m})" if dl is not None and dl < 120 else ""
        warn = " ⚠️" if dl is not None and dl <= 7 else ""
        L.append(f"   Остаток: {c['balance']} шт{end}{warn}")
    rv_s = ""
    if rv and rv["new"]:
        rv_s = f" · новых {rv['new']}" + (f", плохих {rv['neg']}" if rv["neg"] else "")
    L.append(f"   Отзывы: {c['comments']}{rv_s} · рейтинг {c['rating']}" + (f" · негатив {c['neg']} %" if c["neg"] else ""))
    return "\n".join(L)


def build(mode: str, dry: bool) -> None:
    from src.brush_watch import cmd_status
    try:
        D = Data()
        cur, meta = search(D)
    except Exception as e:                                                # noqa: BLE001
        cmd_status(argparse.Namespace(ok=False, down=str(e)[:150], dry=dry)); return
    cmd_status(argparse.Namespace(ok=True, down=None, dry=dry))
    skus = universe(cur)
    bp_f = BASE / "report_bp.json"
    if mode == "morning" or not bp_f.exists():
        bp = by_period(D, skus)
    else:
        bp = {int(k): v for k, v in json.load(open(bp_f, encoding="utf-8")).items()}
    last_f = BASE / "report_last.json"
    last = json.load(open(last_f, encoding="utf-8")) if last_f.exists() else {}
    prevc = {int(k): v for k, v in (last.get("cards") or {}).items()}
    C = [card(k, cur.get(k), bp.get(k, []), prevc.get(k)) for k in skus]
    since = last.get("ts") or (NOW - dt.timedelta(days=1)).isoformat()
    RV = reviews(skus, since[:19])
    spp, spp_date = spp_now() if mode == "morning" else (last.get("spp"), last.get("spp_date"))
    f, f_txt = season_factor()

    # рынок
    a7, p7 = sum(c["a7"] for c in C), sum(c["p7"] for c in C)
    fc = round(a7 * f)
    prices = sorted(c["price"] for c in C if c["price"])
    q0 = meta.get(CFG["queries"][0], {})
    med = st.median(prices) if prices else 0
    promo_top30, top30_n = q0.get("top30_promo", 0), q0.get("top30", 30) or 30
    soon = sorted((c for c in C if c["days_left"] is not None and c["days_left"] <= 7), key=lambda c: c["days_left"])
    growers = sorted((c for c in C if c["p7"] >= 10), key=lambda c: c["a7"] / c["p7"], reverse=True)

    # изменения с прошлого отчёта
    S = []
    for c in C:
        p = c["prev"]
        if not p:
            continue
        if p.get("price") and c["price"] and abs(c["price"] / p["price"] - 1) >= 0.03:
            S.append(f"💸 {c['name'][:40]}: цена {p['price']} → {c['price']} ₽ ({(c['price'] / p['price'] - 1) * 100:+.0f} %)")
        if p.get("ads") is not None and p["ads"] != c["ads"]:
            S.append(f"{'📣 включил' if c['ads'] else '📴 выключил'} рекламу: {c['name'][:40]}")
        if p.get("pos") and c["pos"] and abs(p["pos"] - c["pos"]) >= 10:
            S.append(f"{'⬆️' if c['pos'] < p['pos'] else '⬇️'} {c['name'][:40]}: место {p['pos']} → {c['pos']}")
        if p.get("balance") and c["balance"] is not None and c["balance"] - p["balance"] > 20:
            S.append(f"📥 {c['name'][:40]}: пополнил склад {p['balance']} → {c['balance']} шт")
    new_top = [k for k, v in cur.items() if v["pos"] <= 20 and str(k) not in (last.get("top20") or []) and last]
    for k in new_top[:5]:
        S.append(f"🆕 новый в топ-20: «{cur[k]['name'][:40]}» {cur[k]['price']} ₽ — https://www.wildberries.ru/catalog/{k}/detail.aspx")
    if mode == "morning" and last.get("spp") is not None and spp is not None and spp != last.get("spp"):
        S.append(f"💳 СПП изменилась: {last['spp']} → {spp} %")

    # рекомендации (тест-режим, пока товара нет)
    buyer = CFG.get("our_price_buyer") or 1390
    rec_price = buyer
    why = []
    if med and med > buyer * 1.1:
        rec_price = int(round(min(med * 0.95, buyer * 1.1), -1)); why.append(f"медиана цен конкурентов {med:.0f} ₽ выше нашей")
    if len(soon) >= 3:
        rec_price = int(round(rec_price * 1.05, -1)); why.append(f"у {len(soon)} конкурентов товар закончится за 7 дней")
    dumpers = [c for c in C if c["prev"].get("price") and c["price"] and c["price"] < c["prev"]["price"] * 0.9]
    if dumpers:
        why.append(f"{len(dumpers)} конкурентов резко снизили цену — не догоняем, держим цену и качество")
    e_now, e_rec = econ(buyer, spp), econ(rec_price, spp)
    ads_share = promo_top30 / top30_n
    plan_m = CFG.get("our_sales_plan_month") or 92
    plan_7 = round(plan_m / 30 * 7 * f)
    batch = CFG.get("our_batch") or 300
    R = [f"• Цена: держать {buyer} ₽" + (f" → можно {rec_price} ₽ ({'; '.join(why)})" if rec_price != buyer else (f" ({'; '.join(why)})" if why else " — рынок спокойный")),
         f"   прибыль с набора при {rec_price} ₽: {e_rec['start']} ₽ на старте / {e_rec['norm']} ₽ потом (СПП {spp} %, цена продавца {e_rec['seller']} ₽)",
         f"• Реклама: {'ОБЯЗАТЕЛЬНА с первого дня' if ads_share >= 0.6 else 'желательна'} — в топ-30 с рекламой {promo_top30} из {top30_n}; "
         f"бюджет ≈ {round(rec_price * plan_m * 0.15 / 30)} ₽/день (15 % выручки на старте)",
         f"• Остатки у нас: план {plan_7} шт/неделю → партии {batch} шт хватит на ≈{round(batch / max(1, plan_7))} недель; дозаказ при 100 шт",
         ]
    if soon:
        R.append(f"• Шанс: {', '.join(c['name'][:25].strip() for c in soon[:3])} — товар закончится за ≤7 дн, их покупатели уйдут к тем, у кого есть")
    top_theme = collections.Counter()
    for v in RV.values():
        top_theme.update(v["themes"])
    if top_theme:
        R.append(f"• В карточке закрыть жалобы конкурентов: {', '.join(k for k, _ in top_theme.most_common(3))}")

    # текст
    title = "☀️ УТРЕННИЙ" if mode == "morning" else "🌙 ВЕЧЕРНИЙ"
    head = [f"{title} ОТЧЁТ — КИСТИ ДЛЯ МАКИЯЖА (ниша 437)",
            f"{NOW:%d.%m.%Y %H:%M} · {len(C)} конкурентов · поиск WB, Москва · 🧪 тест-режим: нашего товара ещё нет", "",
            "📈 РЫНОК",
            f"• Продажи наших {len(C)} конкурентов: 7 дн {a7} шт (прошлые 7 дн {p7} шт, {((a7 / p7 - 1) * 100 if p7 else 0):+.0f} %)",
            f"• 🔮 Прогноз на следующие 7 дней: ≈{fc} шт ({f_txt})",
            f"• Цены конкурентов: медиана {med:.0f} ₽, от {prices[0] if prices else '—'} до {prices[-1] if prices else '—'} ₽ · наша плановая {buyer} ₽",
            f"• Реклама: в топ-30 {promo_top30} из {top30_n}; всего рекламных мест {q0.get('promoted_total')} из {q0.get('total')}",
            f"• 💳 СПП FBS при нашей цене: {spp} % (Evirma {spp_date})" + ("" if mode == "morning" else " — из утреннего замера")]
    if soon:
        head += ["", "📦 У КОГО СКОРО ЗАКОНЧИТСЯ ТОВАР"] + [
            (f"• {c['name'][:45].strip()}: уже нет в наличии" if not c["balance"] else
             f"• {c['name'][:45].strip()}: {c['balance']} шт ≈ {c['days_left']} дн (до {(NOW + dt.timedelta(days=c['days_left'])):%d.%m})") for c in soon[:8]]
    if growers:
        head += ["", "🚀 КТО РАСТЁТ (7 дн к прошлым 7)"] + [f"• {c['name'][:45]}: {c['p7']} → {c['a7']} шт ({(c['a7'] / c['p7'] - 1) * 100:+.0f} %), {c['price']} ₽, реклама {'да' if c['ads'] else 'нет'}" for c in growers[:5]]
    nr = sum(v["new"] for v in RV.values()); nn = sum(v["neg"] for v in RV.values())
    head += ["", "💬 НОВЫЕ ОТЗЫВЫ (с прошлого отчёта)",
             f"• Всего {nr}, плохих (≤3★) {nn}" + (f" — {', '.join(f'{k} {v}' for k, v in top_theme.most_common(3))}" if top_theme else "")]
    head += [f"   «{q}»" for v in RV.values() for q in v["quote"]][:2]
    head += ["", "🔔 ЧТО ИЗМЕНИЛОСЬ С ПРОШЛОГО ОТЧЁТА"] + (S[:15] if S else ["Первый отчёт — сравнение будет в следующем." if not last else "Существенных изменений нет."])
    head += ["", "✅ ЧТО ДЕЛАТЬ НАМ (стратегия)"] + R
    cards = [fmt_card(c, i, RV.get(c["sku"])) for i, c in enumerate(sorted(C, key=lambda c: -c["a7"]), 1)]
    nf = meta.get("_not_found") or []
    tail = [f"❔ Ориентиры не найдены в поиске (нет в первых 500): {', '.join(WATCH.get(k, str(k))[:25] for k in nf)}"] if nf else []
    text1 = "\n".join(head)
    body = "👥 ВСЕ КОНКУРЕНТЫ (по продажам за 7 дней)\n\n" + "\n\n".join(cards) + ("\n\n" + "\n".join(tail) if tail else "")
    rep = ROOT / "reports" / "monitor" / "watch437" / f"{NOW:%Y-%m-%d}_{mode}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(text1 + "\n\n" + body + "\n", encoding="utf-8")
    send(text1, dry)
    chunk = ""
    for part in body.split("\n\n"):                                       # Telegram ≤ 4096 знаков
        if len(chunk) + len(part) > 3800:
            send(chunk, dry); chunk = ""
        chunk += ("\n\n" if chunk else "") + part
    if chunk:
        send(chunk, dry)
    json.dump({"ts": NOW.isoformat(timespec="seconds"), "spp": spp, "spp_date": spp_date,
               "top20": [str(k) for k, v in cur.items() if v["pos"] <= 20],
               "cards": {str(c["sku"]): {k: c[k] for k in ("pos", "price", "ads", "balance", "a7")} for c in C}},
              open(last_f, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["morning", "evening"])
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    build(a.mode, a.dry)
