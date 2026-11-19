"""Edits made on a picture after its look: parts of it adjusted (a click picks
the part: a face, the player, the sky), straightening and cropping, and text.

They belong to one picture (a result), as a dict:

    {"areas": [{"x": .4, "y": .3, "exposure": .3, "warmth": 0, "saturation": 0}],
     "angle": 1.5,                  # degrees, clockwise; the picture is enlarged so no corner is empty
     "crop": [x0, y0, x1, y1],      # shares of the straightened picture
     "texts": [{"text": "WAKE UP", "x": .5, "y": .85, "size": .07, "style": "bold", "color": "#ffffff"}]}

Removals ({"points": [[x, y]], "strokes": [...]}, see retouch.py) take what was
clicked or brushed out of the picture, filled from around it. Areas and points are shares of the picture before straightening and
cropping; a text's place is a share of the finished picture. The page shows
the same thing: it rotates with the same enlargement and draws the text with
the same font, so what you place is what you export.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from photo_presets import fonts

FONT = "/System/Library/Fonts/Avenir Next.ttc"
FACES = {"bold": 8, "clean": 2, "spaced": 5, "banner": 0}  # Heavy, Demi Bold, Medium, Bold
TRACKING = {"bold": 0.04, "clean": 0.0, "spaced": 0.28, "banner": 0.06}  # letter spacing, in em
UPPER = {"bold", "spaced", "banner"}
MAX_ANGLE = 20.0
WB_MAX = 3.0  # warmth and tint reach: about 25% either way, enough for indoor and evening light
AREA_EDGE = 1024  # px: a part's traced outline, scaled to each picture


def edited(edits: dict | None) -> bool:
    e = edits or {}
    return bool(e.get("areas") or e.get("angle") or e.get("crop") or e.get("texts") or e.get("removals")
                or e.get("logos") or e.get("poster") or e.get("background"))


def cover_scale(w: int, h: int, angle: float) -> float:
    """How much a w x h picture turned by angle must grow to leave no empty corner."""
    t = math.radians(abs(angle))
    c, s = math.cos(t), math.sin(t)
    return max((w * c + h * s) / w, (w * s + h * c) / h)


def straighten(arr: np.ndarray, angle: float) -> np.ndarray:
    """Turned clockwise by angle degrees about its middle, enlarged to fill (as the page's CSS rotate + scale)."""
    if not angle:
        return arr
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, cover_scale(w, h, angle))
    return cv2.warpAffine(arr, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def crop_box(edits: dict | None, w: int, h: int) -> tuple[int, int, int, int]:
    c = (edits or {}).get("crop")
    if not c:
        return 0, 0, w, h
    x0, y0, x1, y1 = (float(v) for v in c)
    X0, Y0 = int(round(np.clip(x0, 0, 1) * w)), int(round(np.clip(y0, 0, 1) * h))
    X1, Y1 = int(round(np.clip(x1, 0, 1) * w)), int(round(np.clip(y1, 0, 1) * h))
    return X0, Y0, max(X0 + 1, X1), max(Y0 + 1, Y1)


def geometry(arr: np.ndarray, edits: dict | None) -> np.ndarray:
    """Straightened and cropped."""
    e = edits or {}
    out = straighten(arr, float(e.get("angle") or 0))
    x0, y0, x1, y1 = crop_box(e, out.shape[1], out.shape[0])
    return out[y0:y1, x0:x1]


def final_size(w: int, h: int, edits: dict | None) -> tuple[int, int]:
    x0, y0, x1, y1 = crop_box(edits, w, h)
    if (edits or {}).get("poster"):
        from photo_presets import poster
        return poster.size_for(x1 - x0, y1 - y0, edits["poster"])
    return x1 - x0, y1 - y0


def map_point(x: float, y: float, w: int, h: int, edits: dict | None) -> tuple[float, float]:
    """A point (shares of the picture) in the straightened, cropped picture (shares)."""
    e = edits or {}
    angle = float(e.get("angle") or 0)
    px, py = x * w, y * h
    if angle:
        s, t = cover_scale(w, h, angle), math.radians(angle)
        dx, dy = px - w / 2, py - h / 2
        px = w / 2 + s * (dx * math.cos(t) - dy * math.sin(t))
        py = h / 2 + s * (dx * math.sin(t) + dy * math.cos(t))
    x0, y0, x1, y1 = crop_box(e, w, h)
    return (px - x0) / max(1, x1 - x0), (py - y0) / max(1, y1 - y0)


def map_box(box, w: int, h: int, edits: dict | None):
    """A box (shares) in the finished picture, kept inside it; None if it is cropped away."""
    if box is None:
        return None
    pts = [map_point(x, y, w, h, edits) for x in (box[0], box[2]) for y in (box[1], box[3])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    out = (max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys)))
    return out if out[2] > out[0] and out[3] > out[1] else None


