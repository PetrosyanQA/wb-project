"""Bright Data Web Unlocker — клиент с кэшем (2026-10-18). Нужен для цен 1688, пока кредит Apify обнулён до 1 ноября.

    python -m src.brightdata_client ping                       # тест зоны (geo.brdtest.com), 1 запрос
    python -m src.brightdata_client get <url> --name <имя>     # любой URL → data/raw/brightdata/<дата>/<имя>.html
    python -m src.brightdata_client s1688 "狗玩具 耐咬 橡胶" --name 731   # поиск 1688 (keywords в GBK)

Токен — только из .env (BRIGHTDATA_TOKEN), никогда не печатается и не пишется в отчёты.
    python -m src.brightdata_client usage                      # сколько платных запросов ушло по дням (0 запросов)

Зона — BRIGHTDATA_ZONE из .env (по умолчанию web_unlocker1). Повторный запуск с тем же именем в тот же день = 0 запросов (кэш).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
API = "https://api.brightdata.com/request"
OUT = f"data/raw/brightdata/{dt.date.today().isoformat()}"
USAGE = "data/raw/brightdata/_usage.json"     # счётчик платных запросов по дням (сбой тоже считается)


def usage() -> dict:
    try:
        return json.load(open(USAGE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def spend_one() -> None:
    """Потолок платных запросов в день: BRIGHTDATA_MAX_DAY в .env (по умолчанию 20). Выше — отказ без запроса."""
    u, day = usage(), dt.date.today().isoformat()
    cap = int(env("BRIGHTDATA_MAX_DAY", "20"))
    if u.get(day, 0) >= cap:
        raise SystemExit(f"стоп: сегодня уже {u[day]} платных запросов (потолок {cap}) — поднимите BRIGHTDATA_MAX_DAY осознанно")
    u[day] = u.get(day, 0) + 1
    os.makedirs(os.path.dirname(USAGE), exist_ok=True)
    json.dump(u, open(USAGE, "w", encoding="utf-8"), indent=1)


def env(key: str, default: str | None = None) -> str:
    for line in open(".env", encoding="utf-8-sig"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    if default is None:
        raise SystemExit(f"нет {key} в .env — добавьте строку {key}=<ключ> вручную (в чат ключ не присылать)")
    return default


def fetch(url: str, name: str, timeout: int = 120) -> str:
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/{name}.html"
    if os.path.exists(path):
        print("кэш:", path)
        return open(path, encoding="utf-8").read()
    spend_one()
    body = json.dumps({"zone": env("BRIGHTDATA_ZONE", "web_unlocker1"), "url": url, "format": "raw"}).encode()
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + env("BRIGHTDATA_TOKEN"),
                                          "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Bright Data HTTP {e.code}: {e.read()[:200]!r}" + (" — ключ неверный/отозван" if e.code in (401, 403) else ""))
    text = raw.decode("utf-8", errors="replace")
    open(path, "w", encoding="utf-8").write(text)
    print(f"сохранено: {path} ({len(raw)} байт)")
    return text


def offers_1688(html: str) -> list[dict]:
    """Карточки выдачи 1688 (вёрстка 2026-10: titleText → ¥ → priceMain + дробь → «N件» продано)."""
    out = []
    for blk in html.split('class="titleText--')[1:]:
        t = [x.strip() for x in re.sub(r"<[^>]+>", "|", blk[:3000]).split("|") if x.strip()]
        if "¥" not in t:
            continue
        i = t.index("¥")
        title = "".join(x for x in t[1:i] if x not in ("｜", "全网低价") and "首单" not in x)
        num = t[i + 1] + (t[i + 2] if i + 2 < len(t) and t[i + 2].startswith(".") else "")
        try:
            price = float(num)
        except ValueError:
            continue
        sold = next((x for x in t[i + 1:i + 6] if x.endswith("件")), "")
        rep = next((x[3:] for x in t[i + 1:i + 12] if x.startswith("回头率")), "")
        out.append({"title": title[:80], "price_cny": price, "sold": sold, "repeat": rep})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ping", "get", "s1688", "usage"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--name")
    a = ap.parse_args()
    if a.cmd == "usage":
        print(json.dumps(usage(), ensure_ascii=False))
    elif a.cmd == "ping":
        print(fetch("https://geo.brdtest.com/welcome.txt?product=unlocker&method=api", f"ping_{dt.datetime.now():%H%M%S}")[:300])
    elif a.cmd == "get":
        fetch(a.arg, a.name or re.sub(r"\W+", "_", a.arg)[-60:])
    else:
        q = urllib.parse.quote(a.arg.encode("gbk"))
        html = fetch(f"https://s.1688.com/selloffer/offer_search.htm?keywords={q}", f"1688_{a.name or 'q'}")
        rows = offers_1688(html)
        ps = sorted(r["price_cny"] for r in rows)
        print(f"офферов распознано: {len(rows)}" + (f" | ¥ P25/P50: {ps[len(ps)//4]} / {ps[len(ps)//2]}" if ps else
              " — разметка не распознана, смотрите сохранённый HTML (возможна страница входа)"))
        for r in rows[:10]:
            print(f"  ¥{r['price_cny']:>7}  {r['sold']:>9}  {r['title'][:60]}")


if __name__ == "__main__":
    main()
