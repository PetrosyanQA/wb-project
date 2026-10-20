"""Перенос WB-токенов из «почтового ящика» в .env без пересылки через чат.

Папка проекта синхронизируется OneDrive. С телефона (приложение OneDrive) создайте в корне проекта файл
`token_inbox.txt` и вставьте туда токен(ы) — по одному на строку, можно с именем: `WB_TOKEN_TEST=eyJ...`.

    python -m src.token_inbox          # перенести в .env, затереть и удалить token_inbox.txt

Имя без явного указания выбирается по JWT: Test → WB_TOKEN_TEST; Personal/Base — по первой категории
(Контент → CARDS, Маркетплейс → FBS, Продвижение → ADS, Финансы → FIN, иначе P<n>).
Скрипт никогда не печатает сам токен — только имя, тип, категории и срок.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from src.wb_seller import ACC_NAME, token_bits

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "token_inbox.txt"
ENV = ROOT / ".env"
CAT = {1: "Контент", 2: "Аналитика", 3: "Цены и скидки", 4: "Маркетплейс", 5: "Статистика", 6: "Продвижение",
       7: "Вопросы и отзывы", 9: "Чат", 10: "Поставки", 11: "Возвраты", 12: "Документы", 13: "Финансы", 16: "Пользователи"}
NAME_BY_BIT = [(1, "CARDS"), (4, "FBS"), (6, "ADS"), (13, "FIN"), (7, "FEEDBACKS"), (2, "ANALYTICS")]
JWT = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")


def mask_bits(token: str) -> set[int]:
    import base64, json
    try:
        p = token.split(".")[1]
        s = int(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("s", 0))
    except Exception:                                          # noqa: BLE001
        return set()
    return {b for b in CAT if s >> b & 1}


def auto_name(info: dict, bits: set[int], used: set[str]) -> str:
    if info["acc"] == 2 or info["sandbox"]:
        base = "WB_TOKEN_TEST"
    else:
        base = next((f"WB_TOKEN_{n}" for b, n in NAME_BY_BIT if b in bits), "WB_TOKEN_P")
    name, i = base, 2
    while name in used:
        name, i = f"{base}{i}", i + 1
    return name


def main() -> None:
    if not INBOX.exists():
        print(f"Нет файла {INBOX.name} в корне проекта — нечего переносить.")
        return
    raw = INBOX.read_text(encoding="utf-8", errors="ignore")
    items = []
    for line in raw.splitlines():
        m = JWT.search(line)
        if not m:
            continue
        explicit = re.match(r"\s*(WB_[A-Z0-9_]+)\s*=", line)
        items.append((explicit.group(1) if explicit else None, m.group(0)))
    env = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    used = set()
    for name, tok in items:
        info, bits = token_bits(tok), mask_bits(tok)
        if info["acc"] is None:
            print("⚠️ строка похожа на токен, но не декодируется — пропущена")
            continue
        key = name or auto_name(info, bits, used)
        used.add(key)
        line = f"{key}={tok}"
        if re.search(rf"(?m)^{re.escape(key)}=.*$", env):
            env = re.sub(rf"(?m)^{re.escape(key)}=.*$", lambda _: line, env)
            act = "заменён"
        else:
            env = env.rstrip("\n") + "\n" + line + "\n"
            act = "добавлен"
        cats = ", ".join(CAT[b] for b in sorted(bits)) or "—"
        exp = info["exp"].strftime("%Y-%m-%d") if info["exp"] else "—"
        ro = "только чтение" if info["readonly"] else "чтение и запись"
        print(f"✅ {key} {act}: {ACC_NAME.get(info['acc'], info['acc'])} | {ro} | {cats} | до {exp}")
    if items:
        ENV.write_text(env, encoding="utf-8")
    INBOX.write_text("", encoding="utf-8")                     # затираем содержимое до удаления (OneDrive-версии)
    INBOX.unlink()
    print(f"{INBOX.name} затёрт и удалён. Токенов перенесено: {len(used)}."
          + ("" if items else " (в файле не найдено токенов)"))


if __name__ == "__main__":
    main()
