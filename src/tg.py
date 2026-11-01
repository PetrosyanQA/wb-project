"""Telegram для отчётов и кнопок-команд: отправка (HTML, кнопки), ответы на нажатия.

Токен и чат: в облаке — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (секреты GitHub); на компьютере — токен плагина
(~/.claude/channels/telegram/.env) и чат из config/notify.yaml. Токен не печатается.
"""
from __future__ import annotations

import html
import os
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]


def creds() -> tuple[str | None, str | None]:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        return tok, chat
    cfg = ROOT / "config" / "notify.yaml"
    chat = chat or ((yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("telegram_chat_id") if cfg.exists() else None)
    env = Path.home() / ".claude" / "channels" / "telegram" / ".env"
    if not tok and env.exists():
        tok = next((l.split("=", 1)[1].strip() for l in env.read_text(encoding="utf-8").splitlines()
                    if l.startswith("TELEGRAM_BOT_TOKEN=")), None)
    return tok, (str(chat) if chat else None)


def h(s) -> str:
    """Экранирование для parse_mode=HTML."""
    return html.escape(str(s), quote=False)


def api(method: str, **payload) -> dict | None:
    tok, _ = creds()
    if not tok:
        return None
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/{method}", json=payload, timeout=30)
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


def _chunks(text: str, limit: int = 4000) -> list[str]:
    """Режем по строкам (не посреди HTML-тега): Telegram принимает ≤ 4 096 символов."""
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:                      # одна сверхдлинная строка — режем как есть
            out.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            out.append(cur); cur = ""
        cur = f"{cur}\n{line}" if cur else line
    return out + ([cur] if cur else [])


def send(text: str, html_mode: bool = True, buttons: list[list[dict]] | None = None) -> bool:
    """[аудит 2026-11-01] длинный текст — несколькими сообщениями (было text[:4096] → обрыв HTML и тихая ошибка 400);
    HTML не принят → повтор простым текстом. True только если дошли все части."""
    _, chat = creds()
    if not chat:
        return False
    parts, ok = _chunks(text), True
    for i, part in enumerate(parts):
        p = {"chat_id": chat, "text": part, "disable_web_page_preview": True}
        if html_mode:
            p["parse_mode"] = "HTML"
        if buttons and i == len(parts) - 1:
            p["reply_markup"] = {"inline_keyboard": buttons}
        r = api("sendMessage", **p)
        if not r and html_mode:
            p.pop("parse_mode")
            r = api("sendMessage", **p)
        ok = ok and bool(r)
    return ok


def send_photo(jpg: bytes, caption: str) -> bool:
    tok, chat = creds()
    if not (tok and chat):
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat, "caption": caption[:1000], "parse_mode": "HTML"},
                          files={"photo": ("photo.jpg", jpg, "image/jpeg")}, timeout=60)
        return r.ok
    except requests.RequestException:
        return False
