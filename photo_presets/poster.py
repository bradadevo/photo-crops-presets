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
    "name": "Name Stack",
    "goal": "Goal",
    "teamcolor": "Team Color",
    "matchday": "Matchday",
    "champions": "Champions",
}
SHAPES = {"post": 4 / 5, "square": 1.0, "story": 9 / 16, "wide": 16 / 9}  # width / height
SIZE_RANGE = (0.6, 1.5)  # the words and banners: smaller or bigger than the layout's own
DEFAULTS = {
    "gameday": {"title": "GAME DAY", "line": "VS WEST PARK · SATURDAY"},
    "spotlight": {"title": "LINCOLN", "line": "MIDFIELD", "number": "7"},
    "final": {"title": "FINAL", "home": "PSG", "away": "WEST PARK", "home_score": "3", "away_score": "1"},
    "mvp": {"title": "MVP", "line": "PLAYER OF THE MATCH"},
    "name": {"title": "LINCOLN", "line": "MIDFIELD  ·  #7"},
    "goal": {"title": "GOAL", "name": "LINCOLN", "minute": "23'"},
    "teamcolor": {"title": "LINCOLN", "line": "PSG LAKE NONA  ·  U11"},
    "matchday": {"title": "MATCHDAY", "away": "VS WEST PARK", "line": "SAT 9:00 AM  ·  FIELD 4"},
    "champions": {"title": "CHAMPIONS", "line": "SPRING CUP 2026"},
}
GOLD = (212, 175, 55)


def clean(p: dict | None) -> dict | None:
    if not p or p.get("template") not in TEMPLATES:
        return None
    out = {"template": p["template"], "shape": p.get("shape") if p.get("shape") in SHAPES else "post",
           "color": str(p.get("color", "#1f2a44"))[:9], "logo": str(p.get("logo") or "")[:20]}
    try:
        size = float(p.get("size", 1.0))
    except (TypeError, ValueError):
        size = 1.0
    if abs(size - 1.0) > 1e-3:
        out["size"] = round(float(np.clip(size, *SIZE_RANGE)), 3)
    for k in ("title", "line", "number", "home", "away", "home_score", "away_score", "name", "minute"):
        if k in p or k in DEFAULTS[p["template"]]:
            out[k] = str(p.get(k, DEFAULTS[p["template"]].get(k, "")))[:40]
    colors = {k: v for k, v in (p.get("colors") or {}).items()
              if isinstance(v, str) and len(v) == 7 and v.startswith("#") and k in WORD_KEYS}
    if colors:
        out["colors"] = colors  # each word's own color (else the layout's)
    try:  # (an export size's own shape: the poster laid out again for it)
        if p.get("aspect") and 0.3 <= float(p["aspect"]) <= 3.0:
            out["aspect"] = round(float(p["aspect"]), 4)
    except (TypeError, ValueError):
        pass
    if p["template"] == "spotlight":
        out["number_style"] = p.get("number_style") if p.get("number_style") in NUMBER_STYLES else "badge"
    return out


WORD_KEYS = ("title", "line", "number", "home", "away", "home_score", "name", "minute")
NUMBER_STYLES = ("badge", "behind")  # Spotlight's number: a solid badge on the card's corner, or big behind it


def size_for(w: int, h: int, p: dict) -> tuple[int, int]:
    """The poster's size for a picture of w x h: its shape, about as many pixels wide."""
    aspect = float(p.get("aspect") or SHAPES[p.get("shape", "post")])
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


import threading

_NOTE = threading.local()  # while words() runs (on this thread): where each word was drawn


def _say(d: ImageDraw.ImageDraw, key: str, xy, text: str, font, **kw) -> None:
    """Draws one of the poster's words (nothing when it was cleared), noting where (for words())."""
    if not text:
        return
    own = (getattr(_NOTE, "colors", None) or {}).get(key)
    if own:  # its own color: the letters (or, for outlined words, their outline), the same see-through
        rgb = tuple(int(own[i:i + 2], 16) for i in (1, 3, 5))
        fill = kw.get("fill", (255, 255, 255, 255))
        if len(fill) == 4 and fill[3] <= 40 and "stroke_fill" in kw:
            kw["stroke_fill"] = rgb + (kw["stroke_fill"][3] if len(kw["stroke_fill"]) == 4 else 255,)
        else:
            kw["fill"] = rgb + ((fill[3],) if len(fill) == 4 else (255,))
    d.text(xy, text, font=font, **kw)
    boxes = getattr(_NOTE, "boxes", None)
    if boxes is not None:
        boxes.append((key, d.textbbox(xy, text, font=font, anchor=kw.get("anchor"), stroke_width=kw.get("stroke_width", 0))))