# Parts adjusted on their own ----------------------------------------------------------------

def _brighten(a: np.ndarray, stops: float) -> np.ndarray:
    out = a * 2 ** stops
    return np.where(out > 0.9, 0.9 + 0.1 * np.tanh((out - 0.9) / 0.1), out) if stops > 0 else out


def adjust_part(arr: np.ndarray, mask: np.ndarray, area: dict) -> np.ndarray:
    """The picture with one part (mask 0-1, the picture's size) brighter or darker, warmer or cooler, more or less colorful."""
    ev, warm, sat = float(area.get("exposure", 0)), float(area.get("warmth", 0)), float(area.get("saturation", 0))
    if not (ev or warm or sat):
        return arr
    part = _brighten(arr, ev) if ev else arr.copy()
    if warm:
        k = 0.08 * warm
        part = part * np.array([1 + k, 1 + k * 0.25, 1 - k], np.float32)
    if sat:
        lum = (part[..., 0] * 0.299 + part[..., 1] * 0.587 + part[..., 2] * 0.114)[..., None]
        part = lum + (part - lum) * (1 + sat)
    h, w = mask.shape[:2]
    soft = cv2.GaussianBlur(np.clip(mask, 0, 1).astype(np.float32), (0, 0), max(1.0, max(h, w) * 0.003))
    m = soft[..., None]  # a soft edge, so the change fades into what is around it
    return np.clip(arr * (1 - m) + part * m, 0, 1).astype(np.float32)


# Text ------------------------------------------------------------------------------------------

def _font(style: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, max(6, px), index=FACES.get(style, 2))


def _line_width(font, line: str, track: float) -> float:
    if not track:
        return font.getlength(line)
    return sum(font.getlength(ch) for ch in line) + track * max(0, len(line) - 1)


def text_layer(size: tuple[int, int], t: dict) -> Image.Image:
    """One text, drawn on a clear layer the picture's size (RGBA)."""
    w, h = size
    style = t.get("style", "clean")
    words = str(t.get("text", "")).strip("\n")
    if style in UPPER:
        words = words.upper()
    lines = words.split("\n") or [""]
    px = max(6, int(float(t.get("size", 0.06)) * w))
    font = fonts.load(t.get("font"), px) or _font(style, px)
    track = TRACKING.get(style, 0.0) * px
    line_h = px * 1.15
    widths = [_line_width(font, line, track) for line in lines]
    block_w, block_h = max(widths or [0]), line_h * len(lines)
    cx, cy = float(t.get("x", 0.5)) * w, float(t.get("y", 0.5)) * h
    left, top = cx - block_w / 2, cy - block_h / 2
    color = str(t.get("color", "#ffffff"))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if style == "banner":
        pad_x, pad_y = px * 0.6, px * 0.32
        box = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(box).rounded_rectangle((left - pad_x, top - pad_y, left + block_w + pad_x, top + block_h + pad_y),
                                              radius=px * 0.15, fill=(10, 12, 16, 150))
        layer.alpha_composite(box)
    ink = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ink)
    for i, (line, lw) in enumerate(zip(lines, widths)):
        x = left + (block_w - lw) / 2
        y = top + i * line_h + (line_h - px) / 2
        if track:
            for ch in line:
                d.text((x, y), ch, font=font, fill=color, anchor="la")
                x += font.getlength(ch) + track
        else:
            d.text((x, y), line, font=font, fill=color, anchor="la")
    if t.get("angle"):  # turned around its middle (the shadow still falls straight down)
        layer, ink = (fonts.turned(x, float(t["angle"]), (cx, cy)) for x in (layer, ink))
    if style != "banner":  # a soft shadow so it reads on any picture
        alpha = ink.getchannel("A").filter(ImageFilter.GaussianBlur(px * 0.12))
        shadow = Image.new("RGBA", size, (0, 0, 0, 0))
        shadow.putalpha(alpha.point(lambda v: int(v * 0.45)))
        layer.alpha_composite(shadow, (0, int(round(px * 0.04))))
    layer.alpha_composite(ink)
    return layer


