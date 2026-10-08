"""Все отчёты проекта (reports/*.md) + сводные листы Excel → один HTML → PDF (через Edge headless).

    python -m src.export_pdf          # → reports/ALL_NICHES_DATA_<date>.pdf
"""
from __future__ import annotations

import glob
import html
import os
import re
import subprocess
from datetime import date

from openpyxl import load_workbook

OUT = f"reports/ALL_NICHES_DATA_{date(2026, 10, 5).isoformat()}"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# порядок разделов: (заголовок, шаблоны файлов)
SECTIONS = [
    ("0. Полная история и итог", ["HISTORY_full_analysis_2026-10-05.md", "final_choice_2026-10-05.md"]),
    ("1. Первый запуск и доступ к данным (27.09–03.10)", ["doctor_20260927.md", "discovery_20260927.md", "niche_scan_20260927.md", "trend_20260927_7901.md",
                                                        "doctor_20261003.md", "doctor_20261003_desktop.md", "doctor_share.md", "saleflow_diagnosis.md",
                                                        "wb_live_check_20261003.md", "analysis_status_20261003.md", "market_reality_20261003.md",
                                                        "discovery_20261003.md", "discovery_20261003_desktop.md", "niche_scan_20261003.md",
                                                        "niche_scan_20261003_desktop.md", "gates_20261003.md", "category_minprice_cny15.md", "category_econ_1900.md",
                                                        "decide_market_checklist.md"]),
    ("2. Ножи кухонные, вакууматоры, рейтинг ниш (03–04.10)", ["knives_deep_2026-10-03.md", "vacuum_deep_2026-10-03.md", "niches_ranking_2026-10-03.md",
                                                              "best_product_2026-10-04.md", "winners_products_2026-10-04.md", "supplier_letter_knives.md",
                                                              "supplier_letter_knives_with_specs.md", "supplier_letter_knives_A_plus.md"]),
    ("3. Часы наручные и решение 04.10", ["niche2_chasy-naruchnye_2026-10-04.md", "decision_2026-10-04.md"]),
    ("4. Скрин всего WB, cross-border", ["niche3_search_2026-10-04.md", "xborder_niches_2026-10-04.md", "niche_search_1688gate_2026-10-04.md"]),
    ("5. Видеоняня", ["videonyanya_fbs_2026-10-04.md", "videonyanya_winners_2026-10-04.md", "videonyanya_cost_check_2026-10-04.md",
                      "videonyanya_30days_plan_2026-10-04.md", "videonyanya_card_design_2026-10-04.md", "supplier_letter_videonyanya_2026-10-04.md"]),
    ("6. Оправы, раунд 3, мастурбаторы, «золотой выбор»", ["opravy_niche_2026-10-04.md", "niche_search_round3_2026-10-04.md", "masturb_deep_2026-10-05.md",
                                                           "masturbator_auto_specs_1688_2026-10-04.md", "masturbator_1688_eval_2026-10-05.md",
                                                           "golden_choice_2026-10-05.md", "niche_new_winner_2026-10-05.md"]),
    ("7. Жёсткие фильтры, ЗАДАЧА A, уникальный товар, склады Армении", ["gates_v2_screen_2026-10-05.md", "gates_v3_relative_2026-10-05.md",
                                                                        "gates_fbs_moscow_2026-10-05.md", "taskA_niches_2026-10-05.md",
                                                                        "unique_product_search_2026-10-05.md", "armenia_warehouses_check_2026-10-05.md"]),
    ("8. ДНК ниш, держатели в авто, игрушки для животных", ["dna_777_modes_2026-10-05.md", "card_777_magnetic_holder_2026-10-05.md", "best_product_2026-10-05.md",
                                                           "sourcing_3_niches_2026-10-05.md", "niche777_patterns_2026-10-05.md"]),
]
XLSX = [
    ("niches_comparison_2026-10-03.xlsx", None, 60),
    ("niches_season_dec_2026-10-05.xlsx", None, 80),
    ("dna_all_2026-10-05.xlsx", None, 400),
]


def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
    return s


def md2html(text: str) -> str:
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            t = ["<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells(rows[0])) + "</tr>"]
            for r in rows[2:]:
                t.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>")
            out.append("".join(t) + "</table>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            lvl = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif re.match(r"^\s*([-*]|\d+[.)])\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+[.)])\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+[.)])\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue
        elif ln.startswith(">"):
            out.append(f"<blockquote>{inline(ln.lstrip('> '))}</blockquote>")
        elif re.match(r"^-{3,}$", ln.strip()):
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    return "\n".join(out)


