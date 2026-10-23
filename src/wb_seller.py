"""WB Seller API client (պաշտոնական API վաճառողի կաբինետից).

Հոսթեր՝ ամեն կատեգորիա իր դոմենի վրա է։ Authorization: <token> (առանց Bearer-ի)։
Թոքենը՝ WB Partners → Настройки → Доступ к API → **Только на чтение**։
Ժամկետը՝ 180 օր, հետո պետք է վերաթողարկել։

⚠️ Rate limit-երը խիստ են (օր. commission = 1 հարցում/րոպե, statistics = 1/րոպե),
այդ պատճառով ամեն մեթոդ ունի throttle + քեշ։
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .mpstats_client import load_env

ROOT = Path(__file__).resolve().parents[1]

HOSTS = {
    "common":      "https://common-api.wildberries.ru",
    "content":     "https://content-api.wildberries.ru",
    "stats":       "https://statistics-api.wildberries.ru",
    "analytics":   "https://seller-analytics-api.wildberries.ru",
    "advert":      "https://advert-api.wildberries.ru",
    "supplies":    "https://supplies-api.wildberries.ru",
    "feedbacks":   "https://feedbacks-api.wildberries.ru",
    "marketplace": "https://marketplace-api.wildberries.ru",
    "discounts":   "https://discounts-prices-api.wildberries.ru",
    "finance":     "https://finance-api.wildberries.ru",
}

# Նվազագույն ինտերվալ վայրկյաններով (WB-ի պաշտոնական լիմիտներից, պահուստով)
THROTTLE = {
    "/api/v1/tariffs/commission": 62.0,
    "/api/finance/v1/sales-reports": 62.0,
    "/api/v1/tariffs/box": 1.5,
    "/api/v1/tariffs/pallet": 1.5,
    "/api/v1/tariffs/return": 1.5,
    "/api/v1/acceptance/coefficients": 10.0,
    "/api/tariffs/v1/acceptance/coefficients": 10.0,
    "/api/v1/supplier/orders": 62.0,
    "/api/v1/supplier/sales": 62.0,
    "/api/analytics/v3/sales-funnel/products": 21.0,
    "/content/v2/object/all": 1.0,
    "/adv/v1/promotion/count": 1.0,
}
_LAST_CALL: dict[str, float] = {}


class WBError(RuntimeError):
    pass


def rub(value: Any, default: float = 0.0) -> float:
    """WB-ն թվերը տալիս է որպես '11,2' կամ '-' → float."""
    if value in (None, "", "-"):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return default



# ── Բազմա-թոքեն աջակցություն ─────────────────────────────────────────────────
# WB-ն խորհուրդ է տալիս 1-3 կատեգորիա մեկ թոքենում։ Ուստի .env-ում կարող են լինել՝
#   WB_TOKEN_TARIFFS=...      (Тарифы, Контент, Поставки)
#   WB_TOKEN_SALES=...        (Статистика, Аналитика, Вопросы и отзывы)
#   WB_SELLER_TOKEN=...       (հին՝ մեկ ընդհանուր թոքեն, դեռ աշխատում է)
# Կոդը ինքը կարդում է ամեն թոքենի bitmask-ը և ուղարկում հարցումը ԱՅՆ թոքենով,
# որն ունի տվյալ կատեգորիան — ամենաքիչ իրավունք ունեցողին նախապատվությամբ։

HOST_BIT = {                       # ո՞ր բիթն է պետք տվյալ հոսթի համար
    "content": 1, "analytics": 2, "discounts": 3, "marketplace": 4,
    "stats": 5, "advert": 6, "feedbacks": 7, "supplies": 10, "finance": 13,
    "common": None,                # Тарифы՝ աշխատում է ցանկացած թոքենով
}
BIT_NAME = {1: "Контент", 2: "Аналитика", 3: "Цены и скидки", 4: "Маркетплейс",
            5: "Статистика", 6: "Продвижение", 7: "Вопросы и отзывы",
            10: "Поставки", 13: "Финансы", 30: "только чтение"}


def token_bits(token: str) -> dict:
    """JWT payload → {bits, acc, exp, readonly, sandbox} (զուտ base64, առանց հարցման)."""
    import base64
    from datetime import datetime, timezone
    try:
        payload = token.strip().replace("Bearer ", "").split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:                                          # noqa: BLE001
        return {"bits": set(), "acc": None, "exp": None, "readonly": False, "sandbox": False}
    mask = int(data.get("s", 0))
    return {
        "bits": {b for b in list(BIT_NAME) if mask >> b & 1},
        "acc": data.get("acc"),
        "exp": datetime.fromtimestamp(int(data["exp"]), timezone.utc) if data.get("exp") else None,
        "readonly": bool(mask >> 30 & 1),
        "sandbox": bool(data.get("t")),
    }


def collect_tokens() -> dict[str, dict]:
    """Բոլոր WB թոքենները .env-ից՝ WB_SELLER_TOKEN + ցանկացած WB_TOKEN_*."""
    load_env()
    out: dict[str, dict] = {}
    for key, value in os.environ.items():
        if not value or not value.strip():
            continue
        if key == "WB_SELLER_TOKEN" or key.startswith("WB_TOKEN_"):
            info = token_bits(value)
            info["token"] = value.strip()
            out[key] = info
    return out


ACC_NAME = {1: "Base", 2: "Test", 3: "Personal", 4: "Service"}


class WBSellerClient:
    max_wait: float = 120.0          # 429-ի դեպքում ավելի երկար չենք սպասում

    def __init__(self, token: str | None = None, cache_dir: Path | str = ROOT / "data" / "cache_wb",
                 cache_ttl: int = 21_600, timeout: float = 60.0, quiet: bool = False) -> None:
        load_env()
        if token:
            self.tokens = {"explicit": {**token_bits(token), "token": token.strip()}}
        else:
            self.tokens = collect_tokens()
        if not self.tokens:
            raise WBError("WB թոքեն չկա .env-ում։ Ավելացրու WB_SELLER_TOKEN կամ "
                          "WB_TOKEN_TARIFFS / WB_TOKEN_SALES (WB Partners → Доступ к API).")
        self.token = next(iter(self.tokens.values()))["token"]   # հետընթաց համատեղելիություն
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.quiet = quiet
        self.api_calls = 0
        self.cache_hits = 0
        self.session = requests.Session()

    def token_for(self, host: str) -> tuple[str, str]:
        """→ (թոքեն, որ .env-բանալիից). Ընտրում է ամենաքիչ իրավունք ունեցողը."""
        bit = HOST_BIT.get(host)
        fit = [(k, v) for k, v in self.tokens.items()
               if (bit is None or bit in v["bits"]) and not v.get("sandbox")]   # sandbox-ключ на боевых хостах → 403
        if not fit:
            need = BIT_NAME.get(bit, host)
            have = {BIT_NAME[b] for v in self.tokens.values() for b in v["bits"] if b in BIT_NAME}
            raise WBError(f"Ոչ մի թոքեն չունի «{need}» կատեգորիան։ "
                          f"Առկա են՝ {', '.join(sorted(have)) or '—'}։ "
                          f"Ավելացրու նոր թոքեն .env-ում՝ WB_TOKEN_<անուն>=...")
        key, info = min(fit, key=lambda kv: len(kv[1]["bits"]))   # least privilege
        return info["token"], key

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(f"[wb] {msg}", flush=True)

    def _throttle(self, path: str) -> None:
        interval = next((v for k, v in THROTTLE.items() if path.startswith(k)), 0.5)
        last = _LAST_CALL.get(path, 0.0)
        wait = interval - (time.time() - last)
        if wait > 0:
            self._log(f"throttle {path}: սպասում {wait:.0f}s")
            time.sleep(wait)
        _LAST_CALL[path] = time.time()

    def request(self, method: str, host: str, path: str, params: dict | None = None,
                body: dict | list | None = None, ttl: int | None = None, force: bool = False) -> Any:
        url = f"{HOSTS[host]}{path}"
        token, token_key = self.token_for(host)
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        ttl = self.cache_ttl if ttl is None else ttl
        key = hashlib.sha1(json.dumps([method, url, params, body], sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        if not force and ttl > 0 and cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - cached["ts"] < ttl:
                self.cache_hits += 1
                return cached["data"]

        headers = {"Authorization": token, "Content-Type": "application/json"}
        for attempt in range(1, 5):
            self._throttle(path)
            self.api_calls += 1
            resp = self.session.request(method.upper(), url, params=params, headers=headers,
                                        json=body, timeout=self.timeout)
            if resp.status_code in (200, 201):
                data = resp.json() if resp.content else {}
                if ttl > 0:
                    cache_file.write_text(json.dumps({"ts": time.time(), "data": data},
                                                     ensure_ascii=False), encoding="utf-8")
                return data
            if resp.status_code == 429:
                wait = float(resp.headers.get("X-Ratelimit-Retry", 60))
                if wait > self.max_wait:
                    raise WBError(
                        f"429 {path}: լիմիտը սպառված է, WB-ն խնդրում է սպասել "
                        f"{wait/60:.0f} րոպե։ Base-թոքենի դեպքում որոշ մեթոդներ "
                        f"սահմանափակված են 1 հարցում/ժամ — սարքիր Personal access token։")
                self._log(f"429 {path} — սպասում {wait:.0f}s ({attempt}/4)")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                raise WBError("401 — թոքենը սխալ է, ժամկետանց է կամ չունի այս կատեգորիայի իրավունք.")
            if resp.status_code == 403:
                raise WBError("403 — թոքենին պակասում է կատեգորիա (Тарифы/Статистика/Аналитика).")
            if resp.status_code >= 500:
                time.sleep(5 * attempt)
                continue
            raise WBError(f"{resp.status_code} {path}: {resp.text[:300]}")
        raise WBError(f"{path}: 4 փորձ անհաջող")

    # ------------------------------------------------------------- ТАРИФЫ
    def tariffs_box(self, day: str | None = None) -> dict:
        """Լոգիստիկա + պահեստավորում ըստ պահեստի (короба). 60 հարցում/րոպե."""
        return self.request("GET", "common", "/api/v1/tariffs/box",
                            {"date": day or str(date.today())})

    def tariffs_pallet(self, day: str | None = None) -> dict:
        return self.request("GET", "common", "/api/v1/tariffs/pallet",
                            {"date": day or str(date.today())})

    def tariffs_return(self, day: str | None = None) -> dict:
        """Հետադարձ լոգիստիկայի տարիֆներ."""
        return self.request("GET", "common", "/api/v1/tariffs/return",
                            {"date": day or str(date.today())})

    def tariffs_commission(self) -> dict:
        """Կոմիսիա ըստ предмет-ի և վաճառքի մոդելի. ⚠️ 1 հարցում/րոպե."""
        return self.request("GET", "common", "/api/v1/tariffs/commission", ttl=86_400)

    def acceptance_coefficients(self, warehouse_ids: list[int] | None = None) -> Any:
        """Приёмка-ի գործակիցներ 14 օրվա համար.

        `common-api/api/tariffs/v1/...` աշխատում է ՑԱՆԿԱՑԱԾ կատեգորիայի թոքենով
        (Base-ի դեպքում՝ 1 հարցում/ժամ)։ `supplies-api`-ի FBW մեթոդները պահանջում են
        Personal/Service թոքեն — Base-ի դեպքում վերադարձնում են 404։
        """
        params = {}
        if warehouse_ids:
            params["warehouseIDs"] = ",".join(str(w) for w in warehouse_ids)
        try:
            return self.request("GET", "common", "/api/tariffs/v1/acceptance/coefficients",
                                params, ttl=3600)
        except WBError as exc:
            if "temporarily disabled" in str(exc):
                raise WBError("Приёмка-ի գործակիցները WB-ն ԺԱՄԱՆԱԿԱՎՈՐ անջատել է "
                              "(dev.wildberries.ru/release-notes?id=570) — ոչ թե թոքենի խնդիր։ "
                              "Օգտագործիր кабинет → Поставки → Коэффициенты приёмки։") from exc
            self._log(f"common-api acceptance ձախողվեց ({exc}) → փորձում ենք supplies-api")
            return self.request("GET", "supplies", "/api/v1/acceptance/coefficients",
                                params, ttl=3600)

    def subjects(self, name: str = "", limit: int = 50, locale: str = "ru") -> Any:
        """Предмет-ների ցանկ (subjectID պետք է քարտի և կոմիսիայի համար)."""
        return self.request("GET", "content", "/content/v2/object/all",
                            {"name": name, "limit": limit, "locale": locale}, ttl=86_400)

    def characteristics(self, subject_id: int, locale: str = "ru") -> Any:
        """Предмет-ի բնութագրերը՝ որոնք պարտադիր են քարտի համար (SEO-ի հումք)."""
        return self.request("GET", "content", f"/content/v2/object/charcs/{subject_id}",
                            {"locale": locale}, ttl=86_400)

    # --------------------------------------------------------- СТАТИСТИКА
    def orders(self, date_from: str, flag: int = 0) -> Any:
        """Պատվերներ. ⚠️ 1 հարցում/րոպե."""
        return self.request("GET", "stats", "/api/v1/supplier/orders",
                            {"dateFrom": date_from, "flag": flag}, ttl=3600)

    def sales(self, date_from: str, flag: int = 0) -> Any:
        """Վաճառքներ/վերադարձներ. ⚠️ 1 հարցում/րոպե."""
        return self.request("GET", "stats", "/api/v1/supplier/sales",
                            {"dateFrom": date_from, "flag": flag}, ttl=3600)

    def report_detail_by_period(self, date_from: str, date_to: str, rrdid: int = 0,
                                limit: int = 100_000, period: str = "weekly") -> Any:
        """Детализация отчётов реализации — фактические удержания WB.

        Старый GET statistics-api /api/v5/supplier/reportDetailByPeriod отключён (release-notes id=498, 404 с
        2026-10). Новый: POST finance-api /api/finance/v1/sales-reports/detailed, токен категории «Финансы»
        (бит 13), 1 запрос/мин. Поля в camelCase: retailPriceWithDisc, retailAmount, spp, commissionPercent,
        ppvzSalesCommission, vw, vwNds, forPay, docTypeName, nmId.
        """
        return self.request("POST", "finance", "/api/finance/v1/sales-reports/detailed",
                            body={"dateFrom": date_from, "dateTo": date_to, "limit": limit,
                                  "rrdId": rrdid, "period": period}, ttl=3600)

    # ---------------------------------------------------------- АНАЛИТИКА
    def funnel(self, nm_ids: list[int], d1: str, d2: str, page: int = 1,
               past: bool = False) -> Any:
        """Воронка продаж v3 (v2 `/api/v2/nm-report/detail` անջատված է 09.12.2025).

        Սխեման փոխվել է՝ `period` → `selectedPeriod`, `nmIDs` → `nmIds`,
        էջերի փոխարեն՝ cursor-pagination։
        """
        body: dict[str, Any] = {"selectedPeriod": {"start": d1, "end": d2}}
        if nm_ids:
            body["nmIds"] = list(nm_ids)[:1000]
        if past:
            body["pastPeriod"] = {"start": d1, "end": d2}
        return self.request("POST", "analytics",
                            "/api/analytics/v3/sales-funnel/products",
                            body=body, ttl=3600)

    def advert_count(self) -> Any:
        """Գովազդային արշավների ցանկ (ստուգում՝ Продвижение կատեգորիան միացա՞ծ է)."""
        return self.request("GET", "advert", "/adv/v1/promotion/count", ttl=1800)

    def advert_stats(self, campaigns: list[dict]) -> Any:
        """POST /adv/v2/fullstats — փաստացի CPC/CPM/ДРР."""
        return self.request("POST", "advert", "/adv/v2/fullstats", body=campaigns, ttl=1800)


# ------------------------------------------------------------------- CLI
TOKEN_BITS = {1: "Контент", 2: "Аналитика", 3: "Цены и скидки", 4: "Маркетплейс",
              5: "Статистика", 6: "Продвижение", 7: "Вопросы и отзывы",
              9: "Чат с покупателями", 10: "Поставки", 11: "Возвраты покупателями",
              12: "Документы", 13: "Финансы", 16: "Пользователи", 30: "ТОЛЬКО НА ЧТЕНИЕ"}
NEEDED = {1: "предмет-ների ID (պարտադիր)", 2: "վաճառքի ձագար", 5: "выкуп % հաշվարկ",
          10: "приёмка-ի գործակիցներ"}


def decode_token(token: str | None = None) -> dict:
    """Ցույց է տալիս .env-ի ԲՈԼՈՐ WB թոքենները՝ իրավունքներ, տիպ, ժամկետ, երթուղղում.
    Զուտ base64 ապակոդավորում — ոչ մի հարցում չի ուղարկվում."""
    tokens = ({"explicit": {**token_bits(token), "token": token}} if token
              else collect_tokens())
    if not tokens:
        print("❌ WB թոքեն չկա .env-ում (WB_SELLER_TOKEN կամ WB_TOKEN_*)")
        return {}

    from datetime import datetime, timezone
    print("WB թոքեններ (ապակոդավորված տեղում, հարցում չի արվել)\n")
    for key, info in tokens.items():
        cats = ", ".join(BIT_NAME[b] for b in sorted(info["bits"]) if b != 30) or "—"
        acc = ACC_NAME.get(info["acc"], f"acc={info['acc']}")
        left = (info["exp"] - datetime.now(timezone.utc)).days if info["exp"] else None
        flags = []
        if info["readonly"]:
            flags.append("🔒 только чтение")
        else:
            flags.append("⚠️ ԳՐԵԼՈՒ ԻՐԱՎՈՒՆՔՈՎ")
        if info["sandbox"]:
            flags.append("⚠️ sandbox")
        if acc == "Base":
            flags.append("⚠️ Base — որոշ մեթոդներ 1 հարցում/ժամ")
        print(f"  {key}")
        print(f"     տիպ՝ {acc} | {' | '.join(flags)}"
              + (f" | 📅 {left} օր" if left is not None else ""))
        print(f"     կատեգորիաներ՝ {cats}")

    print("\nԵրթուղղում (ո՞ր թոքենով է գնալու ամեն հարցում)\n")
    print(f"  {'Հոսթ':<12}{'Կատեգորիա':<20}{'Թոքեն':<22}Ինչի համար")
    print("  " + "─" * 86)
    use = {"common": "տարիֆներ, կոմիսիա, приёмка", "content": "предмет-ների ID",
           "stats": "քո պատվերներ/վաճառքներ", "analytics": "վաճառքի ձագար v3",
           "supplies": "FBW պահեստներ", "advert": "գովազդ", "feedbacks": "կարծիքներ"}
    dummy = WBSellerClient.__new__(WBSellerClient)
    dummy.tokens = tokens
    for host, why in use.items():
        bit = HOST_BIT.get(host)
        try:
            _, key = WBSellerClient.token_for(dummy, host)
            mark, name = "✅", key
        except WBError:
            mark, name = "❌", "— չկա —"
        print(f"  {mark} {host:<10}{BIT_NAME.get(bit, 'любая'):<20}{name:<22}{why}")

    missing = [n for b, n in BIT_NAME.items()
               if b in (1, 2, 5, 10) and not any(b in v["bits"] for v in tokens.values())]
    if missing:
        print(f"\n  Պակասում է՝ {', '.join(missing)}")
    return tokens


def main() -> None:
    p = argparse.ArgumentParser(description="WB Seller API CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="ստուգել թոքենը և հասանելի կատեգորիաները")
    sub.add_parser("decode", help="կարդալ .env-ի թոքենի իրավունքները ԱՌԱՆՑ հարցման")
    p_box = sub.add_parser("box", help="պահեստների լոգիստիկա/պահեստավորում")
    p_box.add_argument("--warehouse", default="")
    p_com = sub.add_parser("commission", help="կոմիսիա ըստ предмет-ի")
    p_com.add_argument("--subject", default="")
    p_acc = sub.add_parser("acceptance", help="приёмка-ի գործակիցներ")
    p_acc.add_argument("--free-only", action="store_true")
    p_sub = sub.add_parser("subjects", help="предмет-ների որոնում")
    p_sub.add_argument("name")
    args = p.parse_args()

    c = WBSellerClient()
    if args.cmd == "decode":
        decode_token()
        return

    if args.cmd == "check":
        from datetime import date as _date, timedelta as _td
        yday = (_date.today() - _td(days=1)).isoformat()
        checks = [
            ("Тарифы",            "ՊԱՐՏԱԴԻՐ — լոգիստիկա, պահեստավորում, կոմիսիա (sync_tariffs)",
             lambda: c.tariffs_box()),
            ("Контент",           "ՊԱՐՏԱԴԻՐ — предмет-ների ID և բնութագրեր",
             lambda: c.subjects("нож", 1)),
            ("Статистика",        "ՑԱՆԿԱԼԻ — քո իրական պատվերներ/վաճառքներ (wb_facts buyout)",
             lambda: c.orders(yday)),
            ("Аналитика",         "ՑԱՆԿԱԼԻ — վաճառքի ձագար v3 (ցուցադրում→զամբյուղ→պատվեր)",
             lambda: c.funnel([], yday, yday)),
            ("Поставки",          "ՕԳՏԱԿԱՐ — приёмка-ի գործակիցներ ըստ պահեստի",
             lambda: c.acceptance_coefficients()),
            ("Продвижение",       "ՈՉ ՊԱՐՏԱԴԻՐ — գովազդային վիճակագրություն",
             lambda: c.advert_count()),
        ]
        print(f"{'Կատեգորիա':<14}{'Կարգավիճակ':<34}Ինչի համար է")
        print("─" * 100)
        missing = []
        for label, why, fn in checks:
            try:
                fn()
                status = "✅ հասանելի"
            except WBError as exc:
                msg = str(exc)
                if "401" in msg or "403" in msg:
                    status = "❌ չկա թոքենում"
                    missing.append(label)
                elif "429" in msg:
                    status = "⏳ լիմիտ (Base-թոքեն?)"
                else:
                    status = f"⚠️ {msg[:22]}"
            print(f"{label:<14}{status:<34}{why}")
        print()
        if missing:
            print("Պակասող կատեգորիաները՝ " + ", ".join(missing))
            print("WB Partners → Профиль → Настройки → Доступ к API → Создать новый токен →")
            print("նշիր դրանք + ☑️ «Только на чтение» → նոր թոքենը դիր .env-ում")
        else:
            print("🟢 Բոլոր կատեգորիաները տեղում են")

    elif args.cmd == "box":
        data = c.tariffs_box()
        whs = (data.get("response", {}).get("data", {}).get("warehouseList", []))
        whs = [w for w in whs if args.warehouse.lower() in str(w.get("warehouseName", "")).lower()]
        print(f"{'Պահեստ':<28}{'1լ ₽':>8}{'+1լ ₽':>8}{'коэф%':>8}{'պահեստ. ₽/լ/օր':>16}")
        for w in whs[:40]:
            print(f"{str(w.get('warehouseName'))[:27]:<28}{rub(w.get('boxDeliveryBase')):>8.1f}"
                  f"{rub(w.get('boxDeliveryLiter')):>8.1f}{rub(w.get('boxDeliveryCoefExpr')):>8.0f}"
                  f"{rub(w.get('boxStorageLiter')):>16.3f}")
    elif args.cmd == "commission":
        data = c.tariffs_commission()
        rowset = data.get("report", data.get("data", []))
        needle = args.subject.lower()
        hits = [r for r in rowset if needle in str(r.get("subjectName", "")).lower()][:30]
        print(f"{'Предмет':<38}{'FBO%':>7}{'FBS%':>7}{'DBS%':>7}")
        for r in hits:
            print(f"{str(r.get('subjectName'))[:37]:<38}{rub(r.get('paidStorageKgvp')):>7.1f}"
                  f"{rub(r.get('kgvpMarketplace')):>7.1f}{rub(r.get('kgvpSupplier')):>7.1f}")
    elif args.cmd == "acceptance":
        data = c.acceptance_coefficients()
        items = data if isinstance(data, list) else data.get("data", [])
        for row in items[:60]:
            coef = row.get("coefficient")
            if args.free_only and coef not in (0, "0"):
                continue
            print(f"{str(row.get('date'))[:10]}  {str(row.get('warehouseName'))[:24]:<26}"
                  f"coef={coef}  {row.get('boxTypeName')}")
    elif args.cmd == "subjects":
        data = c.subjects(args.name, 50)
        for row in (data.get("data") or []):
            print(f"{row.get('subjectID'):>8}  {row.get('subjectName')}  ← {row.get('parentName')}")
    print(f"\n[wb api_calls={c.api_calls} cache_hits={c.cache_hits}]")


if __name__ == "__main__":
    try:
        main()
    except WBError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1)
