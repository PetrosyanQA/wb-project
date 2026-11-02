"""Живая выдача WB для проверки уникальности (/analiz 1.2): запрос → сырой JSON на диск → короткая сводка и вердикт.

    python -m src.radar check "лампа для подогрева свечей" "аромалампа для свечей" --name candle
    python -m src.radar show data/raw/saleflow/2026-11-02/radar/candle/*.json      # сводка по сохранённому, 0 запросов
    python -m src.radar ingest resp.json --name candle     # ответ MCP wb_check_rates → диск + сводка (если stdio даёт 401)

Зачем (аудит /analiz 02.11): ответы wb_check_rates не сохранялись и забивали контекст; кросс-бордер карточки (доставка
6–14 дней) путали вывод — их 0 продаж не доказывает «нет спроса», а их наличие не делает их «сильным аналогом».
Поле `sales` — продажи карточки по данным Saleflow за его короткое окно; использовать как относительную величину.
1 запрос Saleflow на формулировку.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
CROSS_BORDER_HOURS = 120      # доставка дольше — кросс-бордер, не локальный конкурент
STRONG_REVIEWS = 200          # «сильный аналог» — локальная карточка с отзывами больше этого
MAX_STRONG = 5                # уникально, если сильных аналогов меньше


def summarize(resp: dict) -> dict:
    rows = [r for r in resp.get("data", []) if r.get("name")]        # строки без данных (name null) — пропускаем
    organic = [r for r in rows if not r.get("promoted")]
    local = [r for r in rows if (r.get("deliveryHours") or 0) <= CROSS_BORDER_HOURS]
    cross = [r for r in rows if (r.get("deliveryHours") or 0) > CROSS_BORDER_HOURS]
    strong = [r for r in local if (r.get("comments") or 0) > STRONG_REVIEWS]
    local_sales = [r.get("sales") or 0 for r in local]
    prices = [r["final_price"] for r in rows if r.get("final_price")]
    if len(strong) >= MAX_STRONG:
        verdict = "CROWDED"
    elif sum(local_sales) > 0:
        verdict = "UNIQUE"
    else:
        verdict = "NO_DEMAND_SIGNAL"
    return {"query": resp.get("query"), "total": resp.get("total"), "rows": len(rows),
            "promoted": len(rows) - len(organic), "organic": len(organic), "local": len(local), "cross_border": len(cross),
            "strong": len(strong), "local_sales_sum": sum(local_sales),
            "local_sales_median": st.median(local_sales) if local_sales else 0,
            "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
            "subject": Counter(r.get("subject") for r in rows).most_common(1)[0][0] if rows else None,
            "top_strong": sorted(strong, key=lambda r: -(r.get("comments") or 0))[:3], "verdict": verdict}


def render(s: dict) -> str:
    out = [f"«{s['query']}»: всего {s['total']}, в выборке {s['rows']} (реклама {s['promoted']}, органика {s['organic']}); "
           f"локальных {s['local']}, кросс-бордер {s['cross_border']}",
           f"  сильных аналогов (> {STRONG_REVIEWS} отз., доставка ≤ {CROSS_BORDER_HOURS} ч): {s['strong']}; "
           f"продажи локальных: сумма {s['local_sales_sum']}, медиана {s['local_sales_median']}; "
           f"цена {s['price_min']}–{s['price_max']} ₽; предмет: {s['subject']}"]
    out += [f"    {r['id']} {r.get('brand') or '—'}: {r.get('comments')} отз., {r.get('final_price')} ₽, sales {r.get('sales')}"
            for r in s["top_strong"]]
    out.append(f"  ВЕРДИКТ: {s['verdict']}")
    return "\n".join(out)


def _slug(text: str) -> str:
    return re.sub(r"[^\w]+", "_", text.lower()).strip("_")[:60]


def check(queries: list[str], name: str, limit: int, region: str) -> None:
    from src.saleflow_stdio import Client
    outdir = ROOT / "data" / "raw" / "saleflow" / str(dt.date.today()) / "radar" / _slug(name)
    outdir.mkdir(parents=True, exist_ok=True)
    c = Client()
    try:
        for q in queries:
            resp = c.call("wb_check_rates", {"query": q, "limit": limit, "region": region})
            f = outdir / f"{_slug(q)}.json"
            f.write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
            print(render(summarize(resp)) + f"\n  → {f.relative_to(ROOT)}")
    finally:
        c.close()


def ingest(src: str, name: str) -> None:
    """Ответ MCP wb_check_rates (файл или «-» = stdin) → сохранить сырой JSON + сводка. Запасной путь, когда stdio-клиент
    Saleflow недоступен (401 у ключа в конфиге Claude Desktop), а MCP в чате работает."""
    raw = sys.stdin.buffer.read().decode("utf-8") if src == "-" else Path(src).read_text(encoding="utf-8")
    resp = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])        # терпим текст вокруг JSON
    outdir = ROOT / "data" / "raw" / "saleflow" / str(dt.date.today()) / "radar" / _slug(name)
    outdir.mkdir(parents=True, exist_ok=True)
    f = outdir / f"{_slug(resp.get('query') or 'query')}.json"
    f.write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
    print(render(summarize(resp)) + f"\n  → {f.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("check"); p.add_argument("queries", nargs="+"); p.add_argument("--name", required=True)
    p.add_argument("--limit", type=int, default=100); p.add_argument("--region", default="Москва")
    p = sp.add_parser("ingest"); p.add_argument("src"); p.add_argument("--name", required=True)
    p = sp.add_parser("show"); p.add_argument("files", nargs="+")
    a = ap.parse_args()
    if a.cmd == "check":
        check(a.queries, a.name, a.limit, a.region)
    elif a.cmd == "ingest":
        ingest(a.src, a.name)
    else:
        for f in a.files:
            print(render(summarize(json.loads(Path(f).read_text(encoding="utf-8")))))


if __name__ == "__main__":
    main()
