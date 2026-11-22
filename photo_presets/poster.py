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

from photo_presets import fonts

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
    "jersey": "Jersey Number",
    "cover": "Cover Story",
    "split": "Diagonal Split",
    "card": "Player Card",
    "cinematic": "Cinematic",
    "banner": "Stadium Banner",
    "smoke": "Smoke Burst",
    "featured": "Featured Split",
    "storm": "Storm Night",
    "collector": "Collector's Edition",
    "fillband": "Fill Band",
    "lowerthird": "Lower Third",
    "knockout": "Knockout",
    "sidelabel": "Side Label",
    "cornertag": "Corner Tag",
    "outlinestack": "Outline Stack",
    "frosted": "Frosted Panel",
    "custom": "Custom",
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
    "jersey": {"number": "7", "title": "LINCOLN", "line": "MIDFIELD"},
    "cover": {"title": "ELITE", "line": "ISSUE 07  ·  FALL 2026", "name": "LINCOLN", "away": "THE MIDFIELD ENGINE"},
    "split": {"title": "LINCOLN", "line": "PSG LAKE NONA  ·  U11", "number": "7"},
    "card": {"title": "LINCOLN", "line": "MIDFIELD  ·  2026", "number": "7"},
    "cinematic": {"title": "LINCOLN", "line": "PSG LAKE NONA  ·  FALL SEASON"},
    "banner": {"line": "LAKE NONA SOCCER CLUB", "title": "LIONS", "name": "Lincoln Hayes"},
    "smoke": {"line": "LAKE NONA YOUTH SOCCER", "title": "STRIKERS", "name": "LINCOLN HAYES"},
    "featured": {"line": "2026", "title": "Featured", "away": "athlete", "number": "10", "home": "CAPTAIN", "name": "LINCOLN HAYES"},
    "storm": {"line": "PSG LAKE NONA  ·  U11", "title": "LINCOLN", "number": "7"},
    "collector": {"title": "SOCCER", "line": "THE SEASON ISSUE", "minute": "2026", "away": "All-Star", "home": "COLLECTOR'S EDITION"},
    "fillband": {"title": "LINCOLN HAYES", "line": "PSG LAKE NONA  ·  #7"},
    "lowerthird": {"title": "Lincoln Hayes", "line": "MIDFIELD  ·  PSG LAKE NONA"},
    "knockout": {"title": "HAYES", "line": "LINCOLN  ·  NUMBER 7"},
    "sidelabel": {"title": "LINCOLN HAYES", "line": "FALL SEASON 2026"},
    "cornertag": {"title": "GAME DAY", "name": "Lincoln Hayes", "line": "PSG LAKE NONA"},
    "outlinestack": {"title": "LINCOLN", "name": "HAYES", "line": "PSG LAKE NONA  ·  U11"},
    "frosted": {"title": "Lincoln Hayes", "line": "PSG LAKE NONA  ·  FALL 2026"},
    "custom": {},
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
            out[k] = fonts.lines(str(p.get(k, DEFAULTS[p["template"]].get(k, "")))[:60])
    colors = {k: v for k, v in (p.get("colors") or {}).items()
              if isinstance(v, str) and len(v) == 7 and v.startswith("#") and k in WORD_KEYS}
    if colors:
        out["colors"] = colors  # each word's own color (else the layout's)
    try:  # (an export size's own shape: the poster laid out again for it)
        if p.get("aspect") and 0.3 <= float(p["aspect"]) <= 3.0:
            out["aspect"] = round(float(p["aspect"]), 4)
    except (TypeError, ValueError):
        pass
    kept = {t: {k: str(v)[:40] for k, v in (w or {}).items() if k in FIELD_KEYS}
            for t, w in (p.get("kept") or {}).items() if t in TEMPLATES and isinstance(w, dict)}
    if kept:
        out["kept"] = kept  # the words typed for the other layouts: back when you switch back
    moves = _moves(p.get("moves"))
    if moves:
        out["moves"] = moves  # words moved, resized, turned or set in another font by you
    kept_moves = {t: _moves(m) for t, m in (p.get("kept_moves") or {}).items() if t in TEMPLATES and isinstance(m, dict)}
    if any(kept_moves.values()):
        out["kept_moves"] = {t: m for t, m in kept_moves.items() if m}  # the other layouts' word changes, for coming back
    if p.get("family"):  # one of a team's posters: the same design, each player's own picture, name and number
        out["family"] = str(p["family"])[:12]
    pic = p.get("pic") or {}
    try:
        placed = {"x": round(float(np.clip(float(pic.get("x", 0)), -2, 2)), 4), "y": round(float(np.clip(float(pic.get("y", 0)), -2, 2)), 4),
                  "zoom": round(float(np.clip(float(pic.get("zoom", 1)), 1, 4)), 3)}
        if placed != {"x": 0, "y": 0, "zoom": 1}:
            out["pic"] = placed  # the photo moved and zoomed in the poster, as you placed it
    except (TypeError, ValueError, AttributeError):
        pass
    at = p.get("logo_at") or {}
    try:
        if at:
            out["logo_at"] = {"x": round(float(np.clip(float(at["x"]), -0.2, 1.2)), 4), "y": round(float(np.clip(float(at["y"]), -0.2, 1.2)), 4),
                              "size": round(float(np.clip(float(at.get("size", 0.13)), 0.03, 0.8)), 4)}  # the logo where you put it
    except (TypeError, ValueError, KeyError, AttributeError):
        pass
    if p["template"] != "custom" and p.get("extras"):  # pieces you added on top of the layout (stripes, text…)
        from photo_presets import custom_poster
        extras = custom_poster.clean(p["extras"])
        if extras:
            out["extras"] = extras
    if p["template"] == "custom":  # your own layout: its pieces and its fades
        from photo_presets import custom_poster
        out["elements"] = custom_poster.clean(p.get("elements"))
        for k, d in (("fade_top", 0.35), ("fade_bottom", 0.55)):
            try:
                out[k] = round(float(np.clip(float(p.get(k, d)), 0, 0.9)), 3)
            except (TypeError, ValueError):
                out[k] = d
    if p["template"] == "spotlight":
        out["number_style"] = p.get("number_style") if p.get("number_style") in NUMBER_STYLES else "badge"
    return out


def _moves(raw) -> dict:
    """Words you moved, resized, turned or set in another font: {key: {x, y, s, r?, f?}}."""
    moves = {}
    for k, m in (raw or {}).items():
        if k in FIELD_KEYS and isinstance(m, dict):
            try:
                mv = {"x": round(float(np.clip(float(m.get("x", 0)), -1, 1)), 4), "y": round(float(np.clip(float(m.get("y", 0)), -1, 1)), 4),
                      "s": round(float(np.clip(float(m.get("s", 1)), 0.3, 4)), 3)}
            except (TypeError, ValueError):
                continue
            if fonts.angle_ok(m.get("r", 0)):
                mv["r"] = fonts.angle_ok(m["r"])  # turned to any angle (degrees, clockwise)
            if fonts.name_ok(m.get("f")):
                mv["f"] = m["f"]  # in a font of your choice
            if mv != {"x": 0, "y": 0, "s": 1}:
                moves[k] = mv
    return moves


WORD_KEYS = ("title", "line", "number", "home", "away", "home_score", "name", "minute")
FIELD_KEYS = ("title", "line", "number", "home", "away", "home_score", "away_score", "name", "minute")
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
    return fonts.MultiFont(FONT, max(6, int(px)), index=index)


def _fit_font(text: str, index: int, width: float, max_px: float) -> ImageFont.FreeTypeFont:
    px = max_px
    f = _font(index, px)
    while px > 8 and f.getlength(text) > width:
        px *= 0.94
        f = _font(index, px)
    return f


