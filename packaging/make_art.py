"""Render installer art from packaging/mascot.png (run on a Mac, commit the output):

  wizard.bmp / wizard@2x.bmp      Inno Setup side panel
  wizard-small.bmp / @2x          Inno Setup top-right badge
  dmg-background.png (+@2x)       the Mac DMG window
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
BG = (15, 15, 17)
BLUE = (53, 112, 212)
MASCOT = Image.open(HERE / "mascot.png").convert("RGBA")
FONT = "/System/Library/Fonts/SFNS.ttf"
ROUNDED = "/System/Library/Fonts/SFNSRounded.ttf"


def font(size, rounded=False):
    return ImageFont.truetype(ROUNDED if rounded else FONT, size)


def paste_mascot(img, height, cx, bottom):
    m = MASCOT.copy()
    m.thumbnail((10_000, height), Image.LANCZOS)
    img.alpha_composite(m, (int(cx - m.width / 2), int(bottom - m.height)))


def glow(img, cx, cy, r):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(r, 0, -4):
        a = int(70 * (1 - i / r) ** 2)
        d.ellipse((cx - i, cy - i * 0.6, cx + i, cy + i * 0.6), fill=(59, 130, 246, a))
    img.alpha_composite(layer)


def wizard(scale):
    w, h = 164 * scale, 314 * scale
    img = Image.new("RGBA", (w, h), BG + (255,))
    glow(img, w // 2, int(h * 0.55), int(w * 0.75))
    paste_mascot(img, int(h * 0.48), w / 2, h * 0.78)
    d = ImageDraw.Draw(img)
    d.text((w / 2, h * 0.86), "Made by Garv", font=font(15 * scale, True), fill=(250, 250, 250), anchor="mm")
    img.convert("RGB").save(HERE / f"wizard{'@2x' if scale == 2 else ''}.bmp")


def wizard_small(scale):
    s = 55 * scale
    img = Image.new("RGBA", (s, s), (255, 255, 255, 255))
    paste_mascot(img, int(s * 0.95), s / 2, s * 0.98)
    img.convert("RGB").save(HERE / f"wizard-small{'@2x' if scale == 2 else ''}.bmp")


def dmg(scale):
    w, h = 640 * scale, 400 * scale
    img = Image.new("RGBA", (w, h), BG + (255,))
    glow(img, w // 2, int(h * 0.42), int(w * 0.35))
    d = ImageDraw.Draw(img)
    # app icon sits at (170, 190), Applications at (470, 190) — see build_mac.sh
    y = 190 * scale
    d.line((250 * scale, y, 390 * scale, y), fill=BLUE + (255,), width=4 * scale)
    d.polygon([(392 * scale, y), (376 * scale, y - 10 * scale), (376 * scale, y + 10 * scale)], fill=BLUE + (255,))
    paste_mascot(img, 84 * scale, 320 * scale, y - 8 * scale)
    d.text((w / 2, 40 * scale), "Drag YT Downloader into Applications", font=font(17 * scale), fill=(250, 250, 250), anchor="mm")
    d.text((w / 2, 330 * scale), "Made by Garv", font=font(15 * scale, True), fill=(250, 250, 250), anchor="mm")
    d.text((w / 2, 354 * scale), "Built between chai breaks. It downloads videos; it doesn't judge your watch history.",
           font=font(11 * scale), fill=(142, 142, 152), anchor="mm")
    img.convert("RGB").save(HERE / f"dmg-background{'@2x' if scale == 2 else ''}.png")


if __name__ == "__main__":
    for s in (1, 2):
        wizard(s)
        wizard_small(s)
        dmg(s)
