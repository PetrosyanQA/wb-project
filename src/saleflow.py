"""SALEFLOW ադապտեր — MCP-ի պատասխանները դարձնում է նույն շարքերը, ինչ MPStats-ը.

Saleflow-ը **MCP սերվեր** է (ոչ թե REST API), այսինքն՝ հարցումներն անում է ոչ թե
Python-ը, այլ ինքը՝ Claude-ը։ Ուստի կամուրջն այսպիսին է.

    Claude (MCP tool call)  →  JSON պատասխան
            ↓  պահում է անփոփոխ
    data/raw/saleflow/<tool>_<sha1>.json          ← հում ապացույց, վերստուգելի
            ↓  src.saleflow normalize
    նույն սխեման, ինչ MPStats items  →  niche_metrics / gates / unit_econ

Ինչ է սա տալիս.
  • հում պատասխանը պահվում է → կարող ես վերագործարկել վերլուծությունը առանց նոր հարցման
  • քեշ TTL-ով → նույն հարցումը երկու անգամ չի գնում
  • **երկու աղբյուրի խաչաստուգում** — MPStats vs Saleflow նույն նիշայի վրա

CLI:
    python -m src.saleflow ingest file.json --tool items --note "Дом/Хранение"
    python -m src.saleflow list
    python -m src.saleflow show <sha1>
    python -m src.saleflow crosscheck --mpstats data/raw/mps_items.json --saleflow <sha1>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fields import fnum, median, pick

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "saleflow"
INDEX = RAW / "_index.json"
DEFAULT_TTL_H = 24


# ─────────────────────────────────────────────────────────── պահպանում
def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _atomic_write(path: Path, text: str) -> None:
    """Запись через временный файл + replace: оборванная запись не портит индекс/ответ."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_raw(payload: Any, tool: str, note: str = "") -> Path:
    """Պահում է MCP-ի պատասխանը ԱՆՓՈՓՈԽ + գրանցում ինդեքսում."""
    RAW.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = _sha(tool, note, body)                     # [аудит 2026-11-02] хэш по ВСЕМУ ответу (было body[:4000] → коллизии)
    path = RAW / f"{tool}_{digest}.json"
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=1))

    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    index[digest] = {"tool": tool, "note": note, "file": path.name,
                     "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "ts": time.time(), "rows": len(extract_rows(payload))}
    _atomic_write(INDEX, json.dumps(index, ensure_ascii=False, indent=1))
    return path


def load_index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def fresh(digest: str, ttl_hours: int = DEFAULT_TTL_H) -> bool:
    entry = load_index().get(digest)
    return bool(entry) and (time.time() - entry.get("ts", 0)) < ttl_hours * 3600


def load_raw(digest: str) -> Any:
    entry = load_index().get(digest)
    if not entry:
        raise FileNotFoundError(f"{digest} չկա ինդեքսում")
    return json.loads((RAW / entry["file"]).read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────── նորմալացում
def extract_rows(payload: Any, _depth: int = 0) -> list[dict]:
    """MCP-ի պատասխանի խորքից գտնում է տողերի ցուցակը (սխեման նախապես հայտնի չէ)."""
    if _depth > 6:
        return []
    if isinstance(payload, list):
        dicts = [x for x in payload if isinstance(x, dict)]
        return dicts if len(dicts) >= max(1, len(payload) // 2) else []
    if isinstance(payload, dict):
        # MCP content-блок՝ {"content":[{"type":"text","text":"{...json...}"}]}
        content = payload.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    try:
                        return extract_rows(json.loads(block["text"]), _depth + 1)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
        best: list[dict] = []
        for key in ("data", "items", "rows", "result", "results", "products", "cards",
                    "list", "goods", "payload"):
            if key in payload:
                found = extract_rows(payload[key], _depth + 1)
                if len(found) > len(best):
                    best = found
        if best:
            return best
        for value in payload.values():
            found = extract_rows(value, _depth + 1)
            if len(found) > len(best):
                best = found
        return best
    return []


SCHEMA = ("id", "name", "brand", "seller", "revenue", "sales", "price", "rating",
          "comments", "balance", "start_date", "category")


def normalize(payload: Any, source: str = "saleflow") -> list[dict]:
    """→ MPStats-ի items-ի հետ նույն դաշտերով տողեր (աշխատում է `fields.ALIASES`-ով)."""
    out = []
    for row in extract_rows(payload):
        item = {key: pick(row, key) for key in SCHEMA}
        if item["id"] is None and item["name"] is None:
            continue
        for key in ("revenue", "sales", "price", "rating", "comments", "balance"):
            item[key] = fnum(row, key)
        item["_source"] = source
        item["_raw_keys"] = len(row)
        out.append(item)
    return out


# ─────────────────────────────────────────────────── երկու աղբյուրի խաչաստուգում
def crosscheck(mps_items: list[dict], sf_items: list[dict]) -> dict:
    """Նույն նիշան երկու աղբյուրով՝ որքանո՞վ են համընկնում թվերը."""
    def by_id(items):
        out = {}
        for i in items:
            key = str(pick(i, "id") or pick(i, "name") or "")
            if key:
                out[key] = i
        return out

    a, b = by_id(mps_items), by_id(sf_items)
    common = sorted(set(a) & set(b))
    diffs = []
    for key in common:
        ra, rb = fnum(a[key], "revenue"), fnum(b[key], "revenue")
        if ra > 0 and rb > 0:
            diffs.append(abs(ra - rb) / max(ra, rb) * 100)
    rev_a = sum(fnum(i, "revenue") for i in mps_items)
    rev_b = sum(fnum(i, "revenue") for i in sf_items)
    med_diff = round(median(diffs), 1) if diffs else None
    if not common or rev_a <= 0 or rev_b <= 0:
        verdict = "⚪️ չհամեմատվեց — կողմերից մեկում շրջանառություն չկա (ստուգիր դաշտերի ալիասները)"
    elif med_diff is None:
        verdict = "⚪️ ընդհանուր SKU-ներ չգտնվեցին"
    else:
        verdict = "🟢 աղբյուրները համաձայն են"
    if med_diff is not None and med_diff > 35:
        verdict = "🔴 աղբյուրները խիստ տարբերվում են — մի՛ վստահիր ոչ մեկին առանց 3-րդի"
    elif med_diff is not None and med_diff > 15:
        verdict = "🟡 նկատելի տարբերություն — որոշման համար վերցրու ավելի ՊԱՀՊԱՆՈՂԱԿԱՆԸ"
    return {
        "mpstats_rows": len(mps_items), "saleflow_rows": len(sf_items),
        "matched": len(common),
        "median_revenue_diff_pct": med_diff,
        "total_revenue_mpstats": round(rev_a), "total_revenue_saleflow": round(rev_b),
        "total_diff_pct": round(abs(rev_a - rev_b) / max(rev_a, rev_b, 1) * 100, 1),
        "verdict": verdict,
        "conservative_revenue": round(min(rev_a, rev_b)),
    }


# ─────────────────────────────────────────────────────────────────── CLI
# ── Saleflow Analytics API (saleflow.pro) ────────────────────────────────────
# Հայտնաբերված է զոնդավորմամբ 2026-10-03՝
#   endpoint     https://saleflow.pro/api/mcp   (JSON-RPC 2.0, MCP over HTTP)
#   auth         Authorization: Bearer <token>  ← ՄԻԱՅՆ այս ձևը ճանաչվում է
#   վավեր թոքեն  → 403 {"error":"API token auth not enabled for this user"}
#   կեղծ թոքեն   → 401 "Invalid API token"
#   առանց թոքեն  → 200 HTML login էջ
# Այսինքն՝ 403-ը նշանակում է «թոքենը ճիշտ է, բայց հաշվի վրա API-ն միացված չէ»։

SALEFLOW_BASE = "https://saleflow.pro"
SALEFLOW_MCP = "/api/mcp"


def _token() -> str:
    import os
    if not os.environ.get("SALEFLOW_TOKEN"):
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("SALEFLOW_TOKEN=") and line.split("=", 1)[1].strip():
                    os.environ["SALEFLOW_TOKEN"] = line.split("=", 1)[1].strip()
    tok = os.environ.get("SALEFLOW_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("SALEFLOW_TOKEN չկա .env-ում")
    return tok


def rpc(method: str, params: dict | None = None, timeout: int = 20) -> dict:
    """JSON-RPC հարցում Saleflow MCP-ին. Բարձրացնում է պարզ սխալ 401/403-ի դեպքում."""
    import urllib.error
    import urllib.request
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(
        SALEFLOW_BASE + SALEFLOW_MCP, data=body,
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as f:
            raw = f.read().decode("utf-8", "replace")
        if raw.lstrip().startswith("data:"):              # SSE
            raw = "\n".join(l[5:].strip() for l in raw.splitlines()
                            if l.startswith("data:"))
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace").strip()
        if e.code == 403 and "not enabled" in detail:
            raise RuntimeError(
                "Թոքենը ՎԱՎԵՐ է, բայց Saleflow-ի հաշվի վրա API-ն միացված չէ։\n"
                "   → saleflow.pro → Личный кабинет → Настройки / API → միացրու "
                "«API доступ» (հնարավոր է՝ սակագնային փաթեթի հատկություն է)։\n"
                f"   Սերվերի պատասխանը՝ {detail}") from e
        if e.code == 401:
            raise RuntimeError(f"Թոքենը մերժվեց (401): {detail}") from e
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e


def probe() -> dict:
    """Ստուգում է Saleflow-ի հասանելիությունը և, եթե բաց է, քաշում գործիքների ցանկը."""
    import urllib.error
    import urllib.request
    out: dict[str, Any] = {"base": SALEFLOW_BASE, "endpoint": SALEFLOW_MCP}
    try:
        tok = _token()
        out["token"] = f"задан ({len(tok)} символов)"          # [аудит 2026-11-02] не показываем даже часть ключа
    except RuntimeError as e:
        out["error"] = str(e)
        return out
    try:
        res = rpc("tools/list")
        tools = (res.get("result") or {}).get("tools") or []
        out["status"] = "🟢 միացված"
        out["tools"] = [{"name": t.get("name"), "desc": (t.get("description") or "")[:70]}
                        for t in tools]
    except RuntimeError as e:
        out["status"] = "🔴 փակ"
        out["error"] = str(e)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Saleflow MCP → նորմալացված տվյալներ")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_in = sub.add_parser("ingest", help="պահել MCP-ի JSON պատասխանը ('-' = stdin)")
    p_in.add_argument("file", help="JSON ֆայլ, կամ '-' որ պատճենես ուղիղ տերմինալ")
    p_in.add_argument("--tool", default="items")
    p_in.add_argument("--note", default="")

    sub.add_parser("list", help="ինչ է պահված")
    sub.add_parser("probe", help="ստուգել Saleflow API-ի հասանելիությունը (live)")

    p_show = sub.add_parser("show", help="նորմալացված տողեր")
    p_show.add_argument("digest")
    p_show.add_argument("--limit", type=int, default=10)

    p_cc = sub.add_parser("crosscheck", help="MPStats vs Saleflow")
    p_cc.add_argument("--mpstats", required=True, help="JSON ֆայլ MPStats items-ով")
    p_cc.add_argument("--saleflow", required=True, help="sha1 ինդեքսից կամ ֆայլի ուղի")

    args = p.parse_args()

    if args.cmd == "ingest":
        if args.file == "-":
            import sys
            raw = sys.stdin.read()
        else:
            raw = Path(args.file).read_text(encoding="utf-8")
        raw = raw.strip()
        if raw.startswith("```"):                      # markdown ցանկապատ՝ չատից պատճենելիս
            raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```"))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
            end = max(raw.rfind("}"), raw.rfind("]"))
            if start < 0 or end <= start:
                raise SystemExit("❌ JSON չգտնվեց։ Պատճենիր ամբողջ պատասխանը՝ { ... } կամ [ ... ]")
            payload = json.loads(raw[start:end + 1])
        path = save_raw(payload, args.tool, args.note)
        rows = normalize(payload)
        print(f"✔ պահված՝ {path}")
        print(f"  տողեր՝ {len(rows)}")
        if rows:
            filled = [k for k in SCHEMA if rows[0].get(k) not in (None, "", 0)]
            missing = [k for k in SCHEMA if k not in filled]
            print(f"  ճանաչված դաշտեր՝ {', '.join(filled)}")
            if missing:
                print(f"  ⚠️ չճանաչված՝ {', '.join(missing)} → ավելացրու ալիաս src/fields.py-ում")

    elif args.cmd == "probe":
        r = probe()
        print(f"\nSaleflow Analytics  {r['base']}{r['endpoint']}")
        print(f"  Թոքեն՝  {r.get('token', '—')}")
        print(f"  Վիճակ՝  {r.get('status', '—')}")
        if r.get("tools"):
            print(f"\n  Հասանելի գործիքներ ({len(r['tools'])}).")
            for t in r["tools"]:
                print(f"    • {t['name']:<28}{t['desc']}")
        if r.get("error"):
            print(f"\n  {r['error']}")
        print()

    elif args.cmd == "list":
        index = load_index()
        if not index:
            print("Դատարկ է։ Claude-ին ասա՝ MCP պատասխանը պահի data/raw/saleflow/-ում,"
                  " հետո՝ python -m src.saleflow ingest <ֆայլ>")
            return
        print(f"{'sha1':<14}{'tool':<16}{'տողեր':>7}  {'ժամանակ':<22}նշում")
        for digest, e in sorted(index.items(), key=lambda kv: -kv[1]["ts"]):
            age = (time.time() - e["ts"]) / 3600
            mark = "🟢" if age < DEFAULT_TTL_H else "⚪️"
            print(f"{digest:<14}{e['tool']:<16}{e['rows']:>7}  {mark} {e['saved_at']:<20}{e['note']}")

    elif args.cmd == "show":
        rows = normalize(load_raw(args.digest))
        for row in rows[: args.limit]:
            print(json.dumps({k: v for k, v in row.items() if not k.startswith("_")},
                             ensure_ascii=False))
        print(f"\nԸնդամենը՝ {len(rows)} տող")

    elif args.cmd == "crosscheck":
        mps = normalize(json.loads(Path(args.mpstats).read_text(encoding="utf-8")), "mpstats")
        sf_path = Path(args.saleflow)
        sf_payload = (json.loads(sf_path.read_text(encoding="utf-8"))
                      if sf_path.exists() else load_raw(args.saleflow))
        sf = normalize(sf_payload)
        res = crosscheck(mps, sf)
        for key, value in res.items():
            print(f"{key:<26}{value}")


if __name__ == "__main__":
    main()
