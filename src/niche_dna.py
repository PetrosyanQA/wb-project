"""ДНК ниши WB — конструктор товара (промт «Анализ ДНК ниши ВБ»).

Вход: 12 помесячных выгрузок Saleflow `wb_subject keywords` + `wb_subject products` (500 карточек)
в data/raw/saleflow/<run>/dna/<subject_id>/. Выход: Excel на 7 листов.

Поля Saleflow keywords: wb_count = Частота WB (месяц), count = Результаты WB (товаров в выдаче),
items_count = карточек этого предмета по запросу. Выручки/продаж по запросу в выгрузке НЕТ →
средний чек берётся из карточек предмета, сопоставленных со смыслами запроса.

    python -m src.niche_dna --subject 777 --run 2026-10-05
"""
from __future__ import annotations

import argparse
import collections
import glob
import itertools
import json
import os
import re
import statistics as st

from src.dna_dicts import DICTS, get_cfg

STOP = {"для", "в", "на", "с", "под", "и", "от", "к", "по", "из", "без", "со", "во", "а", "the", "шт", "штуки"}

MONTH_RU = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]


def tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[а-яёa-z0-9]+", s.lower()) if t not in STOP]


class Dict:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base = re.compile(cfg["base"])
        self.general = re.compile(cfg["general"])
        self.rules = [(g, m, re.compile(rx)) for g, ms in cfg["groups"].items() for m, rx in ms.items()]
        self.group_of = {m: g for g, m, _ in self.rules}

    def parse(self, text: str) -> tuple[set[str], list[str], bool]:
        """→ (смыслы, нераспознанные токены, есть базовое слово)."""
        found, unk, has_base = set(), [], False
        for t in tokens(text):
            if self.base.search(t):
                has_base = True
                continue
            hit = [m for g, m, rx in self.rules if rx.search(t)]
            if hit:
                found.update(hit[:1])
            elif not self.general.search(t) and not t.isdigit() and not re.match(r"^\d+[хx×]\d+", t):
                unk.append(t)
        # одна группа «КУДА: в авто» не должна дублироваться с «авто» внутри «автовизитка»
        return found, unk, has_base


def load(run: str, sid: int):
    d = f"data/raw/saleflow/{run}/dna/{sid}"
    months = sorted(os.path.basename(f)[9:16] for f in glob.glob(f"{d}/keywords_*.json"))
    q = collections.defaultdict(dict)
    for m in months:
        for x in json.load(open(f"{d}/keywords_{m}.json", encoding="utf-8"))["queries"]:
            q[x["word"]][m] = x
    prod_file = f"{d}/products500_2026-07.json" if os.path.exists(f"{d}/products500_2026-07.json") else f"{d}/products_2026-07.json"
    prods = json.load(open(prod_file, encoding="utf-8"))["data"]
    return months, q, prods


def season_metrics(freq12: list[float], thr_cv: float, k: float) -> dict:
    """freq12 — по календарным месяцам Янв…Дек."""
    mean = st.mean(freq12) if freq12 else 0
    if mean <= 0:
        return {"cv": 0, "type": "—", "entry": "—", "length": 0, "peaks": "—"}
    cv = st.pstdev(freq12) / mean
    peak_i = max(range(12), key=lambda i: freq12[i])
    peak = freq12[peak_i]
    if cv < thr_cv:
        typ = "Всесезон"
    else:
        ss = st.mean(freq12[2:8])
        aw = st.mean(freq12[8:] + freq12[:2])
        typ = "Весна-Лето" if ss > aw * k else ("Осень-Зима" if aw > ss * k else "Сезонный")
    if cv < thr_cv and peak < 1.5 * mean:
        entry = "Любой"
    else:
        i = peak_i
        for _ in range(12):
            i = (i - 1) % 12
            if freq12[i] < mean:
                break
        entry = MONTH_RU[(i - 2) % 12]
    length = sum(1 for v in freq12 if v > 0.3 * peak)
    peaks = "-".join(MONTH_RU[i] for i in range(12) if freq12[i] > 1.3 * mean) or "—"
    return {"cv": round(cv, 2), "type": typ, "entry": entry, "length": length, "peaks": peaks}


