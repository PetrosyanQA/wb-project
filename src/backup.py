"""Резервная копия данных проекта ВНЕ OneDrive (zip). Секреты (.env, .mcp.json) не копируются никогда.

    python -m src.backup                 # инкрементально: только новые/изменённые файлы с прошлого раза
    python -m src.backup --full          # полная копия
    python -m src.backup --dest D:\\wb    # другая папка (внешний диск)
    python -m src.backup --list          # что уже есть

По умолчанию: %USERPROFILE%\\wb_backups\\mpstats-research\\ (вне OneDrive — синхронизация не перезапишет).
Хранится последние KEEP_FULL полных копий; инкрементальные — до следующей полной.
Что входит: data/raw, data/processed, data/cache_wb, reports, wb_algorithm, config, docs, src, *.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
INCLUDE = ["data/raw", "data/processed", "data/cache_wb", "reports", "wb_algorithm", "config", "docs", "src", ".claude/commands"]
TOP_FILES = ["*.md", "requirements.txt", ".gitignore", ".env.example"]
NEVER = {".env", ".mcp.json", "settings.local.json"}
KEEP_FULL = 3
DEFAULT_DEST = os.path.join(os.path.expanduser("~"), "wb_backups", "mpstats-research")


def files() -> list[str]:
    out = []
    for d in INCLUDE:
        for p in glob.glob(f"{d}/**/*", recursive=True):
            if os.path.isfile(p) and os.path.basename(p) not in NEVER and "__pycache__" not in p:
                out.append(p.replace("\\", "/"))
    for pat in TOP_FILES:
        out += [p for p in glob.glob(pat) if os.path.basename(p) not in NEVER]
    return sorted(set(out))


def stamp(p: str) -> list:
    s = os.stat(p)
    return [s.st_size, int(s.st_mtime)]


def run(dest: str, full: bool) -> None:
    os.makedirs(dest, exist_ok=True)
    man_path = os.path.join(dest, "manifest.json")
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) and not full else {}
    F = files()
    todo = [p for p in F if man.get(p) != stamp(p)]
    if not todo:
        print("изменений нет — копия не нужна")
        return
    kind = "full" if full or not man else "incr"
    name = os.path.join(dest, f"{dt.datetime.now():%Y-%m-%d_%H%M}_{kind}.zip")
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, p in enumerate(todo, 1):
            z.write(p)
            if i % 500 == 0:
                print(f"  {i}/{len(todo)}")
    new = {p: stamp(p) for p in F} if kind == "full" else {**man, **{p: stamp(p) for p in todo}}
    json.dump(new, open(man_path, "w", encoding="utf-8"))
    if kind == "full":                                   # старые полные + их инкременты сверх KEEP_FULL удаляем
        fulls = sorted(glob.glob(os.path.join(dest, "*_full.zip")))
        for old in fulls[:-KEEP_FULL]:
            cutoff = os.path.basename(fulls[len(fulls) - KEEP_FULL])[:15]
            for z in glob.glob(os.path.join(dest, "*.zip")):
                if os.path.basename(z)[:15] < cutoff:
                    os.remove(z)
            break
    mb_src = sum(os.path.getsize(p) for p in todo) / 1e6
    print(f"{kind}: {len(todo)} файлов, {mb_src:.0f} МБ → {name} ({os.path.getsize(name) / 1e6:.0f} МБ)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for z in sorted(glob.glob(os.path.join(a.dest, "*.zip"))):
            print(f"{os.path.getsize(z) / 1e6:8.0f} МБ  {z}")
        return
    run(a.dest, a.full)


if __name__ == "__main__":
    main()