def words(p: dict, has_logo: bool = False) -> list[dict]:
    """Where each of the poster's words sits ({"key", "x0", "y0", "x1", "y1"}, shares of the poster):
    for clicking a word on the picture to edit it. The layout does not depend on the picture."""
    p = clean(p)
    if p is None:
        return []
    W, H = size_for(800, 1000, p)
    logo = Image.new("RGBA", (10, 10), (255, 255, 255, 255)) if has_logo else None
    _NOTE.boxes = found = []
    try:
        compose(np.zeros((H, W, 3), np.float32), None, p, logo)
    finally:
        _NOTE.boxes = None
    return [{"key": k, "x0": b[0] / W, "y0": b[1] / H, "x1": b[2] / W, "y1": b[3] / H} for k, b in found]


def compose(arr: np.ndarray, matte: np.ndarray | None, p: dict, logo=None) -> np.ndarray:
    """The poster (floats 0-1). arr: the picture as edited; matte: its players (0-1, same size);
    logo: an RGBA logo (or None)."""
    _NOTE.colors = p.get("colors")
    try:
        return _compose(arr, matte, p, logo)
    finally:
        _NOTE.colors = None


def word_color(key: str, default: tuple) -> tuple:
    """A decoration that goes with a word (Champions' rules with its title): the word's own color."""
    own = (getattr(_NOTE, "colors", None) or {}).get(key)
    return tuple(int(own[i:i + 2], 16) for i in (1, 3, 5)) if own else default


def _unit(W: int, H: int, p: dict) -> float:
    """The size every word and banner is measured in: the height of a 4:5 post as wide as this one
    (so a tall story gets them smaller, in proportion to its width), times the poster's own size."""
    return min(W * 1.25, H) * float(p.get("size", 1.0))


def _compose(arr: np.ndarray, matte: np.ndarray | None, p: dict, logo=None) -> np.ndarray:
    ih, iw = arr.shape[:2]
    W, H = size_for(iw, ih, p)
    u = _NOTE.u = _unit(W, H, p)
    fx, fy, box = _focus(matte)
    t = p["template"]
    color = np.array(_rgb(p.get("color", "#1f2a44")), np.float32)
    if t == "spotlight":
        out = _spotlight(arr, matte, p, W, H, color, box)
    elif t in MORE:
        pic, _ = _cover(arr, W, H, (fx, fy - 0.05))
        m = None
        if matte is not None:
            m, _ = _cover(matte.astype(np.float32), W, H, (fx, fy - 0.05))
            m = cv2.GaussianBlur(np.clip((m - 0.35) / 0.4, 0, 1), (0, 0), 0.8)[..., None]
        out = MORE[t](pic.astype(np.float32), m, p, W, H, color, logo is not None)
    else:
        pic, (s, x0, y0) = _cover(arr, W, H, (fx, fy - 0.05))
        m = None
        if matte is not None:
            m, _ = _cover(matte.astype(np.float32), W, H, (fx, fy - 0.05))
            m = cv2.GaussianBlur(np.clip((m - 0.35) / 0.4, 0, 1), (0, 0), 0.8)[..., None]
        out = pic.astype(np.float32)
        if t in ("gameday", "mvp"):
            out = out * (1 - _gradient(H, W, 0.0, 0.62, 0.55))
            title = p.get("title", "")
            f = _fit_font(title, HEAVY, W * 0.92, u * (0.24 if t == "gameday" else 0.3))
            lay, d = _layer((W, H))
            ty = u * 0.035
            _say(d, "title", (W / 2, ty), title, font=f, fill=(255, 255, 255, 240), anchor="mt")
            out = _over(out, _shadowed(lay, u * 0.012, 0.35))
            if m is not None:  # the player in front of the title
                out = out * (1 - m) + pic.astype(np.float32) * m
            lay, d = _layer((W, H))
            line = p.get("line", "")
            if line:  # (with a logo at the right, the line keeps clear of it)
                lx, lwid = (W * 0.43, W * 0.66) if logo is not None else (W / 2, W * 0.86)
                lf = _fit_font(line, DEMI, lwid, u * 0.034)
                _say(d, "line", (lx, H - u * 0.07), line, font=lf, fill=(255, 255, 255, 235), anchor="mm")
                bar_w = min(W * 0.18, lf.getlength(line) * 0.3)
                d.rectangle((lx - bar_w / 2, H - u * 0.107, lx + bar_w / 2, H - u * 0.103), fill=tuple(int(c * 255) for c in color) + (255,))
            out = _over(out, lay)
        else:  # final score
            out = out * (1 - _gradient(H, W, 0.0, 0.8, 0.45))
            lay, d = _layer((W, H))
            y1 = H - u * 0.08
            y0 = y1 - u * 0.2
            mid = y0 + u * 0.1
            panel = (W * 0.07, y0, W * 0.93, y1)
            d.rounded_rectangle(panel, radius=u * 0.018, fill=(10, 12, 16, 170))
            d.rectangle((panel[0], panel[1], panel[0] + max(3, u * 0.0096), panel[3]), fill=tuple(int(c * 255) for c in color) + (255,))
            _say(d, "title", (W / 2, y0 + u * 0.025), p.get("title", "FINAL"), font=_font(BOLD, u * 0.026), fill=(255, 255, 255, 200), anchor="mt")
            score = f"{p.get('home_score', '')}  –  {p.get('away_score', '')}" if (p.get("home_score") or p.get("away_score")) else ""
            sf = _fit_font(score, HEAVY, W * 0.3, u * 0.075)
            _say(d, "home_score", (W / 2, mid), score, font=sf, fill=(255, 255, 255, 255), anchor="mm")
            nf = _fit_font(p.get("home", ""), DEMI, W * 0.24, u * 0.03)
            _say(d, "home", (W * 0.24, mid), p.get("home", ""), font=nf, fill=(255, 255, 255, 235), anchor="mm")
            nf = _fit_font(p.get("away", ""), DEMI, W * 0.24, u * 0.03)
            _say(d, "away", (W * 0.76, mid), p.get("away", ""), font=nf, fill=(255, 255, 255, 235), anchor="mm")
            out = _over(out, lay)
    if logo is not None and t in MORE:
        out = _logo_at(out, logo, W, H, LOGO_AT[t])
    elif logo is not None:
        out = _logo_at(out, logo, W, H, "br" if t in ("gameday", "mvp") else "tl")
    return np.clip(out, 0, 1).astype(np.float32)


