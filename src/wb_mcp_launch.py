"""Запуск MCP-сервера Wildberries (пакет wildberries-mcp-ru, MIT) с нашим токеном из .env — токен не попадает в конфиги.

Подключён в .mcp.json как сервер «wb». Токен: WB_SELLER_TOKEN (Personal, только чтение) → WB_API_TOKEN для сервера.
Сервер ходит только на *.wildberries.ru (allowed_host_suffixes в пакете), любые изменения — только после подтверждения.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("WB_SELLER_TOKEN="):
            os.environ["WB_API_TOKEN"] = line.split("=", 1)[1].strip()
            break
    os.environ.setdefault("MARKETPLACE_MCP_HOME", str(ROOT / "data" / "wb_mcp"))   # хранилище сервера — внутри проекта, вне git
    from wb_mcp.server import main as serve
    serve()


if __name__ == "__main__":
    main()
