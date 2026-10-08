"""MPSTATS API client: кэш на диске, защита от 429/202, учёт лимита запросов.

Базовые URL:
  https://mpstats.io/api/analytics/v1/wb   — новые отчёты Wildberries
  https://mpstats.io/api/analytics/v1/oz   — Ozon
  https://mpstats.io/api                   — служебные методы (лимит API)

Авторизация: заголовок X-Mpstats-TOKEN (токен из mpstats.io/userpanel).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

API_ROOT = "https://mpstats.io/api"
BASES = {
    "wb": f"{API_ROOT}/analytics/v1/wb",
    "oz": f"{API_ROOT}/analytics/v1/oz",
    "root": API_ROOT,
}
ROOT = Path(__file__).resolve().parents[1]
MAX_ROWS_PER_REQUEST = 500  # жёсткое ограничение API


def load_env(path: Path = ROOT / ".env") -> None:
    """Минималистичный .env-лоадер (без внешних зависимостей)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class MpstatsError(RuntimeError):
    pass


def rows(payload: Any) -> list[dict]:
    """Приводит ответ API к списку строк."""
    if isinstance(payload, dict):
        for key in ("data", "items", "result"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []
    return payload if isinstance(payload, list) else []


class MpstatsClient:
    def __init__(
        self,
        token: str | None = None,
        market: str = "wb",
        cache_dir: Path | str = ROOT / "data" / "cache",
        cache_ttl: int = 86_400,
        timeout: float = 90.0,
        max_retries: int = 4,
        quiet: bool = False,
    ) -> None:
        load_env()
        self.token = (token or os.environ.get("MPSTATS_TOKEN", "")).strip()
        if not self.token:
            raise MpstatsError(
                "MPSTATS_TOKEN չկա։ Պատճենիր .env.example -> .env և դիր թոքենը "
                "(mpstats.io/userpanel -> API token)."
            )
        self.market = market
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.max_retries = max_retries
        self.quiet = quiet
        self.api_calls = 0      # реальные обращения к API
        self.cache_hits = 0
        self.session = requests.Session()

    # ------------------------------------------------------------------ infra
    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(f"[mpstats] {msg}", flush=True)

    def _cache_path(self, method: str, url: str, params: dict | None, body: dict | None) -> Path:
        blob = json.dumps([method, url, params, body], sort_keys=True, ensure_ascii=False)
        return self.cache_dir / f"{hashlib.sha1(blob.encode()).hexdigest()}.json"

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        base: str | None = None,
        ttl: int | None = None,
        force: bool = False,
    ) -> Any:
        base_url = BASES.get(base or self.market, base or BASES["wb"])
        url = path if path.startswith("http") else f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        ttl = self.cache_ttl if ttl is None else ttl

        cache_file = self._cache_path(method, url, params, body)
        if not force and ttl > 0 and cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - cached["ts"] < ttl:
                self.cache_hits += 1
                return cached["data"]

        headers = {
            "X-Mpstats-TOKEN": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        delay = 5.0
        for attempt in range(1, self.max_retries + 1):
            self.api_calls += 1
            resp = self.session.request(
                method.upper(), url, params=params, headers=headers,
                json=body if method.upper() == "POST" else None, timeout=self.timeout,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise MpstatsError(f"Ответ не JSON: {resp.text[:300]}") from exc
                if ttl > 0:
                    cache_file.write_text(
                        json.dumps({"ts": time.time(), "url": url, "params": params, "data": data},
                                   ensure_ascii=False),
                        encoding="utf-8",
                    )
                return data
            if resp.status_code == 202:              # отчёт ещё готовится
                self._log(f"202 — отчёт готовится, жду {delay:.0f}s ({attempt}/{self.max_retries})")
            elif resp.status_code == 429:            # лимит тарифа
                delay = float(resp.headers.get("Retry-After", delay))
                self._log(f"429 — лимит API, жду {delay:.0f}s ({attempt}/{self.max_retries})")
            elif resp.status_code == 401:
                raise MpstatsError("401 — неверный или просроченный токен MPSTATS.")
            elif resp.status_code >= 500:
                self._log(f"{resp.status_code} — ошибка сервера, повтор через {delay:.0f}s")
            else:
                raise MpstatsError(f"{resp.status_code}: {resp.text[:400]}")
            time.sleep(delay)
            delay = min(delay * 2, 60)
        raise MpstatsError(f"Не удалось получить {url} за {self.max_retries} попыток.")

    @staticmethod
    def _body(start: int, limit: int, sort_by: str | None, sort_dir: str,
              filters: dict | None) -> dict:
        limit = min(max(1, int(limit)), MAX_ROWS_PER_REQUEST)
        return {
            "startRow": max(0, int(start)),
            "endRow": max(0, int(start)) + limit,
            "filterModel": filters or {},
            "sortModel": [{"colId": sort_by, "sort": sort_dir}] if sort_by else [],
        }

    # ---------------------------------------------------------------- методы
    def api_limit(self) -> dict:
        """Остаток лимита запросов по тарифу. Вызывать перед тяжёлой серией."""
        return self.request("GET", "user/report_api_limit", base="root", ttl=0)

    def category_tree(self, query: str = "", date: str | None = None, limit: int = 200) -> list[dict]:
        """Дерево категорий. Нужен ТОЧНЫЙ path — все остальные отчёты идут по нему."""
        data = self.request("POST", "category/list", params={"date": date},
                            body=self._body(0, MAX_ROWS_PER_REQUEST, None, "desc", None),
                            ttl=21_600)
        result = rows(data)
        needle = query.strip().lower()
        if needle:
            result = [r for r in result
                      if needle in str(r.get("path", "")).lower()
                      or needle in str(r.get("name", "")).lower()]
        return result[:limit]

    def category_report(self, path: str, report: str, d1: str, d2: str, start: int = 0,
                        limit: int = 500, sort_by: str | None = "revenue", sort_dir: str = "desc",
                        filters: dict | None = None, fbs: int | None = None, ttl: int | None = None) -> Any:
        """report: items | categories | brands | sellers | trends | by_date |
        price_segmentation | subjects | keywords | warehouses | geography"""
        params = {"path": path, "d1": d1, "d2": d2}
        if fbs is not None:
            params["fbs"] = fbs
        return self.request("POST", f"category/{report}", params,
                            self._body(start, limit, sort_by, sort_dir, filters), ttl=ttl)

    def category_items_all(self, path: str, d1: str, d2: str, max_rows: int = 1500,
                           filters: dict | None = None, fbs: int | None = None) -> list[dict]:
        """Постраничная выкачка товаров категории (по 500 строк = 1 единица лимита)."""
        out: list[dict] = []
        for start in range(0, max_rows, MAX_ROWS_PER_REQUEST):
            chunk = rows(self.category_report(path, "items", d1, d2, start=start,
                                              limit=MAX_ROWS_PER_REQUEST, filters=filters, fbs=fbs))
            out.extend(chunk)
            if len(chunk) < MAX_ROWS_PER_REQUEST:
                break
        return out

    def subject_report(self, subject: str, report: str, d1: str, d2: str, start: int = 0,
                       limit: int = 500, sort_by: str | None = "revenue", sort_dir: str = "desc",
                       fbs: int | None = None) -> Any:
        """Ниша (предмет) WB: items | brands | sellers | trends | by_date | keywords | similar ..."""
        params = {"path": subject, "d1": d1, "d2": d2}
        if fbs is not None:
            params["fbs"] = fbs
        return self.request("POST", f"subject/{report}", params,
                            self._body(start, limit, sort_by, sort_dir, None))

    def item(self, sku: str | int, report: str = "card", d1: str | None = None,
             d2: str | None = None, date: str | None = None) -> Any:
        """card | full | by_period | sales/stores | balance/stores | keywords |
        search_stats | comments | faq | photos_history"""
        table = {
            "card": "", "full": "full", "by_period": "by_period",
            "sales": "sales/stores", "sales_sizes": "sales/sizes",
            "balance": "balance/stores", "balance_sizes": "balance/sizes",
            "keywords": "keywords", "search_stats": "search_stats",
            "comments": "comments", "faq": "faq", "photos_history": "photos_history",
        }
        suffix = table.get(report, report)
        path = f"items/{sku}" + (f"/{suffix}" if suffix else "")
        return self.request("GET", path, {"d1": d1, "d2": d2, "date": date})

    def similar(self, sku: str | int, report: str = "items", family: str = "similar",
                d1: str | None = None, d2: str | None = None, limit: int = 100) -> Any:
        """family: similar | identical | identical_wb | in_similar"""
        return self.request("POST", f"{family}/{report}", {"path": str(sku), "d1": d1, "d2": d2},
                            self._body(0, limit, "revenue", "desc", None))

    def compare(self, value: str, d11: str, d12: str, d21: str, d22: str,
                entity: str = "category", limit: int = 100) -> Any:
        """Сравнение двух периодов: category | brand | seller | subject."""
        return self.request("POST", f"{entity}/compare",
                            {"path": value, "d11": d11, "d12": d12, "d21": d21, "d22": d22},
                            self._body(0, limit, None, "desc", None))

    def forecast(self, path: str, report: str = "forecast/trend", entity: str = "category",
                 period: str | None = None) -> Any:
        """forecast/daily | forecast/trend | season_effects/annual | season_effects/weekly"""
        return self.request("GET", f"{entity}/{report}", {"path": path, "period": period})


# --------------------------------------------------------------- budget plan
COSTS = {
    "discover_screen": ("Էժան մաղ (discover --depth 2)", 22, "~600 ենթա-նիշա"),
    "probe": ("Զոնդ 1 նիշայի վրա (մոնոպոլիա+աճ)", 2, "1 նիշա"),
    "deep": ("Խորը սքան 1 նիշայի վրա (500 քարտ)", 2, "1 նիշա"),
    "trend": ("18-ամսյա դինամիկա 1 նիշայի վրա", 6, "1 նիշա"),
    "sku": ("1 մրցակցի աուդիտ (քարտ+վաճառք+բառեր+նմանատիպ)", 4, "1 SKU"),
}


def plan_budget(remaining: int | None = None) -> None:
    """Ասում է՝ մնացած լիմիտով ինչ ծավալի հետազոտություն է հնարավոր."""
    if remaining is None:
        data = MpstatsClient().api_limit()
        text = json.dumps(data, ensure_ascii=False)
        candidates = []
        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (int, float)) and any(
                            w in k.lower() for w in ("left", "remain", "balance", "available")):
                        candidates.append(int(v))
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
        walk(data)
        remaining = max(candidates) if candidates else None
        print(f"[limit] {text}")
        if remaining is None:
            print("\n⚠️ Չհաջողվեց ավտոմատ կարդալ մնացորդը։ Գործարկիր՝ "
                  "python -m src.mpstats_client plan --remaining <թիվ>")
            return

    print(f"\nՄնացած լիմիտ՝ ~{remaining} հարցում\n")
    print(f"{'Գործողություն':<44}{'Արժեք':>7}{'Ծածկույթ':>18}")
    print("─" * 70)
    for _, (label, cost, cover) in COSTS.items():
        print(f"{label:<44}{cost:>7}{cover:>18}")

    print("\nՊԱՏՐԱՍՏԻ ՍՑԵՆԱՐՆԵՐ")
    print("─" * 70)
    scenarios = [
        ("Ամբողջական որոնում զրոյից", 22 + 10 * 2 + 5 * 2,
         "~600 մաղված, 10 զոնդ, 5 խորը"),
        ("  + 18-ամսյա դինամիկա տոպ-3-ի վրա", 22 + 10 * 2 + 5 * 2 + 3 * 6,
         "նույնը + սեզոն/հագեցում"),
        ("  + 5 մրցակցի աուդիտ", 22 + 10 * 2 + 5 * 2 + 3 * 6 + 5 * 4,
         "մինչև ապրանքի բրիֆ"),
        ("Շաբաթական մոնիտորինգ (10 նիշա)", 10 * 2, "10 նիշայի թարմացում"),
    ]
    for label, cost, cover in scenarios:
        mark = "✅" if remaining >= cost else "❌ չի հերիքում"
        print(f"{label:<44}{cost:>7}  {mark}  ({cover})")

    screen_budget = max(0, remaining - 22)
    print(f"\nՄնացորդով կարող ես զոնդել ~{screen_budget // 2} նիշա "
          f"կամ խորը սքանել ~{screen_budget // 2} նիշա։")
    print("💡 Քեշը միացված է (24ժ) — նույն հարցումը կրկնելը լիմիտ ՉԻ ծախսում։")


# ---------------------------------------------------------------------- CLI
def main() -> None:
    parser = argparse.ArgumentParser(description="MPSTATS API CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("limit", help="остаток лимита запросов")
    p_plan = sub.add_parser("plan", help="ինչքան նիշա կարող ես ստուգել մնացած լիմիտով")
    p_plan.add_argument("--remaining", type=int, help="ձեռքով նշել մնացած հարցումները")
    p_cat = sub.add_parser("categories", help="поиск пути категории")
    p_cat.add_argument("query")
    p_cat.add_argument("--limit", type=int, default=40)
    p_raw = sub.add_parser("raw", help="сырой вызов метода")
    p_raw.add_argument("path")
    p_raw.add_argument("--post", action="store_true")
    p_raw.add_argument("--param", action="append", default=[], metavar="K=V")
    p_raw.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.cmd == "plan":
        plan_budget(args.remaining)
        return

    client = MpstatsClient()
    if args.cmd == "limit":
        print(json.dumps(client.api_limit(), ensure_ascii=False, indent=2))
    elif args.cmd == "categories":
        for row in client.category_tree(args.query, limit=args.limit):
            print(f"{row.get('path')}")
    else:
        params = dict(p.split("=", 1) for p in args.param)
        body = client._body(0, args.limit, "revenue", "desc", None) if args.post else None
        data = client.request("POST" if args.post else "GET", args.path, params, body)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:8000])
    print(f"\n[api_calls={client.api_calls} cache_hits={client.cache_hits}]")


if __name__ == "__main__":
    main()
