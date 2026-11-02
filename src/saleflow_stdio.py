"""Прямой stdio-клиент к локальному Saleflow MCP (server.cjs) — запасной путь, когда коннектор в Claude теряет сессию
("Missing session ID"). Запускает свой экземпляр сервера (новая upstream-сессия), ответы пишет сразу на диск.

    python -m src.saleflow_stdio status
    python -m src.saleflow_stdio call wb_subject '{"subject_id": 1594, "report": "products", ...}' --out file.json
    python -m src.saleflow_stdio products 1594 937 --d1 2026-07-01 --d2 2026-07-31 --outdir data/raw/saleflow/v3_products500
    (файл <ниша>.json — его находят datastore.products / screen_white; limit 500, при ошибке — 100)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Saleflow MCP")
TIMEOUT_S = int(os.environ.get("SF_TIMEOUT", "240"))   # [аудит 2026-11-01] ответ дольше — ошибка, а не вечное ожидание
ROOT = Path(__file__).resolve().parents[1]
from src.project_cfg import get as _P  # noqa: E402
RESERVE = _P("budgets.saleflow_reserve", 50)          # не опускать дневной остаток ниже (config/project.yaml)
CACHE_TTL_S = 24 * 3600
FBS_TOOLS = {"wb_subject", "wb_similar", "wb_brand", "wb_category_stats", "wb_compare", "wb_seller", "wb_category"}
NO_CACHE = {"account_limits", "saleflow_connection_status", "wb_check_rates"}   # живое — всегда свежее


def prepare_args(tool: str, args: dict) -> dict:
    """fbs=1 по умолчанию: при fbs=0 с августа 2026 продажи — единицы процентов (описание инструментов Saleflow/MPSTATS)."""
    a = dict(args)
    if tool in FBS_TOOLS and "fbs" not in a:
        a["fbs"] = 1
    return a


def _key(tool: str, args: dict) -> str:
    return hashlib.sha1(json.dumps([tool, args], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def cache_get(tool: str, args: dict):
    f = ROOT / "data" / "cache" / "saleflow" / f"{tool}_{_key(tool, args)}.json"
    if tool in NO_CACHE or not f.exists() or time.time() - f.stat().st_mtime > CACHE_TTL_S:
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def cache_put(tool: str, args: dict, res) -> None:
    d = ROOT / "data" / "cache" / "saleflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tool}_{_key(tool, args)}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")


def save_raw(tool: str, args: dict, res) -> None:
    """Правило CLAUDE.md: каждый ответ Saleflow — сырой JSON в data/raw/saleflow/<дата>/<инструмент>/."""
    if tool in ("account_limits", "saleflow_connection_status"):
        return
    d = ROOT / "data" / "raw" / "saleflow" / str(dt.date.today()) / tool
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_key(tool, args)}.json").write_text(json.dumps({"args": args, "response": res}, ensure_ascii=False), encoding="utf-8")


def _server_cmd() -> list[str]:
    cfg = json.load(open(os.path.join(os.environ["APPDATA"], "Claude", "claude_desktop_config.json"), encoding="utf-8"))
    s = cfg["mcpServers"]["saleflow_universal"]
    return [s["command"], *s["args"]]


class Client:
    def __init__(self) -> None:
        self.p = subprocess.Popen(_server_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(os.environ.get("SF_ERRLOG", os.devnull), "ab"))
        self.n = 0
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: [self.q.put(x) for x in iter(self.p.stdout.readline, b"")] + [self.q.put(b"")],
                         daemon=True).start()
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                "clientInfo": {"name": "mpstats-research", "version": "1.0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        self.p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            try:
                line = self.q.get(timeout=TIMEOUT_S)
            except queue.Empty:
                raise RuntimeError(f"Saleflow не ответил за {TIMEOUT_S} с ({method})") from None
            if not line:
                raise RuntimeError("Saleflow server закрылся")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def call(self, tool: str, args: dict, cache: bool = True):
        args = prepare_args(tool, args)
        hit = cache_get(tool, args) if cache else None
        if hit is not None:
            return hit
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        if r.get("isError"):
            if "401" in text:
                raise RuntimeError("Saleflow 401: токен недействителен — перевыпустите токен в кабинете saleflow.pro "
                                   "и вставьте в конфиг Claude Desktop (saleflow_universal, AUTH_HEADER) и .env")
            raise RuntimeError(text[:300])
        try:
            res = json.loads(text)
        except json.JSONDecodeError:
            res = text
        save_raw(tool, args, res)
        if cache and tool not in NO_CACHE:
            cache_put(tool, args, res)
        return res

    def remaining(self) -> int | None:
        r = self.call("account_limits", {}, cache=False)
        return r.get("remaining") if isinstance(r, dict) else None

    def guard(self, need: int) -> None:
        """Стоп, если после `need` запросов останется меньше резерва (CLAUDE.md: держать ≥ 50)."""
        left = self.remaining()
        if left is not None and left - need < RESERVE:
            raise RuntimeError(f"Saleflow: осталось {left}, нужно {need}, резерв {RESERVE} — стоп")

    def close(self) -> None:
        self.p.stdin.close()
        self.p.terminate()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "call", "products"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--outdir")
    ap.add_argument("--d1", default="2026-07-01")
    ap.add_argument("--d2", default="2026-07-31")
    a = ap.parse_args()
    c = Client()
    try:
        if a.cmd == "status":
            print(c.call("account_limits", {}))
        elif a.cmd == "call":
            res = c.call(a.rest[0], json.loads(a.rest[1]) if len(a.rest) > 1 else {})
            if a.out:
                json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"→ {a.out}")
            else:
                print(json.dumps(res, ensure_ascii=False)[:2000])
        else:
            os.makedirs(a.outdir, exist_ok=True)
            for sid in a.rest:
                f = os.path.join(a.outdir, f"{sid}.json")    # [аудит 2026-11-01] было products_<sid>_<месяц>.json — никто не читал
                try:
                    args = {"subject_id": int(sid), "report": "products", "d1": a.d1, "d2": a.d2}
                    try:
                        res = c.call("wb_subject", {**args, "limit": 500})
                    except RuntimeError:
                        res = c.call("wb_subject", {**args, "limit": 100})   # limit 500 у Saleflow иногда падает (18.10)
                    json.dump(res, open(f, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"{sid}: {len(res.get('data', [])) if isinstance(res, dict) else '?'} строк → {f}")
                except Exception as e:                      # noqa: BLE001 — продолжаем остальные ниши
                    print(f"{sid}: ошибка {str(e)[:200]}")
    finally:
        c.close()


if __name__ == "__main__":
    main()
