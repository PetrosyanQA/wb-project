"""Слияние всех волн поиска ниш v1…v6 + итоговая перепроверка 22 ниш в одну таблицу (2026-10-16). 0 запросов.

    python -m src.niche_merge            # → data/processed/niche_merge_<дата>.json, reports/niche_merge_<дата>.md/.xlsx

Статусы: ✅ прошла · 🟡 условно · ❌ отсеяна (первая причина) · ⏳ ждёт сбора · · не входила в волну.
v1 = all_niches 10-11 (3 020 предметов → 243 → 241 с сезонностью), v2 = newcomer-first 10-14,
v3 = «новички везде» 10-15, v4 = лёгкие 1 500–3 000 ₽ 10-16 (лучший вердикт из всех полос),
v5 = 1 030 ниш без фильтра деклараций 10-16, v6 = без карго-запретов (только universe/preview, сбор ждёт квоты),
«итог» = all_selected_recheck_2026-10-16 (модель am_fbs + карго).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
P = "data/processed"
TODAY = dt.date.today().isoformat()
OUT_J = f"{P}/niche_merge_{TODAY}.json"
OUT_MD = f"reports/niche_merge_{TODAY}.md"
OUT_X = f"reports/niche_merge_{TODAY}.xlsx"
WAVES = ["v1", "v2", "v3", "v4", "v5", "v6", "итог"]
RANK = {"✅": 3, "🟡": 2, "⏳": 1, "❌": 0}


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def mark(st: str) -> str:
    return st.split(" ", 1)[0] if st else ""


class Merge:
    def __init__(self):
        self.n: dict[int, dict] = {}

    def put(self, nid, name, wave, status, note=""):
        nid = int(nid)
        r = self.n.setdefault(nid, {"id": nid, "name": name or "", "waves": {}})
        if name and not r["name"]:
            r["name"] = name
        old = r["waves"].get(wave)
        if old is None or RANK.get(mark(status), -1) > RANK.get(mark(old["status"]), -1):
            r["waves"][wave] = {"status": status, "note": note}


def first(fails) -> str:
    return str(fails[0])[:60] if fails else ""


def build() -> Merge:
    M = Merge()
    # v1 — all_niches 10-11
    pre = load(f"{P}/all_niches_prefilter_2026-10-11.json") or {}
    for r in pre.get("keep", []):
        M.put(r["id"], r["name"], "v1", "❌ не дошла до финала")
    for r in load(f"{P}/all_niches_finalists_2026-10-11.json") or []:
        st = "✅ strict" if r.get("pass_strict") else ("🟡 сезонная" if r.get("pass_seasonal") else "❌ " + first(r.get("fails")))
        M.put(r["id"], r["name"], "v1", st, f"маржа {r.get('margin')}%")
    # v2 — newcomer-first 10-14
    for r in load(f"{P}/niche_v2_screen_2026-10-14.json") or []:
        M.put(r["id"], r["name"], "v2", "❌ " + first(r["fails"]) if r["fails"] else "❌ не прошла в глубокий этап")
    for r in (load(f"{P}/niche_v2_2026-10-14.json") or {}).get("rows", []):
        M.put(r["id"], r["name"], "v2", "✅" if not r["fails"] else "❌ " + first(r["fails"]), f"новичок P50 {r.get('nc_p50')}")
    # v3 — вердикт из таблицы отчёта, остальные — по score
    v3verd = {}
    if os.path.exists("reports/niche_v3_2026-10-15.md"):
        for line in open("reports/niche_v3_2026-10-15.md", encoding="utf-8"):
            m = re.match(r"\|\s*\**(\d+)\s[^|]*\|.*\|\s*([^|]+)\|\s*$", line)
            if m:
                last = m.group(2).strip()
                v3verd[int(m.group(1))] = ("✅" if "✅" in last else "❌" if "❌" in last else "🟡") + " " + last.replace("*", "")[:50]
    for r in load(f"{P}/niche_v3_2026-10-15.json") or []:
        st = v3verd.get(int(r["id"]), "❌ ниже топ-10 по score")
        M.put(r["id"], r["name"], "v3", st, f"score {r.get('score')}, новичок P50 {r.get('nc_p50')}")
    # v4 — лучший вердикт по всем ценовым полосам
    for f in sorted(glob.glob(f"{P}/screen_v4_*2026-10-16.json")):
        for r in load(f) or []:
            if "verdict" in r:
                v = r["verdict"]
                st = "✅" if v.startswith("✅") else "❌ " + v[2:60].strip()
                M.put(r["id"], r["name"], "v4", st, f"новичок P50 {r.get('nc_p50')}, max ¥ ДРР10 {r.get('max_yuan_drr10')}")
    # v5 — universe → собранные → stage1 → final
    try:
        from src import niche_v5 as V
        has = lambda i: bool(V.p500(int(i)))
    except Exception:
        has = lambda i: False
    s1 = {r["id"] for r in load(f"{P}/niche_v5_stage1.json") or []}
    for r in load(f"{P}/niche_v5_universe.json") or []:
        if r["id"] in s1:
            continue
        M.put(r["id"], r["name"], "v5", "❌ слабые новички в полосах" if has(r["id"]) else "⏳ не собрана")
    fin = {r["id"]: r for r in load(f"{P}/niche_v5_final.json") or []}
    for r in load(f"{P}/niche_v5_stage1.json") or []:
        if r["id"] not in fin:
            M.put(r["id"], r["name"], "v5", "❌ карточки: габарит/ЧЗ/сертификат", f"score {r['best'].get('score')}")
    for i, r in fin.items():
        m = r.get("margin_drr15_assumed")
        if m is not None and m >= 18:
            st = f"✅ маржа ДРР15 {m}% (¥ допущение)"
        elif m is not None and m > 0:
            st = f"🟡 маржа ДРР15 {m}% (¥ допущение)"
        else:
            st = f"❌ маржа ДРР15 {m}%"
        M.put(i, r["name"], "v5", st)
    # v6 — только universe/preview
    prev = {r["id"] for r in load(f"{P}/niche_v6_preview.json") or []}
    for r in load(f"{P}/niche_v6_universe.json") or []:
        if r["id"] in prev:
            M.put(r["id"], r["name"], "v6", "⏳ открыта снятием карго-запретов")
    # итог — таблица перепроверки
    if os.path.exists("reports/all_selected_recheck_2026-10-16.md"):
        for line in open("reports/all_selected_recheck_2026-10-16.md", encoding="utf-8"):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) >= 9 and c[0].isdigit():
                m = re.match(r"(\d+)\s+(.*)", c[1])
                if not m:
                    continue
                last = c[-1].replace("*", "")
                st = "✅" if "✅" in last else "❌" if "❌" in last else "🟡"
                M.put(m.group(1), m.group(2), "итог", f"{st} {c[2][:45]}", last[:60])
    for r in M.n.values():
        ms = [mark(w["status"]) for w in r["waves"].values()]
        r["n_pass"] = sum(1 for k, w in r["waves"].items() if k != "итог" and mark(w["status"]) == "✅")
        r["n_cond"] = sum(1 for k, w in r["waves"].items() if k != "итог" and mark(w["status"]) == "🟡")
        r["n_waves"] = sum(1 for k, w in r["waves"].items() if k != "итог" and mark(w["status"]) != "⏳")
        fin_st = r["waves"].get("итог", {}).get("status", "")
        if fin_st:
            r["final"] = mark(fin_st)
        elif r["n_pass"] or r["n_cond"]:
            r["final"] = "🟡"
        elif "⏳" in ms:
            r["final"] = "⏳"
        else:
            r["final"] = "❌"
    return M


def cell(r, w):
    x = r["waves"].get(w)
    return x["status"] if x else "·"


def main():
    M = build()
    rows = sorted(M.n.values(), key=lambda r: (-RANK.get(r["final"], -1), -r["n_pass"], -r["n_cond"], r["id"]))
    json.dump(rows, open(OUT_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cnt = {w: {"всего": 0, "✅": 0, "🟡": 0, "❌": 0, "⏳": 0} for w in WAVES}
    for r in rows:
        for w, x in r["waves"].items():
            cnt[w]["всего"] += 1
            cnt[w][mark(x["status"])] = cnt[w].get(mark(x["status"]), 0) + 1
    good = [r for r in rows if r["n_pass"] or r["n_cond"] or "итог" in r["waves"]]
    L = [f"# Все волны поиска ниш v1–v6 в одной таблице ({TODAY})", "",
         "Код: `src/niche_merge.py` (0 запросов). Источники: `data/processed/all_niches_*_2026-10-11`, `niche_v2_*`, `niche_v3_*`,",
         "`screen_v4_*`, `niche_v5_*`, `niche_v6_*`, `reports/all_selected_recheck_2026-10-16.md`.", "",
         "## Сводка по волнам", "", "| Волна | Ниш | ✅ | 🟡 | ❌ | ⏳ |", "|---|---:|---:|---:|---:|---:|"]
    for w in WAVES:
        c = cnt[w]
        L.append(f"| {w} | {c['всего']} | {c['✅']} | {c['🟡']} | {c['❌']} | {c['⏳']} |")
    L += ["", f"Уникальных ниш во всех волнах: **{len(rows)}**; хоть раз ✅/🟡 или в итоговой перепроверке: **{len(good)}**.", "",
          "## Ниши, прошедшие хотя бы одну волну", "",
          "| Ниша | " + " | ".join(WAVES) + " | ✅ раз |", "|---|" + "---|" * len(WAVES) + "---:|"]
    for r in good:
        L.append(f"| {r['id']} {r['name'].split(' / ')[-1][:30]} | " + " | ".join(cell(r, w)[:40] for w in WAVES) + f" | {r['n_pass']} |")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "все ниши"
        ws.append(["id", "ниша", *WAVES, "✅ раз", "🟡 раз", "волн", "итог"])
        for r in rows:
            ws.append([r["id"], r["name"], *[cell(r, w) for w in WAVES], r["n_pass"], r["n_cond"], r["n_waves"], r["final"]])
        ws2 = wb.create_sheet("сводка")
        ws2.append(["волна", "всего", "✅", "🟡", "❌", "⏳"])
        for w in WAVES:
            ws2.append([w, *[cnt[w][k] for k in ("всего", "✅", "🟡", "❌", "⏳")]])
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(OUT_X)
    except Exception as e:
        print("xlsx:", e)
    print(f"{len(rows)} ниш, {len(good)} хоть раз прошли → {OUT_MD}")
    for w in WAVES:
        print(w, cnt[w])


if __name__ == "__main__":
    main()