def _cover(arr: np.ndarray, w: int, h: int, focus: tuple[float, float]) -> tuple[np.ndarray, tuple[float, float, float]]:
    """The picture scaled to fill w x h, cut around focus (shares), then moved and zoomed as you placed
    it (the poster's "pic"). Returns it and (scale, x0, y0) of the cut."""
    ih, iw = arr.shape[:2]
    pic = getattr(_NOTE, "pic", None) or {}
    zoom = float(pic.get("zoom", 1.0))
    s = max(w / iw, h / ih) * zoom
    big = cv2.resize(arr, (max(w, round(iw * s)), max(h, round(ih * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    # moved by you: in poster widths and heights (dragging the photo right shows more of its left)
    x0 = int(np.clip(focus[0] * big.shape[1] - w / 2 - float(pic.get("x", 0)) * w, 0, big.shape[1] - w))
    y0 = int(np.clip(focus[1] * big.shape[0] - h / 2 - float(pic.get("y", 0)) * h, 0, big.shape[0] - h))
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


def _badge_moves(p: dict) -> dict:
    """The poster's moves with the number's place and size left to its badge (its font and angle kept)."""
    out = {k: v for k, v in (p.get("moves") or {}).items() if k != "number"}
    own = {k: v for k, v in ((p.get("moves") or {}).get("number") or {}).items() if k in ("f", "r")}
    return out | ({"number": {"x": 0, "y": 0, "s": 1, **own}} if own else {})


def _say(d: ImageDraw.ImageDraw, key: str, xy, text: str, font, turn: float = 0.0, **kw) -> None:
    """Draws one of the poster's words (nothing when it was cleared), noting where (for words())."""
    if not text:
        return
    move = (getattr(_NOTE, "moves", None) or {}).get(key)
    if move and move.get("f"):  # your font, as wide as the layout's (not much taller)
        own = fonts.load(move["f"], font.size)
        if own is not None:
            was, now = font.getlength(text), own.getlength(text)
            k = min(1.25, was / now) if now > 0 and was > 0 else 1.0
            font = own.font_variant(size=max(6, int(font.size * k))) if abs(k - 1) > 0.02 else own
    if move:  # moved or resized by you on the picture (shares of the poster; its size times s)
        W, H = d.im.size
        xy = (xy[0] + move.get("x", 0) * W, xy[1] + move.get("y", 0) * H)
        if move.get("s", 1) != 1:
            font = font.font_variant(size=max(6, int(font.size * move["s"])))
            if "stroke_width" in kw:
                kw["stroke_width"] = max(1, int(kw["stroke_width"] * move["s"]))
    own = (getattr(_NOTE, "colors", None) or {}).get(key)
    if own:  # its own color: the letters (or, for outlined words, their outline), the same see-through
        rgb = tuple(int(own[i:i + 2], 16) for i in (1, 3, 5))
        fill = kw.get("fill", (255, 255, 255, 255))
        if len(fill) == 4 and fill[3] <= 40 and "stroke_fill" in kw:
            kw["stroke_fill"] = rgb + (kw["stroke_fill"][3] if len(kw["stroke_fill"]) == 4 else 255,)
        else:
            kw["fill"] = rgb + ((fill[3],) if len(fill) == 4 else (255,))
    font = fonts.multi(font)
    if "\n" in text:  # several lines: centered on each other, the block growing away from where the line was set
        a = kw.get("anchor") or "la"
        a = a[0] + {"t": "a", "b": "d"}.get(a[1], a[1])
        kw.update(anchor=a, align={"l": "left", "r": "right"}.get(a[0], "center"), spacing=int(font.size * 0.12))
        one = d.textbbox(xy, text.split("\n")[0], font=font, anchor=a)
        whole = d.textbbox(xy, text, font=font, anchor=a, align=kw["align"], spacing=kw["spacing"])
        extra = (whole[3] - whole[1]) - (one[3] - one[1])
        xy = (xy[0], xy[1] - (extra if a[1] == "s" else 0))  # (on a baseline: the lines go up; "m" is centered already)
    box = d.textbbox(xy, text, font=font, anchor=kw.get("anchor"), stroke_width=kw.get("stroke_width", 0),
                     **{k: kw[k] for k in ("align", "spacing") if k in kw})
    angle = turn + (move or {}).get("r", 0)  # the layout's own slant (a ribbon) plus your turn
    turns = getattr(_NOTE, "turns", None)
    if turns is not None and angle:
        turns[key] = (angle, turn)
    image = getattr(d, "_image", None)
    if angle and image is not None and image.mode == "RGBA":  # turned around its middle (a word in parts: the whole word's)
        mid = (getattr(_NOTE, "middles", None) or {}).get(key)
        mid = (mid[0] * image.size[0], mid[1] * image.size[1]) if mid else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        side = fonts.room(box, mid, font.size * 0.2 + kw.get("stroke_width", 0))  # (all of it, even past the edge, before turning)
        lay = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ImageDraw.Draw(lay).text((xy[0] - mid[0] + side / 2, xy[1] - mid[1] + side / 2), text, font=font, **kw)
        fonts.paste(image, fonts.turned(lay, angle, (side / 2, side / 2)), mid[0] - side / 2, mid[1] - side / 2)
    else:
        d.text(xy, text, font=font, **kw)
    boxes = getattr(_NOTE, "boxes", None)
    if boxes is not None:
        boxes.append((key, box))


def words(p: dict, has_logo: bool = False, logo_img: Image.Image | None = None) -> list[dict]:
    """Where each of the poster's words sits ({"key", "x0", "y0", "x1", "y1"}, shares of the poster):
    for clicking a word on the picture to edit it. The layout does not depend on the picture."""
    p = clean(p)
    if p is None:
        return []
    W, H = size_for(800, 1000, p)
    logo = logo_img if logo_img is not None else (Image.new("RGBA", (10, 10), (255, 255, 255, 255)) if has_logo else None)
    _NOTE.boxes = found = []
    _NOTE.turns = turned = {}
    try:
        compose(np.zeros((H, W, 3), np.float32), None, p, logo)
    finally:
        _NOTE.boxes = _NOTE.turns = None
    turn = {k: a for k, (a, _) in turned.items()}  # each word's angle as drawn (its own slant: r0)
    turn |= {f"el:{e['id']}": e.get("angle", 0) for e in (p.get("elements") or p.get("extras") or [])}
    return [{"key": k, "x0": b[0] / W, "y0": b[1] / H, "x1": b[2] / W, "y1": b[3] / H} | ({"r": turn[k]} if turn.get(k) else {})
            | ({"r0": turned[k][1]} if k in turned and turned[k][1] else {}) for k, b in found]


def middles(found: list[dict]) -> dict[str, tuple[float, float]]:
    """The middle of each word (all its parts together), in shares of the poster."""
    out = {}
    for k in {w["key"] for w in found}:
        parts = [w for w in found if w["key"] == k]
        out[k] = ((min(w["x0"] for w in parts) + max(w["x1"] for w in parts)) / 2,
                  (min(w["y0"] for w in parts) + max(w["y1"] for w in parts)) / 2)
    return out


def compose(arr: np.ndarray, matte: np.ndarray | None, p: dict, logo=None, logos=None) -> np.ndarray:
    """The poster (floats 0-1). arr: the picture as edited; matte: its players (0-1, same size);
    logo: an RGBA logo (or None); logos: a logo by its id (for a custom poster's logo pieces)."""
    _NOTE.middles = None
    if any(m.get("r") for m in (p.get("moves") or {}).values()) and getattr(_NOTE, "boxes", None) is None:
        _NOTE.middles = middles(words(p, bool(logo)))  # (a turned word in parts turns as one)
    _NOTE.colors = p.get("colors")
    _NOTE.logos = logos
    _NOTE.pic = p.get("pic")
    _NOTE.moves = p.get("moves")
    try:
        return _compose(arr, matte, p, logo)
    finally:
        _NOTE.colors = None
        _NOTE.middles = None
        _NOTE.pic = None
        _NOTE.moves = None


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
    elif t == "custom":
        from photo_presets import custom_poster
        pic, _ = _cover(arr, W, H, (fx, fy - 0.05))
        m = None
        if matte is not None:
            m, _ = _cover(matte.astype(np.float32), W, H, (fx, fy - 0.05))
            m = cv2.GaussianBlur(np.clip((m - 0.35) / 0.4, 0, 1), (0, 0), 0.8)[..., None]
        boxes = getattr(_NOTE, "boxes", None)
        out = custom_poster.draw(pic.astype(np.float32), m, p, W, H, u, color, getattr(_NOTE, "logos", None),
                                 _over, _shadowed, _say, _font, boxes if boxes is not None else [],
                                 card=lambda base, e: _card(base, arr, matte, W, H, e, box))
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
    if t != "custom" and p.get("extras"):  # your pieces on the layout: behind the players, or on top
        from photo_presets import custom_poster
        boxes = getattr(_NOTE, "boxes", None)
        team = tuple(int(c * 255) for c in color)
        mm = None
        if matte is not None and t != "spotlight":  # (the players where the layout put them)
            mm, _ = _cover(matte.astype(np.float32), W, H, (fx, fy - 0.05))
            mm = cv2.GaussianBlur(np.clip((mm - 0.35) / 0.4, 0, 1), (0, 0), 0.8)[..., None]
        for behind in (True, False):
            if mm is None:  # (no players found: every piece on top)
                group = [] if behind else p["extras"]
            else:
                group = [e for e in p["extras"] if bool(e.get("behind")) == behind]
            if not group:
                continue
            base = out
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            for e in group:
                custom_poster._piece(lay, e, W, H, u, team, getattr(_NOTE, "logos", None), _say, _font,
                                     boxes if boxes is not None else [])
            out = _over(out, _shadowed(lay, u * 0.008, 0.3))
            if behind:  # the players (as the layout made them) back in front of these pieces
                out = out * (1 - mm) + base * mm
    if logo is not None and t == "custom":
        pass  # (its logo is one of its pieces)
    elif logo is not None and p.get("logo_at"):
        out = _logo_placed(out, logo, W, H, p["logo_at"], _placed_height(W, p), p)
    elif logo is not None and t in MORE:
        out = _logo_at(out, logo, W, H, LOGO_AT[t])
    elif logo is not None:
        out = _logo_at(out, logo, W, H, "br" if t in ("gameday", "mvp") else "tl")
    return np.clip(out, 0, 1).astype(np.float32)


def _card(out: np.ndarray, arr: np.ndarray, matte, W: int, H: int, e: dict, box) -> np.ndarray:
    """A photo card on the poster (a custom poster's piece): the picture in it, cut so the player's head
    sits at its top edge, a white edge and shadow, the player breaking out of its top and sides."""
    cw, ch = max(8, int(e["w"] * W)), max(8, int(e["h"] * H))
    cx0, cy0 = int(e["x"] * W - cw / 2), int(e["y"] * H - ch / 2)
    return _framed(out, arr, matte, W, H, (cx0, cx0 + cw, cy0, cy0 + ch), box, e.get("border", True))


def _framed(out, arr, matte, W: int, H: int, rect, box, border: bool = True) -> np.ndarray:
    """The picture in a card (rect: x0, x1, y0, y1 on the poster), cut so the player's head sits at
    its top edge (moved and zoomed as you placed it), a white edge and shadow, the player breaking
    out of its top and sides."""
    cx0, cx1, cy0, cy1 = rect
    cx0, cy0 = max(0, cx0), max(0, cy0)
    cx1, cy1 = min(W, cx1), min(H, cy1)
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
    pic = getattr(_NOTE, "pic", None) or {}  # moved and zoomed by you, in the card
    z = float(pic.get("zoom", 1.0))
    s, top, left = s * z, top * z + (z - 1) * ch / 2, left * z + (z - 1) * cw / 2
    left -= float(pic.get("x", 0)) * W
    top -= float(pic.get("y", 0)) * H
    big = cv2.resize(arr, (max(1, int(iw * s)), max(1, int(ih * s))), interpolation=cv2.INTER_CUBIC)
    bm = cv2.resize(matte.astype(np.float32), (big.shape[1], big.shape[0]), interpolation=cv2.INTER_LINEAR) if matte is not None else None
    left = int(np.clip(left, 0, max(0, big.shape[1] - cw)))
    top = int(np.clip(top, 0, max(0, big.shape[0] - ch)))
    card = np.zeros((ch, cw, 3), np.float32)
    part = big[top:top + ch, left:left + cw]
    card[:part.shape[0], :part.shape[1]] = part
    # a white border and shadow around the card
    lay, d = _layer((W, H))
    b = max(3, int(W * 0.01)) if border else 0
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
    return out


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
    out = _framed(out, arr, matte, W, H, (cx0, cx1, cy0, cy1), box)
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
        mv = (p.get("moves") or {}).get("number")
        if mv:  # (the badge goes where its number was dragged, as big as it was made)
            cx, cy, r = cx + mv.get("x", 0) * W, cy + mv.get("y", 0) * H, r * mv.get("s", 1)
        ring = max(3, int(u * 0.0064))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_c255(color), outline=(255, 255, 255, 255), width=ring)
        f = _fit_font(num, HEAVY, r * 1.35, r * 1.15)
        _NOTE.moves = _badge_moves(p)  # (placed with its badge; its font and angle its own)
        _say(d, "number", (cx, cy + r * 0.04), num, font=f, fill=(255, 255, 255, 255), anchor="mm")
        _NOTE.moves = p.get("moves")
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


def _jersey(pic, m, p, W, H, color, has_logo):
    """Their number, giant, in the team color behind them; the name and a line at the bottom."""
    u = _NOTE.u
    out = pic * 0.78 + color * 0.08
    out = out * (1 - _gradient(H, W, 0.0, 0.7, 0.6))
    lay, d = _layer((W, H))
    num = p.get("number", "")
    if num:
        f = _fit_font(num, HEAVY, W * 0.9, H * 0.58)
        lighter = color + (1 - color) * 0.38  # (a shade lighter than the kit, so it reads behind a player in it)
        _say(d, "number", (W / 2, H * 0.42), num, font=f, fill=_c255(lighter, 225), anchor="mm",
             stroke_width=max(3, int(W * 0.006)), stroke_fill=(255, 255, 255, 235))
    out = _over(out, _shadowed(lay, u * 0.015, 0.35))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * (0.66 if has_logo else 0.88), u * 0.1)
    _say(d, "title", (W / 2 if not has_logo else W * 0.43, H - u * 0.135), title, font=f, fill=(255, 255, 255, 255), anchor="mm")
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * 0.6, u * 0.03)
        _say(d, "line", (W / 2 if not has_logo else W * 0.43, H - u * 0.06), line, font=lf, fill=(255, 255, 255, 215), anchor="mm")
    return _over(out, _shadowed(lay, u * 0.008, 0.5))


def _cover_story(pic, m, p, W, H, color, has_logo):
    """A magazine cover: the masthead behind the player's head, the issue line under it, the cover
    headline and its line at the bottom left."""
    u = _NOTE.u
    out = pic * (1 - _gradient(H, W, 0.22, 0.75, 0.55))
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.92, u * 0.27)
    _say(d, "title", (W / 2, u * 0.025), title, font=f, fill=(255, 255, 255, 245), anchor="mt")
    out = _over(out, _shadowed(lay, u * 0.01, 0.3))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, BOLD, W * 0.6, u * 0.024)
        _say(d, "line", (W * 0.05, u * 0.035 + f.size * 0.98), line, font=lf, fill=(255, 255, 255, 230), anchor="lt")
    name = p.get("name", "")
    wid = W * (0.62 if has_logo else 0.86)
    nf = _fit_font(name, HEAVY, wid, u * 0.11)
    if name:
        d.rectangle((W * 0.05, H - u * 0.24, W * 0.05 + u * 0.07, H - u * 0.232), fill=_c255(color))
    _say(d, "name", (W * 0.05, H - u * 0.195 - _more(nf, name)), name, font=nf, fill=(255, 255, 255, 255), anchor="lt")
    sub = p.get("away", "")
    if sub:
        sf = _fit_font(sub, DEMI, wid, u * 0.032)
        _say(d, "away", (W * 0.05, H - u * 0.055), sub, font=sf, fill=(255, 255, 255, 225), anchor="ls")
    return _over(out, _shadowed(lay, u * 0.008, 0.55))