def analyze(run: str, sid: int) -> dict:
    cfg = get_cfg(sid)
    D = Dict(cfg)
    months, rawq, prods = load(run, sid)
    cal = {m: int(m[5:]) - 1 for m in months}          # YYYY-MM → индекс календарного месяца
    # 12 месяцев; допускаем 11 (Saleflow timeout) — пропуск фиксируется в R["missing"] и в Легенде
    assert len(months) >= 11, f"нужно ≥ 11 месяцев, есть {len(months)}"
    missing = [f"{y}-{mm:02d}" for y, mm in ((2025, 9), (2025, 10), (2025, 11), (2025, 12)) + tuple((2026, i) for i in range(1, 9))
               if f"{y}-{mm:02d}" not in months]

    # ── СПП и цены карточек
    sw = sum(p.get("sales_estimated") or 0 for p in prods) or 1
    spp = sum((p.get("spp_avg") or 0) * (p.get("sales_estimated") or 0) for p in prods) / sw
    for p in prods:
        p["seller_price"] = p["final_price"] / (1 - spp / 100) if p.get("final_price") else None
        p["meanings"], _, _ = D.parse(p["name"])
    priced = [p for p in prods if p["seller_price"] and (p.get("sales_estimated") or 0) > 0]
    pr = sorted(p["seller_price"] for p in priced)
    q33, q67 = st.quantiles(pr, n=3)
    lo, hi = round(q33 / 100) * 100, round(q67 / 100) * 100
    market_check = st.median(pr)

    # ── запросы
    log = collections.Counter()
    queries = []
    unk_counter = collections.Counter()
    for w, per in rawq.items():
        fm = [0.0] * 12
        res, items = [], []
        for m, x in per.items():
            fm[cal[m]] += x.get("wb_count") or 0
            if x.get("count"):
                res.append(x["count"])
            items.append(x.get("items_count") or 0)
        fy = sum(fm)
        if max(items) < 20:
            log["нерелевантно предмету (items_count < 20)"] += 1
            continue
        if fy < 100:
            log["частота (год) < 100"] += 1
            continue
        ms, unk, has_base = D.parse(w)
        groups = {D.group_of[m] for m in ms}
        if not ms:
            if has_base:
                log["только базовое слово (ОБЩЕЕ)"] += 1
            else:
                log["общие/посторонние запросы без смыслов"] += 1
                unk_counter.update(unk)
            continue
        if not has_base and not (groups & cfg["anchors"]):
            log["без якоря ниши (только КУДА/НАЗНАЧЕНИЕ/СТИЛЬ)"] += 1
            continue
        defs = [per[m]["wb_count"] / per[m]["count"] for m in per if per[m].get("count") and per[m].get("wb_count")]
        queries.append({"q": w, "fy": fy, "fm": fm, "res": st.mean(res) if res else None,
                        "def": st.median(defs) if defs else None, "ms": ms, "unk": unk})
        if unk:
            unk_counter.update(unk)

    # ── средний чек запроса из карточек: карточки, чьи смыслы ⊇ смыслам запроса (без КУДА/ЦВЕТ/НАЗН/СТИЛЬ)
    core_groups = {"ЧТО", "КОНСТРУКЦИЯ", "ФУНКЦИЯ", "МАТЕРИАЛ"}
    cache = {}
    for qq in queries:
        key = frozenset(m for m in qq["ms"] if D.group_of[m] in core_groups)
        if key not in cache:
            k2, src = set(key), "точно"
            while True:
                hit = [p["seller_price"] for p in priced if k2 <= p["meanings"]]
                if len(hit) >= 3 or not k2:
                    break
                # ослабляем: убираем самый редкий в карточках смысл
                k2.remove(min(k2, key=lambda m: sum(1 for p in priced if m in p["meanings"])))
                src = "приближённо"
            cache[key] = (st.median(hit) if len(hit) >= 3 else market_check, src if len(hit) >= 3 else "рынок")
        qq["check"], qq["check_src"] = cache[key]

    def seg(c):
        return 0 if c < lo else (1 if c <= hi else 2)

    # ── резкая сезонность ниши?
    tot12 = [sum(q["fm"][i] for q in queries) for i in range(12)]
    m_cv = {}
    for qq in queries:
        for m in qq["ms"]:
            m_cv.setdefault(m, [0.0] * 12)
            for i in range(12):
                m_cv[m][i] += qq["fm"][i]
    cvs = [st.pstdev(v) / st.mean(v) for v in m_cv.values() if st.mean(v) > 0]
    sharp = sum(c > 0.5 for c in cvs) > len(cvs) / 2
    thr_cv, k = (0.2, 1.1) if sharp else (0.3, 1.2)

    # ── агрегация по смыслам (explode)
    by_m = collections.defaultdict(list)
    for qq in queries:
        for m in qq["ms"]:
            by_m[m].append(qq)
    meanings = {}
    for m, qs in by_m.items():
        fm = [sum(q["fm"][i] for q in qs) for i in range(12)]
        defs = [q["def"] for q in qs if q["def"] is not None]
        meanings[m] = {"m": m, "g": D.group_of[m], "fy": sum(q["fy"] for q in qs), "fm": fm,
                       "def": st.mean(defs) if defs else 0, "check": st.mean(q["check"] for q in qs),
                       "n": len(qs), "res": st.mean([q["res"] for q in qs if q["res"]] or [0]),
                       **season_metrics(fm, thr_cv, k),
                       "uniq": sum(1 for q in qs if len(q["ms"]) == 1) / len(qs) * 100,
                       "seo": seo_core(qs, 3)}
    norm_m = robust_max([v["def"] for v in meanings.values()])
    market = st.mean(q["check"] for q in queries)
    for v in meanings.values():
        v["def_pct"] = min(100, v["def"] / norm_m * 100) if norm_m else 0
        v["dcheck"] = v["check"] - market

    # приоритет группы = средняя частота начинок группы
    gprio = collections.defaultdict(list)
    for v in meanings.values():
        gprio[v["g"]].append(v["fy"])
    gorder = sorted(gprio, key=lambda g: -st.mean(gprio[g]))
    grank = {g: i + 1 for i, g in enumerate(gorder)}

    def combos(n: int) -> dict:
        agg = collections.defaultdict(list)
        for qq in queries:
            ms = sorted(qq["ms"])
            for c in itertools.combinations(ms, n):
                if len({D.group_of[x] for x in c}) == n:
                    agg[c].append(qq)
        out = {}
        for c, qs in agg.items():
            fm = [sum(q["fm"][i] for q in qs) for i in range(12)]
            defs = [q["def"] for q in qs if q["def"] is not None]
            sg = collections.Counter(seg(q["check"]) for q in qs)
            groups = {D.group_of[x] for x in c}
            out[c] = {"c": c, "fy": sum(q["fy"] for q in qs), "fm": fm,
                      "res": st.mean([q["res"] for q in qs if q["res"]] or [0]),
                      "def": st.mean(defs) if defs else 0, "check": st.mean(q["check"] for q in qs),
                      "dist": [sg[i] / len(qs) * 100 for i in range(3)], "n": len(qs),
                      "missing": [g for g in gorder if g not in groups],
                      **season_metrics(fm, thr_cv, k), "seo": seo_core(qs, 5)}
        return out

    pairs, triples = combos(2), combos(3)
    for coll in (pairs, triples):
        nm = robust_max([v["def"] for v in coll.values()])
        for v in coll.values():
            v["def_pct"] = min(100, v["def"] / nm * 100) if nm else 0
    pairs_l = limit(sorted(pairs.values(), key=lambda v: -v["fy"]))
    triples_l = limit(sorted(triples.values(), key=lambda v: -v["fy"]))
    for t in triples_l:
        par = max((pairs[p] for p in itertools.combinations(t["c"], 2) if p in pairs), key=lambda v: v["fy"])
        t["parent"] = par["c"]
        t["new"] = [x for x in t["c"] if x not in par["c"]][0]
        t["pct_parent"] = t["fy"] / par["fy"] * 100 if par["fy"] else 0
    for m, v in meanings.items():
        v["with"] = [" + ".join(p["c"]) for p in pairs_l if m in p["c"]][:3]

    total_fy = sum(q["fy"] for q in queries)
    unk_share = sum(1 for q in queries if q["unk"]) / len(queries) * 100
    return {"cfg": cfg, "D": D, "months": months, "missing": missing, "spp": spp, "lo": lo, "hi": hi, "market": market,
            "market_check_cards": market_check, "queries": queries, "meanings": meanings, "pairs": pairs_l,
            "pairs_all": pairs, "triples": triples_l, "gorder": gorder, "grank": grank, "log": log,
            "unk": unk_counter, "unk_share": unk_share, "total_fy": total_fy, "sharp": sharp,
            "thr_cv": thr_cv, "k": k, "n_raw": len(rawq), "prods": priced}


