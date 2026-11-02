"""Выбор лидеров ниши для отзывов/карточек: top по выручке июля, разные продавцы, без заблокированных смыслов.

    python -m src.dna_leaders --subject 731 [--n 3]
"""
from __future__ import annotations

import argparse
import json
import os

from src.dna_dicts import get_cfg
from src.niche_dna import Dict


def leaders(run: str, sid: int, n: int = 3, min_comments: int = 800) -> list[dict]:
    d = f"data/raw/saleflow/{run}/dna/{sid}"
    f = f"{d}/products500_2026-07.json" if os.path.exists(f"{d}/products500_2026-07.json") else f"{d}/products_2026-07.json"
    rows = json.load(open(f, encoding="utf-8"))["data"]
    cfg = get_cfg(sid)
    D = Dict(cfg)
    rev = lambda x: x.get("revenue_estimated") or x.get("revenue") or 0
    out, sellers = [], set()
    for x in sorted(rows, key=lambda x: -rev(x)):
        ms, _, _ = D.parse(x["name"])
        # ≥ 800 отзывов: меньшие ответы Saleflow приходят в чат, а не в файл (их нельзя сохранить в data/raw)
        if ms & set(cfg["blocked"]) or x.get("supplier_id") in sellers or (x.get("comments") or 0) < min_comments:
            continue
        sellers.add(x.get("supplier_id"))
        out.append({"id": x["id"], "name": x["name"], "price": x["final_price"], "sales": x.get("sales"),
                    "rev": rev(x), "seller": x.get("seller"), "comments": x.get("comments"),
                    "dims": (x.get("package_length"), x.get("package_width"), x.get("package_height"))})
        if len(out) == n:
            break
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", type=int, required=True)
    ap.add_argument("--run", default="2026-10-05")
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    for x in leaders(a.run, a.subject, a.n):
        print(x["id"], "|", x["name"][:70], "|", x["price"], "₽ |", x["sales"], "шт |", x["seller"], "| отз", x["comments"], "|", x["dims"])