def _split(pic, m, p, W, H, color, has_logo):
    """A team-color panel cut on the diagonal across the bottom left, the player in front of it, their
    name on it, their number big and outlined at the top right."""
    u = _NOTE.u
    out = pic * (1 - _gradient(H, W, 0.0, 0.35, 0.6))
    lay, d = _layer((W, H))
    num = p.get("number", "")
    if num:
        f = _fit_font(num, HEAVY, W * 0.4, u * 0.3)
        _say(d, "number", (W * 0.95, u * 0.03), num, font=f, fill=(255, 255, 255, 0), anchor="rt",
             stroke_width=max(2, int(W * 0.004)), stroke_fill=(255, 255, 255, 200))
    edge = max(3, int(u * 0.008))
    d.polygon([(0, H * 0.56), (W * 0.78, H), (0, H)], fill=_c255(color, 238))
    d.line([(0, H * 0.56 - edge * 3), (W * 0.78 + edge * 4, H)], fill=(255, 255, 255, 230), width=edge)
    out = _over(out, _shadowed(lay, u * 0.012, 0.45))
    out = _front(out, pic, m)
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.5, u * 0.1)
    _say(d, "title", (W * 0.05, H - u * 0.105), title, font=f, fill=(255, 255, 255, 255), anchor="ls")
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * 0.42, u * 0.026)
        _say(d, "line", (W * 0.05, H - u * 0.05), line, font=lf, fill=(255, 255, 255, 225), anchor="ls")
    return _over(out, _shadowed(lay, u * 0.006, 0.5))


