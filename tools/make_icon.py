"""生成「林」主题应用图标（深林绿底 + 浅金字），输出 assets/app.ico 与 app.png。

用法:
    python tools/make_icon.py
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "assets")

# ---- 主题配色（中国红底 + 浅金）----
BG_TOP = (217, 58, 43)     # #D93A2B 正红（亮部）
BG_BOTTOM = (112, 12, 20)  # #700C14 深酒红（暗部）
RING = (255, 216, 122)     # #FFD87A 浅金环
TEXT = (255, 246, 232)     # #FFF6E8 暖白（金字底）
SHADOW = (58, 4, 10)       # 字阴影（深红，不用纯黑）

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def pick_font() -> str:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("No usable font found for icon text")


def rounded_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    r = int(size * radius_ratio)
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    return m


def vertical_gradient(size: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return grad.resize((size, size), Image.BILINEAR)


def draw_base(size: int, detailed: bool) -> Image.Image:
    """绘制方形图标（未套圆角），返回 RGBA。"""
    img = vertical_gradient(size, BG_TOP, BG_BOTTOM).convert("RGBA")

    # 斜向柔光（左上高光），让图标在深色任务栏里更有立体感
    if detailed:
        glow = Image.new("L", (size, size), 0)
        gd = ImageDraw.Draw(glow)
        gd.ellipse((-size * 0.55, -size * 0.70, size * 0.75, size * 0.45), fill=54)
        glow = glow.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(size * 0.10))
        layer = Image.new("RGBA", (size, size), (255, 196, 150, 0))
        layer.putalpha(glow)
        img = Image.alpha_composite(img, layer)

    d = ImageDraw.Draw(img)

    # 金色内环
    if detailed:
        inset = int(size * 0.055)
        d.rounded_rectangle(
            (inset, inset, size - 1 - inset, size - 1 - inset),
            radius=int(size * 0.17),
            outline=RING + (150,),
            width=max(2, int(size * 0.022)),
        )

    # 「林」字
    font_path = pick_font()
    fs = int(size * (0.60 if detailed else 0.74))
    font = ImageFont.truetype(font_path, fs)
    txt = "林"
    bbox = d.textbbox((0, 0), txt, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1]

    if detailed:
        off = max(1, int(size * 0.012))
        d.text((x, y + off), txt, font=font, fill=SHADOW + (200,))
    d.text((x, y), txt, font=font, fill=TEXT + (255,))
    return img


def make(size: int) -> Image.Image:
    detailed = size >= 48
    base = draw_base(512, detailed)
    img = base.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), rounded_mask(size))
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 24, 16]
    imgs = [make(s) for s in sizes]
    ico_path = os.path.join(OUT_DIR, "app.ico")
    png_path = os.path.join(OUT_DIR, "app.png")
    imgs[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    make(512).save(png_path, format="PNG")
    print("ICO :", ico_path, os.path.getsize(ico_path), "bytes")
    print("PNG :", png_path, os.path.getsize(png_path), "bytes")
    print("sizes:", ", ".join(str(s) for s in sizes))


if __name__ == "__main__":
    sys.exit(main())
