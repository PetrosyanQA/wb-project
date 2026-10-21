"""Вопрос к Claude Fable 5.1 через API (оплата с баланса Console). Ключ — ANTHROPIC_API_KEY в .env.

    python -m src.fable "вопрос" [--files a.md b.md] [--effort high] [--name review]
Ответ печатается и сохраняется в reports/fable/<дата>_<name>.md. Ключ не печатается.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-fable-5-1"
SYSTEM = ("Ты опытный аналитик Wildberries и эксперт по запуску товаров. Отвечай по-русски, структурно, с цифрами. "
          "Проверяй расчёты и логику, ищи ошибки; не соглашайся ради вежливости. Если данных не хватает — скажи каких.")


def key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("нет ANTHROPIC_API_KEY в .env")


def ask(question: str, files: list[str], effort: str = "high", max_tokens: int = 16000) -> dict:
    parts = [f"=== {f} ===\n{(ROOT / f).read_text(encoding='utf-8')}" for f in files]
    content = ("\n\n".join(parts) + "\n\n---\n\n" if parts else "") + question
    body = {"model": MODEL, "max_tokens": max_tokens, "system": SYSTEM, "output_config": {"effort": effort},
            "messages": [{"role": "user", "content": content}], "fallbacks": "default"}
    hdr = {"x-api-key": key(), "anthropic-version": "2023-06-01", "content-type": "application/json",
           "anthropic-beta": "server-side-fallback-2026-07-01"}
    r = requests.post("https://api.anthropic.com/v1/messages", headers=hdr, json=body, timeout=1800)
    if r.status_code == 400 and "fallback" in r.text:                     # без резервной модели, если параметр не принят
        body.pop("fallbacks"); hdr.pop("anthropic-beta")
        r = requests.post("https://api.anthropic.com/v1/messages", headers=hdr, json=body, timeout=1800)
    if r.status_code != 200:
        raise SystemExit(f"ошибка API {r.status_code}: {r.text[:300]}")
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--name", default="answer")
    a = ap.parse_args()
    d = ask(a.question, a.files, a.effort)
    if d.get("stop_reason") == "refusal":
        raise SystemExit("модель отказалась отвечать")
    text = "\n".join(b["text"] for b in d["content"] if b.get("type") == "text")
    u = d.get("usage", {})
    cost = (u.get("input_tokens", 0) * 10 + u.get("output_tokens", 0) * 50) / 1e6
    out = ROOT / "reports" / "fable" / f"{dt.date.today().isoformat()}_{a.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# Fable 5.1 — {a.name} ({dt.date.today().isoformat()})\n\nФайлы: {', '.join(a.files) or '—'}\n\n"
                   f"**Вопрос:** {a.question}\n\n---\n\n{text}\n", encoding="utf-8")
    print(text)
    print(f"\n[модель {d.get('model')}, токены вход {u.get('input_tokens')} / выход {u.get('output_tokens')}, ≈ ${cost:.2f}] → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
