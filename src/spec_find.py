"""Поиск товара на 1688 по ОПИСАНИЮ (ТЗ), без фото: китайские запросы → все офферы → баллы за совпадение с ТЗ.

    python -m src.spec_find search --spec tote          # запросы из SPECS (1 кредит Bright Data на запрос, кэш на день)
    python -m src.spec_find rank --spec tote --top 25   # 0 кредитов: собрать офферы из сохранённых выдач, начислить баллы
    python -m src.spec_find detail --spec tote --top 6  # 1 кредит на карточку: цены по вариантам, вес, цвета → итог

Баллы — по словам в названии оффера (+ за требования ТЗ, − за запреты), цена ≤ потолка ¥. Чем выше балл, тем ближе к ТЗ.
Итог: reports/spec_find_<spec>_<дата>.md. Новое ТЗ = новый ключ в SPECS (слова на китайском).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]

SPECS = {
    "tote": {
        "title": "Сумка-тоут А4, экокожа, молния, без магнитов, жёсткое дно с ножками, косметичка, чёрный/шоколадный",
        "spec_file": "marketing/8986/card_text_2026-10-27.md",
        "queries": ["托特包", "拉链托特包", "PU托特包女", "子母托特包", "底钉托特包", "A4托特包", "拉链通勤包"],
        "files": ["wv_tote", "tote_zip", "tote_pu", "t_zimu", "t_dding", "t_a4", "t_tongqin"],
        "max_cny": 22,
        "plus": {r"托特": 2, r"拉链": 3, r"PU|皮革|皮质|软皮|仿皮|皮包": 3, r"大容量": 1, r"通勤|上班|上课": 1, r"A4|电脑|笔记本": 2,
                 r"子母|化妆包|配包": 3, r"底钉|硬底|定型|底板": 3, r"肩带|斜挎": 1, r"黑色|咖啡|棕色|深棕|黑茶": 1, r"纯色|简约|百搭": 1},
        "minus": {r"磁扣|磁吸": -5, r"帆布|布包|针织|编织|毛绒|帆": -4, r"儿童|童": -4, r"男": -2, r"定制|LOGO|logo": -1,
                  r"老花|印花|鳄鱼|格纹|波点|卡通|涂鸦|小熊": -2, r"透明|果冻": -3, r"小号|迷你|mini": -3,
                  r"抽绳|运动|饺子|内胆|包中包|文件袋|公文": -3, r"自立|立体": 2},
    },
    "brush": {
        "title": "Набор 12 кистей для макияжа, синтетика без запаха, не линяет, без логотипа, чехол-конверт/сумка в комплекте",
        "spec_file": "reports/vnutri_437_brushes_2026-10-28.md",
        "queries": ["化妆刷套装 12支 无logo", "化妆刷套装 收纳包 12支", "化妆刷 套刷 裸刷 定制logo", "化妆刷套装 不掉毛 无异味", "化妆刷 12支 化妆包 套装 沧州"],
        "files": ["b_nologo", "b_bag", "b_naked", "b_noshed", "b_cangzhou"],
        "max_cny": 14,
        "plus": {r"12支|12件|十二支": 3, r"套装|套刷": 2, r"无logo|裸刷|定制|可定制": 2, r"包|收纳|信封|化妆包": 2,
                 r"不掉毛|不吃粉|无异味|柔软|纤维毛|人造纤维": 2, r"沧州": 1, r"木柄|铝管": 1},
        "minus": {r"单支|1支|单只": -4, r"动物毛|马毛|山羊毛|羊毛": -2, r"儿童|玩具": -5, r"电动|充电|洗刷机": -5,
                  r"美甲|油画|画笔": -5, r"散粉刷$": -2, r"眼影刷": -1},
    },
    "knife": {
        "title": "Набор кухонных ножей 5 + ножницы, сталь 5Cr15MoV, цельная ручка, подставка без магнита, чёрный",
        "spec_file": "marketing/811/research/analysis_2026-10-28.md",
        "queries": ["刀具套装 5cr15", "厨房刀具套装 六件套", "不锈钢刀具套装 刀座", "一体刀具套装", "菜刀套装 家用 黑色"],
        "files": ["k_5cr15", "k_6pc", "k_block", "k_onepiece", "k_black"],
        "max_cny": 15,
        "plus": {r"套装|套刀|件套": 2, r"5[Cc][Rr]15|5铬15|7[Cc][Rr]17|德国|钼钒": 3, r"六件套|6件|五件套|5件": 2, r"剪刀": 2,
                 r"刀座|刀架": 2, r"一体|全钢|空心柄": 1, r"黑色|黑刃|哑光": 1, r"不锈钢": 1, r"厨师刀|面包刀|水果刀": 1},
        "minus": {r"磁|磁吸|磁性": -5, r"3[Cc][Rr]13": -2, r"陶瓷": -4, r"儿童|玩具|模型": -5, r"单把|单刀": -3,
                  r"折叠|户外|露营|军|猎": -5, r"大马士革": -1, r"定制|LOGO|logo": -1, r"磨刀石|磨刀器$": -3},
    },
}


def offers(spec: dict) -> list[dict]:
    from src.brightdata_client import offers_1688
    seen, out = set(), []
    for name in spec["files"]:
        for p in sorted(glob.glob(str(ROOT / f"data/raw/brightdata/*/1688_{name}.html")))[-1:]:
            for r in offers_1688(open(p, encoding="utf-8", errors="ignore").read()):
                k = r["offer_id"] or r["title"]
                if k in seen:
                    continue
                seen.add(k)
                r["query"] = name
                out.append(r)
    return out


def score(r: dict, spec: dict) -> tuple[int, list[str]]:
    s, why = 0, []
    for rx, w in {**spec["plus"], **spec["minus"]}.items():
        if re.search(rx, r["title"]):
            s += w
            why.append(f"{'+' if w > 0 else ''}{w} {rx.split('|')[0]}")
    if r["price_cny"] > spec["max_cny"]:
        s -= 3
        why.append(f"−3 ¥>{spec['max_cny']}")
    if r["price_cny"] < 5:
        s -= 3
        why.append("−3 ¥<5 (не та категория)")
    return s, why


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "rank", "detail"])
    ap.add_argument("--spec", default="tote")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    spec = SPECS[a.spec]
    if a.cmd == "search":
        for q, n in zip(spec["queries"], spec["files"]):
            subprocess.run([sys.executable, "-m", "src.brightdata_client", "s1688", q, "--name", n], check=False)
        return
    rows = []
    for r in offers(spec):
        s, why = score(r, spec)
        rows.append({**r, "score": s, "why": why})
    rows.sort(key=lambda r: (-r["score"], r["price_cny"]))
    top = rows[:a.top]
    det = {}
    if a.cmd == "detail":
        from src.brightdata_client import BudgetStop, detail_1688, fetch
        for r in [x for x in top if x["offer_id"]][:a.top]:
            try:
                d = detail_1688(fetch(f"https://detail.1688.com/offer/{r['offer_id']}.html", f"1688d_{r['offer_id']}"))
            except BudgetStop:
                raise
            except SystemExit:
                continue
            g = [p["g"] for p in d["pack"] if p.get("g")]
            det[r["offer_id"]] = dict(skus=len(d["skus"]), colors=sorted({s["sku"].split(" / ")[0] for s in d["skus"]})[:8],
                                      pmin=min([s["price_cny"] for s in d["skus"]] or [r["price_cny"]]),
                                      pmax=max([s["price_cny"] for s in d["skus"]] or [r["price_cny"]]),
                                      g=f"{min(g)}–{max(g)} г" if g else "—", moq=d["moq"])
    L = [f"# Поиск по описанию на 1688: {spec['title']} — {dt.date.today()}", "",
         f"ТЗ: `{spec['spec_file']}`. Запросы: {', '.join(spec['queries'])}. Офферов: {len(rows)}; потолок ¥{spec['max_cny']}.", "",
         "| # | Балл | ¥ | Продано | Повторные | Оффер | Название | Почему |", "|---:|---:|---:|---|---:|---|---|---|"]
    for i, r in enumerate(top, 1):
        link = f"[{r['offer_id']}](https://detail.1688.com/offer/{r['offer_id']}.html)" if r["offer_id"] else "—"
        L.append(f"| {i} | {r['score']} | {r['price_cny']} | {r['sold'] or '—'} | {r['repeat'] or '—'} | {link} | {r['title'][:55]} | {', '.join(r['why'][:6])} |")
    if det:
        L += ["", "## Карточки (варианты, цвета, вес)", "", "| Оффер | ¥ мин–макс | Вариантов | Цвета | Вес | MOQ |", "|---|---:|---:|---|---|---:|"]
        for oid, d in det.items():
            L.append(f"| {oid} | {d['pmin']}–{d['pmax']} | {d['skus']} | {', '.join(d['colors'])} | {d['g']} | {d['moq']} |")
    L += ["", f"Балл — совпадение названия с ТЗ «{spec['title']}» (слова-плюсы и минусы — `SPECS['{a.spec}']`). "
          "Доработки, которых нет в названии, спрашиваем у фабрики через YUAN EXIM (`docs/suppliers/`)."]
    text = "\n".join(L)
    out = ROOT / "reports" / f"spec_find_{a.spec}_{dt.date.today()}.md"
    out.write_text(text, encoding="utf-8")
    json.dump(dict(rows=top, detail=det), open(ROOT / "data" / "processed" / f"spec_find_{a.spec}_{dt.date.today()}.json", "w", encoding="utf-8"),
              ensure_ascii=False, default=str)
    print(text)
    print(f"\n→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