def _player_card(pic, m, p, W, H, color, has_logo):
    """A classic collector's card: the picture inside a team-color frame with a thin gold rule, a
    nameplate at the bottom, the number on a gold-ringed badge."""
    u = _NOTE.u
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    out = np.broadcast_to(color * (0.55 + 0.35 * (1 - y)), (H, W, 3)).astype(np.float32).copy()
    x0, y0, x1, y1 = int(W * 0.06), int(u * 0.06), int(W * 0.94), int(H - u * 0.2)
    cw, ch = x1 - x0, y1 - y0
    # the picture into the window, around the player
    if m is not None and (m[..., 0] > 0.5).any():
        ys, xs = np.nonzero(m[..., 0] > 0.5)
        cx, cy = (xs.min() + xs.max()) / 2, ys.min() + (ys.max() - ys.min()) * 0.45
    else:
        cx, cy = W / 2, H / 2
    k = max(cw / W, ch / H)
    sw, sh = cw / k, ch / k
    sx = int(np.clip(cx - sw / 2, 0, W - sw))
    sy = int(np.clip(cy - sh / 2, 0, H - sh))
    out[y0:y1, x0:x1] = cv2.resize(pic[sy:sy + int(sh), sx:sx + int(sw)], (cw, ch), interpolation=cv2.INTER_AREA)
    lay, d = _layer((W, H))
    rule = max(2, int(u * 0.004))
    d.rectangle((x0 - rule * 2, y0 - rule * 2, x1 + rule * 2, y1 + rule * 2), outline=GOLD + (255,), width=rule)
    out = _over(out, lay)
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * (0.62 if has_logo else 0.84), u * 0.085)
    tx = W * 0.43 if has_logo else W / 2
    _say(d, "title", (tx, H - u * 0.13), title, font=f, fill=(255, 255, 255, 255), anchor="mm")
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, DEMI, W * 0.6, u * 0.028)
        _say(d, "line", (tx, H - u * 0.065), line, font=lf, fill=GOLD + (255,), anchor="mm")
    num = p.get("number", "")
    if num:
        r = u * 0.062
        bx, by = x0 + r * 1.25, y0 + r * 1.25
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=_c255(color), outline=GOLD + (255,), width=max(3, int(u * 0.006)))
        nf = _fit_font(num, HEAVY, r * 1.35, r * 1.15)
        _NOTE.moves = _badge_moves(p)
        _say(d, "number", (bx, by + r * 0.04), num, font=nf, fill=(255, 255, 255, 255), anchor="mm")
        _NOTE.moves = p.get("moves")
    return _over(out, _shadowed(lay, u * 0.01, 0.5))


def _cinematic(pic, m, p, W, H, color, has_logo):
    """Film letterbox bars, the name in the bottom bar between thin gold rules, a quiet line under it."""
    u = _NOTE.u
    out = pic.copy()
    top, bottom = int(H * 0.1), int(H - max(H * 0.17, u * 0.17))
    out[:top] = out[:top] * 0.06
    out[bottom:] = out[bottom:] * 0.06
    lay, d = _layer((W, H))
    title = p.get("title", "")
    f = _fit_font(title, HEAVY, W * 0.7, u * 0.07)
    mid = bottom + (H - bottom) * 0.42
    _say(d, "title", (W / 2, mid), title, font=f, fill=(255, 255, 255, 250), anchor="mm")
    half = (f.getlength(title) / 2 if title else 0) + W * 0.04
    th = max(1, int(u * 0.002))
    for a, b in ((W * 0.1, W / 2 - half), (W / 2 + half, W * 0.9)):
        if b > a:
            d.rectangle((a, mid - th, b, mid + th), fill=GOLD + (220,))
    line = p.get("line", "")
    if line:
        lf = _fit_font(line, MEDIUM, W * 0.7, u * 0.024)
        _say(d, "line", (W / 2, mid + f.size * 0.75), line, font=lf, fill=(220, 220, 220, 230), anchor="mt")
    return _over(out, lay)


# Studio themes: the player cut out onto a background made here (see backgrounds.py) -----------
SUPP = "/System/Library/Fonts/Supplemental/"
COND = "/System/Library/Fonts/Avenir Next Condensed.ttc"
HEAVY_IT = 9  # Avenir Next (and Condensed) Heavy Italic


def _ff(path: str, index: int, px: float) -> ImageFont.FreeTypeFont:
    try:
        return fonts.MultiFont(path, max(6, int(px)), index=index)
    except OSError:
        return _font(HEAVY, px)


def _fit_ff(text: str, path: str, index: int, width: float, max_px: float) -> ImageFont.FreeTypeFont:
    px = max_px
    f = _ff(path, index, px)
    while px > 8 and text and f.getlength(text) > width:
        px *= 0.94
        f = _ff(path, index, px)
    return f


def _more(font, text: str) -> float:
    """How much taller text typed on several lines is than its first line (0 for one line)."""
    if "\n" not in (text or ""):
        return 0.0
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    one = d.textbbox((0, 0), text.split("\n")[0], font=font)
    whole = d.textbbox((0, 0), text, font=font, spacing=int(font.size * 0.12))
    return float((whole[3] - whole[1]) - (one[3] - one[1]))


def _spaced(text: str) -> str:
    return "\n".join(" ".join(r) for r in text.split("\n"))  # (letter-spaced, for small lines in capitals)


def _hex(color) -> str:
    return "#%02x%02x%02x" % tuple(int(np.clip(c, 0, 1) * 255) for c in color)


