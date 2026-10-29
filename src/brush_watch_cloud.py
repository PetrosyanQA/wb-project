"""Мониторинг кистей (437) в облаке (GitHub Actions): сам берёт данные Saleflow по HTTP и вызывает src.brush_watch.

    python -m src.brush_watch_cloud probe     # проверить доступ к Saleflow API и список инструментов (без отправки)
    python -m src.brush_watch_cloud hourly    # 3 запроса wb_check_rates → brush_watch hourly
    python -m src.brush_watch_cloud daily     # by_period по каждому SKU (10–11 запросов) → brush_watch daily

Токен — переменная SALEFLOW_TOKEN (секрет GitHub), Telegram — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID. Токены не печатаются.
Состояние между запусками — WATCH_STATE_DIR (workflow: cloud_state/watch437, коммитится обратно).
Если Saleflow отвечает 403 / «не куплен» / «not enabled» → brush_watch status --down (сообщение только при смене статуса).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get("SALEFLOW_MCP_URL", "https://saleflow.pro/api/mcp")
CFG = yaml.safe_load((ROOT / "config" / "watch_437.yaml").read_text(encoding="utf-8"))


class Saleflow:
    """Минимальный MCP-клиент по HTTP (JSON-RPC 2.0, ответ JSON или SSE)."""

    def __init__(self) -> None:
        tok = os.environ.get("SALEFLOW_TOKEN", "").strip()
        if not tok:
            raise RuntimeError("нет SALEFLOW_TOKEN")
        self.h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                  "Accept": "application/json, text/event-stream"}
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                "clientInfo": {"name": "brush-watch-cloud", "version": "1.0"}})
        self.notify("notifications/initialized")

    def _post(self, body: dict) -> requests.Response:
        r = requests.post(URL, json=body, headers=self.h, timeout=120)
        if sid := r.headers.get("Mcp-Session-Id"):
            self.h["Mcp-Session-Id"] = sid
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r

    def notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        raw = self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}).text
        if raw.lstrip().startswith(("event:", "data:")):
            raw = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")][-1]
        d = json.loads(raw)
        if d.get("error"):
            raise RuntimeError(str(d["error"])[:300])
        return d.get("result") or {}

    def tool(self, name: str, args: dict):
        res = self.rpc("tools/call", {"name": name, "arguments": args})
        txt = "".join(c.get("text", "") for c in res.get("content") or [] if c.get("type") == "text")
        if res.get("isError"):
            raise RuntimeError(txt[:300])
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            s = txt.find("```json")                                       # ответ с текстом + блоком JSON
            if s >= 0:
                return json.loads(txt[s + 7:txt.find("```", s + 7)])
            raise RuntimeError(f"не JSON: {txt[:200]}")


def bw(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "src.brush_watch", *args], check=True, cwd=ROOT)


def blocked(e: Exception) -> bool:
    s = str(e)
    return any(k in s for k in ("403", "не куплен", "not enabled", "401"))


def run(mode: str) -> None:
    try:
        sf = Saleflow()
        if mode == "probe":
            tools = sf.rpc("tools/list", {}).get("tools") or []
            print("инструментов:", len(tools), [t["name"] for t in tools if t["name"].startswith("wb_")][:15])
            return
        out = Path(tempfile.mkdtemp())
        files = []
        if mode == "hourly":
            q = CFG["queries"]
            calls = [{"query": q[0], "region": "Москва", "limit": 30}, {"query": q[-1], "region": "Москва", "limit": 30},
                     {"query": q[0], "region": "Москва", "limit": 100, "skus": [int(s) for s in CFG["competitors"]] + list(CFG.get("our_skus") or [])}]
            for i, a in enumerate(calls):
                p = out / f"rates_{i}.json"
                p.write_text(json.dumps(sf.tool("wb_check_rates", a), ensure_ascii=False), encoding="utf-8")
                files.append(str(p))
        else:
            d2 = dt.date.today() - dt.timedelta(days=1)
            for sku in [int(s) for s in CFG["competitors"]] + list(CFG.get("our_skus") or []):
                p = out / f"bp_{sku}.json"
                p.write_text(json.dumps(sf.tool("wb_sku", {"report": "by_period", "sku": sku, "d1": str(d2 - dt.timedelta(days=14)),
                                                          "d2": str(d2)}), ensure_ascii=False), encoding="utf-8")
                files.append(str(p))
    except Exception as e:                                                # noqa: BLE001
        print("Saleflow:", str(e)[:200])
        if blocked(e) and mode != "probe":
            bw("status", "--down", str(e)[:150])
            return
        raise
    bw("status", "--ok")
    bw(mode, *files)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "probe")
