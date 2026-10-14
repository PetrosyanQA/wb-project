"""Сбор данных Saleflow для стратегии ниши (шаблон «Senior E-commerce Strategist», 2026-10-07). Ответы — сразу на диск.

    python -m src.strategy_collect --niche 2486 --step trends --dry-run
    python -m src.strategy_collect --niche 2486 --step trends|cards20|core|daily|cards|leaders [--sku …] [--comments …]
    python -m src.strategy_collect --niche 777  --step trends|extra

Шаги (квота Saleflow — 500 запросов/день; wb_card_content идёт в CDN WB, не в MPSTATS):
  trends   — wb_subject trends по месяцам, 2024-09-01 … 2026-09-30 (1; диапазон длиннее или d2 не конец месяца → «request failed»)
  cards20  — wb_card_content top-20 по выручке июля → габариты упаковки ДО трат квоты (гейт ≤ 1 л)
  core     — products500 июль, top-100 за 30 дней, price_segmentation июль/30 дней, sellers июль,
             keywords 30 дней + по месяцам 2025-04 … 2026-08 (год одним запросом падает по таймауту)
  daily    — wb_sku by_period 2025-10-01 … вчера для top-100 июля (или --sku)
  cards    — wb_card_content остального top-100
  leaders  — wb_sku keywords для --sku (позиции по запросам), wb_sku comments для --comments
  extra    — 777: sellers июль, keywords 2024-12 (YoY пика), by_period новых карточек top-100 со стартом 2025-10 … 2026-03

Уже скачанные файлы пропускаются → повторный запуск = 0 запросов. Сбой upstream — 1 повтор через 30 с;
3 сбоя подряд → стоп (неудачные вызовы тоже списываются с квоты, проверено 2026-10-07).
"""
from __future__ import annotations

import argparse
import calendar
import glob
import json
import os
import shutil
import sys
import threading
import time

from src.saleflow_stdio import Client

sys.stdout.reconfigure(encoding="utf-8")
RUN = "2026-10-07"
D2 = "2026-10-06"                                   # вчера: данные за сегодня у MPSTATS ещё не готовы
D1_30 = "2026-09-06"
JUL = ("2026-07-01", "2026-07-31")
BASE = f"data/raw/saleflow/{RUN}"
TOP100 = {777: "data/raw/saleflow/2026-10-05/dna/777/top100/top100_products_2026-07.json",
          2486: "data/raw/saleflow/2026-10-06/fresh/products_2486_2026-07.json",
          729: "data/raw/saleflow/2026-10-11/strategy729/products500_2026-07.json",
          2499: "data/raw/saleflow/2026-10-13/strategy2499/products500_2026-07.json",
          7640: "data/raw/saleflow/2026-10-14/strategy7640/products500_2026-07.json"}
TOP100_FALLBACK = {729: "data/raw/saleflow/2026-10-11/all/finalists/products_729.json",
                   2499: "data/raw/saleflow/2026-10-11/all/finalists/products_2499.json",
                   7640: "data/raw/saleflow/2026-10-14/v2/products500_7640_2026-07.json"}   # top-100 пика (март 2026) до core
DAILY_D2 = {729: "2026-07-31", 2499: "2026-07-31", 7640: "2026-07-31"}    # 2026-10-11: 2025-10-01 … 2026-10-10 падает upstream; после 07-31 Saleflow всё равно неполный
RUNS = {729: ("2026-10-11", "2026-10-10", "2026-09-10"), 2499: ("2026-10-13", "2026-10-12", "2026-09-12"),
        7640: ("2026-10-14", "2026-10-13", "2026-09-13")}    # (RUN, D2, D1_30) — ниша собирается в другой день
