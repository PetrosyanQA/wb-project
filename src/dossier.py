"""Досье ниши: ВСЕ источники проекта в одном анализе (02.11.2026). Блок без данных не валит прогон — пишет «— недоступно (почему)».

    python -m src.wb analyze 1142 --query "петличный микрофон беспроводной" --yuan 30
    python -m src.wb analyze --top 10            # досье для 10 лучших КАНДИДАТОВ копилки + сводная таблица

Блоки: 1 паспорт (мастер-список) · 2 сегменты (копилка) · 3 типы внутри (niche_inside) · 4 структура рынка, 5 динамика,
6 сезонность (Saleflow: wb_subject price_segmentation/sellers/warehouses/geography, wb_compare, wb_analytics) · 7 живая выдача
(radar) · 8 жалобы (отчёт product_deep) · 9 тренды за рубежом (файлы Exa) · 10 ¥ (аргумент или сохранённая выдача 1688) ·
11 комиссия кабинета · 12 СПП Evirma · 13 экономика СПП 18/10/0 × ¥ × партия × ДРР · 14 Монте-Карло · 15 решение (src.decision).
10b карточки WB (габариты, ЧЗ, магнит — бесплатно). Ворота и пороги — config/project.yaml; планка считается тем же кодом.
Бюджет: ≤ 10 Saleflow за досье (guard до первого запроса); Bright Data — только при --offer (1 кредит).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import re
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
from src.project_cfg import get as P  # noqa: E402
SF_BUDGET = P("dossier.saleflow_budget", 10)
MONTH = P("data_month")                                   # «2026-07»


def month_range(m: str) -> tuple[str, str]:
    y, mm = map(int, m.split("-"))
    last = (dt.date(y + (mm == 12), mm % 12 + 1, 1) - dt.timedelta(days=1)).day
    return f"{m}-01", f"{m}-{last:02d}"


def fmt(n) -> str:
    return f"{n:,}".replace(",", " ")


def latest(pattern: str) -> Path | None:
    f = sorted(glob.glob(str(ROOT / pattern)))
    return Path(f[-1]) if f else None


def load_row(pattern: str, sid: int, key: str = "id"):
    f = latest(pattern)
    if not f:
        return None
    return next((r for r in json.load(open(f, encoding="utf-8")) if r.get(key) == sid), None)


def best_segment(sid: int, band: str | None = None) -> dict | None:
    """Сегмент копилки (прошёл отбор) — иначе самый прибыльный по оценке. Самая дорогая полоса часто — другой товар."""
    f = latest("data/processed/screen_white_*_all.json")
    if not f:
        return None
    segs = [r for r in json.load(open(f, encoding="utf-8")) if r["id"] == sid]
    if band:
        segs = [r for r in segs if r["band"] == band] or segs
    if not segs:
        return None
    return max(segs, key=lambda r: (r["month8_winter"] if r["month8_winter"] is not None else r["month8"]))


def yuan_from_1688(sid: int, kw: list[str] | None = None, offer: int | None = None) -> tuple[float | None, float | None, str]:
    """¥: явный оффер (карточка 1688, цена нужной комплектации) > офферы выдачи, отфильтрованные по ключевым словам >
    медиана всей выдачи (⚠️ шумно: в выдаче бывают соседние товары)."""
    from src.brightdata_client import detail_1688, offers_1688
    if offer:
        f = latest(f"data/raw/brightdata/*/1688d_{offer}.html")
        if not f:
            subprocess.run([sys.executable, "-m", "src.brightdata_client", "d1688", str(offer), "--name", str(sid)], cwd=ROOT,
                           capture_output=True)                         # 1 кредит Bright Data
            f = latest(f"data/raw/brightdata/*/1688d_{offer}.html")
        if f:
            d = detail_1688(f.read_text(encoding="utf-8", errors="ignore"))
            rows = (d.get("tiers") or d.get("skus") or []) if isinstance(d, dict) else []
            prices = sorted(x["price_cny"] for x in rows if isinstance(x, dict) and x.get("price_cny"))
            if prices:
                return prices[0], prices[-1], f"✅ оффер {offer} (карточка 1688, цены вариантов {prices[0]}–{prices[-1]})"
    f = latest(f"data/raw/brightdata/*/1688_{sid}*.html")
    if not f:
        return None, None, "нет выдачи 1688"
    offs = [o for o in offers_1688(f.read_text(encoding="utf-8", errors="ignore")) if o["price_cny"] > 0]
    if kw:
        offs = [o for o in offs if any(k in o["title"] for k in kw)]
    p = sorted(o["price_cny"] for o in offs)
    if len(p) < 3:
        return None, None, f"{f.name}: после фильтра {len(p)} офферов — мало"
    p50, p75 = st.median(p), p[int(len(p) * 0.75)]
    tag = f"✅ 1688, офферы с «{'/'.join(kw)}»" if kw else "⚠️ 1688, медиана ВСЕЙ выдачи (без фильтра — шумно; задайте --yuan-kw)"
    return p50, p75, f"{tag}: {len(p)} офферов, P50 {p50} / P75 {p75} ({f.parent.name}/{f.name})"


def card_facts(sid: int, band: str | None) -> dict:
    """Бесплатно из карточек WB (CDN) топ-5 сегмента: габариты, вес, ЧЗ (need_kiz), упоминание магнита/электроники."""
    from src.datastore import products
    from src.niche_v5 import card_dims
    from src.wb_cdn_card import fetch
    rows = products(sid, MONTH)[0] or []
    if band:
        lo, hi = map(int, band.split("-"))
        rows = [r for r in rows if lo <= (r.get("final_price") or 0) < hi]
    vols, kgs, kiz, magnet, electro, n = [], [], 0, 0, 0, 0
    for r in sorted(rows, key=lambda r: -(r.get("sales") or 0))[:5]:
        try:
            card = fetch(r["id"])
        except Exception:                                       # noqa: BLE001 — сеть: блок помечается, досье идёт дальше
            card = None
        if not card:
            continue
        n += 1
        d = card_dims(card)
        if d["vol_l"]:
            vols.append(d["vol_l"])
        if d["kg"]:
            kgs.append(d["kg"])
        kiz += bool(d["need_kiz"])
        electro += bool(d["electro"])
        magnet += "магнит" in json.dumps(card, ensure_ascii=False).lower()
    return {"cards": n, "vol": round(st.median(vols), 2) if vols else None, "kg": round(st.median(kgs), 2) if kgs else None,
            "kiz": kiz, "magnet": magnet, "electro": electro}


def table(rows: list, n: int = 8) -> list[str]:
    """Неизвестный формат ответа Saleflow → компактная таблица первых строк по скалярным полям."""
    rows = [r for r in rows if isinstance(r, dict)][:n]
    if not rows:
        return ["(пусто)"]
    keys = [k for k, v in rows[0].items() if isinstance(v, (int, float, str)) and k not in ("thumb", "image", "url")][:8]
    out = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    out += ["| " + " | ".join(str(r.get(k, ""))[:30] for k in keys) + " |" for r in rows]
    return out


def rows_of(res) -> list:
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        for k in ("data", "rows", "items", "result"):
            if isinstance(res.get(k), list):
                return res[k]
    return []


def saleflow_blocks(sid: int, queries: list[str]) -> tuple[dict, list[str], str | None]:
    out, used = {}, []
    try:
        from src.saleflow_stdio import Client
        c = Client()
    except Exception as e:                                      # noqa: BLE001
        return out, used, f"Saleflow не запускается: {str(e)[:100]}"
    try:
        c.guard(min(SF_BUDGET, 6 + len(queries)))
        for rep in ("price_segmentation", "sellers", "warehouses", "geography"):
            d1, d2 = month_range(MONTH)
            out[rep] = c.call("wb_subject", {"subject_id": sid, "report": rep, "d1": d1, "d2": d2})
            used.append(f"wb_subject {rep}")
        out["compare"] = c.call("wb_compare", {"scope": "subject", "value": str(sid), "d11": "2026-07-01", "d12": "2026-07-31",
                                               "d21": "2026-10-01", "d22": "2026-10-31", "limit": 100})
        used.append("wb_compare июль→октябрь")
        out["season"] = c.call("wb_analytics", {"entity": "subject", "path_value": str(sid), "report": "season_effects/annual",
                                                "period": "month"})
        used.append("wb_analytics season_effects")
        for q in queries:
            out.setdefault("radar", []).append(c.call("wb_check_rates", {"query": q, "limit": 100, "region": "Москва"}))
            used.append(f"wb_check_rates «{q}»")
        return out, used, None
    except Exception as e:                                      # noqa: BLE001 — 401, лимит, сбой: блоки помечаются
        msg = str(e)
        if "request failed" in msg:
            try:
                msg = str(c.call("saleflow_connection_status", {}, cache=False))
            except Exception as e2:                             # noqa: BLE001
                msg = str(e2)
        return out, used, msg[:200]
    finally:
        c.close()


def economics(seg: dict, buyer: float, yuan: float, sid: int, facts: dict | None = None) -> tuple[list[str], dict]:
    from src import screen_white as sw
    com = sw.COM.get(sid)
    if not com:
        return ["— нет комиссии кабинета по предмету (обновить дамп: python -m src.wb_seller commission)"], {}
    facts = facts or {}
    vol_src = "карточки WB" if facts.get("vol") else ("выгрузка Saleflow" if seg and not seg.get("vol_assumed", True) else "допущение")
    vol = facts.get("vol") or (seg or {}).get("vol") or 2.0
    kg = facts.get("kg") or (seg or {}).get("kg") or max(0.1, 0.22 * vol)
    buyout = (seg or {}).get("buyout") or 80
    ev_seller, ev_spp = sw.seller_for(sid, buyer)
    L = [f"Цена покупателя {round(buyer)} ₽; комиссия FBS {com} % (WB API); выкуп {buyout} %; объём {vol} л, вес {kg} кг ({vol_src}); "
         f"СПП Evirma {ev_spp if ev_spp is not None else '—'} %.", "",
         "| СПП | ¥ | Партия | ДРР 8 %: прибыль/шт (маржа) | ДРР 15 %: прибыль/шт (маржа) |", "|---:|---:|---:|---|---|"]
    res, marg = {}, {}
    for spp in (18, 10, 0):
        seller = round(buyer / (1 - spp / 100))
        for y in sorted({round(yuan, 1), round(yuan * P("dossier.yuan_markup_check", 1.3), 1)}):
            for batch in (100, 300):
                e8, e15 = (sw.econ(seller, y, vol, kg, com, buyout, d, batch) for d in (8, 15))
                res[(spp, y, batch)] = e15["net_profit"]
                marg[(spp, y, batch)] = e15["net_margin_pct"]
                L.append(f"| {spp} % | {y} | {batch} | {e8['net_profit']:.0f} ₽ ({e8['net_margin_pct']} %) | "
                         f"{e15['net_profit']:.0f} ₽ ({e15['net_margin_pct']} %) |")
    L.append(f"Потолок ¥ (маржа ≥ 18 %, ДРР 8 %, партия 300): {sw.max_yuan(round(buyer / 0.82), vol, kg, com, buyout, 300)}")
    y = round(yuan, 1)
    return L, {"com": com, "vol": vol, "kg": kg, "buyout": buyout, "profit15_spp18_300": res.get((18, y, 300)),
               "margin_spp18": marg.get((18, y, 300)), "margin_spp0": marg.get((0, y, 300))}


def benchmark() -> dict:
    """Планка — текущий товар, посчитанный тем же кодом и теми же данными (config/project.yaml → benchmark)."""
    b = P("benchmark")
    f = latest("data/processed/screen_white_*_all.json")
    segs = [r for r in json.load(open(f, encoding="utf-8")) if r["id"] == b["sid"]] if f else []
    seg = next((r for r in segs if int(r["band"].split("-")[0]) <= b["price"] < int(r["band"].split("-")[1])), None)
    if seg is None:
        seg = best_segment(b["sid"], (load_row("data/processed/niche_pool_*.json", b["sid"]) or {}).get("band"))
    _, e = economics(seg, b["price"], b["yuan"], b["sid"])
    month = round((e.get("profit15_spp18_300") or 0) * ((seg or {}).get("new_p50") or 0))
    return {"name": b["name"], "month": month, "p50": (seg or {}).get("new_p50"), "profit": e.get("profit15_spp18_300")}


def build(sid: int, queries: list[str], yuan_arg: float | None, price_arg: float | None, yuan_kw: list[str] | None = None,
          offer: int | None = None, abroad: str | None = None, complaints: bool = False) -> dict:
    today = dt.date.today()
    master, pool = load_row("data/processed/niche_master_*.json", sid), load_row("data/processed/niche_pool_*.json", sid)
    seg = best_segment(sid, (pool or {}).get("band"))
    subj = (master or {}).get("subject") or (seg or {}).get("subj") or str(sid)
    if not queries:
        queries = [subj.lower()]
    src_ok, src_no = [], []
    L = [f"# Досье ниши {sid} «{subj}» — {today}", "",
         "Все источники проекта в одном анализе. ✅ — данные, ⚠️ — оценка/допущение, — — недоступно. "
         f"Продажи Saleflow — {MONTH} (данным > 30 дней — вывод предварительный). Пороги — config/project.yaml.", ""]
    # 1–2
    L += ["## 1. Паспорт ниши (мастер-список, все ниши WB)", ""]
    if master:
        L += [f"✅ Статус **{master['status']}**; выручка {master['rev_mln']} млн ₽/мес; продавцов с продажами {master['sellers']}; "
              f"продаж на продавца {master['per_seller']}; медиана {master['price']} ₽; выкуп {master['buyout']} %; документы {master['docs']} "
              f"{master.get('flags') or ''}. Причины: {'; '.join(master['why']) or 'все пороги'}.", ""]
        src_ok.append("мастер-список (снимок всех ниш)")
    else:
        L += ["— нет в мастер-списке (python -m src.wb screen)", ""]
    L += ["## 2. Лучший ценовой сегмент (копилка)", ""]
    if seg:
        L += [f"✅ {seg['band']} ₽: медиана {seg['buyer']} ₽, карточек {seg['cards']}, продаж {seg['sales']}/мес, новичков {seg['new']} "
              f"(P25/P50 {seg['new_p25']}/{seg['new_p50']} шт/мес), топ-1 {seg['top1']} %, топ-6 {seg['top6']} %, продавцов {seg['sellers']}; "
              f"статус копилки: {(pool or {}).get('status', '—')}.", ""]
        src_ok.append("сегменты (товары за июль)")
    else:
        L += ["— товары ниши не скачаны (очередь: python -m src.wb collect)", ""]
    # 3
    L += ["## 3. Типы товара внутри ниши", ""]
    f3 = latest(f"reports/niche_inside_{sid}_*.md")
    if seg and not f3:
        subprocess.run([sys.executable, "-m", "src.niche_inside", str(sid), "--month", MONTH], cwd=ROOT, capture_output=True)
        f3 = latest(f"reports/niche_inside_{sid}_*.md")
    if f3:
        rows = [x for x in f3.read_text(encoding="utf-8").splitlines() if x.startswith("| ") and "✅" in x][:6]
        L += [f"✅ из `{f3.name}` (типы без монополии):"] + (rows or ["(нет типов со статусом ✅)"]) + [""]
        src_ok.append("niche_inside")
    else:
        L += ["— нет данных", ""]
    # 4–7 Saleflow
    sf, used, err = saleflow_blocks(sid, queries)
    L += ["## 4. Структура рынка (Saleflow)", ""]
    for rep, title in (("price_segmentation", "Сегменты цены"), ("sellers", "Продавцы"), ("warehouses", "Склады"), ("geography", "Регионы")):
        if rep in sf:
            L += [f"**{title}** ✅"] + table(rows_of(sf[rep])) + [""]
    if not any(k in sf for k in ("price_segmentation", "sellers")):
        L += [f"— недоступно: {err or 'нет ответа'}", ""]
    L += ["## 5. Динамика июль → октябрь (wb_compare)", ""]
    L += (["✅"] + table(rows_of(sf["compare"]), 10) + [""]) if "compare" in sf else [f"— недоступно: {err or 'нет ответа'}", ""]
    L += ["## 6. Сезонность (wb_analytics)", ""]
    L += (["✅"] + table(rows_of(sf["season"]), 12) + [""]) if "season" in sf else [f"— недоступно: {err or 'нет ответа'}", ""]
    L += ["## 7. Живая выдача и уникальность (radar)", ""]
    radar_verdicts = []
    if sf.get("radar"):
        from src.radar import render, summarize
        for resp in sf["radar"]:
            s = summarize(resp)
            radar_verdicts.append(s["verdict"])
            L += [render(s), ""]
    else:
        L += [f"— недоступно: {err or 'нет ответа'}", ""]
    (src_ok if used else src_no).append(f"Saleflow: {', '.join(used)}" if used else f"Saleflow ({err})")
    # 8 жалобы
    L += ["## 8. Жалобы покупателей (product_deep, отзывы WB)", ""]
    if complaints and seg:
        lo, hi = seg["band"].split("-")
        subprocess.run([sys.executable, "-m", "src.product_deep", str(sid), "--price", lo, hi], cwd=ROOT, capture_output=True)
    f8 = latest(f"reports/product_deep_{sid}_*.md")
    if f8:
        rows = [x for x in f8.read_text(encoding="utf-8").splitlines() if x.startswith("| ") and "%" in x and "кандидат" in x][:5]
        L += [f"✅ `{f8.name}`:"] + (rows or ["(нет темы ≥ 12 %)"]) + [""]
        src_ok.append("жалобы product_deep")
    else:
        L += [f"— отчёта нет: python -m src.product_deep {sid} --include \"<слова типа>\" (бесплатно, 5–15 мин)", ""]
        src_no.append("жалобы (запустить product_deep)")
    # 9 Exa
    L += ["## 9. Спрос за рубежом (Exa / Amazon / TikTok)", ""]
    fa = latest(f"data/raw/exa/*/abroad_{sid}.md")
    if abroad:
        hits = [abroad]
    elif fa:
        hits = [x.strip()[:200] for x in fa.read_text(encoding="utf-8").splitlines() if re.search(r"[0-9]", x)][:6]
    else:
        hits = []
    if hits:
        L += [f"✅ {'аргумент --abroad' if abroad else fa.parent.name + '/' + fa.name}:"] + [f"- {h}" for h in hits] + [""]
        src_ok.append("спрос за рубежом (Exa)")
    else:
        L += [f"— нет файла data/raw/exa/<дата>/abroad_{sid}.md с цифрами — /analiz шаг 1 (Exa) должен его записать", ""]
        src_no.append("спрос за рубежом (запустить /analiz шаг 1 — Exa)")
    # 10 ¥
    L += ["## 10. Цена в Китае", ""]
    y50, y75, ysrc = yuan_from_1688(sid, yuan_kw, offer)
    buyer = price_arg or (seg or {}).get("buyer") or (master or {}).get("price") or 0
    if yuan_arg:
        yuan, ytag = yuan_arg, "✅ задано (КП/1688)"
    elif y50:
        yuan, ytag = y50, ysrc
    else:
        pct = P("pool.china_pct")
        yuan, ytag = round(buyer * pct / 100 / 13.29, 1), f"⚠️ оценка ¥ = {pct} % цены ({ysrc}; поиск: python -m src.brightdata_client s1688 …, 1 кредит)"
    L += [f"{ytag}; в расчёте ¥ {yuan}.", ""]
    # 11–14
    L += ["## 10b. Карточки WB: габариты, ЧЗ, магнит (бесплатно, CDN)", ""]
    facts = card_facts(sid, (seg or {}).get("band")) if seg else {}
    if facts.get("cards"):
        L += [f"✅ по {facts['cards']} карточкам топа сегмента: объём {facts['vol'] or '—'} л, вес {facts['kg'] or '—'} кг; "
              f"ЧЗ (need_kiz) у {facts['kiz']}; электроника у {facts['electro']}; упоминание магнита у {facts['magnet']}.", ""]
        src_ok.append("карточки WB (CDN)")
    else:
        L += ["— карточки не получены (объём — из выгрузки или допущение)", ""]
    L += ["## 11–13. Комиссия кабинета, СПП Evirma, экономика (СПП 18 / 10 / 0 %, ¥ и ¥ × 1,3, партия 100 / 300)", ""]
    econ_lines, econ = economics(seg, buyer, yuan, sid, facts) if buyer else (["— нет цены"], {})
    L += econ_lines + [""]
    L += ["## 14. Риск (Монте-Карло, 10 000 сценариев, партия 300)", ""]
    mc = None
    if econ:
        from src.monte_carlo import simulate
        from src.screen_white import seller_for
        _, spp_ev = seller_for(sid, buyer)
        mc = simulate(buyer, spp_ev if spp_ev is not None else 18, yuan, econ["kg"], econ["vol"], econ["com"], econ["buyout"], batch=300)
        L += [f"✅ риск убытка {mc['loss_pct']} %; прибыль/шт P10/P50/P90 {mc['p10']}/{mc['p50']}/{mc['p90']} ₽; маржа P50 {mc['m50']} %.", ""]
    # 15 решение
    p50 = (seg or {}).get("new_p50") or 0
    month = round((econ.get("profit15_spp18_300") or 0) * p50) if econ else 0
    from src.decision import decide
    text = " ".join(str(x) for x in (subj, (master or {}).get("flags"), " ".join(queries))).lower()
    legal_fail = any(b in text for b in P("banned_words")) or bool(facts.get("cards") and facts.get("magnet", 0) >= max(2, facts["cards"] // 2))
    legal_note = ("магнит в нише/карточках — запрет пользователя" if legal_fail else
                  f"оформить: {(master or {}).get('docs') or '—'} {(master or {}).get('flags') or ''}"
                  + (f"; ЧЗ у {facts['kiz']} из {facts['cards']} карточек" if facts.get("kiz") else ""))
    econ_ok = bool(econ and mc and mc["loss_pct"] <= P("dossier.loss_max")
                   and (econ.get("margin_spp18") if econ.get("margin_spp18") is not None else -99) >= P("dossier.margin_spp18_min")
                   and (econ.get("margin_spp0") if econ.get("margin_spp0") is not None else -99) > P("dossier.margin_spp0_min"))
    uniq = "SUPPORTED" if "UNIQUE" in radar_verdicts else ("REJECT" if radar_verdicts and all(v == "CROWDED" for v in radar_verdicts) else "UNKNOWN")
    gates = {"external_demand": {"status": "PASS" if hits else "UNKNOWN"},
             "wb_demand": {"status": "PASS" if p50 >= P("pool.new_p50_min") else "UNKNOWN"},
             "uniqueness": {"status": uniq}, "supplier": {"status": "ESTIMATE"},
             "economics": {"status": "ESTIMATE" if econ_ok else ("FAIL" if mc else "UNKNOWN")},
             "legal": {"status": "FAIL" if legal_fail else "PASS"}, "sample": {"status": "UNKNOWN"}, "test_sales": {"status": "UNKNOWN"}}
    d = decide({"current_product": subj, "current_niche": sid, "mode": "DISCOVERY", "gates": gates})
    bench = benchmark()
    m18 = econ.get("margin_spp18") if econ else "—"
    m0 = econ.get("margin_spp0") if econ else "—"
    L += ["## 15. Решение", "",
          f"**{d['decision']}** (уверенность {d['confidence']}); блокирует: {', '.join(d['blocked_by']) or '—'}; дальше: {d['next_action']}.",
          "Ворота: " + "; ".join(f"{k} {v['status']}" for k, v in gates.items()) + f". Документы: {legal_note}.",
          f"Экономика: маржа при СПП 18 % {m18} %, при СПП 0 % {m0} % (порог {P('dossier.margin_spp18_min')} / > {P('dossier.margin_spp0_min')}), "
          f"риск {(mc or {}).get('loss_pct', '—')} % (порог {P('dossier.loss_max')}).",
          f"Прибыль новичка ≈ {fmt(month)} ₽/мес (прибыль/шт при СПП 18 %, ДРР 15 %, партия 300 × P50 новичка {p50}) "
          f"против планки {bench['name']} ≈ {fmt(bench['month'])} ₽/мес (тот же расчёт) — [оценка].", "",
          "## Источники", "", "Использовано: " + "; ".join(src_ok), "", "Недоступно / не запущено: " + ("; ".join(src_no) or "—"), "",
          "Следующий шаг: " + ("новый токен Saleflow → повторить досье (блоки 4–7)" if err else d["next_action"])]
    out = {"sid": sid, "subject": subj, "decision": d["decision"], "month_est": month, "bench_month": bench["month"],
           "legal": gates["legal"]["status"], "margin_spp18": econ.get("margin_spp18") if econ else None, "loss_pct": (mc or {}).get("loss_pct"),
           "uniqueness": uniq, "yuan": yuan, "yuan_src": "оценка" if ytag.startswith("⚠️ оценка") else ("1688 без фильтра" if ytag.startswith("⚠️") else "1688/КП"), "buyer": buyer, "docs": (master or {}).get("docs"), "saleflow_error": err,
           "sources_ok": src_ok, "sources_missing": src_no}
    (ROOT / f"reports/dossier_{sid}_{today}.md").write_text("\n".join(L), encoding="utf-8")
    json.dump(out, open(ROOT / f"data/processed/dossier_{sid}_{today}.json", "w", encoding="utf-8"), ensure_ascii=False)
    return out


def batch(top: int) -> None:
    f = latest("data/processed/niche_pool_*.json")
    cands = [p for p in json.load(open(f, encoding="utf-8")) if p["status"] == "КАНДИДАТ"][:top] if f else []
    print(f"досье для {len(cands)} кандидатов (≤ {SF_BUDGET * len(cands)} запросов Saleflow)")
    res = [build(p["id"], [], None, None) for p in cands]
    today = dt.date.today()
    L = [f"# Сводка досье — {today}", "", "| id | Ниша | Решение | Прибыль/мес (оценка) | Риск убытка | ¥ (источник) | Уникальность | Документы | Saleflow |",
         "|---:|---|---|---:|---:|---|---|---|---|"]
    for r in sorted(res, key=lambda x: -x["month_est"]):
        L.append(f"| {r['sid']} | {r['subject']} | {r['decision']} | {fmt(r['month_est'])} ₽ | {r['loss_pct'] if r['loss_pct'] is not None else '—'} % | "
                 f"{r['yuan']} ({r['yuan_src']}) | {r['uniqueness']} | {r['docs'] or '—'} | {'✅' if not r['saleflow_error'] else '— ' + r['saleflow_error'][:40]} |")
    bench = benchmark()
    L += ["", "Где ¥ — «оценка», прибыль и риск завышены (особенно электроника): сначала цена на 1688 (Bright Data, 1 кредит).",
          f"Планка: {bench['name']} ≈ {fmt(bench['month'])} ₽/мес (тот же расчёт).", "", "Следующий шаг: по лучшим — /analiz (Exa, жалобы, КП)."]
    (ROOT / f"reports/dossier_summary_{today}.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
