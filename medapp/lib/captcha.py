from __future__ import annotations

import io
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_W, _H = 260, 90

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()

def captcha_image_bytes(text: str) -> bytes:
    rng = random.SystemRandom()
    img = Image.new("RGB", (_W, _H), (238, 242, 246))
    draw = ImageDraw.Draw(img)

    for _ in range(220):
        x, y = rng.randrange(_W), rng.randrange(_H)
        g = rng.randrange(170, 215)
        draw.point((x, y), fill=(g, g + 5, g + 10))

    palette = [(15, 118, 110), (22, 50, 63), (179, 38, 30),
               (91, 114, 130), (154, 103, 0)]
    step = (_W - 40) // max(1, len(text))
    for i, ch in enumerate(text):
        size = rng.randrange(38, 50)
        font = _load_font(size)
        layer = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((10, 4), ch, font=font,
                                   fill=palette[i % len(palette)])
        layer = layer.rotate(rng.uniform(-28, 28), expand=True,
                             resample=Image.BICUBIC)
        x = 18 + i * step + rng.randrange(-6, 7)
        y = rng.randrange(4, max(5, _H - layer.height - 4 + 1))
        img.paste(layer, (x, y), layer)

    for _ in range(3):
        amp = rng.uniform(4, 10)
        phase = rng.uniform(0, math.tau)
        freq = rng.uniform(0.02, 0.05)
        y0 = rng.randrange(15, _H - 15)
        pts = [(x, y0 + amp * math.sin(freq * x + phase)) for x in range(0, _W, 4)]
        draw = ImageDraw.Draw(img)
        draw.line(pts, fill=(186, 200, 212), width=2)

    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def qr_png_bytes(data: str, scale: int = 5) -> bytes:
    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=scale,
                                     dark="#0f172a", light="#e2e8f0", border=2)
    return buf.getvalue()
