from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

def locate_suspicious_zone(image_bytes: bytes,
                           sensitivity: float = 0.55) -> tuple[int, int, int, int] | None:
    """Localise la région pulmonaire la plus « voilée » d'une radio frontale.

    Heuristique sans apprentissage, purement indicative :
    1. segmenter grossièrement les champs pulmonaires (pixels sombres du corps,
       les poumons aérés étant les zones les plus radio-transparentes) ;
    2. choisir le côté dont le champ pulmonaire est le plus lumineux (voilé) ;
    3. y entourer la région au voile régional maximal, en restant au cœur du
       champ pulmonaire pour ne pas accrocher paroi, clavicules ou diaphragme.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:
        return None
    # Normalisation : les clichés peu contrastés (cf. registre d'erreurs)
    # rendaient toute détection impossible.
    img = ImageOps.autocontrast(img, cutoff=1)
    W, H = img.size
    S = 256
    small = img.resize((S, S))
    a = np.asarray(small.filter(ImageFilter.GaussianBlur(5)), dtype=float)
    reg = np.asarray(small.filter(ImageFilter.GaussianBlur(12)), dtype=float)
    wide = np.asarray(small.filter(ImageFilter.GaussianBlur(25)), dtype=float)

    body = wide > 50                      # le fond du cliché est quasi noir
    if body.sum() < S * S * 0.2:
        body = np.ones_like(a, dtype=bool)
    lung_thr = np.percentile(a[body], 35)
    lung = body & (a < lung_thr)
    lung[: int(S * 0.18)] = False         # clavicules / épaules
    lung[int(S * 0.85):] = False          # abdomen
    lung[:, : int(S * 0.08)] = False      # aisselles / bords
    lung[:, int(S * 0.92):] = False

    # Densité pulmonaire locale : ne garder que l'intérieur du champ, pas ses
    # bords (paroi thoracique, cœur, coupole diaphragmatique).
    dens_img = Image.fromarray((lung * 255).astype(np.uint8))
    dens = np.asarray(dens_img.filter(ImageFilter.GaussianBlur(10)), dtype=float) / 255
    inside = dens > 0.50
    if inside.sum() < 30:
        inside = dens > 0.35
        if inside.sum() < 30:
            return None                   # cliché illisible : pas d'annotation

    mid = S // 2
    best = None
    for sl, xoff in ((np.s_[:, :mid], 0), (np.s_[:, mid:], mid)):
        sel = inside[sl]
        if sel.sum() < 30:
            continue
        veil = float(a[sl][sel].mean())   # côté le plus voilé = le plus clair
        if best is None or veil > best[0]:
            best = (veil, sl, xoff)
    if best is None:
        return None
    _, sl, xoff = best

    zone = np.where(inside[sl], reg[sl], -1.0)
    iy, ix = np.unravel_index(int(np.argmax(zone)), zone.shape)
    cy, cx = iy, ix + xoff
    r = int(S * 0.15)
    fx, fy = W / S, H / S
    return (int(max(cx - r, 0) * fx), int(max(cy - r, 0) * fy),
            int(min(cx + r, S) * fx), int(min(cy + r, S) * fy))

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
