from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MIN_PEAK_CONTRAST = 10.0

def locate_suspicious_zone(image_bytes: bytes,
                           sensitivity: float = 0.55) -> tuple[int, int, int, int] | None:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:
        return None
    W, H = img.size
    S = 256
    small = img.resize((S, S))

    fg = np.asarray(small.filter(ImageFilter.GaussianBlur(3)), dtype=float)
    bg = np.asarray(small.filter(ImageFilter.GaussianBlur(35)), dtype=float)
    diff = fg - bg

    m = int(S * 0.10)
    diff[:m, :] = 0
    diff[-m:, :] = 0
    diff[:, :m] = 0
    diff[:, -m:] = 0

    peak = float(diff.max())
    if peak < MIN_PEAK_CONTRAST:
        return None

    py, px = np.unravel_index(int(np.argmax(diff)), diff.shape)
    ys, xs = np.where(diff >= sensitivity * peak)
    keep = (np.abs(ys - py) < S * 0.25) & (np.abs(xs - px) < S * 0.25)
    ys, xs = ys[keep], xs[keep]
    if xs.size < 4:
        return None

    pad = 10
    x0 = max(int(xs.min()) - pad, 0)
    x1 = min(int(xs.max()) + pad, S)
    y0 = max(int(ys.min()) - pad, 0)
    y1 = min(int(ys.max()) + pad, S)
    fx, fy = W / S, H / S
    return (int(x0 * fx), int(y0 * fy), int(x1 * fx), int(y1 * fy))

def annotate_image(image_bytes: bytes,
                   box: tuple[int, int, int, int] | None = None
                   ) -> tuple[bytes, bool]:
    if box is None:
        box = locate_suspicious_zone(image_bytes)
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return image_bytes, False
    if box:
        d = ImageDraw.Draw(img)
        stroke = max(2, img.size[0] // 200)
        for i in range(stroke):
            d.ellipse([box[0] - i, box[1] - i, box[2] + i, box[3] + i],
                      outline=(211, 47, 47))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), bool(box)