def _studio(pic, m, p, name, color, H, W) -> np.ndarray:
    """The player in front of a background made here (or, with no cut-out, the photo softly over it)."""
    from photo_presets import backgrounds
    bg = backgrounds.make(name, W, H, p.get("color", "#1f2a44"))
    if m is None:
        return pic * 0.45 + bg * 0.55
    return backgrounds.compose(pic, m[..., 0], bg, wrap=0.6, match=0.3, shadow=0.0)


def _chrome(out, key, xy, text, font, anchor, top=(1, 1, 1), bottom=(0.62, 0.66, 0.72), edge=(0.05, 0.06, 0.08),
            glow=None, stroke=None):
    """A word in polished metal (a light-to-dark sweep) with a dark edge and a soft shadow (or a glow)."""
    if not text:
        return out
    own = (getattr(_NOTE, "colors", None) or {}).get(key)
    if own:  # your color, as polished metal: light at the top, your color below, a dark edge of it
        c = np.array(_rgb(own), np.float32)
        top, bottom, edge = tuple(c + (1 - c) * 0.6), tuple(c), tuple(c * 0.22)
    H, W = out.shape[:2]
    lay, d = _layer((W, H))
    sw = stroke if stroke is not None else max(2, int(font.size * 0.06))
    colors, _NOTE.colors = getattr(_NOTE, "colors", None), None  # (the stencil stays white; the color is the metal's)
    try:
        _say(d, key, xy, text, font=font, fill=(255, 255, 255, 255), anchor=anchor, stroke_width=sw, stroke_fill=(0, 0, 0, 255))
    finally:
        _NOTE.colors = colors
    a = np.asarray(lay).astype(np.float32) / 255
    alpha, inner = a[..., 3:4], a[..., :1]
    ys, xs = np.nonzero(alpha[..., 0] > 0.1)
    if not len(ys):
        return out
    t = np.clip((np.arange(H, dtype=np.float32)[:, None, None] - ys.min()) / max(1, ys.max() - ys.min()), 0, 1)
    top, bottom, edge = (np.array(v, np.float32) for v in (top, bottom, edge))
    sweep = top * (1 - t) + bottom * t
    sweep = sweep + (top - sweep) * np.clip(1 - np.abs(t - 0.55) / 0.08, 0, 1)[..., :1] * 0.8  # a bright band across
    col = sweep * inner + edge * (1 - inner)
    soft = cv2.GaussianBlur(alpha[..., 0], (0, 0), max(1.0, font.size * 0.05))[..., None]
    if glow is not None:
        out = out + np.array(glow, np.float32) * soft * 0.7
    else:
        off = max(1, int(font.size * 0.04))
        sh = np.roll(np.roll(soft, off, 0), off, 1)
        out = out * (1 - sh * 0.6)
    return out * (1 - alpha) + col * alpha


def _banner(pic, m, p, W, H, color, has_logo):
    """A stadium banner: the team's name huge in chrome over a team-color stadium glow, the club in spaced
    capitals above it, the player in front, their name in a flowing script at the bottom right."""
    u = _NOTE.u
    base = _studio(pic, m, p, "Stadium Lights", color, H, W)
    out = base.copy()
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(_spaced(line), DEMI, W * 0.86, u * 0.026)
        _say(d, "line", (W / 2, u * 0.03), _spaced(line), font=lf, fill=(255, 255, 255, 230), anchor="mt")
    out = _over(out, lay)
    title = p.get("title", "")
    tf = _fit_ff(title, COND, HEAVY_IT, W * 0.92, u * 0.2)
    lift = tuple(color + (1 - color) * 0.55)
    out = _chrome(out, "title", (W / 2, u * 0.075), title, tf, "mt", top=(1, 1, 1), bottom=lift, edge=tuple(color * 0.25))
    if m is not None:  # the player in front of the name
        out = out * (1 - m) + base * m
    name = p.get("name", "")
    nf = _fit_ff(name, SUPP + "SnellRoundhand.ttc", 2, W * 0.5, u * 0.11)
    out = _chrome(out, "name", (W * 0.95, H - u * 0.07), name, nf, "rs", top=(1, 0.97, 0.88), bottom=(0.78, 0.66, 0.36),
                  edge=(0.05, 0.05, 0.05), stroke=max(2, int(nf.size * 0.05)))
    return out


def _smoke_burst(pic, m, p, W, H, color, has_logo):
    """Powder smoke in the team color bursting behind the player, light slashes at the sides, the team's
    name in chrome behind their head, their name big at the bottom (first name solid, last name outlined)."""
    u = _NOTE.u
    base = _studio(pic, m, p, "Powder Smoke", color, H, W)
    out = base.copy()
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(_spaced(line), DEMI, W * 0.8, u * 0.022)
        _say(d, "line", (W / 2, u * 0.05), _spaced(line), font=lf, fill=(255, 255, 255, 220), anchor="mt")
    out = _over(out, lay)
    title = p.get("title", "")
    tf = _fit_ff(title, COND, HEAVY_IT, W * 0.9, u * 0.17)
    light = tuple(color + (1 - color) * 0.6)
    out = _chrome(out, "title", (W / 2, u * 0.085), title, tf, "mt", top=(1, 1, 1), bottom=light, edge=(0.03, 0.04, 0.06))
    if m is not None:
        out = out * (1 - m) + base * m
    name = p.get("name", "")
    if name:
        first, _, last = name.partition(" ")
        f1 = _fit_ff(first, COND, HEAVY_IT, W * 0.7, u * 0.1)
        f2 = _fit_ff(last or first, COND, HEAVY_IT, W * 0.86, u * 0.13)
        y2 = H - u * 0.05
        y1 = y2 - f2.size * 0.95
        out = _chrome(out, "name", (W / 2, y1), first if last else "", f1, "ms", top=light, bottom=tuple(color * 0.8 + 0.1),
                      edge=(0.02, 0.02, 0.03))
        lay, d = _layer((W, H))
        _say(d, "name", (W / 2, y2), last or first, font=f2, fill=(255, 255, 255, 0), anchor="ms",
             stroke_width=max(2, int(f2.size * 0.05)), stroke_fill=(255, 255, 255, 245))
        out = _over(out, _shadowed(lay, u * 0.006, 0.6))
    return out


def _featured(pic, m, p, W, H, color, has_logo):
    """Half black-and-white texture, half team color, split on the diagonal; a year and a flowing script
    word at the top right; the number big and brushed with a row of dots and a role under it; the name
    spaced along the bottom."""
    u = _NOTE.u
    base = _studio(pic, m, p, "Signature Split", color, H, W)
    out = base * (1 - _gradient(H, W, 0.0, 0.55, 0.75))
    lay, d = _layer((W, H))
    year = p.get("line", "")
    if year:
        _say(d, "line", (W * 0.94, u * 0.06), year, font=_font(DEMI, u * 0.03), fill=(255, 255, 255, 235), anchor="rm")
    title = p.get("title", "")
    sf = _fit_ff(title, SUPP + "SnellRoundhand.ttc", 2, W * 0.4, u * 0.085)
    _say(d, "title", (W * 0.95, u * 0.125), title, font=sf, fill=(255, 255, 255, 250), anchor="rm")
    sub = p.get("away", "")
    if sub:
        _say(d, "away", (W * 0.93, u * 0.18), sub, font=_ff(SUPP + "SnellRoundhand.ttc", 1, u * 0.045), fill=(255, 255, 255, 235), anchor="rm")
    out = _over(out, _shadowed(lay, u * 0.006, 0.6))
    if m is not None:
        out = out * (1 - m) + base * m
    lay, d = _layer((W, H))
    num = p.get("number", "")
    cx = W * 0.83
    if num:
        nf = _fit_ff(num, SUPP + "Brush Script.ttf", 0, W * 0.3, u * 0.2)
        _say(d, "number", (cx, H - u * 0.27), num, font=nf, fill=(255, 255, 255, 250), anchor="mm")
        r = max(2, u * 0.006)
        for i in range(7):
            x = cx + (i - 3) * u * 0.024
            d.ellipse((x - r, H - u * 0.175 - r, x + r, H - u * 0.175 + r), fill=(255, 255, 255, 235))
    role = p.get("home", "")
    if role:
        rf = _fit_font(_spaced(role), DEMI, W * 0.3, u * 0.032)
        _say(d, "home", (cx, H - u * 0.13), _spaced(role), font=rf, fill=(255, 255, 255, 245), anchor="mm")
    name = p.get("name", "")
    if name:
        nm = "   ".join(_spaced(w) for w in name.split())
        f = _fit_font(nm, MEDIUM, W * 0.9, u * 0.045)
        _say(d, "name", (W / 2, H - u * 0.045), nm, font=f, fill=(255, 255, 255, 250), anchor="mm")
    return _over(out, _shadowed(lay, u * 0.006, 0.6))