def sheet_html(path: str, max_rows: int) -> str:
    wb = load_workbook(path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
        if not rows:
            continue
        ncol = max(len(r) for r in rows)
        keep = [j for j in range(ncol) if any(j < len(r) and r[j] not in (None, "") for r in rows)]
        t = [f"<h3>{html.escape(os.path.basename(path))} — лист «{html.escape(ws.title)}» ({len(rows)} строк{', показаны первые ' + str(max_rows) if len(rows) > max_rows else ''})</h3><table>"]
        for r in rows[:max_rows]:
            t.append("<tr>" + "".join(f"<td>{html.escape(str(r[j]) if j < len(r) and r[j] is not None else '')}</td>" for j in keep) + "</tr>")
        parts.append("".join(t) + "</table>")
    return "\n".join(parts)


CSS = """
@page { size: A4 landscape; margin: 10mm; }
body { font-family: 'Segoe UI', 'Sylfaen', 'Microsoft YaHei', Arial, sans-serif; font-size: 8.5pt; color: #111; }
h1 { font-size: 20pt; page-break-before: always; color: #1F3864; border-bottom: 3px solid #1F3864; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 13pt; color: #2F5496; margin-top: 18px; border-bottom: 1px solid #ccc; }
h3 { font-size: 11pt; color: #2F5496; } h4, h5, h6 { font-size: 9.5pt; }
table { border-collapse: collapse; margin: 6px 0; width: 100%; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 2px 4px; vertical-align: top; word-break: break-word; }
th { background: #DDEBF7; }
pre { background: #f4f4f4; padding: 6px; white-space: pre-wrap; font-size: 8pt; }
code { background: #f1f1f1; font-size: 8pt; }
blockquote { border-left: 3px solid #999; margin: 4px 0; padding-left: 8px; color: #444; }
.src { color: #777; font-size: 8pt; }
.toc li { margin: 1px 0; }
"""


def rpath(f: str) -> str:
    """Путь отчёта: reports/<f> или, если он перенесён, reports/archive/**/<f>."""
    p = os.path.join("reports", f)
    if os.path.exists(p):
        return p
    hits = glob.glob(os.path.join("reports", "archive", "**", f), recursive=True)
    return hits[0] if hits else p


def collect() -> list[tuple[str, str]]:
    """[(заголовок раздела, html раздела)] — общий источник для PDF и веб-страницы."""
    secs, used = [], set()
    for title, files in SECTIONS:
        parts = []
        for f in files:
            p = rpath(f)
            if os.path.exists(p):
                used.add(f)
                parts.append(f"<h2>📄 {html.escape(f)}</h2>" + md2html(open(p, encoding="utf-8").read()))
        secs.append((title, "\n".join(parts)))
    rest = sorted(set(os.path.basename(p) for p in glob.glob("reports/*.md")) - used)
    if rest:
        secs.append(("9. Прочие отчёты", "".join(f"<h2>📄 {html.escape(f)}</h2>" + md2html(open(os.path.join('reports', f), encoding='utf-8').read()) for f in rest)))
    secs.append(("10. Таблицы данных (Excel)", "\n".join(sheet_html(rpath(f), mx) for f, _, mx in XLSX if os.path.exists(rpath(f)))))
    dparts = []
    for p in sorted(x for x in glob.glob("reports/dna_*_2026-10-05.xlsx") if "dna_all" not in x):
        wb = load_workbook(p, read_only=True, data_only=True)
        for name in ("📋 Обзор", "🎯 Гипотезы"):
            if name in wb.sheetnames:
                rows = [r for r in wb[name].iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
                ncol = max(len(r) for r in rows)
                keep = [j for j in range(ncol) if any(j < len(r) and r[j] not in (None, "") for r in rows)]
                dparts.append(f"<h3>{html.escape(os.path.basename(p))} — {html.escape(name)}</h3><table>" + "".join(
                    "<tr>" + "".join(f"<td>{html.escape(str(r[j]) if j < len(r) and r[j] is not None else '')}</td>" for j in keep) + "</tr>"
                    for r in rows) + "</table>")
    secs.append(("11. ДНК каждой из 24 ниш — «Обзор» и «Гипотезы»", "\n".join(dparts)))
    return secs


def print_pdf(html_path: str, pdf_path: str) -> None:
    subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={os.path.abspath(pdf_path)}",
                    "file:///" + os.path.abspath(html_path).replace("\\", "/")], check=True, timeout=600)


