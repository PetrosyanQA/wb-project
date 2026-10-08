"""Ինտերակտիվ HTML աղյուսակ՝ բոլոր նիշաները սքորերով (սորտավորում + ֆիլտր, առանց ինտերնետի)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

COLUMNS = [
    ("rank", "#", "num"),
    ("path", "Նիշա", "text"),
    ("score", "Սքոր", "num"),
    ("cheap_score", "Մաղ", "num"),
    ("probe_score", "Զոնդ", "num"),
    ("yoy_peak_pct", "YoY պիկ %", "num"),
    ("slope_pct_month", "%/ամիս", "num"),
    ("top10_share", "Տոպ-10 %", "num"),
    ("top_seller_share", "1 վաճ. %", "num"),
    ("comments_barrier", "Կարծիք", "num"),
    ("fresh_pct", "Թարմ %", "num"),
    ("revenue", "Շրջ. ₽", "num"),
    ("sku", "SKU", "num"),
    ("revenue_per_sku", "₽/SKU", "num"),
    ("avg_price", "Միջին գին", "num"),
    ("tier", "Խումբ", "text"),
    ("flags", "Ազդանշաններ", "text"),
]

TEMPLATE = """<!doctype html>
<html lang="hy"><head><meta charset="utf-8">
<title>Նիշաների սքորինգ — {date}</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;
      background:#0f1115;color:#e8eaed}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#9aa0a6;margin-bottom:16px;font-size:13px}}
 .bar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}}
 input,select{{background:#1b1e24;border:1px solid #2c313a;color:#e8eaed;padding:7px 10px;
      border-radius:7px;font-size:13px}}
 input{{min-width:230px}}
 .chip{{padding:5px 11px;border-radius:99px;font-size:12px;border:1px solid #2c313a;
      cursor:pointer;user-select:none;background:#1b1e24}}
 .chip.on{{background:#2b4b32;border-color:#3f7a4d}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{padding:7px 9px;border-bottom:1px solid #22262e;text-align:right;white-space:nowrap}}
 th{{position:sticky;top:0;background:#171a20;cursor:pointer;user-select:none;text-align:right;
      font-weight:600;color:#c7cbd1}}
 th:hover{{color:#fff}}
 td:nth-child(2),th:nth-child(2),td:last-child,th:last-child{{text-align:left;white-space:normal}}
 tr:hover td{{background:#171a20}}
 .A{{color:#5ed37e;font-weight:700}} .B{{color:#e4c95b;font-weight:600}}
 .C{{color:#9aa0a6}} .X{{color:#e2695f}}
 .bad{{color:#e2695f}} .good{{color:#5ed37e}}
 .muted{{color:#6b7280}}
 footer{{margin-top:18px;color:#6b7280;font-size:12px}}
</style></head><body>
<h1>Նիշաների սքորինգ</h1>
<div class="sub">{date} · մաղվել է {scanned} նիշա · {used} API հարցում ·
  սեղմիր սյան վրա՝ սորտավորելու համար</div>
<div class="bar">
  <input id="q" placeholder="Որոնում նիշայի անունով…">
  <span class="chip on" data-t="A">🟢 A (≥70)</span>
  <span class="chip on" data-t="B">🟡 B (55–69)</span>
  <span class="chip" data-t="C">⚪️ C (40–54)</span>
  <span class="chip" data-t="X">❌ մերժված</span>
  <span id="cnt" class="muted"></span>
</div>
<table id="t"><thead><tr>{head}</tr></thead><tbody></tbody></table>
<footer>Սքոր = 40% էժան մաղ + 60% զոնդ։ Զոնդը տեսնում է մոնոպոլիան, աճը, կարծիքների բարիերը
և թարմ քարտերի հաջողությունը։ Խորը որոշման համար՝ trend_scan + niche_scan + unit_econ։</footer>
<script>
const DATA = {data};
const COLS = {cols};
let sortKey='score', sortDir=-1;
const tiers = new Set(['A','B']);
const fmt = (v,k)=>{{
  if(v===null||v===undefined||v==='') return '<span class=muted>—</span>';
  if(typeof v!=='number') return v;
  if(k==='score'||k==='cheap_score'||k==='probe_score') return v.toFixed(1);
  if(k==='yoy_peak_pct'||k==='slope_pct_month') return `<span class="${{v<0?'bad':'good'}}">${{v>0?'+':''}}${{v.toFixed(0)}}</span>`;
  if(k==='top10_share'||k==='top_seller_share') return `<span class="${{v>70?'bad':''}}">${{v.toFixed(0)}}</span>`;
  if(k==='comments_barrier') return `<span class="${{v>800?'bad':''}}">${{v.toLocaleString()}}</span>`;
  return Math.round(v).toLocaleString();
}};
function render(){{
  const q=document.getElementById('q').value.toLowerCase();
  let rows=DATA.filter(r=>tiers.has(r.tier)&&(!q||r.path.toLowerCase().includes(q)));
  rows.sort((a,b)=>{{const x=a[sortKey],y=b[sortKey];
    if(x===null||x===undefined)return 1; if(y===null||y===undefined)return -1;
    return (x>y?1:x<y?-1:0)*sortDir;}});
  document.querySelector('#t tbody').innerHTML=rows.map((r,i)=>'<tr>'+COLS.map(c=>{{
    let v=c[0]==='rank'?i+1:r[c[0]];
    let cls=c[0]==='score'?r.tier:(c[0]==='tier'?r.tier:'');
    return `<td class="${{cls}}">${{fmt(v,c[0])}}</td>`;}}).join('')+'</tr>').join('');
  document.getElementById('cnt').textContent=`ցուցադրված՝ ${{rows.length}} / ${{DATA.length}}`;
}}
document.querySelectorAll('th').forEach((th,i)=>th.onclick=()=>{{
  const k=COLS[i][0]; sortDir=(k===sortKey)?-sortDir:-1; sortKey=k; render();}});
document.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{{
  const t=ch.dataset.t; ch.classList.toggle('on');
  tiers.has(t)?tiers.delete(t):tiers.add(t); render();}});
document.getElementById('q').oninput=render;
render();
</script></body></html>"""


def tier_of(score: float, rejected: list[str]) -> str:
    if rejected:
        return "X"
    return "A" if score >= 70 else "B" if score >= 55 else "C" if score >= 40 else "X"


def write_html(cands: list[dict], scanned: int, used: int, out: Path) -> Path:
    data = []
    for c in cands:
        pr = c.get("_probe") or {}
        data.append({
            "path": c["path"],
            "score": c["score"],
            "cheap_score": c.get("cheap_score", c["score"]),
            "probe_score": c.get("_probe_score"),
            "yoy_peak_pct": pr.get("yoy_peak_pct"),
            "slope_pct_month": pr.get("slope_pct_month"),
            "top10_share": pr.get("top10_share"),
            "top_seller_share": pr.get("top_seller_share"),
            "comments_barrier": pr.get("comments_barrier"),
            "fresh_pct": pr.get("fresh_pct"),
            "revenue": round(c["revenue"]),
            "sku": round(c["sku"]),
            "revenue_per_sku": round(c["revenue_per_sku"]),
            "avg_price": round(c["avg_price"]),
            "tier": tier_of(c["score"], c["rejected"]),
            "flags": " ".join(c.get("_flags") or []) or "; ".join(c["rejected"]),
        })
    head = "".join(f"<th>{label}</th>" for _, label, _ in COLUMNS)
    html = TEMPLATE.format(
        date=date.today().isoformat(), scanned=scanned, used=used, head=head,
        data=json.dumps(data, ensure_ascii=False),
        cols=json.dumps([[k, lbl, t] for k, lbl, t in COLUMNS], ensure_ascii=False))
    out.write_text(html, encoding="utf-8")
    return out