def _storm(pic, m, p, W, H, color, has_logo):
    """A storm sky with a floodlight breaking through, the number faint and huge behind the player, the
    name at the bottom with a cool glow."""
    u = _NOTE.u
    base = _studio(pic, m, p, "Storm Sky", color, H, W)
    out = base * (1 - _gradient(H, W, 0.0, 0.6, 0.7))
    lay, d = _layer((W, H))
    num = p.get("number", "")
    if num:
        f = _fit_font(num, HEAVY, W * 0.8, H * 0.55)
        _say(d, "number", (W / 2, H * 0.42), num, font=f, fill=(255, 255, 255, 46), anchor="mm")
    out = _over(out, lay)
    if m is not None:
        out = out * (1 - m) + base * m
    title = p.get("title", "")
    tf = _fit_ff(title, COND, 8, W * 0.86, u * 0.13)
    out = _chrome(out, "title", (W / 2, H - u * 0.085), title, tf, "ms", top=(1, 1, 1), bottom=(0.72, 0.78, 0.9),
                  edge=(0.03, 0.04, 0.08), glow=(0.35, 0.5, 0.85))
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_font(_spaced(line), DEMI, W * 0.8, u * 0.024)
        _say(d, "line", (W / 2, H - u * 0.04), _spaced(line), font=lf, fill=(220, 228, 245, 235), anchor="mm")
    return _over(out, lay)


def _collector(pic, m, p, W, H, color, has_logo):
    """A collector's magazine cover: a team-color studio with a darker panel down one side, the title
    huge in chrome, the issue line under it, a script badge in a box at the bottom left and a ribbon
    across the bottom right corner."""
    u = _NOTE.u
    from photo_presets import backgrounds
    bg = backgrounds.make("Team Studio", W, H, p.get("color", "#1f2a44"))
    xx = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]
    panel = (xx > 0.56).astype(np.float32)
    bg = bg * (1 - panel * 0.45) + panel * (color * 0.7 + 0.04)
    bg[:, int(W * 0.56):int(W * 0.56) + max(2, int(W * 0.004))] = 0.92
    base = backgrounds.compose(pic, m[..., 0], bg, wrap=0.5, shadow=0.0) if m is not None else pic * 0.5 + bg * 0.5
    out = base.copy()
    title = p.get("title", "")
    tf = _fit_ff(title, COND, HEAVY_IT, W * 0.94, u * 0.2)
    lift = tuple(color + (1 - color) * 0.5)
    out = _chrome(out, "title", (W / 2, u * 0.02), title, tf, "mt", top=(1, 1, 1), bottom=lift, edge=(0.02, 0.02, 0.02))
    lay, d = _layer((W, H))
    line = p.get("line", "")
    if line:
        lf = _fit_ff(_spaced(line), COND, HEAVY_IT, W * 0.42, u * 0.028)
        _say(d, "line", (W * 0.05, u * 0.035 + tf.size * 1.02), _spaced(line), font=lf, fill=(255, 255, 255, 240), anchor="lt")
    out = _over(out, _shadowed(lay, u * 0.005, 0.6))
    if m is not None:
        out = out * (1 - m) + base * m
    lay, d = _layer((W, H))
    box = (W * 0.02, H - u * 0.2, W * 0.5, H - u * 0.07)
    d.rounded_rectangle(box, radius=u * 0.025, fill=(8, 8, 10, 235), outline=(255, 255, 255, 235), width=max(2, int(u * 0.004)))
    yr = p.get("minute", "")
    if yr:
        _say(d, "minute", ((box[0] + box[2]) / 2, box[1] + u * 0.03), yr, font=_font(DEMI, u * 0.028), fill=(255, 255, 255, 240), anchor="mm")
    sc = p.get("away", "")
    if sc:
        sf = _fit_ff(sc, SUPP + "SnellRoundhand.ttc", 2, (box[2] - box[0]) * 0.86, u * 0.075)
        _say(d, "away", ((box[0] + box[2]) / 2, box[1] + u * 0.088), sc, font=sf, fill=(255, 255, 255, 250), anchor="mm")
    out = _over(out, lay)
    rib = p.get("home", "")
    if rib:  # a ribbon across the bottom right corner
        size = int(u * 0.42)
        r = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        rd = ImageDraw.Draw(r)
        band = u * 0.055
        rd.rectangle((0, size - band / 2, size * 2, size + band / 2), fill=(10, 10, 12, 245))
        rd.rectangle((0, size - band / 2, size * 2, size - band / 2 + max(2, u * 0.004)), fill=_c255(color))
        rd.rectangle((0, size + band / 2 - max(2, u * 0.004), size * 2, size + band / 2), fill=_c255(color))
        rf = _fit_ff(rib, COND, HEAVY_IT, size * 1.2, band * 0.6)
        r = r.rotate(45, resample=Image.BICUBIC)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        x0, y0 = int(W - size * 1.45), int(H - size * 1.45)
        lay.alpha_composite(r, (x0, y0))
        d = ImageDraw.Draw(lay)  # its words along the ribbon (your color, font, place and turn apply)
        _say(d, "home", (x0 + size, y0 + size), rib, font=rf, turn=-45, fill=_c255(color + (1 - color) * 0.35), anchor="mm")
        out = _over(out, _shadowed(lay, u * 0.01, 0.5))
    return out


# Clean overlays: the photo as it is, the words set on a quiet fill (a band, a plate, a tag, glass) ---------

def _soft_bottom(pic, H, start=0.55, strength=0.55):
    """A gentle dark fade at the bottom, for white words to read on any photo."""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    return pic * (1 - strength * np.clip((y - start) / (1 - start), 0, 1) ** 1.4)


def _fill_band(pic, m, p, W, H, color, has_logo):
    """A see-through dark band across the lower third, a thin team-color edge on top, the name big and clean
    in it, a spaced line under it."""
    u = _NOTE.u
    out = pic.copy()
    title, line = p.get("title", ""), p.get("line", "")
    tf = _fit_font(title, HEAVY, W * 0.86, u * 0.085)
    lf = _fit_font(_spaced(line), DEMI, W * 0.8, u * 0.024) if line else None
    band_h = tf.size * 1.25 + (lf.size * 2.2 if lf else 0) + u * 0.05
    y1 = H - u * 0.07
    y0 = y1 - band_h
    out[int(y0):int(y1)] = out[int(y0):int(y1)] * 0.3 + np.array([0.02, 0.025, 0.035], np.float32) * 0.7
    out[int(y0):int(y0 + max(2, u * 0.005))] = color
    lay, d = _layer((W, H))
    _say(d, "title", (W / 2, y0 + u * 0.03 + tf.size * 0.55), title, font=tf, fill=(255, 255, 255, 255), anchor="mm")
    if lf:
        _say(d, "line", (W / 2, y1 - u * 0.03 - lf.size * 0.5), _spaced(line), font=lf, fill=(225, 230, 238, 235), anchor="mm")
    return _over(out, lay)