def _spotlight(arr, matte, p, W, H, color, box) -> np.ndarray:
    """Team color, the picture in a card, the player breaking out of its top, their number on a badge (or big behind)."""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    dark = color * 0.35
    out = np.broadcast_to(dark * (1 - y) * 0.6 + color * 0.55 * (1 - y) + 0.04, (H, W, 3)).astype(np.float32).copy()
    lay, d = _layer((W, H))
    num = p.get("number", "")
    badge = p.get("number_style", "badge") == "badge"
    if num and not badge:
        u = _NOTE.u
        f = _fit_font(num, HEAVY, W * 0.5, u * 0.34)  # big behind the card's top right corner
        _say(d, "number", (W * 0.74, H * 0.2), num, font=f, fill=(255, 255, 255, 70), anchor="mm", stroke_width=max(2, int(W * 0.005)),
               stroke_fill=(255, 255, 255, 220))
    out = _over(out, lay)
    # the card: the picture, cut so the player's head sits at the card's top edge
    u = _NOTE.u
    cx0, cx1, cy0, cy1 = int(W * 0.09), int(W * 0.91), int(max(u * 0.2, H * 0.14)), int(H - u * 0.2)
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
        outside[cy1:, :] = 0  # out of the top and the sides only: never over the name below
        solid = np.clip((full - 0.35) / 0.4, 0, 1)  # the player only, not the cut-out's faint haze
        a = (cv2.GaussianBlur(solid, (0, 0), 0.8) * outside)[..., None]
        out = out * (1 - a) + src * a
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.84, u * 0.075)
    _say(d, "title", (W / 2, H - u * 0.125), title, font=f, fill=(255, 255, 255, 255), anchor="mm")
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * 0.84, u * 0.026)
        _say(d, "line", (W / 2, H - u * 0.065), line + (f"  ·  #{num}" if num and not badge else ""), font=lf,
             fill=(255, 255, 255, 200), anchor="mm")
    out = _over(out, lay)
    if num and badge:  # a solid badge on the card's top left corner, in front of everything
        lay, d = _layer((W, H))
        r = u * 0.076
        cx, cy = cx0 + r * 0.55, cy0 + r * 0.55
        ring = max(3, int(u * 0.0064))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_c255(color), outline=(255, 255, 255, 255), width=ring)
        f = _fit_font(num, HEAVY, r * 1.35, r * 1.15)
        _say(d, "number", (cx, cy + r * 0.04), num, font=f, fill=(255, 255, 255, 255), anchor="mm")
        out = _over(out, _shadowed(lay, W * 0.012, 0.5))
    return out


