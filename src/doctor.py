"""ԱՌՈՂՋՈՒԹՅԱՆ ՍՏՈՒԳՈՒՄ — գործարկիր ԱՄԵՆԱԱՌԱՋԻՆԸ, երբ թոքենը դրել ես.

  python -m src.doctor --path "Дом/Кухня"
  python -m src.doctor --demo        # ստուգում է հենց ստուգիչի տրամաբանությունը

Ինչու է սա պետք.
Կոդը գրված է MPSTATS-ի փաստաթղթերի հիման վրա, բայց **դաշտերի իրական անունները**
կարող են տարբերվել ըստ տարիֆի և ըստ հաշվետվության։ Այս սկրիպտը 6–8 հարցումով.
  1. ստուգում է՝ ամեն էնդփոյնթ պատասխանո՞ւմ է
  2. ցույց է տալիս, թե մեր սպասած դաշտերից որոնք ՉԵՆ գտնվել
  3. տալիս է իրական բանալիների ցանկը → ուղղակի պատճենում ես ինձ, և ես ուղղում եմ fields.py-ն

Առանց սրա առաջին իրական գործարկումը կարող է տալ 0-եր և թվալ «չի աշխատում»։
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from .fields import ALIASES, pick
from .mpstats_client import MpstatsClient, MpstatsError, rows

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

# ── Գաղտնիքների ավտոմատ քողարկում, որ ելքը ապահով ուղարկես ──────────────────
import re as _re

SECRET_PATTERNS = [
    (_re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]+)?"), "<JWT-ԹՈՔԵՆ-ՔՈՂԱՐԿՎԱԾ>"),
    (_re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<HEX-ԳԱՂՏՆԻՔ-ՔՈՂԱՐԿՎԱԾ>"),
    (_re.compile(r"(?i)^([\w.\-]*(?:token|api[_-]?key|secret|authorization|auth[_-]?header|password)[\w.\-]*)\s*[:=]\s*\S+",
                 _re.MULTILINE), r"\1=<ՔՈՂԱՐԿՎԱԾ>"),
    (_re.compile(r"(?i)\bBearer\s+\S+"), "Bearer <ՔՈՂԱՐԿՎԱԾ>"),
    (_re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "<BASE64-ՔՈՂԱՐԿՎԱԾ>"),
]


def sanitize(text: str) -> str:
    """Հեռացնում է թոքենները ելքից՝ դաշտերի անունները թողնելով."""
    for pattern, repl in SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text

# Ո՞ր տրամաբանական դաշտերն են կրիտիկական ամեն հաշվետվության համար
REQUIRED = {
    "category/items": ["id", "name", "revenue", "sales", "price", "comments", "rating",
                       "seller", "brand", "balance", "start_date"],
    "category/categories": ["name", "revenue", "sales"],
    "category/by_date": ["date", "revenue"],
}
OPTIONAL_NOTE = {
    "start_date": "առանց սրա չի աշխատի «թարմ քարտերի հաջողություն» ցուցանիշը",
    "comments": "առանց սրա չի աշխատի կարծիքների բարիերը",
    "seller": "առանց սրա չի աշխատի մոնոպոլիայի ստուգումը",
    "balance": "ազդում է միայն պաշարների գնահատականի վրա",
}


def check_fields(report: str, sample: dict) -> tuple[list[str], list[str], list[str]]:
    """→ (գտնված, չգտնված, իրական բանալիներ)"""
    found, missing = [], []
    for logical in REQUIRED.get(report, []):
        if pick(sample, logical) is not None:
            found.append(logical)
        else:
            missing.append(logical)
    return found, missing, sorted(sample.keys())


def demo_payloads(path: str) -> dict:
    """Սինթետիկ պատասխաններ՝ ստուգիչի տրամաբանությունը փորձարկելու համար.
    Դիտմամբ պակասում է `start_date`-ը և `seller`-ի փոխարեն դրված է `supplier_name`."""
    return {
        "api_limit": {"ok": True, "data": {"requests_left": 480}},
        "category/list": [{"path": path, "name": "Кухня"}],
        "category/categories": [{"name": "Аксессуары", "revenue": 4_200_000, "sales": 3100}],
        "category/items": [{
            "id": 123456, "name": "Органайзер", "revenue": 184000, "sales": 126,
            "final_price": 1460, "comments": 212, "rating": 4.8,
            "supplier_name": "ООО Ромашка", "brand": "HomeLine", "balance": 340,
        }],
        "category/by_date": [{"date": "2026-09-01", "revenue": 142000, "sales": 98}],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="MPSTATS/WB integration doctor")
    p.add_argument("--path", default="Дом/Кухня", help="ստուգման կատեգորիա (իրական path)")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--share", action="store_true",
                   help="գրել նաև reports/doctor_share.md՝ գաղտնիքները քողարկված (ապահով ուղարկելու համար)")
    args = p.parse_args()

    today = date.today()
    d2, d1 = str(today - timedelta(days=1)), str(today - timedelta(days=30))
    lines = [f"# Doctor — {today}", "", f"Ստուգման path՝ `{args.path}`", ""]
    problems: list[str] = []
    calls = 0

    if args.demo:
        payloads = demo_payloads(args.path)
        lines.append("_DEMO ռեժիմ՝ սինթետիկ պատասխաններով_\n")
    else:
        payloads = {}
        try:
            client = MpstatsClient()
        except MpstatsError as exc:
            print(f"❌ {exc}")
            return
        steps = [
            ("api_limit", lambda: client.api_limit()),
            ("category/list", lambda: client.category_tree(args.path.split("/")[0], limit=5)),
            ("category/categories", lambda: rows(client.category_report(
                args.path, "categories", d1, d2, limit=20))),
            ("category/items", lambda: rows(client.category_report(
                args.path, "items", d1, d2, limit=20))),
            ("category/by_date", lambda: rows(client.category_report(
                args.path, "by_date", d1, d2, limit=60, sort_by=None))),
        ]
        for name, fn in steps:
            try:
                payloads[name] = fn()
                print(f"✅ {name}")
            except Exception as exc:                          # noqa: BLE001
                payloads[name] = None
                problems.append(f"`{name}` → {exc}")
                print(f"❌ {name}: {exc}")
        calls = client.api_calls

    # ── 1. Կապ ────────────────────────────────────────────────────────────
    lines += ["## 1. Կապ և իրավունքներ", "", "| Էնդփոյնթ | Կարգավիճակ | Տողեր |", "|---|---|---|"]
    for name, payload in payloads.items():
        if payload is None:
            lines.append(f"| `{name}` | ❌ սխալ | — |")
        elif isinstance(payload, list):
            lines.append(f"| `{name}` | {'✅' if payload else '⚠️ դատարկ'} | {len(payload)} |")
        else:
            lines.append(f"| `{name}` | ✅ | — |")

    # ── 2. Դաշտերի քարտեզագրում ───────────────────────────────────────────
    lines += ["", "## 2. Դաշտերի քարտեզագրում (ամենակարևոր մասը)", ""]
    for report in ("category/items", "category/categories", "category/by_date"):
        payload = payloads.get(report)
        if not payload or not isinstance(payload, list):
            continue
        found, missing, keys = check_fields(report, payload[0])
        lines += [f"### `{report}`", "",
                  f"- ✅ Գտնված՝ {', '.join(f'`{f}`' for f in found) or '—'}"]
        if missing:
            lines.append(f"- ❌ **Չգտնված՝ {', '.join(f'`{m}`' for m in missing)}**")
            for m in missing:
                note = OPTIONAL_NOTE.get(m)
                if note:
                    lines.append(f"  - `{m}` — {note}")
                problems.append(f"`{report}` → չգտնված դաշտ `{m}` "
                                f"(ալիասներ՝ {', '.join(ALIASES.get(m, ()))})")
        lines += ["", "<details><summary>Իրական բանալիները</summary>", "",
                  "```", ", ".join(keys), "```", "</details>", ""]

    # ── 3. WB Seller API ──────────────────────────────────────────────────
    lines += ["## 3. WB Seller API", ""]
    if args.demo:
        lines.append("_(demo ռեժիմում չի ստուգվում)_")
    else:
        try:
            from .wb_seller import WBSellerClient
            wb = WBSellerClient()
            wb.tariffs_box()
            lines.append("- ✅ `Тарифы` հասանելի է")
        except Exception as exc:                              # noqa: BLE001
            lines.append(f"- ⚠️ WB API անհասանելի՝ {exc}")

    # ── 4. Եզրակացություն ─────────────────────────────────────────────────
    lines += ["", "## 4. Եզրակացություն", ""]
    if not problems:
        lines += ["🟢 **Ամեն ինչ կարգին է** — կարող ես գործարկել `discover` և `niche_scan`։"]
    else:
        lines += [f"🟠 **Գտնվել է {len(problems)} խնդիր.**", ""]
        lines += [f"{i}. {p}" for i, p in enumerate(problems, 1)]
        lines += ["", "### Ինչ անել",
                  "1. Եթե խնդիրը **դաշտի անունն** է — պատճենիր «Իրական բանալիները» բաժինը "
                  "և ուղարկիր ինձ, ես կուղղեմ `src/fields.py`-ի `ALIASES`-ը (1 րոպե)։",
                  "2. Եթե խնդիրը **403/401** է — թոքենի իրավունքներն են պակասում։",
                  "3. Եթե **դատարկ պատասխան** է — path-ը սխալ է. "
                  "`python -m src.mpstats_client categories \"<բառ>\"`։"]
    lines += ["", f"_Ծախսվեց ~{calls} API հարցում_"]

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"doctor_{today:%Y%m%d}.md"
    body = "\n".join(lines)
    out.write_text(body, encoding="utf-8")
    print("\n".join(lines[-14:]))
    print(f"\n✔ {out}")

    share = REPORTS / "doctor_share.md"
    share.write_text(sanitize(body), encoding="utf-8")
    print(f"✔ {share}  ← ԱՅՍ ֆայլը կարող ես ապահով ուղարկել (գաղտնիքները քողարկված են)")


if __name__ == "__main__":
    main()
