"""Posters: a picture (any look) made into a social post, the way a team's designer
would: the player in front of a big title (the "pop-out" depth of a magazine
cover), or breaking out of a framed card over a big jersey number.

Clean, editorial layouts only: a title, a line or two of text, the team color,
your logo. The player's cut-out does the depth: drawn again over the title (or
over the card's edge), so they stand in front of it.

A poster is part of a picture's edits ({"poster": {...}}), made last (after
crop and parts), so the same layout comes out in the preview and the export.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/System/Library/Fonts/Avenir Next.ttc"
HEAVY, BOLD, DEMI, MEDIUM = 8, 0, 2, 5
TEMPLATES = {
    "gameday": "Game Day",
    "spotlight": "Spotlight",
    "final": "Final Score",
    "mvp": "MVP cover",
}
SHAPES = {"post": 4 / 5, "story": 9 / 16}  # width / height
DEFAULTS = {
    "gameday": {"title": "GAME DAY", "line": "VS WEST PARK · SATURDAY"},
    "spotlight": {"title": "LINCOLN", "line": "MIDFIELD", "number": "7"},
    "final": {"title": "FINAL", "home": "PSG", "away": "WEST PARK", "home_score": "3", "away_score": "1"},
    "mvp": {"title": "MVP", "line": "PLAYER OF THE MATCH"},
}


def clean(p: dict | None) -> dict | None:
    if not p or p.get("template") not in TEMPLATES:
        return None
    out = {"template": p["template"], "shape": p.get("shape") if p.get("shape") in SHAPES else "post",
           "color": str(p.get("color", "#1f2a44"))[:9], "logo": str(p.get("logo") or "")[:20]}
    for k in ("title", "line", "number", "home", "away", "home_score", "away_score"):
        if k in p or k in DEFAULTS[p["template"]]:
            out[k] = str(p.get(k, DEFAULTS[p["template"]].get(k, "")))[:40]
    return out


def size_for(w: int, h: int, p: dict) -> tuple[int, int]:
    """The poster's size for a picture of w x h: its shape, about as many pixels wide."""
    aspect = SHAPES[p.get("shape", "post")]
    pw = max(540, min(w, int(h * aspect * 1.25)))
    return pw, int(round(pw / aspect))


def _rgb(hexcolor: str) -> tuple[float, float, float]:
    h = hexcolor.lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.12, 0.16, 0.27)


def _font(index: int, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, max(6, int(px)), index=index)


def _fit_font(text: str, index: int, width: float, max_px: float) -> ImageFont.FreeTypeFont:
    px = max_px
    f = _font(index, px)
    while px > 8 and f.getlength(text) > width:
        px *= 0.94
        f = _font(index, px)
    return f