# More layouts --------------------------------------------------------------------------------
# Each: (picture, its players' matte or None, the poster, W, H, team color, has a logo) -> floats.

def _c255(color, a=255) -> tuple:
    return tuple(int(c * 255) for c in color) + (a,)


def _front(out: np.ndarray, pic: np.ndarray, m) -> np.ndarray:
    """The players drawn again on top: in front of what was drawn behind them."""
    return out if m is None else out * (1 - m) + pic * m


def _name_stack(pic, m, p, W, H, color, has_logo):
    """The name three times, big, behind the player: outlined, solid, outlined (an editorial echo)."""
    u = _NOTE.u
    out = pic * (1 - _gradient(H, W, 0.0, 0.55, 0.6))
    out = out * 0.82  # (a touch darker, so the white reads)
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.94, u * 0.17)
    lay, d = _layer((W, H))
    step = f.size * 0.92
    mid = H * 0.36
    for i, y in enumerate((mid - step, mid, mid + step)):
        if i == 1:
            _say(d, "title", (W / 2, y), title, font=f, fill=(255, 255, 255, 235), anchor="mm")
        else:
            _say(d, "title", (W / 2, y), title, font=f, fill=(255, 255, 255, 0), anchor="mm",
                   stroke_width=max(2, int(W * 0.0035)), stroke_fill=(255, 255, 255, 150))
    out = _over(out, _shadowed(lay, u * 0.01, 0.3))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * (0.6 if has_logo else 0.84), u * 0.032)
        d.rectangle((W * 0.06, H - u * 0.095, W * 0.06 + max(3, u * 0.0096), H - u * 0.055), fill=_c255(color))
        _say(d, "line", (W * 0.06 + W * 0.03, H - u * 0.075), line, font=lf, fill=(255, 255, 255, 240), anchor="lm")
    return _over(out, lay)


def _goal(pic, m, p, W, H, color, has_logo):
    """GOAL, huge and outlined behind the scorer; their name and the minute at the bottom."""
    u = _NOTE.u
    out = pic * (1 - _gradient(H, W, 0.0, 0.7, 0.5))
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.96, u * 0.3)
    _say(d, "title", (W / 2, H * 0.3), title, font=f, fill=_c255(color, 170), anchor="mm",
           stroke_width=max(3, int(W * 0.005)), stroke_fill=(255, 255, 255, 235))
    out = _over(out, _shadowed(lay, _NOTE.u * 0.012, 0.35))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    name, minute = p.get("name", ""), p.get("minute", "")
    nf = _fit_font(name, HEAVY, W * 0.62, u * 0.07)
    base = H - u * 0.085
    _say(d, "name", (W * 0.06, base), name, font=nf, fill=(255, 255, 255, 250), anchor="ls")
    if minute:
        mf = _font(HEAVY, u * 0.04)
        x0 = W * 0.06 + (nf.getlength(name) + u * 0.024 if name else 0)
        tw = mf.getlength(minute)
        d.rounded_rectangle((x0, base - u * 0.058, x0 + tw + u * 0.032, base - u * 0.004),
                            radius=u * 0.008, fill=_c255(color))
        _say(d, "minute", (x0 + u * 0.016, base - u * 0.031), minute, font=mf, fill=(255, 255, 255, 255), anchor="lm")
    return _over(out, lay)


def _team_color(pic, m, p, W, H, color, has_logo):
    """The background in the team color (a duotone), the player in full color in front of a big name."""
    u = _NOTE.u
    lum = (pic[..., 0] * 0.299 + pic[..., 1] * 0.587 + pic[..., 2] * 0.114)[..., None]
    dark, light = color * 0.25, color + (1 - color) * 0.42
    tone = dark + (light - dark) * np.clip((lum - 0.05) / 0.85, 0, 1) ** 1.1
    out = tone * (1 - _gradient(H, W, 0.0, 0.45, 0.62))
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.94, u * 0.22)
    _say(d, "title", (W / 2, u * 0.04), title, font=f, fill=(255, 255, 255, 235), anchor="mt")
    out = _over(out, _shadowed(lay, _NOTE.u * 0.012, 0.3))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lx, lwid = (W * 0.43, W * 0.66) if has_logo else (W / 2, W * 0.86)
        lf = _fit_font(line, DEMI, lwid, u * 0.032)
        _say(d, "line", (lx, H - u * 0.07), line, font=lf, fill=(255, 255, 255, 240), anchor="mm")
    return _over(out, lay)


