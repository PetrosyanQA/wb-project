"""Справочный центр WB для продавцов (seller.wildberries.ru/instructions) → docs/wb_help/<категория>/<подкатегория>/<slug>.md.

    python -m src.wb_help_sync            # дерево + все статьи (уже скачанные пропускаются)
    python -m src.wb_help_sync --force    # перекачать всё заново
    python -m src.wb_help_sync --offer    # только собрать docs/wb_help/OFFER_full.md из статей оферты

Страницы — Next.js RSC: текст статьи лежит в self.__next_f.push(...), длинные абзацы — в T-чанках ($ссылки).
9 статей WB показывает только в кабинете — в файле будет заглушка «Статья доступна только продавцам».
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, html as H
import requests
from concurrent.futures import ThreadPoolExecutor
sys.stdout.reconfigure(encoding="utf-8")
BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "section", "ul", "ol", "table", "br", "blockquote"}
HEAD = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### "}
def rsc_lines(s):
    raw = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', s, flags=re.S):
        try: raw.append(json.loads('"' + m.group(1) + '"'))
        except Exception: pass
    b = "".join(raw).encode("utf8")
    lines, i, n = {}, 0, len(b)
    rx = re.compile(rb'([0-9a-f]+):')
    while i < n:
        m = rx.match(b, i)
        if not m:
            j = b.find(b"\n", i); i = n if j < 0 else j + 1; continue
        k = m.group(1).decode(); i = m.end()
        if b[i:i+1] == b"T":
            c = b.find(b",", i); ln = int(b[i+1:c], 16)
            lines[k] = ("T", b[c+1:c+1+ln].decode("utf8", "replace")); i = c + 1 + ln
        else:
            j = b.find(b"\n", i); j = n if j < 0 else j
            lines[k] = ("J", b[i:j].decode("utf8", "replace")); i = j + 1
    return lines
def walk(node, out, L, depth=0):
    if depth > 200: return
    if isinstance(node, str):
        m = re.fullmatch(r"\$([0-9a-f]+)", node)
        if m and m.group(1) in L:
            t, v = L[m.group(1)]
            if t == "T": out.append(v); return
            try: walk(json.loads(v), out, L, depth + 1)
            except Exception: pass
            return
        if node.startswith("$") and len(node) < 12: return
        out.append(node); return
    if isinstance(node, list):
        if len(node) == 4 and node[0] == "$" and isinstance(node[1], str):
            tag, props = node[1], node[3] if isinstance(node[3], dict) else {}
            dn = props.get("data-name", "")
            blk = tag in BLOCK or dn in ("Title", "Paragraph", "ListItem", "Callout", "TableRow")
            if tag in ("td", "th"): out.append(" | ")
            if blk: out.append("\n" + HEAD.get(tag, ""))
            if tag == "li": out.append("- ")
            if tag == "img" and props.get("src"): out.append(f"[img:{props.get('alt','')}]")
            if "children" in props: walk(props["children"], out, L, depth + 1)
            if "dangerouslySetInnerHTML" in props:
                h = props["dangerouslySetInnerHTML"].get("__html", "") if isinstance(props["dangerouslySetInnerHTML"], dict) else ""
                if isinstance(h, str):
                    m = re.fullmatch(r"\$([0-9a-f]+)", h)
                    if m and m.group(1) in L: h = L[m.group(1)][1]
                    import html as H
                    h = re.sub(r"</(p|li|h\d|tr|div)>|<br\s*/?>", "\n", h); h = re.sub(r"<li[^>]*>", "- ", h)
                    out.append(H.unescape(re.sub(r"<[^>]+>", "", h)))
            if blk: out.append("\n")
            return
        for x in node: walk(x, out, L, depth + 1)
    elif isinstance(node, dict):
        if "children" in node: walk(node["children"], out, L, depth + 1)
def article_text(html):
    L = rsc_lines(html)
    best = ""
    for k, (t, v) in L.items():
        if t != "J" or "Обновлено" not in v: continue
        try: j = json.loads(v)
        except Exception: continue
        out = []; walk(j, out, L)
        s = re.sub(r"\n\s*\n+", "\n\n", "".join(out)).strip()
        if len(s) > len(best): best = s
    return best


BASE = "https://seller.wildberries.ru/instructions/ru/ru"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
OUT = "docs/wb_help"
OFFER_ORDER = ["how-to-use-offer", "for-reference", "definitions", "contract-concluding-process", "contract-subject", "sale-of-goods",
               "price-reporting-and-calculations", "remuneration-and-ohter-payments", "contract-changing", "final-positions", "site-using-terms",
               "packing-and-labeling-terms", "items-acceptance-and-return-terms", "calculating-remuneration-rules-and-fbs-acceptance-procedure",
               "service-terms", "item-redemtion-terms", "item-promotion-service-terms", "ads-placement-service-terms", "wb-mediservice-application-form",
               "personal-datprocessing-agreement", "items-retention", "vehicle-sale-terms", "placement-of-offers-for-booking-goods", "closing-the-personal-account"]


def get(url: str) -> str | None:
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=90)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(3)
    return None


def items_in(page: str) -> dict:
    txt = "\n".join(v for t, v in rsc_lines(page).values() if t == "J")
    return {m.group(1): (m.group(2), m.group(4)) for m in
            re.finditer(r'\{"id":"(A-\d+)","title":"(.*?)","type":"(\w+)","slug":"([^"]+)"', txt)}


def build_tree() -> dict:
    idx = get(f"{BASE}/categories") or ""
    items, tree = items_in(idx), {}
    for c in sorted(set(re.findall(r"/instructions/ru/ru/category/([a-z0-9\-]+)", idx))):
        tree[c] = {}
        for s in sorted(set(re.findall(r"/instructions/ru/ru/subcategory/([a-z0-9\-]+)", get(f"{BASE}/category/{c}") or ""))):
            hs = get(f"{BASE}/subcategory/{s}") or ""
            items.update(items_in(hs))
            tree[c][s] = sorted(set(re.findall(r"/instructions/ru/ru/material/([A-Za-z0-9\-]+)", hs)))
    os.makedirs(OUT, exist_ok=True)
    json.dump({"tree": tree, "items": items}, open(f"{OUT}/_index.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    return {"tree": tree, "items": items}


def download(index: dict, force: bool, day: str) -> None:
    items = index["items"]
    slug2 = {v[1]: (k, v[0]) for k, v in items.items()}
    jobs = [(c, s, a) for c, subs in index["tree"].items() for s, arts in subs.items() for a in arts]

    def one(j):
        c, s, a = j
        title = items[a][0] if a in items else slug2.get(a, (None, None))[1]
        slug = items[a][1] if a in items else a
        p = f"{OUT}/{c}/{s}/{slug}.md"
        if os.path.exists(p) and not force:
            return "cached"
        for _ in range(3):
            try:
                r = requests.get(f"{BASE}/material/{a}", headers=UA, timeout=90)
                if r.status_code == 200:
                    t = article_text(r.text)
                    if len(t) < 100:
                        return "empty"
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    head = f"# {title or slug}\n\nИсточник: {r.url}\nКатегория: {c} / {s}\nСкачано: {day}\n\n---\n\n"
                    open(p, "w", encoding="utf8").write(head + t + "\n")
                    return "ok"
            except requests.RequestException:
                pass
            time.sleep(4)
        return "fail"

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, jobs))
    print({k: res.count(k) for k in set(res)}, "из", len(jobs))


def offer() -> None:
    d = f"{OUT}/get-started-on-wildberries/offer"
    parts = [open(f"{d}/{s}.md", encoding="utf8").read() for s in OFFER_ORDER if os.path.exists(f"{d}/{s}.md")]
    open(f"{OUT}/OFFER_full.md", "w", encoding="utf8").write(
        "# Оферта Wildberries для продавцов — все разделы одним файлом\n\nСобрано из справочного центра (src.wb_help_sync --offer). "
        "Полная PDF-версия — в кабинете: https://seller.wildberries.ru/confirm-offer-condition/view\n\n" + "\n\n".join(parts))
    print("OFFER_full.md:", len(parts), "разделов")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--offer", action="store_true")
    a = ap.parse_args()
    if not a.offer:
        download(build_tree(), a.force, time.strftime("%Y-%m-%d"))
    offer()


if __name__ == "__main__":
    main()