def _cover(arr: np.ndarray, w: int, h: int, focus: tuple[float, float]) -> tuple[np.ndarray, tuple[float, float, float]]:
    """The picture scaled to fill w x h, cut around focus (shares). Returns it and (scale, x0, y0) of the cut."""
    ih, iw = arr.shape[:2]
    s = max(w / iw, h / ih)
    big = cv2.resize(arr, (max(w, round(iw * s)), max(h, round(ih * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0 = int(np.clip(focus[0] * big.shape[1] - w / 2, 0, big.shape[1] - w))
    y0 = int(np.clip(focus[1] * big.shape[0] - h / 2, 0, big.shape[0] - h))
    return big[y0:y0 + h, x0:x0 + w], (s, x0, y0)


def _focus(matte: np.ndarray | None) -> tuple[float, float, tuple[float, float, float, float] | None]:
    if matte is None or not (matte > 0.5).any():
        return 0.5, 0.5, None
    ys, xs = np.nonzero(matte > 0.5)
    h, w = matte.shape
    box = (xs.min() / w, ys.min() / h, xs.max() / w, ys.max() / h)
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, box


def _layer(size: tuple[int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _over(base: np.ndarray, layer: Image.Image) -> np.ndarray:
    a = np.asarray(layer).astype(np.float32) / 255
    return base * (1 - a[..., 3:4]) + a[..., :3] * a[..., 3:4]


def _shadowed(layer: Image.Image, radius: float, strength: float = 0.5) -> Image.Image:
    alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda v: int(v * strength)))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (0, int(radius * 0.4)))
    out.alpha_composite(layer)
    return out


def _gradient(h: int, w: int, top: float, bottom: float, start: float) -> np.ndarray:
    """Darkening from `start` (share of the height) down: 0 above, rising to `bottom`."""
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    g = np.clip((y - start) / max(1e-3, 1 - start), 0, 1) ** 1.3 * bottom + top * (1 - y)
    return np.repeat(g, w, axis=1)[..., None]


def compose(arr: np.ndarray, matte: np.ndarray | None, p: dict, logo=None) -> np.ndarray:
    """The poster (floats 0-1). arr: the picture as edited; matte: its players (0-1, same size);
    logo: an RGBA logo (or None)."""
    ih, iw = arr.shape[:2]
    W, H = size_for(iw, ih, p)
    fx, fy, box = _focus(matte)
    t = p["template"]
    color = np.array(_rgb(p.get("color", "#1f2a44")), np.float32)
    if t == "spotlight":
        out = _spotlight(arr, matte, p, W, H, color, box)
    else:
        pic, (s, x0, y0) = _cover(arr, W, H, (fx, fy - 0.05))
        m = None
        if matte is not None:
            m, _ = _cover(matte.astype(np.float32), W, H, (fx, fy - 0.05))
            m = cv2.GaussianBlur(np.clip(m, 0, 1), (0, 0), 0.8)[..., None]
        out = pic.astype(np.float32)
        if t in ("gameday", "mvp"):
            out = out * (1 - _gradient(H, W, 0.0, 0.62, 0.55))
            title = p.get("title", "")
            f = _fit_font(title, HEAVY, W * 0.92, H * (0.24 if t == "gameday" else 0.3))
            lay, d = _layer((W, H))
            ty = H * 0.035
            d.text((W / 2, ty), title, font=f, fill=(255, 255, 255, 240), anchor="mt")
            out = _over(out, _shadowed(lay, H * 0.012, 0.35))
            if m is not None:  # the player in front of the title
                out = out * (1 - m) + pic.astype(np.float32) * m
            lay, d = _layer((W, H))
            line = p.get("line", "")
            if line:
                lf = _fit_font(line, DEMI, W * 0.86, H * 0.034)
                d.text((W / 2, H * 0.93), line, font=lf, fill=(255, 255, 255, 235), anchor="mm")
                bar_w = min(W * 0.18, lf.getlength(line) * 0.3)
                d.rectangle((W / 2 - bar_w / 2, H * 0.893, W / 2 + bar_w / 2, H * 0.897), fill=tuple(int(c * 255) for c in color) + (255,))
            out = _over(out, lay)
        else:  # final score
            out = out * (1 - _gradient(H, W, 0.0, 0.8, 0.45))
            lay, d = _layer((W, H))
            panel = (W * 0.07, H * 0.72, W * 0.93, H * 0.92)
            d.rounded_rectangle(panel, radius=H * 0.018, fill=(10, 12, 16, 170))
            d.rectangle((panel[0], panel[1], panel[0] + W * 0.012, panel[3]), fill=tuple(int(c * 255) for c in color) + (255,))
            d.text((W / 2, H * 0.745), p.get("title", "FINAL"), font=_font(BOLD, H * 0.026), fill=(255, 255, 255, 200), anchor="mt")
            sf = _font(HEAVY, H * 0.075)
            score = f"{p.get('home_score', '')}  –  {p.get('away_score', '')}"
            d.text((W / 2, H * 0.82), score, font=sf, fill=(255, 255, 255, 255), anchor="mm")
            nf = _fit_font(p.get("home", ""), DEMI, W * 0.28, H * 0.03)
            d.text((W * 0.24, H * 0.82), p.get("home", ""), font=nf, fill=(255, 255, 255, 235), anchor="mm")
            nf = _fit_font(p.get("away", ""), DEMI, W * 0.28, H * 0.03)
            d.text((W * 0.76, H * 0.82), p.get("away", ""), font=nf, fill=(255, 255, 255, 235), anchor="mm")
            out = _over(out, lay)
    if logo is not None:
        lw = int(W * 0.13)
        lh = int(lw * logo.height / logo.width)
        art = logo.resize((lw, lh), Image.LANCZOS)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        lay.alpha_composite(art, (int(W * 0.05), int(H * 0.035) if t != "gameday" and t != "mvp" else int(H - lh - H * 0.035)))
        if t in ("gameday", "mvp"):
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            lay.alpha_composite(art, (int(W - lw - W * 0.05), int(H * 0.9 - lh / 2)))
        out = _over(out, lay)
    return np.clip(out, 0, 1).astype(np.float32)


def _spotlight(arr, matte, p, W, H, color, box) -> np.ndarray:
    """Team color, a big number behind, the picture in a card, the player breaking out of its top."""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    dark = color * 0.35
    out = np.broadcast_to(dark * (1 - y) * 0.6 + color * 0.55 * (1 - y) + 0.04, (H, W, 3)).astype(np.float32).copy()
    lay, d = _layer((W, H))
    num = p.get("number", "")
    if num:
        f = _fit_font(num, HEAVY, W * 0.95, H * 0.62)
        d.text((W / 2, H * 0.36), num, font=f, fill=(255, 255, 255, 34), anchor="mm", stroke_width=max(2, int(W * 0.004)),
               stroke_fill=(255, 255, 255, 90))
    out = _over(out, lay)
    # the card: the picture, cut so the player's head sits at the card's top edge
    cx0, cx1, cy0, cy1 = int(W * 0.09), int(W * 0.91), int(H * 0.2), int(H * 0.8)
    cw, ch = cx1 - cx0, cy1 - cy0
    ih, iw = arr.shape[:2]
    if box is not None:
        bx0, by0, bx1, by1 = box
        ph = (by1 - by0) * ih
        s = max(cw / iw, ch / ih, (ch * 0.95) / max(ph, 1))  # the player about the card's height
        s = min(s, max(cw / iw, ch / ih) * 3)
        top = by0 * ih * s + ph * s * 0.16  # the card starts a little below the top of their head
        left = (bx0 + bx1) / 2 * iw * s - cw / 2
    else:
        s, top, left = max(cw / iw, ch / ih), 0, 0
    big = cv2.resize(arr, (max(1, int(iw * s)), max(1, int(ih * s))), interpolation=cv2.INTER_CUBIC)
    bm = cv2.resize(matte.astype(np.float32), (big.shape[1], big.shape[0]), interpolation=cv2.INTER_LINEAR) if matte is not None else None
    left = int(np.clip(left, 0, max(0, big.shape[1] - cw)))
    top = int(np.clip(top, 0, max(0, big.shape[0] - ch)))
    card = np.zeros((ch, cw, 3), np.float32)
    part = big[top:top + ch, left:left + cw]
    card[:part.shape[0], :part.shape[1]] = part
    # a white border and shadow around the card
    lay, d = _layer((W, H))
    b = max(3, int(W * 0.01))
    d.rounded_rectangle((cx0 - b, cy0 - b, cx1 + b, cy1 + b), radius=int(W * 0.02), fill=(255, 255, 255, 255))
    out = _over(out, _shadowed(lay, W * 0.025, 0.55))
    out[cy0:cy1, cx0:cx1] = card
    if bm is not None:  # the player again, over the card's edge: they break out of it
        full = np.zeros((H, W), np.float32)
        src = np.zeros((H, W, 3), np.float32)
        oy, ox = cy0 - top, cx0 - left
        Y0, X0 = max(0, oy), max(0, ox)
        Y1, X1 = min(H, oy + big.shape[0]), min(W, ox + big.shape[1])
        full[Y0:Y1, X0:X1] = bm[Y0 - oy:Y1 - oy, X0 - ox:X1 - ox]
        src[Y0:Y1, X0:X1] = big[Y0 - oy:Y1 - oy, X0 - ox:X1 - ox]
        outside = np.ones((H, W), np.float32)
        outside[cy0:cy1, cx0:cx1] = 0
        a = (cv2.GaussianBlur(np.clip(full, 0, 1), (0, 0), 0.8) * outside)[..., None]
        out = out * (1 - a) + src * a
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.84, H * 0.075)
    d.text((W / 2, H * 0.875), title, font=f, fill=(255, 255, 255, 255), anchor="mm")
    line = p.get("line", "")
    if line:
        lf = _font(DEMI, H * 0.026)
        d.text((W / 2, H * 0.935), line + (f"  ·  #{num}" if num else ""), font=lf, fill=(255, 255, 255, 200), anchor="mm")
    return _over(out, lay)