def _lower_third(pic, m, p, W, H, color, has_logo):
    """A broadcast lower third: a team-color plate with the name, a slim dark strip under it with the line."""
    u = _NOTE.u
    out = _soft_bottom(pic, H, 0.6, 0.35)
    title, line = p.get("title", ""), p.get("line", "")
    tf = _fit_ff(title, COND, 8, W * 0.62, u * 0.07)
    lf = _fit_font(_spaced(line), DEMI, W * 0.6, u * 0.021) if line else None
    x0, pad = W * 0.06, u * 0.025
    pw = (tf.getlength(title) if title else W * 0.3) + pad * 2.4
    ph = tf.size * 1.25
    y0 = H - u * 0.12 - ph - (lf.size * 2.0 if lf else 0)
    lay, d = _layer((W, H))
    d.rectangle((x0, y0, x0 + pw, y0 + ph), fill=_c255(color, 240))
    d.rectangle((x0, y0, x0 + max(3, u * 0.008), y0 + ph), fill=(255, 255, 255, 255))
    if lf:
        sw = max(pw * 0.8, lf.getlength(_spaced(line)) + pad * 2)
        d.rectangle((x0, y0 + ph, x0 + sw, y0 + ph + lf.size * 2.0), fill=(8, 10, 14, 225))
        _say(d, "line", (x0 + pad, y0 + ph + lf.size), _spaced(line), font=lf, fill=(230, 233, 240, 240), anchor="lm")
    _say(d, "title", (x0 + pad * 1.2, y0 + ph / 2), title, font=tf, fill=(255, 255, 255, 255), anchor="lm")
    return _over(out, _shadowed(lay, u * 0.008, 0.35))


def _knockout(pic, m, p, W, H, color, has_logo):
    """A solid panel across the bottom with the name cut out of it: the photo shows through the letters.
    The name's color is the panel's."""
    u = _NOTE.u
    out = pic.copy()
    title, line = p.get("title", ""), p.get("line", "")
    tf = _fit_ff(title, COND, 8, W * 0.9, u * 0.2)
    lf = _fit_font(_spaced(line), DEMI, W * 0.8, u * 0.022) if line else None
    ph = tf.size * 1.05 + _more(tf, title) + (lf.size * 2.6 if lf else u * 0.03) + _more(lf, _spaced(line)) if lf else \
        tf.size * 1.05 + _more(tf, title) + u * 0.03
    y0 = H - ph - u * 0.04
    panel = word_color("title", (245, 245, 242))
    cut, cd = _layer((W, H))
    colors, _NOTE.colors = getattr(_NOTE, "colors", None), None  # (the cut-out is a stencil; the color is the panel's)
    try:
        _say(cd, "title", (W / 2, y0 + u * 0.01 + tf.size * 0.52 + _more(tf, title) / 2), title, font=tf, fill=(255, 255, 255, 255), anchor="mm")
    finally:
        _NOTE.colors = colors
    hole = np.asarray(cut).astype(np.float32)[..., 3:4] / 255
    fill = np.zeros((H, W, 1), np.float32)
    fill[int(y0):int(H - u * 0.04), int(W * 0.04):int(W * 0.96)] = 1
    a = np.clip(fill - hole, 0, 1) * 0.94
    out = out * (1 - a) + np.array(panel, np.float32) / 255 * a
    if lf:
        lay, d = _layer((W, H))
        ink = (20, 22, 26, 255) if sum(panel) > 380 else (245, 245, 245, 255)
        _say(d, "line", (W / 2, H - u * 0.04 - lf.size * 1.3), _spaced(line), font=lf, fill=ink, anchor="mm")
        out = _over(out, lay)
    return out


def _side_label(pic, m, p, W, H, color, has_logo):
    """The name standing up along the left edge on a slim team-color strip, a small line at the bottom."""
    u = _NOTE.u
    out = pic.copy()
    title, line = p.get("title", ""), p.get("line", "")
    tf = _fit_ff(_spaced(title), str(Path(__file__).parent / "studio/web/fonts/BigShouldersDisplay-900.ttf"), 0, H * 0.8, u * 0.07)
    strip = tf.size * 1.5
    x0 = W * 0.035
    out[:, int(x0):int(x0 + strip)] = out[:, int(x0):int(x0 + strip)] * 0.15 + np.array(color, np.float32) * 0.85
    lay, d = _layer((W, H))
    _say(d, "title", (x0 + strip / 2, H / 2), _spaced(title), font=tf, turn=-90, fill=(255, 255, 255, 255), anchor="mm")
    if line:
        lf = _fit_font(_spaced(line), DEMI, W * 0.6, u * 0.022)
        _say(d, "line", (x0 + strip + W * 0.04, H - u * 0.05), _spaced(line), font=lf, fill=(255, 255, 255, 235), anchor="ls")
    out = _soft_bottom(out, H, 0.75, 0.3) if line else out
    return _over(out, _shadowed(lay, u * 0.006, 0.3))


def _corner_tag(pic, m, p, W, H, color, has_logo):
    """A small solid tag in the top left corner, the name clean and large at the bottom left, a line under it."""
    u = _NOTE.u
    out = _soft_bottom(pic, H, 0.58, 0.5)
    lay, d = _layer((W, H))
    title = p.get("title", "")
    if title:
        tf = _ff(str(Path(__file__).parent / "studio/web/fonts/ChakraPetch-700.ttf"), 0, u * 0.03)
        tw = tf.getlength(_spaced(title))
        x0, y0 = W * 0.05, u * 0.045
        d.rectangle((x0, y0, x0 + tw + u * 0.05, y0 + tf.size * 1.9), fill=_c255(color, 245))
        _say(d, "title", (x0 + u * 0.025, y0 + tf.size * 0.95), _spaced(title), font=tf, fill=(255, 255, 255, 255), anchor="lm")
    name, line = p.get("name", ""), p.get("line", "")
    nf = _fit_font(name, BOLD, W * 0.86, u * 0.08)
    lf = _fit_font(_spaced(line), MEDIUM, W * 0.8, u * 0.022) if line else None
    ny = H - u * 0.07 - (lf.size * 1.8 if lf else 0)
    _say(d, "name", (W * 0.05, ny), name, font=nf, fill=(255, 255, 255, 255), anchor="ls")
    if lf:
        _say(d, "line", (W * 0.05, H - u * 0.065), _spaced(line), font=lf, fill=(225, 228, 235, 235), anchor="ls")
    return _over(out, _shadowed(lay, u * 0.006, 0.35))


def _outline_stack(pic, m, p, W, H, color, has_logo):
    """Two lines at the bottom left: the first outlined, the second solid, a small line under them."""
    u = _NOTE.u
    out = _soft_bottom(pic, H, 0.5, 0.6)
    lay, d = _layer((W, H))
    title, name, line = p.get("title", ""), p.get("name", ""), p.get("line", "")
    big = min(u * 0.16, W * 0.2)
    tf = _fit_ff(title, COND, 8, W * 0.9, big)
    nf = _fit_ff(name, COND, 8, W * 0.9, big)
    lf = _fit_font(_spaced(line), DEMI, W * 0.8, u * 0.022) if line else None
    y = H - u * 0.07 - (lf.size * 1.9 if lf else 0)
    _say(d, "name", (W * 0.05, y), name, font=nf, fill=(255, 255, 255, 255), anchor="ls")
    _say(d, "title", (W * 0.05, y - nf.size * 0.98 - _more(nf, name)), title, font=tf, fill=(255, 255, 255, 0), anchor="ls",
         stroke_width=max(2, int(tf.size * 0.03)), stroke_fill=(255, 255, 255, 255))
    if lf:
        _say(d, "line", (W * 0.05, H - u * 0.065), _spaced(line), font=lf, fill=_c255(color + (1 - color) * 0.55), anchor="ls")
    return _over(out, _shadowed(lay, u * 0.006, 0.3))


