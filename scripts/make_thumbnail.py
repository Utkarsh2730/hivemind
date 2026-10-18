"""High-resolution YouTube thumbnail for the Hivemind demo.

Usage: .venv/bin/python scripts/make_thumbnail.py <app-screenshot-2x.png>
Writes video/hivemind-thumbnail-1920.jpg (upload this; < 2 MB), video/hivemind-thumbnail.jpg (1280x720)
and video/hivemind-thumbnail-2560.png (master).
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "video")
FONTS = os.path.join(OUT, "fonts")
W, H = 2560, 1440
NIGHT, NIGHT2, AMBER, WHITE = (19, 17, 43), (34, 30, 82), (245, 158, 11), (255, 255, 255)


def font(file, size, axes=None):
    f = ImageFont.truetype(os.path.join(FONTS, file), size)
    if axes:
        try:
            f.set_variation_by_axes(axes)
        except Exception:
            pass
    return f


SERIF = lambda s: font("Fraunces-9e509503.ttf", s, [144, 700])      # opsz, wght
SERIF_I = lambda s: font("Fraunces-d5715532.ttf", s, [144])
SANS = lambda s, w=700: font("Inter-bec94a4d.ttf", s, [w])


def background():
    img = Image.new("RGB", (W, H), NIGHT)
    for box, color, blur in [((W * 0.42, -H * 0.55, W * 1.45, H * 1.05), NIGHT2, 260),
                             ((-W * 0.25, H * 0.55, W * 0.35, H * 1.6), (70, 48, 24), 260)]:
        layer = Image.new("RGB", (W, H), color)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).ellipse(box, fill=230)
        img = Image.composite(layer, img, mask.filter(ImageFilter.GaussianBlur(blur)))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 48):
        for y in range(0, H, 48):
            d.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=(40, 36, 86))
    return img


def logo(d, x, y, s):
    d.rounded_rectangle((x, y, x + s, y + s), radius=int(s * 0.24), fill=AMBER)
    pts = [(x + s / 2 + 0.33 * s * math.cos(math.radians(a)), y + s / 2 + 0.33 * s * math.sin(math.radians(a)))
           for a in range(-90, 270, 60)]
    d.polygon(pts, outline=NIGHT, width=max(4, s // 14))
    for px, py in [(0.5, 0.42), (0.37, 0.61), (0.63, 0.61)]:
        r = s * 0.065
        d.ellipse((x + px * s - r, y + py * s - r, x + px * s + r, y + py * s + r), fill=NIGHT)


def screenshot_card(path):
    shot = Image.open(path).convert("RGB")
    # main area of the app: answer panel + knowledge graph (drop the sidebar)
    shot = shot.crop((int(shot.width * 0.165), int(shot.height * 0.062), shot.width, int(shot.height * 0.84)))
    target_w = 1400
    shot = shot.resize((target_w, int(target_w * shot.height / shot.width)), Image.LANCZOS)
    pad = 6
    frame = Image.new("RGB", (shot.width + 2 * pad, shot.height + 2 * pad), (70, 64, 130))
    frame.paste(shot, (pad, pad))
    mask = Image.new("L", frame.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, frame.width, frame.height), radius=34, fill=255)
    card = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    card.paste(frame, (0, 0), mask)
    return card.rotate(-4, expand=True, resample=Image.BICUBIC)


def main(shot_path):
    img = background().convert("RGBA")
    card = screenshot_card(shot_path)
    x, y = W - card.width + 50, (H - card.height) // 2 + 60
    shadow = Image.new("RGBA", (card.width + 200, card.height + 200), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 190), (100, 100), card.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(50))
    img.alpha_composite(shadow, (x - 100 + 24, y - 100 + 40))
    glow = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    glow.paste((245, 158, 11, 70), (100, 100), card.split()[3])
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(70)), (x - 100, y - 100))
    img.alpha_composite(card, (x, y))

    # dark fade so the headline always reads cleanly over the screenshot edge
    fade = Image.new("L", (W, H), 0)
    fd = ImageDraw.Draw(fade)
    for i in range(0, 1200):
        fd.line([(i, 0), (i, H)], fill=int(255 * max(0.0, min(1.0, (1200 - i) / 380))))
    img = Image.composite(Image.new("RGBA", (W, H), NIGHT + (255,)), img, fade.point(lambda v: int(v * 0.55)))

    d = ImageDraw.Draw(img)
    logo(d, 128, 120, 136)
    d.text((300, 142), "Hivemind", font=SANS(86, 750), fill=WHITE)
    big, big_i = SERIF(166), SERIF_I(166)
    for i, (text, f, c) in enumerate([("The memory", big, WHITE), ("your company", big, WHITE), ("never had.", big_i, AMBER)]):
        d.text((118, 410 + i * 190), text, font=f, fill=c)
    pill_font = SANS(56, 750)
    label = "FalkorDB knowledge graph"
    pw = pill_font.getlength(label) + 104
    d.rounded_rectangle((128, 1150, 128 + pw, 1270), radius=60, fill=AMBER)
    d.text((180, 1176), label, font=pill_font, fill=NIGHT)

    master = img.convert("RGB")
    os.makedirs(OUT, exist_ok=True)
    master.save(os.path.join(OUT, "hivemind-thumbnail-2560.png"))
    hd = master.resize((1920, 1080), Image.LANCZOS)
    q = 95
    while True:
        p = os.path.join(OUT, "hivemind-thumbnail-1920.jpg")
        hd.save(p, quality=q, subsampling=0, optimize=True)
        if os.path.getsize(p) < 1_900_000 or q <= 80:
            break
        q -= 3
    master.resize((1280, 720), Image.LANCZOS).save(os.path.join(OUT, "hivemind-thumbnail.jpg"), quality=95, subsampling=0, optimize=True)
    for f in ["hivemind-thumbnail-1920.jpg", "hivemind-thumbnail.jpg", "hivemind-thumbnail-2560.png"]:
        print(f, os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1])