def draw_texts(arr: np.ndarray, texts: list[dict] | None) -> np.ndarray:
    """The texts drawn on the picture (floats 0-1)."""
    texts = [t for t in (texts or []) if str(t.get("text", "")).strip()]
    if not texts:
        return arr
    h, w = arr.shape[:2]
    out = arr
    for t in texts:
        layer = np.asarray(text_layer((w, h), t), np.float32) / 255
        a = layer[..., 3:4]
        out = out * (1 - a) + layer[..., :3] * a
    return np.clip(out, 0, 1).astype(np.float32)


# White balance and straightening, measured ----------------------------------------------------

def white_balance(arr: np.ndarray, x: float, y: float, warmth: float, tint: float) -> tuple[float, float]:
    """New warmth and tint (see pipeline.finish) that make the color at x, y
    (shares of the picture as it is now) neutral gray."""
    h, w = arr.shape[:2]
    r = max(2, int(min(w, h) * 0.006))
    X, Y = int(np.clip(x * w, 0, w - 1)), int(np.clip(y * h, 0, h - 1))
    patch = arr[max(0, Y - r):Y + r + 1, max(0, X - r):X + r + 1].reshape(-1, 3)
    R, G, B = (float(v) for v in np.median(patch, axis=0))
    if max(R, G, B) < 0.03:
        return warmth, tint
    k = (B - R) / max(1e-6, B + R)  # warmth step: red * (1 + k), green * (1 + k / 4), blue * (1 - k)
    R2, G2 = R * (1 + k), G * (1 + k / 4)
    kt = (G2 - R2) / max(1e-6, G2 + R2 / 2)  # tint step: green * (1 - kt), red and blue * (1 + kt / 2)
    return (float(np.clip(warmth + k / 0.08, -WB_MAX, WB_MAX)), float(np.clip(tint + kt / 0.06, -WB_MAX, WB_MAX)))


def neutral_enough(arr: np.ndarray, x: float, y: float) -> bool:
    """Is the color at x, y close enough to white or gray to set the white balance from?
    (A navy kit or the grass is not: correcting it to gray would turn the picture yellow or purple.)"""
    h, w = arr.shape[:2]
    r = max(2, int(min(w, h) * 0.006))
    X, Y = int(np.clip(x * w, 0, w - 1)), int(np.clip(y * h, 0, h - 1))
    c = np.median(arr[max(0, Y - r):Y + r + 1, max(0, X - r):X + r + 1].reshape(-1, 3), axis=0)
    hi, lo = float(c.max()), float(c.min())
    return hi > 0.08 and (hi - lo) / hi < 0.35