def robust_max(vals: list[float]) -> float:
    vals = sorted(v for v in vals if v)
    if not vals:
        return 0
    return vals[int(0.95 * (len(vals) - 1))]


def limit(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    mx = rows[0]["fy"]
    sel = [r for r in rows if r["fy"] > 0.01 * mx]
    return rows[:max(20, min(100, len(sel)))]


def seo_core(qs: list[dict], n: int) -> list[tuple[str, int]]:
    seen, out = [], []
    for q in sorted(qs, key=lambda q: -q["fy"]):
        ws = frozenset(tokens(q["q"]))
        if any(ws == s for s in seen):
            continue
        seen.append(ws)
        out.append((q["q"], int(q["fy"])))
        if len(out) == n:
            break
    return out


def fmt_check(c: float, lo: int, hi: int) -> str:
    lvl = "Низкий" if c < lo else ("Средний" if c <= hi else "Высокий")
    return f"{lvl} ({c:,.0f}₽)".replace(",", " ")


# ── гипотезы
def hypotheses(R: dict) -> list[dict]:
    cfg, mean = R["cfg"], R["meanings"]
    blocked = cfg["blocked"]
    pairs, triples = R["pairs"], R["triples"]
    bases = [dict(v, kind="тройка") for v in triples] + [dict(v, kind="двойка") for v in pairs]

    def ok(b):
        return not any(x in blocked for x in b["c"]) and "бренд аксессуаров" not in b["c"]

    def together(ms: set[str]) -> float:
        """Частота (год) запросов, где все смыслы встречаются вместе — реальный спрос на сочетание."""
        return sum(q["fy"] for q in R["queries"] if ms <= q["ms"])

    def pick_fill(base, key):
        # начинка допускается, только если покупатели реально ищут её вместе с основой (≥ 0.5% частоты основы)
        fills, bset = [], set(base["c"])
        for g in sorted(base["missing"], key=lambda g: R["grank"][g])[:3]:
            cands = []
            for v in mean.values():
                if v["g"] != g or v["m"] in blocked or v["m"] in ("под модель авто", "тюнинг"):
                    continue
                t = together(bset | {v["m"]})
                if t >= max(0.005 * base["fy"], 500):
                    cands.append((v, t))
            if not cands:
                continue
            if g in ("ЧТО", "КУДА") or key == "safe":
                cands.sort(key=lambda x: -x[1])                 # объект/транспорт и безопасный выбор — по спросу на сочетание
            elif key == "margin":
                cands.sort(key=lambda x: -x[0]["dcheck"])
            else:
                cands.sort(key=lambda x: -x[0]["def_pct"])
            fills.append(cands[0][0])
        return fills

    maxp = max(p["fy"] for p in pairs)
    strat = {
        "🛡️ Безопасный вход": ("safe", sorted([b for b in bases if ok(b) and (b["type"] == "Всесезон" or b["length"] >= 8)],
                                             key=lambda b: -b["fy"])),
        "💰 Маржинальный": ("margin", sorted([b for b in bases if ok(b) and b["check"] > R["market"] and b["fy"] >= 0.03 * maxp],
                                           key=lambda b: -b["check"])),
        "🎯 Нишевый": ("niche", sorted([b for b in bases if ok(b) and b["def_pct"] > 30 and b["fy"] > 0.10 * maxp],
                                     key=lambda b: -b["def_pct"])),
    }
    out, used = [], []
    for s, (key, cands) in strat.items():
        n = 0
        for b in cands:
            fills = pick_fill(b, key)
            sig = frozenset(b["c"]) | {f["m"] for f in fills}
            if any(len(sig & u) / len(sig | u) >= 0.75 for u in used):   # тот же товар другими словами
                continue
            used.append(sig)
            name = product_name(cfg["product_word"], list(b["c"]) + [f["m"] for f in fills], R["D"])
            seo = merge_seo([b["seo"]] + [f["seo"] for f in fills], 5)
            out.append({"s": s, "name": name, "base": " + ".join(b["c"]), "kind": b["kind"],
                        "fills": ", ".join(f"{f['m']} ({f['g']})" for f in fills) or "—",
                        "fy": b["fy"], "def_pct": b["def_pct"], "check": b["check"], "type": b["type"],
                        "length": b["length"], "seo": seo, "risk": risks(b, fills, R)})
            n += 1
            if n == 3:
                break
    return out


ORDER = ["ЧТО", "КТО", "КУДА", "ФУНКЦИЯ", "КОНСТРУКЦИЯ", "РАЗМЕР", "МАТЕРИАЛ", "ЦВЕТ", "НАЗНАЧЕНИЕ", "СТИЛЬ"]


def product_name(word: str, ms: list[str], D: Dict) -> str:
    ms = sorted(set(ms), key=lambda m: ORDER.index(D.group_of[m]) if D.group_of[m] in ORDER else 99)
    parts = []
    swap = D.cfg.get("what_is_word", False)      # общее слово ниши («Аксессуар…») заменяется смыслом ЧТО
    for m in ms:
        g = D.group_of[m]
        if g == "ЧТО" and (swap or m in ("подстаканник", "автовизитка / номер", "коврик на панель", "магнитная пластина",
                                         "картхолдер", "органайзер / карман", "крючок")):
            word, swap = m.split(" / ")[0].split(" (")[0].capitalize(), False
            continue
        parts.append(m.split(" / ")[0])
    return f"{word} " + " ".join(parts)


def merge_seo(lists, n):
    seen, out = set(), []
    for l in lists:
        for q, f in l:
            if q not in seen:
                seen.add(q)
                out.append((q, f))
    out.sort(key=lambda x: -x[1])
    return out[:n]


def risks(b, fills, R) -> str:
    r = []
    ms = set(b["c"]) | {f["m"] for f in fills}
    if b["res"] and b["res"] > 20000:
        r.append(f"высокая конкуренция в выдаче (~{b['res']:,.0f} товаров)".replace(",", " "))
    if "MagSafe" in ms:
        r.append("MagSafe — товарный знак Apple: в карточке писать «совместим с MagSafe», без логотипа")
    if ("магнитный" in ms or "MagSafe" in ms) and "для телефона" in ms:
        r.append("магнит должен держать телефон в чехле на кочках — главный повод для негатива; проверять силу магнита на образце")
    elif "магнитный" in ms:
        r.append("магнит не должен царапать панель — мягкая подложка")
    if "автовизитка / номер" in ms:
        r.append("товар дешёвый в закупке, но много дешёвых аналогов — нужен дизайн/скрытие номера как отличие")
    if "на присоске" in ms:
        r.append("присоска отклеивается в жару/мороз — нужна липкая гель-присоска")
    if "в воздуховод" in ms:
        r.append("не подходит к круглым дефлекторам — указать совместимость")
    if b["def_pct"] > 60 and b["fy"] < 0.1 * R["pairs"][0]["fy"]:
        r.append("высокий дефицит при небольшой частоте — проверить реальную ёмкость")
    if b["check"] > R["market"] * 1.3:
        r.append("премиум-цена: покупатель ждёт металл и плотную упаковку")
    if not r:
        r.append("массовый сегмент — выигрывать фото, отзывами и ценой")
    return "; ".join(r[:2]) + "."


def token_report(run: str, sid: int, top: int = 150) -> None:
    """Подсказка для словаря: частые слова релевантных запросов (для новой ниши) или нераспознанные (для готовой)."""
    from src.dna_dicts import DICTS as _D
    months, rawq, _ = load(run, sid)
    stat = collections.Counter()
    if sid in _D:
        R = analyze(run, sid)
        q = R["queries"]
        share = sum(x["fy"] for x in q if x["unk"]) / R["total_fy"] * 100
        print(f"месяцев {len(months)}; запросов в анализе {len(q)}; смыслов {len(R['meanings'])}; "
              f"частота с нераспознанными словами {share:.1f}% (порог 5%)")
        print("отсечено:", dict(R["log"]))
        for x in q:
            for t in set(x["unk"]):
                stat[t] += x["fy"]
    else:
        for w, per in rawq.items():
            items = max((x.get("items_count") or 0) for x in per.values())
            fy = sum((x.get("wb_count") or 0) for x in per.values())
            if items < 20 or fy < 100:
                continue
            for t in set(tokens(w)):
                stat[t] += fy
        print(f"месяцев {len(months)}; словаря нет — частые слова релевантных запросов:")
    print("; ".join(f"{t} {f:,.0f}".replace(",", " ") for t, f in stat.most_common(top)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tokens"])
    ap.add_argument("--subject", type=int, required=True)
    ap.add_argument("--run", default="2026-10-05")
    ap.add_argument("--top", type=int, default=150)
    a = ap.parse_args()
    token_report(a.run, a.subject, a.top)