def _matchday(pic, m, p, W, H, color, has_logo):
    """A team-color band at the top (MATCHDAY, the opponent), the player standing in front of it,
    when and where at the bottom."""
    u = _NOTE.u
    out = pic * (1 - _gradient(H, W, 0.0, 0.6, 0.62))
    lay, d = _layer((W, H))
    band = (0, u * 0.05, W, u * 0.25)
    d.rectangle(band, fill=_c255(color, 235))
    d.rectangle((0, band[3], W, band[3] + max(2, u * 0.004)), fill=(255, 255, 255, 220))
    out = _over(out, _shadowed(lay, _NOTE.u * 0.012, 0.4))
    out = _front(out, pic, m)  # the players stand in front of the band; its words in front of them
    lay, d = _layer((W, H))
    small = _font(BOLD, u * 0.026)
    _say(d, "title", (W * 0.06, u * 0.085), p.get("title", ""), font=small, fill=(255, 255, 255, 215), anchor="lt")
    away = p.get("away", "")
    af = _fit_font(away, HEAVY, W * (0.62 if has_logo else 0.88), u * 0.085)
    _say(d, "away", (W * 0.06, u * 0.215), away, font=af, fill=(255, 255, 255, 255), anchor="ls")
    out = _over(out, _shadowed(lay, _NOTE.u * 0.006, 0.45))
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * 0.86, u * 0.034)
        _say(d, "line", (W / 2, H - u * 0.07), line, font=lf, fill=(255, 255, 255, 240), anchor="mm")
    return _over(out, lay)


def _champions(pic, m, p, W, H, color, has_logo):
    """CHAMPIONS in gold behind the team, the event between two thin gold rules."""
    u = _NOTE.u
    out = pic * (1 - _gradient(H, W, 0.18, 0.78, 0.5))
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.92, u * 0.2)
    _say(d, "title", (W / 2, u * 0.035), title, font=f, fill=GOLD + (245,), anchor="mt")
    out = _over(out, _shadowed(lay, _NOTE.u * 0.012, 0.4))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * 0.6, u * 0.034)
        y = H - u * (0.175 if has_logo else 0.07)
        half = lf.getlength(line) / 2 + W * 0.03
        _say(d, "line", (W / 2, y), line, font=lf, fill=(255, 255, 255, 245), anchor="mm")
        for x0, x1 in ((W * 0.08, W / 2 - half), (W / 2 + half, W * 0.92)):
            if x1 > x0:
                d.rectangle((x0, y - max(1, u * 0.0015), x1, y + max(1, u * 0.0015)), fill=word_color("title", GOLD) + (230,))
    return _over(out, _shadowed(lay, _NOTE.u * 0.008, 0.6))


MORE = {"name": _name_stack, "goal": _goal, "teamcolor": _team_color, "matchday": _matchday, "champions": _champions}
LOGO_AT = {"name": "tl", "goal": "tr", "teamcolor": "br", "matchday": "band", "champions": "bc"}


def _logo_at(out: np.ndarray, logo: Image.Image, W: int, H: int, where: str) -> np.ndarray:
    u = _NOTE.u
    lw = int(u * (0.088 if where == "bc" else 0.104))
    lh = int(lw * logo.height / logo.width)
    if where == "band":  # inside the band, at its right
        lh = min(lh, int(u * 0.14))
        lw = int(lh * logo.width / logo.height)
    art = logo.resize((max(1, lw), max(1, lh)), Image.LANCZOS)
    m = W * 0.05
    x, y = {"tl": (m, u * 0.035), "tr": (W - lw - m, u * 0.035),
            "br": (W - lw - m, H - u * 0.1 - lh / 2), "band": (W - lw - m, u * 0.15 - lh / 2),
            "bc": (W / 2 - lw / 2, H - u * 0.045 - lh)}[where]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lay.alpha_composite(art, (int(x), int(y)))
    return _over(out, lay)
