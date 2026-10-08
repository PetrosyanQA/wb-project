"""Прямой stdio-клиент к локальному Saleflow MCP (server.cjs) — запасной путь, когда коннектор в Claude теряет сессию
("Missing session ID"). Запускает свой экземпляр сервера (новая upstream-сессия), ответы пишет сразу на диск.

    python -m src.saleflow_stdio status
    python -m src.saleflow_stdio call wb_subject '{"subject_id": 1594, "report": "products", ...}' --out file.json
    python -m src.saleflow_stdio products 1594 937 --d1 2026-07-01 --d2 2026-07-31 --outdir data/raw/saleflow/2026-10-06/fresh
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Saleflow MCP")


def _server_cmd() -> list[str]:
    cfg = json.load(open(os.path.join(os.environ["APPDATA"], "Claude", "claude_desktop_config.json"), encoding="utf-8"))
    s = cfg["mcpServers"]["saleflow_universal"]
    return [s["command"], *s["args"]]


class Client:
    def __init__(self) -> None:
        self.p = subprocess.Popen(_server_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(os.environ.get("SF_ERRLOG", os.devnull), "ab"))
        self.n = 0
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
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("Saleflow server закрылся")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def call(self, tool: str, args: dict):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        if r.get("isError"):
            raise RuntimeError(text[:300])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

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
                f = os.path.join(a.outdir, f"products_{sid}_{a.d1[:7]}.json")
                try:
                    res = c.call("wb_subject", {"subject_id": int(sid), "report": "products", "d1": a.d1, "d2": a.d2,
                                                "limit": 100})
                    json.dump(res, open(f, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"{sid}: {len(res.get('data', [])) if isinstance(res, dict) else '?'} строк → {f}")
                except Exception as e:                      # noqa: BLE001 — продолжаем остальные ниши
                    print(f"{sid}: ошибка {str(e)[:200]}")
    finally:
        c.close()


if __name__ == "__main__":
    main()
