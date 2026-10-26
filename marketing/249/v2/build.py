"""Галерея WB 249 v2 — швейцарский стиль (сетка, тонкие линии, крупный светлый шрифт, один акцент).
HTML-карточки 1080×1440 (3:4) → PNG через установленный Edge/Chrome в headless-режиме. Наш код, без сторонних пакетов.

    .venv\\Scripts\\python.exe marketing/249/v2/build.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
C = (ROOT / "marketing" / "249" / "concept").as_uri()
V1 = (ROOT / "marketing" / "249" / "v1").as_uri()
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');
:root{--paper:#f7f7f5;--ink:#0b0b0c;--g1:#ececea;--g2:#d6d6d3;--g3:#76767a;--acc:#5b2bd6;--acc-on:#fff}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1440px;overflow:hidden;background:var(--paper)}
body{font-family:Inter,'Segoe UI',Arial,sans-serif;color:var(--ink);position:relative}
.pad{position:absolute;inset:72px 72px 72px 72px}
.meta{display:flex;justify-content:space-between;font:600 22px 'IBM Plex Mono',monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--g3);border-bottom:2px solid var(--ink);padding-bottom:18px}
.meta b{color:var(--acc)}
h1{font-weight:300;font-size:118px;line-height:.98;letter-spacing:-.035em;margin-top:56px}
h1 em{font-style:normal;color:var(--acc);font-weight:400}
h2{font-weight:300;font-size:86px;line-height:1.0;letter-spacing:-.03em;margin-top:52px}
.lead{font-size:36px;font-weight:450;line-height:1.3;margin-top:28px;max-width:860px;color:#2a2a2c}
.foot{position:absolute;left:72px;right:72px;bottom:72px;display:grid;grid-template-columns:repeat(3,1fr);border-top:2px solid var(--ink)}
.foot div{padding:22px 0 0 0;font-size:24px;color:var(--g3);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.foot div b{display:block;font-size:52px;color:var(--ink);font-weight:400;letter-spacing:-.02em;text-transform:none;margin-top:6px}
.prod{position:absolute;object-fit:contain}
.rows{margin-top:44px;border-top:2px solid var(--ink)}
.row{display:grid;grid-template-columns:110px 1fr;align-items:baseline;padding:30px 0;border-bottom:1px solid var(--g2)}
.row .n{font:600 30px 'IBM Plex Mono',monospace;color:var(--acc)}
.row .t{font-size:44px;font-weight:400;letter-spacing:-.01em;line-height:1.15}
.row .t small{display:block;font-size:28px;color:var(--g3);font-weight:450;margin-top:8px;letter-spacing:0}
.bar{margin-top:30px}
.bar .lbl{display:flex;justify-content:space-between;font-size:34px;font-weight:500;margin-bottom:14px}
.bar .lbl span:last-child{font-weight:300;font-size:60px;letter-spacing:-.02em}
.bar .track{height:44px;background:var(--g1)}
.bar .fill{height:44px;background:var(--ink)}
.bar .fill.acc{background:var(--acc)}
.note{font:600 20px 'IBM Plex Mono',monospace;color:var(--g3);text-transform:uppercase;letter-spacing:.05em}
.photo{position:absolute;left:0;right:0;bottom:0;object-fit:cover}
.tbl{width:100%;border-collapse:collapse;margin-top:48px;font-size:36px}
.tbl th{font:600 22px 'IBM Plex Mono',monospace;text-transform:uppercase;letter-spacing:.06em;color:var(--g3);text-align:left;padding:0 0 16px;border-bottom:2px solid var(--ink)}
.tbl td{padding:30px 0;border-bottom:1px solid var(--g2);font-weight:400}
.tbl td.acc{color:var(--acc);font-weight:600}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:0;margin-top:48px;border-top:2px solid var(--ink);border-left:1px solid var(--g2)}
.tiles>div{border-right:1px solid var(--g2);border-bottom:1px solid var(--g2);padding:34px 30px 40px;min-height:230px}
.tiles .n{font:600 26px 'IBM Plex Mono',monospace;color:var(--acc)}
.tiles .t{font-size:46px;font-weight:300;letter-spacing:-.02em;margin-top:40px;line-height:1.05}
.dim{position:absolute;font:500 34px Inter,sans-serif}
.dim b{font-weight:300;font-size:74px;letter-spacing:-.03em;display:block;line-height:1}
.dline{position:absolute;background:var(--acc)}
"""