OLD_COMMENTS = {2486: "data/raw/saleflow/2026-10-06/fresh/comments/2486_{}.json"}
KW_MONTHS = {2486: [f"{y}-{m:02d}" for y, m in [(2025, i) for i in range(4, 13)] + [(2026, i) for i in range(1, 9)]],
             777: ["2024-12"],
             7640: [f"{y}-{m:02d}" for y, m in [(2025, i) for i in range(4, 13)] + [(2026, i) for i in range(1, 9)]],
             2499: [f"{y}-{m:02d}" for y, m in [(2025, i) for i in range(4, 13)] + [(2026, i) for i in range(1, 9)]],
             729: [f"{y}-{m:02d}" for y, m in [(2025, i) for i in range(4, 13)] + [(2026, i) for i in range(1, 9)]]}


def out_dir(niche: int) -> str:
    return f"{BASE}/strategy{niche}"


def top100(niche: int) -> list[dict]:
    f = TOP100[niche] if os.path.exists(TOP100[niche]) else TOP100_FALLBACK.get(niche, TOP100[niche])
    d = json.load(open(f, encoding="utf-8"))
    rows = d.get("data", d) if isinstance(d, dict) else d
    return sorted(rows, key=lambda p: -(p.get("revenue") or 0))[:100]


def month_range(ym: str) -> tuple[str, str]:
    y, m = map(int, ym.split("-"))
    return f"{ym}-01", f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


def subj(niche: int, report: str, d1: str, d2: str, **kw) -> dict:
    return {"subject_id": niche, "report": report, "d1": d1, "d2": d2, **kw}


def tasks(niche: int, step: str, skus: list[int], comments: list[int]) -> list[tuple[str, str, dict, bool]]:
    """→ [(относительный путь, tool, args, cdn?)]."""
    o, T = out_dir(niche), top100(niche)
    if step == "trends":
        return [(f"{o}/trends_month.json", "wb_subject", subj(niche, "trends", "2024-09-01", "2026-09-30", group_by="month"), False)]
    if step in ("cards20", "cards"):
        ids = [p["id"] for p in T[:20]] if step == "cards20" else [p["id"] for p in T]
        return [(f"{o}/top100/cards/{i}.json", "wb_card_content", {"sku": str(i)}, True) for i in ids]
    if step == "core":
        L = [(f"{o}/price_seg_2026-07.json", "wb_subject", subj(niche, "price_segmentation", *JUL), False),
             (f"{o}/price_seg_30d.json", "wb_subject", subj(niche, "price_segmentation", D1_30, D2), False),
             (f"{o}/sellers_2026-07.json", "wb_subject", subj(niche, "sellers", *JUL, limit=500), False),
             (f"{o}/keywords_30d.json", "wb_subject", subj(niche, "keywords", D1_30, D2), False),
             (f"{o}/products_30d.json", "wb_subject", subj(niche, "products", D1_30, D2, limit=100), False)]
        kw = [(f"{o}/keywords/keywords_{m}.json", "wb_subject", subj(niche, "keywords", *month_range(m)), False)
              for m in KW_MONTHS[niche]]
        summer25 = [t for t in kw if any(m in t[0] for m in ("2025-06", "2025-07", "2025-08"))]   # падали upstream 2026-10-07
        L += [t for t in kw if t not in summer25]
        L += [(f"{o}/products500_2026-07.json", "wb_subject", subj(niche, "products", *JUL, limit=500), False)]   # тяжёлый
        return L + summer25
    if step == "daily":
        ids = skus or [p["id"] for p in T]
        d2 = DAILY_D2.get(niche, D2)
        return [(f"{o}/top100/daily/{i}.json", "wb_sku", {"sku": i, "report": "by_period", "d1": "2025-10-01", "d2": d2}, False)
                for i in ids]
    if step == "leaders":
        L = [(f"{o}/sku_{i}_keywords.json", "wb_sku", {"sku": i, "report": "keywords", "d1": D1_30, "d2": D2}, False) for i in skus]
        L += [(f"{o}/comments/{i}.json", "wb_sku", {"sku": i, "report": "comments"}, False) for i in comments]
        return L
    if step == "extra":                                  # 777: дозагрузка под общую методику
        new = [p["id"] for p in T if "2025-10-01" <= (p.get("sku_first_date") or "") < "2026-04-01"]
        L = [(f"{o}/sellers_2026-07.json", "wb_subject", subj(niche, "sellers", *JUL, limit=500), False)]
        L += [(f"{o}/keywords/keywords_{m}.json", "wb_subject", subj(niche, "keywords", *month_range(m)), False)
              for m in KW_MONTHS[niche]]
        L += [(f"{o}/daily_long/{i}.json", "wb_sku", {"sku": i, "report": "by_period", "d1": "2025-10-01", "d2": D2}, False)
              for i in new]
        return L
    raise SystemExit(f"неизвестный шаг {step}")