def level_angle(arr: np.ndarray) -> float:
    """The turn (degrees, clockwise) that levels the picture: from its long
    straight lines (field lines, the horizon, goal posts), 0 when there are none."""
    gray = cv2.cvtColor((np.clip(arr, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    scale = 1200 / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, 80, minLineLength=max(gray.shape) * 0.18, maxLineGap=8)
    if lines is None:
        return 0.0
    tilts, weights = [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        a = math.degrees(math.atan2(dy, dx))
        a = (a + 90) % 180 - 90  # -90..90 from horizontal
        if abs(a) <= 12:
            tilts.append(a)
        elif abs(abs(a) - 90) <= 6:  # nearly upright (posts): their lean
            tilts.append(a - 90 if a > 0 else a + 90)
        else:
            continue
        weights.append(length)
    if not tilts or sum(weights) < max(gray.shape) * 0.5:
        return 0.0
    order = np.argsort(tilts)
    t, wts = np.array(tilts)[order], np.array(weights)[order]
    median = float(t[np.searchsorted(np.cumsum(wts), wts.sum() / 2)])
    return round(float(np.clip(-median, -MAX_ANGLE, MAX_ANGLE)), 1) if abs(median) >= 0.2 else 0.0


def clean(edits: dict | None) -> dict:
    """Edits kept tidy (numbers, known styles), with nothing empty."""
    e = edits or {}
    out: dict = {}
    if e.get("areas"):
        out["areas"] = [{"x": float(a["x"]), "y": float(a["y"]), "exposure": float(a.get("exposure", 0)),
                         "warmth": float(a.get("warmth", 0)), "saturation": float(a.get("saturation", 0))}
                        for a in e["areas"]][:12]
    angle = float(e.get("angle") or 0)
    if angle:
        out["angle"] = float(np.clip(angle, -MAX_ANGLE, MAX_ANGLE))
    c = e.get("crop")
    if c and len(c) == 4:
        x0, y0, x1, y1 = (float(np.clip(v, 0, 1)) for v in c)
        if x1 - x0 > 0.02 and y1 - y0 > 0.02 and (x0, y0, x1, y1) != (0, 0, 1, 1):
            out["crop"] = [x0, y0, x1, y1]
    if e.get("removals"):  # what was clicked and brushed away (shares of the picture), in order
        out["removals"] = [{"points": [[float(x), float(y)] for x, y in rm.get("points", [])][:40],
                            "strokes": [{"pts": [[float(x), float(y)] for x, y in st.get("pts", [])][:2000],
                                         "r": float(st.get("r", 0.02))} for st in rm.get("strokes", [])][:200]}
                           for rm in e["removals"] if rm.get("points") or rm.get("strokes")][:30]
    bg = e.get("background")
    if bg and isinstance(bg, dict) and bg.get("src"):  # a new background behind the player (see backgrounds.py)
        from photo_presets import backgrounds
        src = str(bg["src"])[:120]
        if src in backgrounds.NAMES or (src.startswith("file:") and "/" not in src[5:] and ".." not in src):
            num = lambda k, d: float(np.clip(float(bg.get(k, d)), 0, 1))
            out["background"] = {"src": src, "color": str(bg.get("color") or "#1f2a44")[:9], "blur": num("blur", 0.0),
                                 "dim": num("dim", 0.0), "match": num("match", 0.35), "wrap": num("wrap", 0.5)}
    if e.get("poster"):  # a social post layout around the picture (see poster.py)
        from photo_presets import poster
        p = poster.clean(e["poster"])
        if p:
            out["poster"] = p
    if e.get("logos"):  # from the brand kit, placed like text (see brand.py)
        from photo_presets import brand
        out["logos"] = brand.clean(e["logos"])
    if e.get("texts"):
        out["texts"] = [{"text": str(t.get("text", ""))[:200], "x": float(t.get("x", 0.5)), "y": float(t.get("y", 0.5)),
                         "size": float(np.clip(float(t.get("size", 0.06)), 0.01, 0.4)),
                         "style": t.get("style") if t.get("style") in FACES else "clean",
                         "color": str(t.get("color", "#ffffff"))[:9]}
                        | ({"font": t["font"]} if fonts.name_ok(t.get("font")) else {})
                        | ({"angle": fonts.angle_ok(t["angle"])} if fonts.angle_ok(t.get("angle", 0)) else {})
                        for t in e["texts"]][:8]
    return out
