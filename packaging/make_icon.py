"""Render the app icon: the mascot on a blue tile, with a download badge.

  icon.png (1024), icon.ico (Windows, 16-256), icon.icns (macOS),
  ../web/icon-64.png (favicon and the rail logo).

Below 48 px the mascot turns to mush, so the small sizes are a plain
download glyph on the same tile."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
S = 1024
PAD = 100  # macOS icon grid: the tile sits inside the canvas
TOP, BOTTOM = (86, 196, 242), (44, 92, 196)  # mascot highlight -> mascot shadow (small glyph)
NIGHT = (22, 40, 82), (9, 15, 32)  # big icon: dark navy so the blue mascot stands out


def tile(size, pad, radius, colors=(TOP, BOTTOM)):
    """Rounded square with a vertical gradient."""
    top, bottom = colors
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, size - pad, size - pad), radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out, mask


def arrow(d, cx, top, bottom, half, tray_y, w, fill="white"):
    d.line((cx, top, cx, bottom), fill=fill, width=w)
    d.line((cx - half, bottom - half, cx, bottom), fill=fill, width=w)
    d.line((cx + half, bottom - half, cx, bottom), fill=fill, width=w)
    for x, y in ((cx, top), (cx - half, bottom - half), (cx + half, bottom - half), (cx, bottom)):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)
    d.line((cx - half * 1.25, tray_y, cx + half * 1.25, tray_y), fill=fill, width=w)
    for x in (cx - half * 1.25, cx + half * 1.25):
        d.ellipse((x - w / 2, tray_y - w / 2, x + w / 2, tray_y + w / 2), fill=fill)


def big():
    img, mask = tile(S, PAD, 185, NIGHT)
    # the mascot's own glow behind it
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((210, 200, 760, 760), fill=(72, 144, 228, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))

    m = Image.open(HERE / "mascot.png").convert("RGBA")
    m = m.crop(m.getbbox())  # the frame has empty margins
    m = m.resize((round(m.width * 740 / m.height), 740), Image.LANCZOS)  # thumbnail() never enlarges
    shadow = Image.new("RGBA", m.size, (12, 30, 80, 0))
    shadow.putalpha(m.getchannel("A").point(lambda a: a * 0.45))
    x, y = (S - m.width) // 2 - 60, S - PAD - m.height + 30
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)), (x + 10, y + 24))
    img.alpha_composite(m, (x, y))

    # download badge, bottom right
    cx, cy, r = 742, 742, 128
    badge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse((cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12), fill=(9, 15, 32, 255))
    bd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(53, 112, 212, 255))
    arrow(bd, cx, cy - 66, cy + 32, 44, cy + 78, 26)
    img.alpha_composite(badge)

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)  # nothing spills past the tile
    return out


def small(size):
    img, _ = tile(size * 4, 0, size * 4 * 0.22)
    d = ImageDraw.Draw(img)
    s4 = size * 4
    arrow(d, s4 / 2, s4 * 0.22, s4 * 0.62, s4 * 0.17, s4 * 0.78, max(4, round(s4 * 0.1)))
    return img.resize((size, size), Image.LANCZOS)


def main():
    art = big()
    art.save(HERE / "icon.png")
    sized = {n: (small(n) if n < 48 else art.resize((n, n), Image.LANCZOS)) for n in (16, 24, 32, 48, 64, 128, 256)}
    sized[256].save(HERE / "icon.ico", sizes=[(n, n) for n in sized], append_images=[sized[n] for n in sized if n != 256])
    art.resize((64, 64), Image.LANCZOS).save(HERE.parent / "web" / "icon-64.png")
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as t:
            iconset = Path(t) / "icon.iconset"
            iconset.mkdir()
            for n in (16, 32, 128, 256, 512):
                (small(n) if n < 48 else art.resize((n, n), Image.LANCZOS)).save(iconset / f"icon_{n}x{n}.png")
                art.resize((n * 2, n * 2), Image.LANCZOS).save(iconset / f"icon_{n}x{n}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)


if __name__ == "__main__":
    main()
