"""Галерея WB 249 v3 — «Measured Tension» (canvas-design от Anthropic): перекладина-линия, подвешенные ленты, линейки.
Рендер в 2× (2160×2880) и уменьшение до 1080×1440 для чёткости. Шрифты — canvas-fonts (кириллица: IBM Plex Serif, Geist Mono, Jura).

    .venv\\Scripts\\python.exe marketing/249/v3/build.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FONTS = Path(r"C:\Users\ozon2\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\local-agent-mode-sessions\skills-plugin"
             r"\f8b80ee0-3951-4be6-919c-ebc6a747bc61\1fe748d0-a316-42a7-ae21-8752a933896f\skills\canvas-design\canvas-fonts")
S = 2                                    # суперсэмплинг
W, H = 1080 * S, 1440 * S
M = 96 * S                               # поля
PAPER, INK, GREY, HAIR, VIOLET = (244, 241, 234), (20, 20, 22), (120, 118, 112), (205, 200, 190), (75, 43, 196)

BLACK = Image.open(ROOT / "marketing/249/concept/cut_black.png").convert("RGBA")
VIO = Image.open(ROOT / "marketing/249/concept/cut_violet.png").convert("RGBA")
ACT = Image.open(ROOT / "marketing/249/v1/action_woman.png").convert("RGB")


def F(name: str, px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), int(px * S))


SERIF, MONO, MONOB, LIGHT = "IBMPlexSerif-Regular.ttf", "GeistMono-Regular.ttf", "GeistMono-Bold.ttf", "Jura-Light.ttf"


def trim(im: Image.Image) -> Image.Image:
    return im.crop(im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox())


BLACK, VIO = trim(BLACK), trim(VIO)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), PAPER)
    return im, ImageDraw.Draw(im)


def header(d: ImageDraw.ImageDraw, n: int, label: str) -> None:
    f = F(MONO, 17)
    d.text((M, M - 40 * S), f"{n:02d} — 10", font=F(MONOB, 17), fill=INK)
    t = label.upper()
    d.text((W - M - d.textlength(t, font=f), M - 40 * S), t, font=f, fill=GREY)
    d.line([(M, M), (W - M, M)], fill=INK, width=2 * S)


def bar(d: ImageDraw.ImageDraw, y: int, x0: int = None, x1: int = None) -> None:
    """Перекладина — главный мотив."""
    d.rounded_rectangle((x0 or M, y, x1 or W - M, y + 14 * S), radius=7 * S, fill=INK)


def text(d, xy, s, font, fill=INK, spacing=1.08):
    x, y = xy
    for ln in s.split("\n"):
        d.text((x, y), ln, font=font, fill=fill)
        y += int(font.size * spacing)
    return y


def hang(im: Image.Image, band: Image.Image, cx: int, top: int, height: int, angle: float = 0) -> None:
    b = band.rotate(angle, expand=True, resample=Image.BICUBIC) if angle else band
    r = height / b.height
    b = b.resize((int(b.width * r), int(b.height * r)), Image.LANCZOS)
    im.paste(b, (int(cx - b.width / 2), top), b)


def ruler(d: ImageDraw.ImageDraw, x: int, y0: int, y1: int, marks: int = 21, labels: dict | None = None) -> None:
    d.line([(x, y0), (x, y1)], fill=INK, width=S)
    for i in range(marks):
        y = y0 + (y1 - y0) * i / (marks - 1)
        w = 22 * S if i % 5 == 0 else 11 * S
        d.line([(x, y), (x + w, y)], fill=INK, width=S)
    for k, v in (labels or {}).items():
        y = y0 + (y1 - y0) * k
        d.text((x + 34 * S, y - 12 * S), v, font=F(MONO, 16), fill=GREY)


def specs(d: ImageDraw.ImageDraw, items: list[tuple[str, str]], y: int) -> None:
    d.line([(M, y), (W - M, y)], fill=INK, width=2 * S)
    cw = (W - 2 * M) / len(items)
    for i, (k, v) in enumerate(items):
        x = M + i * cw
        d.text((x, y + 22 * S), k.upper(), font=F(MONO, 16), fill=GREY)
        d.text((x, y + 52 * S), v, font=F(SERIF, 44), fill=INK)
        if i:
            d.line([(x - 18 * S, y + 22 * S), (x - 18 * S, y + 110 * S)], fill=HAIR, width=S)


def rows(d, items: list[tuple[str, str, str | None]], y: int, size: int = 40) -> int:
    d.line([(M, y), (W - M, y)], fill=INK, width=2 * S)
    for n, t, sub in items:
        y += 30 * S
        d.text((M, y + 8 * S), n, font=F(MONOB, 18), fill=VIOLET)
        d.text((M + 90 * S, y), t, font=F(SERIF, size), fill=INK)
        y += int(size * 1.25 * S)
        if sub:
            d.text((M + 90 * S, y), sub, font=F(MONO, 18), fill=GREY)
            y += 34 * S
        y += 22 * S
        d.line([(M, y), (W - M, y)], fill=HAIR, width=S)
    return y


def photo(im: Image.Image, box: tuple[int, int, int, int], focus: float = 0.25) -> None:
    x0, y0, x1, y1 = box
    p = ImageOps.fit(ACT, (x1 - x0, y1 - y0), Image.LANCZOS, centering=(0.5, focus))
    im.paste(p, (x0, y0))


def save(im: Image.Image, n: int) -> None:
    im.resize((1080, 1440), Image.LANCZOS).save(HERE / f"slide_{n:02d}.png", optimize=True)
    print("ok", n)


# ── слайды ────────────────────────────────────────────────────────────────

def s1():
    im, d = canvas(); header(d, 1, "Набор для турника")
    text(d, (M, 160 * S), "Первое\nподтягивание", F(SERIF, 96), spacing=1.04)
    d.text((M, 390 * S), "ДВЕ ЛЕНТЫ · TPE", font=F(MONOB, 18), fill=VIOLET)
    bar(d, 470 * S, int(W * 0.24), W - M)
    for x in (W * 0.42, W * 0.72):
        d.line([(x, 484 * S), (x, 510 * S)], fill=HAIR, width=S)
    hang(im, BLACK, int(W * 0.42), 510 * S, 620 * S)
    hang(im, VIO, int(W * 0.72), 510 * S, 620 * S)
    ruler(d, M, 470 * S, 1130 * S, 21, {0: "0", 1: "208"})
    specs(d, [("Ширина", "22 + 32 мм"), ("Длина", "208 см"), ("Толщина", "4,5 мм")], 1180 * S)
    save(im, 1)


def s2():
    im, d = canvas(); header(d, 2, "Комплект")
    text(d, (M, 170 * S), "Две ленты —\nдве силы", F(SERIF, 84))
    bar(d, 420 * S)
    hang(im, BLACK, int(W * 0.30), 470 * S, 680 * S)
    hang(im, VIO, int(W * 0.70), 470 * S, 680 * S)
    for x, a, b in ((W * 0.30, "A — ЧЁРНАЯ", "22 мм"), (W * 0.70, "B — ФИОЛЕТОВАЯ", "32 мм")):
        f = F(MONO, 16); t = a
        d.text((x - d.textlength(t, font=f) / 2, 1200 * S), t, font=f, fill=GREY)
        f2 = F(SERIF, 52)
        d.text((x - d.textlength(b, font=f2) / 2, 1232 * S), b, font=f2, fill=VIOLET if "32" in b else INK)
    save(im, 2)


def s3():
    im, d = canvas(); header(d, 3, "Какую взять")
    text(d, (M, 170 * S), "Шире —\nсильнее", F(SERIF, 96))
    y = 520 * S
    for name, kg, frac, col in (("ЧЁРНАЯ · 22 ММ", "29", 29 / 43, INK), ("ФИОЛЕТОВАЯ · 32 ММ", "43", 1.0, VIOLET)):
        d.text((M, y), name, font=F(MONO, 18), fill=GREY)
        x1 = M + (W - 2 * M - 240 * S) * frac
        d.rounded_rectangle((M, y + 44 * S, x1, y + 44 * S + 34 * S), radius=17 * S, fill=col)
        num = F(LIGHT, 120); s = kg
        d.text((W - M - d.textlength(s, font=num) - 70 * S, y + 6 * S), s, font=num, fill=col)
        d.text((W - M - 58 * S, y + 74 * S), "кг", font=F(SERIF, 34), fill=col)
        y += 230 * S
    rows(d, [("32", "Первые подтягивания", "берёт на себя больше веса"), ("22", "Добиваете повторы", "помогает меньше — работаете сами")], 1000 * S, 38)
    d.text((M, H - M - 10 * S), "ПОМОЩЬ В КГ — ПО ДАННЫМ ПРОИЗВОДИТЕЛЯ", font=F(MONO, 15), fill=GREY)
    save(im, 3)


def s4():
    im, d = canvas()
    photo(im, (0, 0, W, 860 * S), 0.18)
    d.rectangle((0, 860 * S, W, H), fill=PAPER)
    d.line([(M, 920 * S), (W - M, 920 * S)], fill=INK, width=2 * S)
    d.text((M, 880 * S), "04 — 10", font=F(MONOB, 17), fill=INK)
    t = "КАК ПОЛЬЗОВАТЬСЯ"; f = F(MONO, 17); d.text((W - M - d.textlength(t, font=f), 880 * S), t, font=f, fill=GREY)
    y = 940 * S
    for n, s in (("01", "Накиньте ленту на перекладину"), ("02", "Проденьте один конец в другой"), ("03", "Колено или стопу — в петлю")):
        d.text((M, y + 14 * S), n, font=F(MONOB, 18), fill=VIOLET)
        d.text((M + 90 * S, y), s, font=F(SERIF, 40), fill=INK)
        y += 112 * S
        d.line([(M, y - 26 * S), (W - M, y - 26 * S)], fill=HAIR, width=S)
    save(im, 4)


def s5():
    im, d = canvas(); header(d, 5, "Материал")
    d.text((M, 150 * S), "TPE", font=F(LIGHT, 300), fill=VIOLET)
    d.text((M, 500 * S), "термопластичный эластомер", font=F(SERIF, 40), fill=INK)
    y = 640 * S
    d.text((M + 470 * S, y), "TPE", font=F(MONOB, 18), fill=VIOLET)
    d.text((M + 700 * S, y), "ЛАТЕКС", font=F(MONO, 18), fill=GREY)
    y += 44 * S; d.line([(M, y), (W - M, y)], fill=INK, width=2 * S)
    for k, a, b in (("Запах резины", "нет", "бывает"), ("Латекс в составе", "нет", "да"), ("Толщина ленты", "4,5 мм", "разная")):
        y += 30 * S
        d.text((M, y), k, font=F(SERIF, 38), fill=INK)
        d.text((M + 470 * S, y), a, font=F(SERIF, 38), fill=VIOLET)
        d.text((M + 700 * S, y), b, font=F(SERIF, 38), fill=GREY)
        y += 74 * S; d.line([(M, y), (W - M, y)], fill=HAIR, width=S)
    hang(im, VIO, W // 2, 1090 * S, 220 * S, -90)
    bar(d, 1318 * S, M, W - M)
    save(im, 5)


def s6():
    im, d = canvas()
    photo(im, (W // 2, 0, W, H), 0.3)
    header(d, 6, "")
    d.line([(M, M), (W // 2 - 40 * S, M)], fill=INK, width=2 * S)
    d.rectangle((W // 2, 0, W, M + 1), fill=None)
    text(d, (M, 170 * S), "Если\nпока не\nполучается", F(SERIF, 62), spacing=1.08)
    y = 760 * S
    for n, s in (("01", "Новичкам\nи подросткам"), ("02", "Девушкам —\nпервые повторы"), ("03", "После\nперерыва")):
        d.text((M, y + 8 * S), n, font=F(MONOB, 17), fill=VIOLET)
        text(d, (M + 70 * S, y), s, F(SERIF, 34), spacing=1.15)
        y += 190 * S
    save(im, 6)


def s7():
    im, d = canvas(); header(d, 7, "Размеры")
    text(d, (M, 170 * S), "Одна длина,\nдве ширины", F(SERIF, 84))
    top, bot = 470 * S, 1330 * S
    ruler(d, M, top, bot, 21, {0: "0", 0.5: "104", 1: "208 см"})
    hang(im, VIO, int(W * 0.40), top, bot - top)
    x = int(W * 0.60)
    for y, k, v in ((560, "ДЛИНА В КОЛЬЦЕ", "208 см"), (820, "ШИРИНА", "22 / 32 мм"), (1080, "ТОЛЩИНА", "4,5 мм")):
        d.line([(x - 40 * S, y * S + 40 * S), (x - 10 * S, y * S + 40 * S)], fill=VIOLET, width=2 * S)
        d.text((x, y * S), k, font=F(MONO, 16), fill=GREY)
        d.text((x, y * S + 30 * S), v, font=F(LIGHT, 76), fill=INK)
    save(im, 7)


def s8():
    im, d = canvas(); header(d, 8, "Упражнения")
    text(d, (M, 170 * S), "Не только\nтурник", F(SERIF, 84))
    x0, y0, cw, ch = M, 480 * S, (W - 2 * M) // 2, 380 * S
    for i, t in enumerate(("Подтягивания\nс помощью", "Приседания\nи выпады", "Отжимания\nс сопротивлением", "Растяжка\nи разминка")):
        x, y = x0 + (i % 2) * cw, y0 + (i // 2) * ch
        d.rectangle((x, y, x + cw, y + ch), outline=HAIR, width=S)
        d.text((x + 34 * S, y + 34 * S), f"{i + 1:02d}", font=F(MONOB, 18), fill=VIOLET)
        text(d, (x + 34 * S, y + ch - 150 * S), t, F(SERIF, 40), spacing=1.12)
    d.line([(x0, y0), (W - M, y0)], fill=INK, width=2 * S)
    save(im, 8)


def s9():
    im, d = canvas(); header(d, 9, "Частые вопросы")
    text(d, (M, 170 * S), "Коротко\nо главном", F(SERIF, 84))
    rows(d, [("?", "Какая помогает сильнее?", "шире лента — сильнее помощь"), ("?", "Есть ли запах?", "TPE без запаха резины и без латекса"),
             ("?", "Подойдёт для дома?", "да — на любой турник")], 470 * S, 40)
    hang(im, BLACK, int(W * 0.34), 1120 * S, 190 * S, -90)
    hang(im, VIO, int(W * 0.68), 1120 * S, 190 * S, -90)
    bar(d, 1318 * S, M, W - M)
    save(im, 9)


def s10():
    im, d = canvas(); header(d, 10, "Уход")
    text(d, (M, 170 * S), "Чтобы\nслужила\nдольше", F(SERIF, 84))
    rows(d, [("01", "Не растягивать больше ×2,5", None), ("02", "Хранить без прямого солнца", None), ("03", "Осматривать перед тренировкой", None)], 600 * S, 38)
    hang(im, BLACK, int(W * 0.34), 1120 * S, 190 * S, -90)
    hang(im, VIO, int(W * 0.68), 1120 * S, 190 * S, -90)
    bar(d, 1318 * S, M, W - M)
    save(im, 10)


if __name__ == "__main__":
    for fn in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10):
        fn()