def split_pdfs(secs) -> None:
    """Небольшие PDF по разделам — для телефона."""
    pref = lambda *ps: [i for i, (t, _) in enumerate(secs) if t.split(".")[0] in ps]
    groups = [("1_istoriya_i_start", pref("0", "1")), ("2_nozhi_chasy_skrin", pref("2", "3", "4")),
              ("3_videonyanya_opravy_masturb", pref("5", "6")), ("4_filtry_dna_derzhateli", pref("7", "8", "9")),
              ("5_tablicy_excel", pref("10")), ("6_dna_24_nish", pref("11"))]
    os.makedirs("reports/pdf_parts", exist_ok=True)
    for name, idx in groups:
        body = "".join(f"<h1>{html.escape(secs[i][0])}</h1>{secs[i][1]}" for i in idx if i < len(secs))
        hp = f"reports/pdf_parts/{name}.html"
        open(hp, "w", encoding="utf-8").write(f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>")
        print_pdf(hp, hp[:-5] + ".pdf")
        os.remove(hp)
        print("part", name, os.path.getsize(hp[:-5] + ".pdf") // 1024, "KB")


def main() -> None:
    import sys
    if "--parts" in sys.argv:
        split_pdfs(collect())
        return
    body, toc, used = [], [], set()
    for title, files in SECTIONS:
        sec = [f"<h1>{html.escape(title)}</h1>"]
        for f in files:
            p = os.path.join("reports", f)
            if not os.path.exists(p):
                continue
            used.add(f)
            sec.append(f"<h2>📄 {html.escape(f)}</h2>")
            sec.append(md2html(open(p, encoding="utf-8").read()))
        toc.append(f"<li>{html.escape(title)} — {sum(1 for f in files if os.path.exists(os.path.join('reports', f)))} отчётов</li>")
        body.append("\n".join(sec))
    rest = sorted(set(os.path.basename(p) for p in glob.glob("reports/*.md")) - used - {os.path.basename(OUT) + ".md"})
    if rest:
        body.append("<h1>9. Прочие отчёты</h1>" + "".join(f"<h2>📄 {html.escape(f)}</h2>" + md2html(open(os.path.join('reports', f), encoding='utf-8').read()) for f in rest))
        toc.append(f"<li>9. Прочие отчёты — {len(rest)}</li>")
    xs = ["<h1>10. Таблицы данных (Excel)</h1>"]
    for f, _, mx in XLSX:
        p = os.path.join("reports", f)
        if os.path.exists(p):
            xs.append(sheet_html(p, mx))
    dna = sorted(glob.glob("reports/dna_*_2026-10-05.xlsx"))
    dna = [p for p in dna if "dna_all" not in p]
    xs.append("<h1>11. ДНК каждой из 24 ниш — листы «Обзор» и «Гипотезы»</h1>")
    for p in dna:
        wb = load_workbook(p, read_only=True, data_only=True)
        for name in ("📋 Обзор", "🎯 Гипотезы"):
            if name in wb.sheetnames:
                ws = wb[name]
                rows = [r for r in ws.iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
                ncol = max(len(r) for r in rows)
                keep = [j for j in range(ncol) if any(j < len(r) and r[j] not in (None, "") for r in rows)]
                xs.append(f"<h3>{html.escape(os.path.basename(p))} — {html.escape(name)}</h3><table>" + "".join(
                    "<tr>" + "".join(f"<td>{html.escape(str(r[j]) if j < len(r) and r[j] is not None else '')}</td>" for j in keep) + "</tr>"
                    for r in rows) + "</table>")
    body.append("\n".join(xs))
    toc += ["<li>10. Таблицы данных (Excel): сравнение ниш 03.10, сезонный скрин 7/7, сводка ДНК 24 ниш</li>",
            "<li>11. ДНК каждой из 24 ниш (Обзор + Гипотезы)</li>"]
    head = (f"<h1 style='page-break-before:avoid'>Все данные по нишам — проект MPSTATS / Saleflow / WB (27.09–05.10.2026)</h1>"
            f"<p class='src'>Сборка всех отчётов из папки reports/ и сводных Excel. Метки: [факт] — из данных, [оценка] — расчёт, [допущение] — предположение. "
            f"Часть отчётов написана на армянском (по правилу проекта), история и итог — на русском.</p><h2>Содержание</h2><ul class='toc'>{''.join(toc)}</ul>")
    doc = f"<!doctype html><html><head><meta charset='utf-8'><title>Все данные по нишам</title><style>{CSS}</style></head><body>{head}{''.join(body)}</body></html>"
    open(OUT + ".html", "w", encoding="utf-8").write(doc)
    pdf = os.path.abspath(OUT + ".pdf")
    subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                    "file:///" + os.path.abspath(OUT + ".html").replace("\\", "/")], check=True, timeout=600)
    print("saved", pdf, os.path.getsize(pdf) // 1024, "KB")


if __name__ == "__main__":
    main()
