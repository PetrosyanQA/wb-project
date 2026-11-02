"""Сохранить ответ MCP-инструмента Saleflow из журнала сессии Claude Code в data/raw — без перепечатки (2026-10-07).

Нужен, когда stdio-клиент (src.saleflow_stdio) ловит «tools/call timed out», а коннектор сессии отвечает:
ответ приходит в контекст, а правило CLAUDE.md требует сырой JSON на диске.

    python -m src.mcp_dump --session <id>.jsonl --tool wb_subject --match subject_id=2264 report=price_segmentation --out file.json

Берётся ПОСЛЕДНИЙ вызов с совпадающими аргументами. Большие ответы, которые Claude сохранил в tool-results/, читаются оттуда.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
PROJ = os.path.join(os.path.expanduser("~"), ".claude", "projects", "C--Users-ozon2-OneDrive-Desktop-wb-claude-code-mpstats-research")


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")


def find(session: str, tool: str, match: dict) -> str:
    uses, results = {}, {}
    for line in open(session, encoding="utf-8"):
        try:
            m = json.loads(line).get("message") or {}
        except json.JSONDecodeError:
            continue
        for c in m.get("content") or [] if isinstance(m.get("content"), list) else []:
            if c.get("type") == "tool_use" and c.get("name", "").endswith("__" + tool):
                if all(str(c["input"].get(k)) == v for k, v in match.items()):
                    uses[c["id"]] = c["input"]
            elif c.get("type") == "tool_result":
                results[c["tool_use_id"]] = text_of(c.get("content"))
    hits = [i for i in uses if i in results]
    if not hits:
        raise SystemExit(f"нет вызова {tool} с {match}")
    t = results[hits[-1]]
    saved = re.search(r"saved to:?\s*(\S+\.(?:txt|json))", t)
    if saved and ("Output too large" in t or "exceeds maximum allowed" in t or "has been saved to" in t):
        t = open(saved.group(1), encoding="utf-8").read()
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--match", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    session = a.session if os.path.isabs(a.session) else os.path.join(PROJ, a.session)
    t = find(session, a.tool, dict(x.split("=", 1) for x in a.match))
    data = json.loads(t[t.index(next(ch for ch in t if ch in "[{")):])     # отрезаем возможный текст перед JSON
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    n = len(data) if isinstance(data, list) else len(data.get("data", data))
    print(f"→ {a.out} ({n} строк)")


if __name__ == "__main__":
    main()