def seed(niche: int) -> None:
    """Уже скачанное ранее кладём в ту же раскладку (0 запросов)."""
    o = out_dir(niche)
    os.makedirs(f"{o}/top100", exist_ok=True)
    dst = f"{o}/top100/top100_products_2026-07.json"
    if niche in TOP100 and os.path.exists(TOP100[niche]) and not os.path.exists(dst):
        json.dump(top100(niche), open(dst, "w", encoding="utf-8"), ensure_ascii=False)
    for sku_file in glob.glob(OLD_COMMENTS[niche].format("*")) if niche in OLD_COMMENTS else []:
        sku = sku_file.rsplit("_", 1)[1].split(".")[0]
        d = f"{o}/comments/{sku}.json"
        if not os.path.exists(d):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(sku_file, d)


def quota(c: Client) -> str:
    try:
        return str(c.call("account_limits", {}))[:160].replace("\n", " ")
    except Exception as e:                                  # noqa: BLE001 — квота не обязательна для сбора
        return f"не получена ({str(e)[:80]})"


def fetch(c: Client, tool: str, args: dict, timeout: int = 240):
    """Сторож: у stdio-клиента нет таймаута, зависший upstream блокирует навсегда → убиваем сервер, вызов падает."""
    timer = threading.Timer(timeout, c.p.kill)
    timer.start()
    try:
        res = c.call(tool, args)
    finally:
        timer.cancel()
    if not isinstance(res, (dict, list)):
        raise RuntimeError(f"не JSON: {str(res)[:200]}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", type=int, required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--sku", type=int, nargs="*", default=[])
    ap.add_argument("--comments", type=int, nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    global RUN, D2, D1_30, BASE
    if a.niche in RUNS:
        RUN, D2, D1_30 = RUNS[a.niche]
        BASE = f"data/raw/saleflow/{RUN}"
    seed(a.niche)
    todo = [t for t in tasks(a.niche, a.step, a.sku, a.comments) if not os.path.exists(t[0])]
    n_quota = sum(1 for t in todo if not t[3])
    print(f"шаг {a.step}: новых файлов {len(todo)} | запросов к квоте Saleflow {n_quota} | CDN WB {len(todo) - n_quota}")
    if a.dry_run or not todo:
        return
    c = Client()
    fails = []
    try:
        print("квота до:", quota(c))
        streak = 0
        for n, (path, tool, args, _) in enumerate(todo, 1):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            for attempt in range(2):
                try:
                    res = fetch(c, tool, args)
                    json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"[{n}/{len(todo)}] → {path}")
                    streak = 0
                    break
                except Exception as e:                      # noqa: BLE001 — upstream Saleflow нестабилен
                    print(f"[{n}/{len(todo)}] {tool} {args.get('sku') or args.get('report')}: {str(e)[:160]} (попытка {attempt + 1})")
                    if "закрылся" in str(e):
                        c = Client()
                    if attempt == 0:
                        time.sleep(30)
            else:
                fails.append(path)
                streak += 1
                if streak >= 3:
                    print("3 сбоя подряд — стоп, чтобы не жечь квоту")
                    break
        print("квота после:", quota(c))
    finally:
        c.close()
    done = sum(1 for t in todo if os.path.exists(t[0]))
    print(f"готово: {done} из {len(todo)}; не скачано (сбой): {fails}; не дошли из-за стопа: {len(todo) - done - len(fails)}")


if __name__ == "__main__":
    main()