def page(n: int, body: str) -> str:
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def meta(n: int, title: str) -> str:
    return f"<div class='meta'><span><b>{n:02d}</b> / 10 · {title}</span><span>Ленты TPE · 22 + 32 мм</span></div>"


BLACK, VIOLET, ACT = f"{C}/cut_black.png", f"{C}/cut_violet.png", f"{V1}/action_woman.png"

CARDS = [
 # 1 обложка
 f"""<div class='pad'>{meta(1,'Набор для турника')}
 <h1>Первое<br>подтягивание —<br><em>с двумя<br>лентами</em></h1></div>
 <img class='prod' src='{BLACK}' style='left:540px;top:610px;height:560px;transform:rotate(-8deg)'>
 <img class='prod' src='{VIOLET}' style='left:760px;top:570px;height:600px;transform:rotate(6deg)'>
 <div class='foot'><div>Ширина<b>22 + 32 мм</b></div><div>Длина<b>208 см</b></div><div>Материал<b>TPE</b></div></div>""",
 # 2 комплект
 f"""<div class='pad'>{meta(2,'Комплект')}
 <h2>Две ленты —<br>две силы помощи</h2>
 <div class='lead'>Начните с широкой, переходите на узкую. Можно использовать вместе.</div></div>
 <img class='prod' src='{BLACK}' style='left:150px;top:560px;height:620px'>
 <img class='prod' src='{VIOLET}' style='left:600px;top:560px;height:620px'>
 <div class='foot' style='grid-template-columns:1fr 1fr'><div>Лента A · чёрная<b>22 мм</b></div><div>Лента B · фиолетовая<b>32 мм</b></div></div>""",
 # 3 выбор
 f"""<div class='pad'>{meta(3,'Какую взять')}
 <h2>Чем шире лента,<br>тем сильнее помогает</h2>
 <div class='bar' style='margin-top:90px'><div class='lbl'><span>Чёрная · 22 мм</span><span>до 29 кг</span></div><div class='track'><div class='fill' style='width:67%'></div></div></div>
 <div class='bar' style='margin-top:56px'><div class='lbl'><span>Фиолетовая · 32 мм</span><span>до 43 кг</span></div><div class='track'><div class='fill acc' style='width:100%'></div></div></div>
 <div class='rows' style='margin-top:90px'>
  <div class='row'><span class='n'>32</span><span class='t'>Первые подтягивания<small>берёт на себя больше веса</small></span></div>
  <div class='row'><span class='n'>22</span><span class='t'>Добиваете повторы<small>помогает меньше — работаете сами</small></span></div></div>
 <div class='note' style='position:absolute;bottom:0'>Помощь — по данным производителя</div></div>""",
 # 4 как пользоваться
 f"""<img class='photo' src='{ACT}' style='top:640px;height:800px;width:1080px;object-position:50% 20%'>
 <div class='pad' style='bottom:auto'>{meta(4,'Как пользоваться')}
 <h2 style='font-size:78px'>Три шага —<br>и вы на турнике</h2>
 <div class='rows' style='margin-top:30px'>
  <div class='row' style='padding:18px 0'><span class='n'>01</span><span class='t' style='font-size:36px'>Накиньте ленту на перекладину</span></div>
  <div class='row' style='padding:18px 0'><span class='n'>02</span><span class='t' style='font-size:36px'>Проденьте один конец в другой и затяните</span></div>
  <div class='row' style='padding:18px 0'><span class='n'>03</span><span class='t' style='font-size:36px'>Поставьте колено или стопу в петлю</span></div></div></div>""",
 # 5 материал
 f"""<div class='pad'>{meta(5,'Материал')}
 <h2>TPE —<br>не латекс</h2>
 <div class='lead'>Термопластичный эластомер: плотная лента 4,5 мм без запаха резины.</div>
 <table class='tbl'><tr><th></th><th>TPE · наш набор</th><th>Латекс</th></tr>
 <tr><td>Запах резины</td><td class='acc'>Нет</td><td>Бывает</td></tr>
 <tr><td>Латекс в составе</td><td class='acc'>Нет</td><td>Да</td></tr>
 <tr><td>Толщина</td><td class='acc'>4,5 мм</td><td>от 4,5 мм</td></tr></table></div>
 <img class='prod' src='{VIOLET}' style='left:420px;top:790px;height:600px;transform:rotate(-62deg)'>""",
 # 6 для кого
 f"""<img class='photo' src='{ACT}' style='top:0;height:1440px;width:1080px;object-position:50% 30%;filter:saturate(.9)'>
 <div style='position:absolute;left:0;right:0;bottom:0;height:640px;background:var(--paper)'></div>
 <div class='pad' style='top:840px'>
  <div class='meta'><span><b>06</b> / 10 · Для кого</span><span>Лента берёт часть веса</span></div>
  <div class='rows' style='margin-top:10px;border-top:none'>
   <div class='row' style='padding:22px 0'><span class='n'>01</span><span class='t'>Новичкам и подросткам</span></div>
   <div class='row' style='padding:22px 0'><span class='n'>02</span><span class='t'>Девушкам — первые подтягивания</span></div>
   <div class='row' style='padding:22px 0'><span class='n'>03</span><span class='t'>После перерыва в тренировках</span></div></div></div>""",
 # 7 размеры
 f"""<div class='pad'>{meta(7,'Размеры')}
 <h2>Одна длина,<br>две ширины</h2></div>
 <img class='prod' src='{VIOLET}' style='left:90px;top:470px;height:880px'>
 <div class='dline' style='left:72px;top:480px;width:3px;height:860px'></div>
 <div class='dim' style='left:640px;top:560px'>Длина в кольце<b>208 см</b></div>
 <div class='dim' style='left:640px;top:800px'>Ширина<b>22 / 32 мм</b></div>
 <div class='dim' style='left:640px;top:1040px'>Толщина<b>4,5 мм</b></div>""",
 # 8 упражнения
 f"""<div class='pad'>{meta(8,'Упражнения')}
 <h2>Не только<br>турник</h2>
 <div class='tiles'>
  <div><span class='n'>01</span><div class='t'>Подтягивания<br>с помощью</div></div>
  <div><span class='n'>02</span><div class='t'>Приседания<br>и выпады</div></div>
  <div><span class='n'>03</span><div class='t'>Отжимания<br>с сопротивлением</div></div>
  <div><span class='n'>04</span><div class='t'>Растяжка<br>и разминка</div></div></div></div>""",
 # 9 вопросы
 f"""<div class='pad'>{meta(9,'Частые вопросы')}
 <h2>Коротко<br>о главном</h2>
 <div class='rows'>
  <div class='row'><span class='n'>?</span><span class='t'>Какая помогает сильнее?<small>Шире лента — сильнее помощь: 32 мм сильнее 22 мм</small></span></div>
  <div class='row'><span class='n'>?</span><span class='t'>Есть ли запах?<small>TPE без запаха резины и без латекса</small></span></div>
  <div class='row'><span class='n'>?</span><span class='t'>Подойдёт для дома?<small>Да — на любой турник: в проёме или на стене</small></span></div></div></div>
 <img class='prod' src='{BLACK}' style='left:300px;top:800px;height:540px;transform:rotate(-62deg)'><img class='prod' src='{VIOLET}' style='left:420px;top:930px;height:540px;transform:rotate(-62deg)'>""",
 # 10 уход
 f"""<div class='pad'>{meta(10,'Уход')}
 <h2>Чтобы служила<br>дольше</h2>
 <div class='rows'>
  <div class='row'><span class='n'>01</span><span class='t'>Не растягивайте больше чем в 2,5 раза</span></div>
  <div class='row'><span class='n'>02</span><span class='t'>Храните без прямого солнца</span></div>
  <div class='row'><span class='n'>03</span><span class='t'>Осматривайте перед тренировкой</span></div></div></div>
 <img class='prod' src='{BLACK}' style='left:300px;top:760px;height:560px;transform:rotate(-62deg)'><img class='prod' src='{VIOLET}' style='left:420px;top:900px;height:560px;transform:rotate(-62deg)'>""",
]


def main() -> None:
    br = next((b for b in BROWSERS if Path(b).exists()), None)
    if not br:
        sys.exit("нет Edge/Chrome")
    for i, body in enumerate(CARDS, 1):
        html = HERE / f"card_{i:02d}.html"
        html.write_text(page(i, body), encoding="utf-8")
        png = HERE / f"slide_{i:02d}.png"
        subprocess.run([br, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--window-size=1080,1440", "--virtual-time-budget=4000", f"--screenshot={png}", html.as_uri()],
                       check=True, capture_output=True, timeout=120)
        print("ok", png.name)


if __name__ == "__main__":
    main()
