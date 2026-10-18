"""Bright Data Web Unlocker — клиент с кэшем (2026-10-18). Нужен для цен 1688, пока кредит Apify обнулён до 1 ноября.

    python -m src.brightdata_client ping                       # тест зоны (geo.brdtest.com), 1 запрос
    python -m src.brightdata_client get <url> --name <имя>     # любой URL → data/raw/brightdata/<дата>/<имя>.html
    python -m src.brightdata_client s1688 "狗玩具 耐咬 橡胶" --name 731   # поиск 1688 (keywords в GBK)

Токен — только из .env (BRIGHTDATA_TOKEN), никогда не печатается и не пишется в отчёты.
    python -m src.brightdata_client d1688 954555712385                # карточка 1688: SKU, цены, мин. партия
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
USAGE = "data/raw/brightdata/_usage.json"     # счётчик запросов по дням (сбой тоже считается)


def env(key: str, default: str | None = None) -> str:
    for line in open(".env", encoding="utf-8-sig"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    if default is None:
        raise SystemExit(f"нет {key} в .env — добавьте строку {key}=<ключ> вручную (в чат ключ не присылать)")
    return default


def usage() -> dict:
    try:
        return json.load(open(USAGE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def month_used(u: dict) -> int:
    m = dt.date.today().strftime("%Y-%m")
    return sum(v for k, v in u.items() if k.startswith(m))


def spend_one() -> None:
    """Бюджет: BRIGHTDATA_MONTH_CREDITS (5000 бесплатных/мес, обновление 1-го числа) минус резерв BRIGHTDATA_RESERVE (100).
    Решение пользователя 2026-10-18: тратить сколько нужно, но остановиться и сообщить, когда останется 100.
    Дневной потолок BRIGHTDATA_MAX_DAY (по умолчанию 1000) — страховка от зацикливания."""
    u, day = usage(), dt.date.today().isoformat()
    total, reserve = int(env("BRIGHTDATA_MONTH_CREDITS", "5000")), int(env("BRIGHTDATA_RESERVE", "100"))
    left = total - month_used(u)
    if left <= reserve:
        raise SystemExit(f"СТОП: по счётчику осталось {left} кредитов (резерв {reserve}) — сообщить пользователю, дальше только с его разрешения")
    if u.get(day, 0) >= int(env("BRIGHTDATA_MAX_DAY", "1000")):
        raise SystemExit(f"стоп: дневной потолок {u[day]} запросов")
    u[day] = u.get(day, 0) + 1
    os.makedirs(os.path.dirname(USAGE), exist_ok=True)
    json.dump(u, open(USAGE, "w", encoding="utf-8"), indent=1)
    if left - 1 <= reserve + 50:
        print(f"⚠️ Bright Data: осталось ≈ {left - 1} кредитов — близко к резерву {reserve}")


def fetch(url: str, name: str, timeout: int = 200) -> str:
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
    except TimeoutError:
        raise SystemExit(f"Bright Data: таймаут {timeout} с — повторите позже (запрос засчитан в счётчик)")
    text = raw.decode("utf-8", errors="replace")
    if len(raw) < 2000:                          # пустой/служебный ответ не кэшируем, чтобы повтор не отдавал пустоту
        raise SystemExit(f"Bright Data: короткий ответ ({len(raw)} байт), не сохранён: {text[:150]!r}")
    open(path, "w", encoding="utf-8").write(text)
    print(f"сохранено: {path} ({len(raw)} байт)")
    return text


def offers_1688(html: str) -> list[dict]:
    """Карточки выдачи 1688. Две вёрстки (2026-10): class="titleText--…" и class="title-text";
    в обеих: название → ¥ → целая часть + «.дробь» → «N件» продано → «回头率 N%»."""
    out = []
    for blk in re.split(r'class="(?:titleText--[^"]*|title-text)"', html)[1:]:
        t = [x.strip() for x in re.sub(r"<[^>]+>", "|", blk[:3000]).split("|") if x.strip()]
        if "¥" not in t:
            continue
        i = t.index("¥")
        title = "".join(x for x in t[1:i] if x not in ("｜", "全网低价", "国货品牌", "普通人群", "跨境") and "首单" not in x)
        num = t[i + 1] + (t[i + 2] if i + 2 < len(t) and t[i + 2].startswith(".") else "")
        try:
            price = float(num)
        except ValueError:
            continue
        sold = next((x for x in t[i + 1:i + 6] if x.endswith("件")), "")
        rep = next((x[3:] for x in t[i + 1:i + 12] if x.startswith("回头率")), "")
        out.append({"title": title[:80], "price_cny": price, "sold": sold, "repeat": rep})
    return out


def detail_1688(html: str) -> dict:
    """Карточка товара 1688 (detail.1688.com/offer/<id>.html): SKU (specAttrs → цена, мин. партия), ступени цены, вес."""
    import html as H
    title = (re.search(r"<title>([^<]*)", html) or [None, ""])[1].replace(" - 阿里巴巴", "")
    skus, seen = [], set()
    for m in re.finditer(r'"specAttrs":"([^"]{1,80})","price":"([0-9.]+)","priceAmount":(\d+)', html):
        k = (m.group(1), m.group(2))
        if k not in seen:
            seen.add(k)
            skus.append({"sku": H.unescape(m.group(1)).replace(">", " / "), "price_cny": float(m.group(2)), "moq": int(m.group(3))})
    tiers = []
    m = re.search(r'"currentPrices":(\[[^\]]{0,600}\])', html)
    if m:
        try:
            tiers = [{"from": int(t.get("beginAmount", 0)), "price_cny": float(t["price"])} for t in json.loads(m.group(1))]
        except ValueError:
            pass
    w = re.search(r'"unitWeight":([0-9.]+)', html)
    return {"title": title, "skus": skus, "tiers": tiers,
            "unit_weight_kg": float(w.group(1)) if w else None,
            "moq": min([s["moq"] for s in skus] or [t["from"] for t in tiers] or [0]) or None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ping", "get", "s1688", "d1688", "usage"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--name")
    a = ap.parse_args()
    if a.cmd == "usage":
        u = usage()
        total = int(env("BRIGHTDATA_MONTH_CREDITS", "5000"))
        print(json.dumps(u, ensure_ascii=False), f"| за месяц {month_used(u)} | осталось ≈ {total - month_used(u)} из {total} (резерв {env('BRIGHTDATA_RESERVE', '100')})")
    elif a.cmd == "ping":
        print(fetch("https://geo.brdtest.com/welcome.txt?product=unlocker&method=api", f"ping_{dt.datetime.now():%H%M%S}")[:300])
    elif a.cmd == "get":
        fetch(a.arg, a.name or re.sub(r"\W+", "_", a.arg)[-60:])
    elif a.cmd == "d1688":
        d = detail_1688(fetch(f"https://detail.1688.com/offer/{a.arg}.html", f"1688d_{a.arg}"))
        print(d["title"][:70], "| MOQ", d["moq"], "| вес", d["unit_weight_kg"], "кг (часто заглушка 1.0)", "| ступени", d["tiers"])
        for s in sorted(d["skus"], key=lambda s: s["price_cny"]):
            print(f"  ¥{s['price_cny']:>7}  от {s['moq']:>3} шт  {s['sku'][:60]}")
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