def _frosted(pic, m, p, W, H, color, has_logo):
    """A frosted-glass panel near the bottom (the photo behind it softly blurred and dimmed, a fine light edge),
    the name and a line in it."""
    u = _NOTE.u
    out = pic.copy()
    title, line = p.get("title", ""), p.get("line", "")
    tf = _fit_font(title, BOLD, W * 0.74, u * 0.065)
    lf = _fit_font(_spaced(line), MEDIUM, W * 0.72, u * 0.021) if line else None
    pw = W * 0.86
    ph = tf.size * 1.5 + (lf.size * 2.2 if lf else 0) + u * 0.03
    x0, y1 = (W - pw) / 2, H - u * 0.07
    y0 = y1 - ph
    box = (int(x0), int(y0), int(x0 + pw), int(y1))
    glass = cv2.GaussianBlur(pic, (0, 0), max(4.0, u * 0.03)) * 0.62 + 0.06
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=u * 0.02, fill=255)
    mk = np.asarray(mask).astype(np.float32)[..., None] / 255
    out = out * (1 - mk) + glass * mk
    lay, d = _layer((W, H))
    d.rounded_rectangle(box, radius=u * 0.02, outline=(255, 255, 255, 70), width=max(1, int(u * 0.002)))
    _say(d, "title", (W / 2, y0 + u * 0.02 + tf.size * 0.7), title, font=tf, fill=(255, 255, 255, 255), anchor="mm")
    if lf:
        _say(d, "line", (W / 2, y1 - u * 0.02 - lf.size * 0.9), _spaced(line), font=lf, fill=(230, 233, 240, 230), anchor="mm")
    return _over(out, lay)


MORE = {"name": _name_stack, "goal": _goal, "teamcolor": _team_color, "matchday": _matchday, "champions": _champions,
        "jersey": _jersey, "cover": _cover_story, "split": _split, "card": _player_card, "cinematic": _cinematic,
        "banner": _banner, "smoke": _smoke_burst, "featured": _featured, "storm": _storm, "collector": _collector,
        "fillband": _fill_band, "lowerthird": _lower_third, "knockout": _knockout, "sidelabel": _side_label,
        "cornertag": _corner_tag, "outlinestack": _outline_stack, "frosted": _frosted}
LOGO_AT = {"name": "tl", "goal": "tr", "teamcolor": "br", "matchday": "band", "champions": "bc",
           "jersey": "br", "cover": "br", "split": "tl", "card": "br", "cinematic": "tl",
           "banner": "tr", "smoke": "tl", "featured": "tl", "storm": "tr", "collector": "tr",
           "fillband": "tr", "lowerthird": "tr", "knockout": "tr", "sidelabel": "tr", "cornertag": "tr", "outlinestack": "tr",
           "frosted": "tr"}


def _placed_height(W: int, p: dict) -> int:
    """How tall the poster was (at this width) when you dragged things on it: its own shape. An export
    to another size (a 9:16 story from a 4:5 post) sets only "aspect", and keeps the shape it was made in."""
    return int(round(W / SHAPES.get(p.get("shape", "post"), 0.8)))


def _logo_placed(out: np.ndarray, logo: Image.Image, W: int, H: int, at: dict, H0: int | None = None,
                 p: dict | None = None) -> np.ndarray:
    """The logo with its middle where you dragged it, its width a share of the poster's. On another
    shape than it was dragged on (H0 tall), it keeps its distance from the nearest edge, top or
    bottom, the way the poster's own badges and words do (measured in the poster's unit), so a logo
    level with the number badge stays level with it on a 9:16 story."""
    k = 1.0
    cy = at["y"] * H
    if H0 and H0 != H:
        u, u0 = _unit(W, H, p or {}), _unit(W, H0, p or {})
        k = u / u0
        cy0 = at["y"] * H0
        cy = cy0 * k if at["y"] <= 0.5 else H - (H0 - cy0) * k
    lw = max(4, int(at["size"] * W * k))
    lh = max(1, int(lw * logo.height / logo.width))
    x, y = at["x"] * W - lw / 2, cy - lh / 2
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lay.alpha_composite(logo.resize((lw, lh), Image.LANCZOS), (int(x), int(y)))
    _note_box("logo", (x, y, x + lw, y + lh))
    return _over(out, lay)


def _note_box(key: str, box) -> None:
    boxes = getattr(_NOTE, "boxes", None)
    if boxes is not None:
        boxes.append((key, box))


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
    _note_box("logo", (x, y, x + lw, y + lh))
    return _over(out, lay)


def customized(p: dict, has_logo: bool = False) -> dict:
    """The poster as a custom one: its words, panels and bands as pieces, to move, resize and restyle."""
    from photo_presets import custom_poster
    p = clean(p)
    if p is None:
        return {}
    if p["template"] == "custom":
        return p
    W, H = size_for(800, 1000, p)
    u = _unit(W, H, p)
    els = custom_poster.from_layout(p, words(p, has_logo), W, H, u)
    taken = {e["id"] for e in els}
    for e in p.get("extras") or []:  # your own pieces, kept (drawn over the layout's, as before)
        e = dict(e)
        if e.get("id") in taken:
            e["id"] = "x" + str(e["id"])[:10]
        els.append(e)
    keep = {k: p[k] for k in ("shape", "color", "logo", "size", "colors", "kept", "kept_moves") if k in p}
    return clean({**keep, "template": "custom", "elements": els,
                  "fade_top": 0.3 if p["template"] in ("final", "spotlight") else 0.1,
                  "fade_bottom": 0.62 if p["template"] != "spotlight" else 0.3})


# A team's posters: where each player's name and number go -------------------------------------
NAME_KEY = {"spotlight": "title", "name": "title", "teamcolor": "title", "goal": "name", "mvp": "line",
            "jersey": "title", "cover": "name", "split": "title", "card": "title", "cinematic": "title",
            "banner": "name", "smoke": "name", "featured": "name", "storm": "title",
            "fillband": "title", "lowerthird": "title", "knockout": "title", "sidelabel": "title", "cornertag": "name",
            "outlinestack": "title", "frosted": "title"}
NUMBER_KEY = {"spotlight": "number", "jersey": "number", "split": "number", "card": "number", "featured": "number", "storm": "number"}


def player_fields(p: dict) -> dict:
    """{"name": (where, value), "number": (where, value)} on this poster: a word's key, or a custom
    poster's piece ("el:<id>": its biggest heavy text for the name, its first badge for the number)."""
    out = {}
    t = p.get("template")
    if t == "custom":
        els = p.get("elements") or []
        texts = [e for e in els if e["type"] == "text" and e.get("style") in ("heavy", "outline")] or [e for e in els if e["type"] == "text"]
        if texts:
            big = max(texts, key=lambda e: e.get("size", 0))
            out["name"] = (f"el:{big['id']}", big.get("text", ""))
        badge = next((e for e in els if e["type"] == "badge"), None)
        if badge:
            out["number"] = (f"el:{badge['id']}", badge.get("text", ""))
        return out
    if t in NAME_KEY:
        out["name"] = (NAME_KEY[t], p.get(NAME_KEY[t], ""))
    if t in NUMBER_KEY:
        out["number"] = (NUMBER_KEY[t], p.get(NUMBER_KEY[t], ""))
    return out


def with_player(p: dict, name: str | None = None, number: str | None = None) -> dict:
    """The poster with this player's name and number put where they go."""
    p = dict(p)
    if p.get("template") == "custom":
        p["elements"] = [dict(e) for e in p.get("elements") or []]
    for field_name, value in (("name", name), ("number", number)):
        if value is None or field_name not in player_fields(p):
            continue
        where = player_fields(p)[field_name][0]
        if where.startswith("el:"):
            for e in p["elements"]:
                if e["id"] == where[3:]:
                    e["text"] = value
        else:
            p[where] = value
    return p
