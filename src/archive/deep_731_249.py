"""Сегменты ниш 731 (Игрушки для животных) и 249 (Эспандеры) по названиям + новички по полосам цены (2026-10-16). 0 запросов.

    python src/deep_731_249.py
"""
import json,collections,re,statistics as st,sys
sys.stdout.reconfigure(encoding="utf-8")
seas={r["id"]:r["index"] for r in json.load(open("data/processed/all_niches_season_2026-10-11.json",encoding="utf-8"))}
SEG={731:[("⚡ электронные (запрет)",r"умн|автомат|летающ|usb|светящ|лазер|прятк|magic hide|электр|батаре|вращающ|робот|движущ|на аккум"),
          ("лакомства (не игрушка)",r"лакомств|корм"),
          ("собаки: набор (N в 1 / N шт)",r"(собак|щен).*(набор|\d+ ?в ?1|\d+ ?шт)|(набор|\d+ ?в ?1).*(собак|щен)"),
          ("собаки: канат/кусалка/жевательная",r"(собак|щен).*(канат|верев|кусалк|жеват|грызл|кость|пуллер|кольцо)|(канат|кусалк|пуллер).*(собак|щен)"),
          ("собаки: мяч/пищалка/мягкая/прочее",r"собак|щен"),
          ("кошки: дразнилка/удочка",r"дразнилк|удочк|перь"),
          ("кошки: мышки/мячики/мята",r"мыш|мяч|мят|мататаби|шарик"),
          ("кошки: тоннель/башня/коврик/когтеточка",r"тоннел|башн|коврик|когтеточ|трек"),
          ("кошки: прочее",r"кош|кот"),
          ("грызуны/птицы",r"грызун|хомяк|попуга|птиц|клетк|кролик|шиншил")],
     249:[("⚡ электронные (запрет)",r"электрон|счетчик|счётчик|led|светящ|usb"),
          ("кистевые эспандеры",r"кистев|пальц|кисти|предплеч"),
          ("резинки для подтягивания (power band)",r"подтяг|турник|жгут"),
          ("тканевые резинки",r"ткан"),
          ("латексные мини-петли (ноги/ягодицы)",r"ног|ягодиц|мини|петл"),
          ("трубчатые с ручками",r"трубчат|ручк"),
          ("ленточные/ленты",r"ленточн|лент"),
          ("эспандер лыжника/боксера/борцовский",r"лыжник|боксер|борцов"),
          ("грудной/плечевой/пружинный/восьмерка",r"грудн|плечев|пружин|восьмерк")]}
P={731:"data/raw/saleflow/2026-10-05/dna/731/products500_2026-07.json",249:"data/raw/saleflow/2026-10-07/newcomer/249/products500_2026-07.json"}
def seg_of(n,name):
    nm=name.lower()
    return next((s for s,rx in SEG[n] if re.search(rx,nm)),"прочее")
if __name__=="__main__":
  for n,p in P.items():
    d=json.load(open(p,encoding="utf-8")); R=[x for x in (d.get("data",d) if isinstance(d,dict) else d) if isinstance(x,dict) and x.get("sales")]
    k=(seas.get(n,{}).get("07") or 100)/100
    tot=sum(x["revenue"] for x in R)
    print(f"\n===== {n} | сезон июль {k} | выручка {round(tot/1e6,1)} млн | выкуп {R[0].get('purchase_after_return')} | rank500 {round(min(x['sales'] for x in R)/31,1)}/д")
    G=collections.defaultdict(list)
    for x in R: G[seg_of(n,x["name"])].append(x)
    print(f"{'сегмент':42} карт  выр%  шт/д/карт  цена мед  ≥900₽  новичков P50/P75  поб≥5(прод)  top1%  Китай%")
    for s in [s for s,_ in SEG[n]]+["прочее"]:
        L=G.get(s,[])
        if not L: continue
        new=[x for x in L if "2025-08-01"<=(x.get("sku_first_date") or "")<="2026-05-31"]
        lv=sorted(x["sales"]/31/k for x in new); q=lambda a: round(lv[int(round(a*(len(lv)-1)))],1) if lv else None
        win=[x for x in new if x["sales"]/31/k>=5]
        by=collections.Counter()
        for x in L: by[x.get("seller")]+=x["revenue"]
        t=sum(by.values())
        print(f"{s:42} {len(L):4} {round(t/tot*100,1):5} {round(st.mean(x['sales']/31 for x in L),1):9} {round(st.median(x['revenue']/x['sales'] for x in L)):8} {sum(1 for x in L if x['revenue']/x['sales']>=900):5} {len(new):6} {q(.5)}/{q(.75)} {len(win):5}({len({x.get('seller') for x in win})}) {round(by.most_common(1)[0][1]/t*100):6} {round(sum(x['revenue'] for x in L if 'кита' in str(x.get('country') or '').lower())/t*100):6}")
