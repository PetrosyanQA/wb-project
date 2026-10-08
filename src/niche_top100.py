"""12-месячная динамика top-100 субъекта: data/raw/saleflow/<date>/<niche>/monthly/products_YYYY-MM.json"""
import json, glob, os, sys, statistics as st, collections
sys.stdout.reconfigure(encoding="utf-8")
niche = sys.argv[1]; date = sys.argv[2] if len(sys.argv) > 2 else "2026-10-03"
D = os.path.join("data", "raw", "saleflow", date, niche, "monthly")
months = {}
for f in sorted(glob.glob(os.path.join(D, "products_*.json"))):
    m = os.path.basename(f)[9:16]
    data = json.load(open(f, encoding="utf-8"))["data"]
    data.sort(key=lambda x: -x["revenue"])
    for i, x in enumerate(data, 1): x["rank"] = i
    months[m] = {x["id"]: x for x in data}
ms = sorted(months)
print("месяцы:", ms[0], "…", ms[-1], len(ms))
print("\n## По месяцам: выручка top-100, top-1 / top-10 доля, новых карточек (не было в прошлом месяце), из них < 365 дн")
prev = set()
for m in ms:
    rows = list(months[m].values()); tot = sum(x["revenue"] for x in rows)
    top = sorted(rows, key=lambda x: -x["revenue"])
    new = [x for x in rows if x["id"] not in prev] if prev else []
    print(m, f"{tot/1e6:.0f}M", f"top1 {100*top[0]['revenue']/tot:.1f}%", f"top10 {100*sum(x['revenue'] for x in top[:10])/tot:.1f}%",
          "новых", len(new), "из них <365д", sum(1 for x in new if x["days_in_site"] < 365), "мед.цена", st.median(x["final_price"] for x in rows))
    prev = set(months[m])
allids = collections.Counter(i for m in ms for i in months[m])
info = {}
for m in ms:
    for i, x in months[m].items(): info[i] = x
print("\n## Постоянство: в скольких месяцах из 12 в top-100")
c = collections.Counter(allids.values())
for k in sorted(c, reverse=True): print(k, "мес:", c[k], "карточек")
last = months[ms[-1]]; first = months[ms[0]]
print("\n## Судьба top-100 сентября 2025 (через 11 мес): остались", len(set(first) & set(last)), "из", len(first))
# трейектории
def traj(i): return [months[m][i]["rank"] if i in months[m] else None for m in ms]
def rev(i): return [months[m][i]["revenue"] if i in months[m] else 0 for m in ms]
res = []
for i in allids:
    x = info[i]; t = traj(i); r = rev(i)
    present = [k for k, v in enumerate(t) if v]
    firstk = present[0]; 
    age_at_first = None
    try:
        import datetime as dt
        sd = dt.date.fromisoformat(x["sku_first_date"]); m0 = dt.date.fromisoformat(ms[firstk] + "-28")
        age_at_first = (m0 - sd).days
    except Exception: pass
    res.append(dict(id=i, seller=x["seller"], price=x["final_price"], t=t, r=r, n=len(present), firstk=firstk, age=age_at_first, x=x))
print("\n## «Новинки-победители»: карточка создана внутри окна (≤ 365 д до входа), вошла в top-100 после 1-го месяца и держится в последнем")
winners = [z for z in res if z["firstk"] > 0 and z["age"] is not None and z["age"] <= 365 and z["t"][-1]]
winners.sort(key=lambda z: z["t"][-1])
print("id | продавец | цена | вход (мес) | возраст при входе, дн | траектория рангов | выручка посл. мес, ₽ | отзывов | объём л")
for z in winners[:20]:
    x = z["x"]; v = x["package_length"] * x["package_width"] * x["package_height"] / 1000
    print(z["id"], z["seller"][:20], z["price"], ms[z["firstk"]], z["age"], z["t"], round(z["r"][-1]), x["comments"], round(v, 1))
print("всего победителей", len(winners))
print("\n## «Падающие звёзды»: в top-30 хотя бы раз, выручка последних 3 мес < 60% от средней 3 лучших мес")
fall = []
for z in res:
    r = z["r"]; best = sorted(r, reverse=True)[:3]
    if min(z["t"][k] or 999 for k in range(len(ms))) <= 30 and best and sum(r[-3:]) / 3 < 0.6 * sum(best) / 3:
        fall.append(z)
for z in fall[:12]: print(z["id"], z["seller"][:20], z["price"], z["t"])
print("всего", len(fall))
print("\n## «Стабильный рост»: ранг улучшился в ≥ 8 из 11 переходов… (упрощённо: выручка посл. 3 мес ≥ 1.3× первых 3 мес, присутствует ≥ 9 мес)")
grow = [z for z in res if z["n"] >= 9 and sum(z["r"][:3]) > 0 and sum(z["r"][-3:]) >= 1.3 * sum(z["r"][:3])]
grow.sort(key=lambda z: z["t"][-1] or 999)
for z in grow[:12]: print(z["id"], z["seller"][:20], z["price"], z["t"])
print("всего", len(grow))
json.dump([{k: v for k, v in z.items() if k != "x"} for z in res], open(os.path.join(D, "..", "top100_trajectories.json"), "w", encoding="utf-8"), ensure_ascii=False)
