# Accio prompts — вакуумно-магнитный держатель MagSafe (2026-10-06)

Эталон: карточка WB 485786521 — прикрепить главное фото к первому сообщению в Accio.
Писать на английском.

## Промпт 1 — найти товар

```
I am a Wildberries (Russia) seller. Find me suppliers for this exact product (reference photo attached):

PRODUCT: Vacuum suction magnetic car phone holder, MagSafe-compatible, compact.

MUST HAVE:
1. Mechanical vacuum suction cup (lever or press type) + sticky washable nano-gel layer. NOT electric: no battery, no charging, no Bluetooth, no lights.
2. Strong N52 magnets in a MagSafe-style ring; must hold a 220–240 g phone (iPhone Pro Max) through a 2 mm case on bumpy roads. Supplier must state magnet count and pull force (N or kg).
3. Ball joint with a tightening/lock nut, 360° rotation.
4. Compact head ~6 cm diameter, total height 4–10 cm; mounts on dashboard, console or windshield.
5. Materials: ABS/PC + TPE or silicone (metal ring is a plus).
6. Color: matte black (main). Also ask if titanium grey / graphite is available.
7. Kit per unit: holder ×1, magnetic rings/plates for phone ×4, rough-surface adhesive base stickers ×2–3, cleaning wipes, instruction.
8. Individual color box ~9×8×5 cm, total weight with box ≤ 0.15 kg.
9. Neutral packaging: NO Apple logo, NO "MagSafe" text on product or box, no other brand logo.

COMMERCIAL:
- Target price: ≤ USD 2.6 (≤ CNY 18) per unit INCLUDING color box and all accessories.
- Order quantity: 200–500 units. MOQ must be ≤ 300.
- Samples: 2 units available.
- Prefer verified manufacturers (not traders), ≥ 3 years on platform, response rate ≥ 90%, good reviews, product video available.

EXCLUDE: electric vacuum holders, wireless charging holders, air-vent clip holders, long telescopic arms, items over 0.2 kg, anything with Apple branding.

OUTPUT: a comparison table of the 8–10 best suppliers with columns:
supplier name | manufacturer or trader | years | rating | unit price at 200 and 500 pcs | MOQ | magnet count & pull force | suction type (mechanical/electric) | kit contents | box size | weight with box | colors | sample cost & time | production lead time | link.
Mark which ones meet ALL must-have points.
```

## Промпт 2 — сообщение поставщикам (топ 5–8 из таблицы)

```
Send this RFQ to the top 5–8 suppliers that meet all requirements:

Hello! I'm interested in your vacuum suction magnetic car phone holder (MagSafe-compatible). Please confirm:
1. Is the suction cup mechanical (no battery, not electric)?
2. Magnet grade, number of magnets and pull force (N or kg). Will it hold a 230 g phone through a 2 mm case?
3. Does the ball joint have a tightening nut?
4. Can the kit include: 4 magnetic rings, 2–3 rough-surface adhesive stickers, cleaning wipes, instruction?
5. Neutral color box, no Apple logo and no "MagSafe" text — possible?
6. Box size and weight with box.
7. Unit price for 200 / 300 / 500 pcs including box and accessories (EXW and to a Moscow cargo forwarder in Guangzhou/Yiwu).
8. Available colors (black matte, grey/graphite).
9. Sample cost for 2 pcs and shipping time; production lead time.
10. Please send a real video of the product holding a phone while shaking.
Thank you!

我需要：真空吸盘磁吸手机支架（兼容MagSafe），手动/按压式，非电动、无电池；N52强磁（请说明磁铁数量和吸力）；球头360°带锁紧螺母；配件：引磁环4个、粗糙面贴片2-3个、清洁湿巾、说明书；黑色，中性彩盒，不要苹果标志和MagSafe字样；含包装重量≤0.15kg。请报价200/500个单价，可否寄2个样品，请发视频。
```

## Промпт 3 — выбрать подходящие (после ответов)

```
Compare all supplier replies and score each (0–10) on:
1. Fits ALL must-have specs (mechanical vacuum, N52 + stated pull force, lock nut, 4 rings + stickers + wipes, neutral box) — any failure = REJECT.
2. Unit price incl. box ≤ CNY 18 — over CNY 18 = REJECT.
3. Weight with box ≤ 0.15 kg, box ≈ 9×8×5 cm.
4. Real shaking video provided.
5. Manufacturer (not trader), years on platform, rating.
6. MOQ ≤ 300, sample available, lead time ≤ 15 days.
Give a final ranked table and recommend the TOP-3 to order samples from, with reasons and any risks.
```

## Финальный отбор
- Сразу отсеиваем: электрический вакуум, цена > ¥18 с коробкой, Apple-логотип / надпись MagSafe, нет видео.
- Образцы у топ-3, тест 3 дня в машине: не падает на кочках в чехле; присоска держится на шершавой панели и на солнце; шарнир держит угол; вес с коробкой ≤ 0,15 кг.
- Таблицу Accio и ответы поставщиков — Claude на сверку с юнит-экономикой (¥ × 17 ₽, маржа ≥ 18%) и жалобами WB.
