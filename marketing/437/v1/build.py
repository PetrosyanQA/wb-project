"""Черновик 10 слайдов карточки WB: набор 12 кистей (ниша 437), 900×1200 (3:4).

    python marketing/437/v1/build.py   → marketing/437/v1/slide_01.png … slide_10.png + sheet.jpg

ЧЕРНОВИК: фото — поставщика 1688 (оффер 971130985611), китайский текст обрезан. В карточку WB — только после
съёмки своего образца (режим «без образца», правило пользователя 26.10). «Без запаха» / «не линяет» не пишем до теста.
Назначение кистей — по подписям поставщика на фото 6 (散粉刷 → пудра и т.д.).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "marketing" / "437" / "suppliers"
OUT = Path(__file__).resolve().parent
W, H = 900, 1200
NAVY, GOLD, CREAM, PINK, INK, WHITE = (27, 38, 64), (201, 163, 91), (247, 242, 234), (236, 196, 205), (34, 34, 40), (255, 255, 255)
FONTS = "C:/Windows/Fonts/"


def F(bold: bool, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS + ("georgiab.ttf" if bold else "arial.ttf"), px)


def src(n: int) -> Image.Image:
    return Image.open(SRC / f"971130985611_{n}.jpg").convert("RGB")


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    r = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def canvas(bg=CREAM) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), bg)
    return im, ImageDraw.Draw(im)


def title(d: ImageDraw.ImageDraw, s: str, y: int = 60, fill=NAVY, size: int = 62) -> int:
    for line in s.split("\n"):
        d.text((W // 2, y), line, font=F(True, size), fill=fill, anchor="mt")
        y += int(size * 1.18)
    return y


def sub(d, s: str, y: int, fill=INK, size: int = 34) -> int:
    for line in s.split("\n"):
        d.text((W // 2, y), line, font=F(False, size), fill=fill, anchor="mt")
        y += int(size * 1.35)
    return y


def pill(d, xy, s: str, fill=GOLD, ink=WHITE, size: int = 30) -> None:
    f = F(False, size)
    w = d.textlength(s, font=f)
    x, y = xy
    d.rounded_rectangle((x, y, x + w + 48, y + size + 30), radius=(size + 30) // 2, fill=fill)
    d.text((x + 24, y + 15), s, font=f, fill=ink)


def save(im: Image.Image, n: int) -> None:
    d = ImageDraw.Draw(im)
    d.text((W - 18, H - 14), "черновик · фото поставщика", font=F(False, 18), fill=(150, 150, 150), anchor="rd")
    im.save(OUT / f"slide_{n:02d}.png")


def s1():   # главный
    im, d = canvas(NAVY)
    im.paste(fit(src(4), W, 860), (0, 340))
    y = title(d, "Кисти для макияжа", 60, WHITE, 70)
    sub(d, "12 штук + чехол-конверт", y + 6, GOLD, 44)
    pill(d, (40, 1080), "12 кистей", GOLD)
    pill(d, (270, 1080), "мягкий ворс", WHITE, NAVY)
    pill(d, (560, 1080), "чехол в комплекте", PINK, NAVY)
    save(im, 1)


NAMES = ["Пудра", "Румяна", "Контур", "Хайлайтер", "Тени L", "Нос", "Растушёвка", "Тени M", "Подводка", "Консилер", "Детали", "Брови"]


def s2():   # что в наборе: фото 6 без китайских подписей + русские подписи
    im, d = canvas(WHITE)
    y = title(d, "Что в наборе", 50, NAVY, 60)
    sub(d, "12 кистей для лица и глаз", y, INK, 34)
    p = src(6)
    p = p.crop((0, 0, p.width, int(p.height * 0.66)))
    k = W / p.width
    p = p.resize((W, int(p.height * k)), Image.LANCZOS)
    im.paste(p, (0, 240))
    xs = [38, 76, 118, 158, 193, 217, 249, 280, 307, 333, 357, 382]  # центры кистей на фото поставщика (из 400 px)
    for x, n in zip(xs, NAMES):                                     # подписи столбиком под каждой кистью
        lab = Image.new("RGBA", (230, 36), (0, 0, 0, 0))
        ImageDraw.Draw(lab).text((230, 2), n, font=F(False, 26), fill=NAVY, anchor="ra")
        lab = lab.rotate(90, expand=True)
        cx = int(x * 2 * k)
        im.paste(lab, (cx - 18, 240 + p.height + 20), lab)
    save(im, 2)


def s3():   # мягкость
    im, d = canvas(NAVY)
    p = src(2)
    p = p.crop((0, int(p.height * 0.32), p.width, p.height))
    im.paste(fit(p, W, 820), (0, 380))
    y = title(d, "Мягкий плотный ворс", 70, WHITE, 60)
    sub(d, "не колет кожу и ровно\nраспределяет пудру и тени", y + 10, CREAM, 36)
    save(im, 3)


def s4():   # лицо и глаза
    im, d = canvas(CREAM)
    y = title(d, "Для лица и для глаз", 60, NAVY, 58)
    p = fit(src(5), W, 760)
    im.paste(p, (0, 230))
    d.rounded_rectangle((40, 1010, 430, 1150), 24, fill=NAVY)
    d.rounded_rectangle((470, 1010, 860, 1150), 24, fill=GOLD)
    d.text((235, 1040), "Лицо", font=F(True, 40), fill=WHITE, anchor="mt")
    d.text((235, 1095), "пудра, румяна, контур", font=F(False, 26), fill=CREAM, anchor="mt")
    d.text((665, 1040), "Глаза и брови", font=F(True, 40), fill=WHITE, anchor="mt")
    d.text((665, 1095), "тени, подводка, брови", font=F(False, 26), fill=WHITE, anchor="mt")
    save(im, 4)


def s5():   # чехол
    im, d = canvas(NAVY)
    p = src(4)
    im.paste(fit(p.crop((0, 0, int(p.width * 0.62), p.height)), W, 900), (0, 300))
    y = title(d, "Чехол в комплекте", 70, WHITE, 60)
    sub(d, "все 12 кистей в одном конверте —\nдома и в дороге", y + 6, PINK, 34)
    save(im, 5)


def s6():   # ручки
    im, d = canvas(CREAM)
    p = src(1)
    p = p.crop((0, int(p.height * 0.30), int(p.width * 0.66), int(p.height * 0.88)))
    im.paste(fit(p, W, 760), (0, 300))
    y = title(d, "Удобные ручки", 70, NAVY, 60)
    sub(d, "лёгкие, с золотой обоймой —\nкисть не скользит в руке", y + 6, INK, 34)
    d.rectangle((0, 1060, W, H), fill=NAVY)
    d.text((W // 2, 1110), "приятно держать и красиво хранить", font=F(False, 32), fill=GOLD, anchor="mm")
    save(im, 6)


def s7():   # порядок макияжа
    im, d = canvas(WHITE)
    y = title(d, "Макияж за 5 шагов", 60, NAVY, 58)
    steps = [("1", "Тон и консилер", "кисть для консилера"), ("2", "Пудра", "большая пушистая кисть"),
             ("3", "Румяна и контур", "скошенная и круглая"), ("4", "Хайлайтер", "веерная кисть"),
             ("5", "Тени и брови", "кисти для глаз и бровей")]
    y += 50
    for n, a, b in steps:
        d.ellipse((70, y, 160, y + 90), fill=GOLD)
        d.text((115, y + 45), n, font=F(True, 46), fill=WHITE, anchor="mm")
        d.text((200, y + 6), a, font=F(True, 40), fill=NAVY)
        d.text((200, y + 56), b, font=F(False, 28), fill=INK)
        y += 160
    im.paste(fit(src(5), W, 220).filter(ImageFilter.GaussianBlur(0)), (0, H - 220))
    save(im, 7)


def s8():   # уход
    im, d = canvas(NAVY)
    y = title(d, "Как ухаживать", 70, WHITE, 60)
    tips = ["Мойте раз в неделю тёплой\nводой с мылом", "Отжимайте ворс полотенцем,\nне выкручивайте",
            "Сушите ворсом вниз\nили лёжа", "Храните в чехле —\nворс не мнётся"]
    y += 60
    for t in tips:
        d.rounded_rectangle((60, y, 840, y + 170), 28, fill=CREAM)
        d.ellipse((90, y + 60, 140, y + 110), fill=GOLD)
        d.line((102, y + 86, 113, y + 97, 130, y + 73), fill=WHITE, width=6)
        d.multiline_text((180, y + 85), t, font=F(False, 34), fill=NAVY, anchor="lm", spacing=8)
        y += 200
    save(im, 8)


def s9():   # подарок
    im, d = canvas(PINK)
    p = src(4)
    im.paste(fit(p, W, 820), (0, 380))
    y = title(d, "Красивый подарок", 70, NAVY, 60)
    sub(d, "маме, подруге, дочке —\nна Новый год и 8 Марта", y + 6, NAVY, 36)
    save(im, 9)


def s10():  # итог
    im, d = canvas(CREAM)
    y = title(d, "Всё для макияжа\nв одном наборе", 60, NAVY, 56)
    im.paste(fit(src(5), W, 520), (0, y + 30))
    y = y + 590
    for a, b in (("12", "кистей для лица и глаз"), ("1", "чехол-конверт"), ("5", "шагов — полный макияж")):
        d.text((150, y), a, font=F(True, 64), fill=GOLD, anchor="mm")
        d.text((240, y), b, font=F(False, 36), fill=NAVY, anchor="lm")
        y += 100
    save(im, 10)


if __name__ == "__main__":
    for f in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10):
        f()
    ims = [Image.open(OUT / f"slide_{i:02d}.png").resize((300, 400)) for i in range(1, 11)]
    sheet = Image.new("RGB", (1500, 800), "white")
    for i, t in enumerate(ims):
        sheet.paste(t, ((i % 5) * 300, (i // 5) * 400))
    sheet.save(OUT / "sheet.jpg", quality=88)
    print("ok", OUT)
