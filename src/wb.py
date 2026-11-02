"""Единая точка входа проекта (02.11.2026): 7 команд вместо 140 модулей. Внутри — уже проверенные модули, логика не переписана.

    python -m src.wb status                     # все источники: работает ли, сколько осталось, свежесть данных (0–1 запрос)
    python -m src.wb fbs-check                  # Saleflow fbs=1: полный ли октябрь против июля (кисти 437) — 2 запроса
    python -m src.wb collect [--limit 100]      # докачка ниш из очереди (хорошие/пограничные без товаров), стоп при запасе 50
    python -m src.wb screen                     # все ниши → сегменты → копилка → мастер-список (0 запросов)
    python -m src.wb check "<запрос>" ["<запрос2>"] [--sid N]   # живая выдача + ниша изнутри + строка мастер-списка
    python -m src.wb decide                     # решение по текущему товару + срок цикла поиска
    python -m src.wb daily [--tg]               # самообучение: СПП, когорта новичков, прогнозы против факта
    python -m src.wb analyze <sid> --query … --yuan-kw …   # досье: все источники проекта, ворота, решение
    python -m src.wb selftest                   # сквозная проверка проекта (офлайн, 0 запросов)

Порядок работы — README.md; правила — CLAUDE.md; сценарий анализа — /analiz.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(*args: str) -> int:
    print(f"$ python -m {' '.join(args)}")
    return subprocess.run([PY, "-m", *args], cwd=ROOT).returncode


def latest(pattern: str) -> Path | None:
    files = sorted(glob.glob(str(ROOT / pattern)))
    return Path(files[-1]) if files else None


def status() -> None:
    from src.wb_seller import ACC_NAME, collect_tokens
    print(f"СТАТУС ПРОЕКТА — {dt.date.today()}")
    # Saleflow
    try:
        from src.saleflow_stdio import Client
        c = Client()
        try:
            left = c.remaining()
            print(f"  Saleflow       ✅ работает, осталось {left} из 500 (резерв 50)")
        except Exception as e:                                 # noqa: BLE001 — узнаём причину у сервера
            try:
                msg = str(c.call("saleflow_connection_status", {}, cache=False))
            except Exception as e2:                            # noqa: BLE001
                msg = str(e2) or str(e)
            print(f"  Saleflow       ❌ {msg[:220]}")
        finally:
            c.close()
    except Exception as e:                                     # noqa: BLE001 — статус должен показать всё
        print(f"  Saleflow       ❌ не запускается: {str(e)[:110]}")
    # WB Seller API (без запросов)
    toks = collect_tokens()
    if toks:
        for k, v in toks.items():
            exp = v.get("exp").strftime("%Y-%m-%d") if v.get("exp") else "—"
            print(f"  WB Seller API  ✅ {k}: {ACC_NAME.get(v.get('acc'), v.get('acc'))}, до {exp}")
    else:
        print("  WB Seller API  ❌ нет токена в .env")
    # Bright Data
    try:
        from src.brightdata_client import month_used, usage
        used = month_used(usage())
        print(f"  Bright Data    ✅ за месяц {used}, осталось ≈ {5000 - used} из 5000 (стоп при 100)")
    except Exception as e:                                     # noqa: BLE001
        print(f"  Bright Data    ❓ {str(e)[:80]}")
    # Apify, Evirma
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / ".env")
    print(f"  Apify          {'✅ ключ задан' if env.get('APIFY_TOKEN') else '❌ ключа нет'} (баланс: python -m src.apify_client me)")
    ev = latest("data/raw/evirma/*/ranges.json")
    if ev:
        age = (dt.date.today() - dt.date.fromisoformat(ev.parent.name)).days
        print(f"  Evirma (СПП)   {'✅' if age <= 14 else '⚠️'} снимок {ev.parent.name} ({age} дн.)")
    # данные и решения
    m = latest("data/processed/niche_master_*.json")
    if m:
        rows = json.load(open(m, encoding="utf-8"))
        cnt = {s: sum(r["status"] == s for r in rows) for s in ("ХОРОШАЯ", "ПОГРАНИЧНАЯ", "СЛАБАЯ", "ЛОВУШКА")}
        print(f"  Мастер-список  {m.name}: {cnt}")
    q = latest("data/processed/niche_collect_queue_*.json")
    if q:
        print(f"  Очередь сбора  {q.name}: {len(json.load(open(q, encoding='utf-8')))} ниш")
    print("  Данные продаж  июль 2026 — последний проверенный месяц (fbs-check покажет, полный ли октябрь)")
    from src.decision import decide, discovery_warning, load
    c = load()
    print(f"  Решение        {decide(c)['decision']} — {c.get('current_product', '')[:60]}; {discovery_warning(c)}")


def fbs_check() -> None:
    """Главная непроверенная гипотеза: «Saleflow после июля неполный» мог быть артефактом fbs=0."""
    from src.saleflow_stdio import Client
    c = Client()
    try:
        c.guard(2)
        res = {}
        for label, d1, d2 in (("июль", "2026-07-01", "2026-07-31"), ("октябрь", "2026-10-01", "2026-10-31")):
            r = c.call("wb_subject", {"subject_id": 437, "report": "products", "d1": d1, "d2": d2, "limit": 500})
            rows = r.get("data", []) if isinstance(r, dict) else []
            res[label] = (sum(x.get("sales") or 0 for x in rows), sum(1 for x in rows if x.get("sales")))
            print(f"  {label}: продаж в топ-500 {res[label][0]}, карточек с продажами {res[label][1]}")
        ratio = res["октябрь"][0] / res["июль"][0] if res["июль"][0] else 0
        print(f"  октябрь / июль = {ratio:.2f} → " + ("похоже на полные данные: можно брать свежие месяцы" if ratio >= 0.8
                                                    else "октябрь всё ещё заметно ниже: держим июль, проверить сезон"))
    finally:
        c.close()


def collect(limit: int, d1: str, d2: str) -> None:
    from src.saleflow_stdio import Client
    q = latest("data/processed/niche_collect_queue_*.json")
    if not q:
        print("нет очереди: сначала python -m src.wb screen")
        return
    outdir = ROOT / "data" / "raw" / "saleflow" / "v3_products500"
    todo = [x for x in json.load(open(q, encoding="utf-8")) if not (outdir / f"{x['id']}.json").exists()][:limit]
    c = Client()
    try:
        c.guard(len(todo))
        for i, x in enumerate(todo, 1):
            try:
                r = c.call("wb_subject", {"subject_id": x["id"], "report": "products", "d1": d1, "d2": d2, "limit": 500})
            except RuntimeError:
                r = c.call("wb_subject", {"subject_id": x["id"], "report": "products", "d1": d1, "d2": d2, "limit": 100})
            (outdir / f"{x['id']}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
            print(f"  {i}/{len(todo)} {x['id']} {x['subject']}: {len(r.get('data', [])) if isinstance(r, dict) else '?'} строк")
    finally:
        c.close()
    print("дальше: python -m src.wb screen")


def screen() -> None:
    for args in (("src.screen_white", "--all", "--top", "0"), ("src.niche_pool",), ("src.niche_all",)):
        if run(*args):
            print("остановка: шаг завершился с ошибкой")
            return


def check(queries: list[str], sid: int | None, name: str) -> None:
    if queries:
        run("src.radar", "check", *queries, "--name", name)
    if sid:
        run("src.niche_inside", str(sid), "--month", "2026-07")
        m = latest("data/processed/niche_master_*.json")
        row = next((r for r in json.load(open(m, encoding="utf-8")) if r["id"] == sid), None) if m else None
        if row:
            print(f"мастер-список: {row['subject']} — {row['status']}; {'; '.join(row['why']) or 'все пороги'} → {row['todo']}")


def selftest() -> int:
    """Сквозная проверка «проект работает» — офлайн, 0 запросов к Saleflow и Bright Data."""
    from unittest import mock
    results = []

    def step(name, fn):
        try:
            msg = fn() or "ok"
            results.append(("PASS", name, msg))
        except Exception as e:                                 # noqa: BLE001 — показать все шаги
            results.append(("FAIL", name, str(e)[:160]))

    def s_config():
        from src.project_cfg import get
        need = ["data_month", "master.rev_min", "pool.new_p50_min", "dossier.loss_max", "budgets.saleflow_reserve", "benchmark.sid"]
        miss = [k for k in need if get(k) is None]
        assert not miss, f"нет ключей {miss}"
        return f"data_month {get('data_month')}"

    def s_files():
        out = []
        for pat in ("data/processed/niche_master_*.json", "data/processed/niche_pool_*.json", "data/processed/screen_white_*_all.json"):
            f = latest(pat)
            assert f, f"нет {pat} — python -m src.wb screen"
            out.append(f"{f.name}: {len(json.load(open(f, encoding='utf-8')))}")
        return "; ".join(out)

    def s_econ():
        from src import screen_white as sw
        from src.unit_econ import unit_economics
        from src.white_import import landed
        a = sw.econ(2500, 30, 0.6, 0.2, 15, 80, 15, 300)
        b = unit_economics(2500, landed(30, 0.2, 300), 0.6, sw.CFG, with_breakeven=False, buyout_pct=80,
                           ad_share_of_revenue_pct=15, commission_pct=15, tax_rate_pct=10)
        assert abs(a["net_profit"] - b["net_profit"]) < 0.01, "screen_white.econ ≠ unit_economics"
        return f"прибыль/шт {a['net_profit']:.0f} ₽ совпадает"

    def s_dossier():
        from src import dossier
        with mock.patch.object(dossier, "saleflow_blocks", return_value=({}, [], "selftest: Saleflow не вызывается")),              mock.patch.object(dossier, "card_facts", return_value={}):
            r = dossier.build(1142, ["петличный микрофон"], 30, None)
        assert r["decision"] in ("HOLD", "WATCHLIST", "REJECT"), f"решение {r['decision']} выше WATCHLIST без уникальности"
        assert r["bench_month"] > 0, "планка не посчиталась"
        return f"1142 → {r['decision']}, ≈ {r['month_est']} ₽/мес против планки {r['bench_month']}"

    def s_decision():
        from src.decision import decide, discovery_warning, load
        c = load()
        return f"{decide(c)['decision']}; {discovery_warning(c)}"

    def s_tests():
        r = subprocess.run([PY, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, capture_output=True, text=True)
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:]
        assert r.returncode == 0, "тесты упали: " + " ".join(tail)
        return " ".join(tail)

    def s_saleflow():
        try:
            from src.saleflow_stdio import Client
            c = Client()
            try:
                return f"работает, осталось {c.remaining()}"
            finally:
                c.close()
        except Exception as e:                                 # noqa: BLE001 — внешний сервис, не ошибка кода
            return f"ВНЕШНЕЕ: {str(e)[:90]}"

    for name, fn in (("конфиг config/project.yaml", s_config), ("данные: мастер-список, копилка, сегменты", s_files),
                     ("экономика = unit_econ", s_econ), ("досье офлайн (1142)", s_dossier), ("решение текущего товара", s_decision),
                     ("юнит-тесты", s_tests), ("Saleflow (внешний)", s_saleflow)):
        step(name, fn)
    for st_, name, msg in results:
        print(f"  {'✅' if st_ == 'PASS' else '❌'} {name}: {msg}")
    fails = sum(r[0] == "FAIL" for r in results)
    print(f"ИТОГ: {len(results) - fails}/{len(results)} шагов PASS")
    return fails


def main() -> None:
    ap = argparse.ArgumentParser(description="Единая точка входа проекта WB")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status")
    sp.add_parser("fbs-check")
    p = sp.add_parser("collect")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--d1", default="2026-07-01")
    p.add_argument("--d2", default="2026-07-31")
    sp.add_parser("screen")
    p = sp.add_parser("check")
    p.add_argument("queries", nargs="*")
    p.add_argument("--sid", type=int)
    p.add_argument("--name", default="check")
    p = sp.add_parser("analyze", help="досье ниши: все источники проекта в одном анализе")
    p.add_argument("sid", type=int, nargs="?")
    p.add_argument("--query", action="append", default=[], help="формулировка для живой выдачи (можно несколько)")
    p.add_argument("--yuan", type=float)
    p.add_argument("--price", type=float)
    p.add_argument("--top", type=int, help="досье для N лучших кандидатов копилки")
    p.add_argument("--yuan-kw", help="ключевые слова офферов 1688 через запятую (фильтр шумной выдачи)")
    p.add_argument("--offer", type=int, help="конкретный оффер 1688 — цена нужной комплектации (1 кредит, если не скачан)")
    p.add_argument("--abroad", help="доказательство спроса за рубежом (ссылка + цифра), если нет файла Exa")
    p.add_argument("--complaints", action="store_true", help="запустить разбор отзывов WB (бесплатно, 5–15 мин)")
    p.add_argument("--vol", type=float, help="объём упаковки, л (КП/замер), если в карточках WB нет габаритов")
    p.add_argument("--no-saleflow", action="store_true", help="не обращаться к Saleflow (сбой/401) — блоки 4–7 помечаются")
    sp.add_parser("decide")
    sp.add_parser("selftest", help="сквозная проверка проекта (офлайн)")
    p = sp.add_parser("daily")
    p.add_argument("--tg", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status":
        status()
    elif a.cmd == "fbs-check":
        fbs_check()
    elif a.cmd == "collect":
        collect(a.limit, a.d1, a.d2)
    elif a.cmd == "screen":
        screen()
    elif a.cmd == "check":
        check(a.queries, a.sid, a.name)
    elif a.cmd == "analyze":
        from src import dossier
        if a.top:
            dossier.batch(a.top)
        elif a.sid:
            kw = [k.strip() for k in a.yuan_kw.split(",")] if a.yuan_kw else None
            r = dossier.build(a.sid, a.query, a.yuan, a.price, kw, a.offer, a.abroad, a.complaints, a.vol, not a.no_saleflow)
            print(Path(ROOT / f"reports/dossier_{a.sid}_{dt.date.today()}.md").read_text(encoding="utf-8"))
            print(f"\n→ reports/dossier_{a.sid}_{dt.date.today()}.md; решение {r['decision']}")
        else:
            print("укажите sid или --top N")
    elif a.cmd == "selftest":
        sys.exit(1 if selftest() else 0)
    elif a.cmd == "decide":
        run("src.decision")
    else:
        run("src.learning", "daily", *(["--tg"] if a.tg else []))


if __name__ == "__main__":
    main()
