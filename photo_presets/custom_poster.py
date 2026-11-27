"""A custom poster: your own layout, built from the same pieces the ready-made layouts use.

The picture fills the poster's shape; a dark fade at the top and the bottom (each as strong as
you like) lets words read; then the pieces, in order:

- text: any words, in a style (heavy, bold, clean, spaced, outline, banner), size and color
- badge: a number in a team-color circle with a white ring
- box: a panel or a band (any width, height, color and strength), with the team-color edge or not
- rule: a thin line
- logo: one of your logos

Any piece but the photo card turns to any angle (degrees, clockwise); text can be in any of fonts.FONTS.

Any piece can sit behind the players (they stand in front of it: the "pop-out"), or in front.
Each is placed by its middle (shares of the poster) and sized in the poster's unit (see
poster._unit), so it fits any shape. Drawn here for the preview and the export alike.
"""

from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageDraw

from photo_presets import fonts

TYPES = ("text", "badge", "box", "rule", "logo", "card", "stripes")
TEXT_STYLES = ("heavy", "bold", "clean", "spaced", "outline", "banner")
LIMIT = 30  # pieces on one poster


def _hex(v, default: str) -> str:
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        return float(np.clip(float(v), lo, hi))
    except (TypeError, ValueError):
        return default


def clean(elements) -> list[dict]:
    out = []
    for i, e in enumerate(elements or []):
        if not isinstance(e, dict) or e.get("type") not in TYPES:
            continue
        t = e["type"]
        c = {"id": re.sub(r"[^a-z0-9]", "", str(e.get("id") or f"e{i}").lower())[:12] or f"e{i}", "type": t,
             "x": _num(e.get("x"), -0.2, 1.2, 0.5), "y": _num(e.get("y"), -0.2, 1.2, 0.5), "behind": bool(e.get("behind"))}
        if t != "card" and fonts.angle_ok(e.get("angle", 0)):
            c["angle"] = fonts.angle_ok(e["angle"])
        if t == "text":
            c.update(text=fonts.lines(str(e.get("text", ""))[:80]), style=e.get("style") if e.get("style") in TEXT_STYLES else "bold",
                     size=_num(e.get("size"), 0.01, 0.5, 0.06), color=_hex(e.get("color"), "#ffffff"))
            if fonts.name_ok(e.get("font")):
                c["font"] = e["font"]
        elif t == "badge":
            c.update(text=str(e.get("text", "7"))[:4], size=_num(e.get("size"), 0.02, 0.3, 0.07),
                     color=_hex(e.get("color"), ""), ink=_hex(e.get("ink"), "#ffffff"))
        elif t == "box":
            c.update(w=_num(e.get("w"), 0.02, 1.2, 0.86), h=_num(e.get("h"), 0.005, 1.2, 0.18),
                     color=_hex(e.get("color"), "#0a0c10"), opacity=_num(e.get("opacity"), 0.05, 1.0, 0.66),
                     round=bool(e.get("round", True)), accent=bool(e.get("accent", False)))
        elif t == "rule":
            c.update(w=_num(e.get("w"), 0.02, 1.2, 0.3), thick=_num(e.get("thick"), 0.001, 0.05, 0.004),
                     color=_hex(e.get("color"), "#d4af37"))
        elif t == "logo":
            c.update(logo=str(e.get("logo") or "")[:20], size=_num(e.get("size"), 0.03, 0.8, 0.13))
        elif t == "stripes":  # bands of color side by side (red, white and blue; the team's colors…)
            cols = [_hex(c, "") for c in (e.get("colors") or [])][:6]
            cols = [c for c in cols if c] or ["#c8102e", "#ffffff", "#0b3d91"]
            c.update(colors=cols, dir="v" if e.get("dir") == "v" else "h", w=_num(e.get("w"), 0.01, 1.2, 1.1),
                     h=_num(e.get("h"), 0.005, 1.2, 0.06), opacity=_num(e.get("opacity"), 0.05, 1.0, 1.0))
        elif t == "card":  # the photo in a white-edged card, the players breaking out of its top
            c.update(w=_num(e.get("w"), 0.1, 1.0, 0.82), h=_num(e.get("h"), 0.1, 1.0, 0.6), border=bool(e.get("border", True)))
        out.append(c)
    return out[:LIMIT]


def draw(pic: np.ndarray, m, p: dict, W: int, H: int, u: float, color, logos, over, shadowed, say, font, boxes,
         card=None) -> np.ndarray:
    """The custom poster (floats 0-1): pic is the picture filling the poster, m its players (or None);
    card(el) draws a photo card (the picture in it, the players breaking out) on the poster."""
    cards = [e for e in (p.get("elements") or []) if e["type"] == "card"]
    if p.get("background") == "team" or cards:  # a team-color background (the photo is in its card)
        y0 = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        c = np.array(color, np.float32)
        out = np.broadcast_to(c * 0.35 * (1 - y0) * 0.6 + c * 0.55 * (1 - y0) + 0.04, (H, W, 3)).astype(np.float32).copy()
        for e in cards:
            out = card(out, e) if card else out
            if boxes is not None:
                w, h = e["w"] * W, e["h"] * H
                boxes.append((f"el:{e['id']}", (e["x"] * W - w / 2, e["y"] * H - h / 2, e["x"] * W + w / 2, e["y"] * H + h / 2)))
        return _pieces(out, out.copy(), None, [e for e in p.get("elements") or [] if e["type"] != "card"], W, H, u, color, logos,
                       over, shadowed, say, font, boxes)
    out = pic.astype(np.float32)
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    top, bottom = float(p.get("fade_top", 0.35)), float(p.get("fade_bottom", 0.55))
    if top or bottom:  # a dark fade at the top and the bottom, for the words to read
        shade = top * np.clip(1 - y / 0.35, 0, 1) ** 1.6 + bottom * np.clip((y - 0.55) / 0.45, 0, 1) ** 1.3
        out = out * (1 - np.clip(shade, 0, 0.92))
    return _pieces(out, pic, m, p.get("elements") or [], W, H, u, color, logos, over, shadowed, say, font, boxes)


def _pieces(out, pic, m, els, W, H, u, color, logos, over, shadowed, say, font, boxes) -> np.ndarray:
    team = tuple(int(c * 255) for c in color)
    for behind in (True, False):
        group = [e for e in els if e["behind"] == behind]
        if group:
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            for e in group:
                _piece(lay, e, W, H, u, team, logos, say, font, boxes)
            out = over(out, shadowed(lay, u * 0.01, 0.35))
        if behind and m is not None:  # the players in front of what is behind them
            out = out * (1 - m) + pic * m
    return out


def _piece(lay: Image.Image, e: dict, W: int, H: int, u: float, team: tuple, logos, say, font, boxes) -> None:
    if e.get("angle"):  # drawn on its own (with room past the edges, so none of it is lost), then turned
        P = max(W, H) // 2
        own = Image.new("RGBA", (W + 2 * P, H + 2 * P), (0, 0, 0, 0))
        n = len(boxes)
        _piece(own, {**e, "angle": 0, "x": (e["x"] * W + P) / W, "y": (e["y"] * H + P) / H}, W, H, u, team, logos, say, font, boxes)
        boxes[n:] = [(k, (b[0] - P, b[1] - P, b[2] - P, b[3] - P)) for k, b in boxes[n:]]
        fonts.paste(lay, fonts.turned(own, e["angle"], (e["x"] * W + P, e["y"] * H + P)), -P, -P)
        return
    d = ImageDraw.Draw(lay)
    cx, cy = e["x"] * W, e["y"] * H
    key = f"el:{e['id']}"
    t = e["type"]
    if t == "text":
        px = max(6, e["size"] * u)
        style = e["style"]
        fill = tuple(int(e["color"][i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        text = e["text"]
        if style in ("heavy", "bold", "spaced", "outline", "banner"):
            text = text.upper()
        idx = {"heavy": 8, "bold": 0, "clean": 2, "spaced": 5, "outline": 8, "banner": 0}[style]
        f = fonts.load(e.get("font"), px) or font(idx, px)
        ml = {"align": "center", "spacing": int(px * 0.12)}  # (several lines: centered on each other)
        if style == "spaced":
            text = "\n".join(" ".join(r) for r in text.split("\n"))  # (hair spaces: the letters set apart)
        if style == "banner" and text:
            x0, y0, x1, y1 = d.textbbox((cx, cy), text, font=f, anchor="mm", **ml)
            pad = px * 0.35
            d.rounded_rectangle((x0 - pad * 1.3, y0 - pad, x1 + pad * 1.3, y1 + pad), radius=px * 0.18, fill=(10, 12, 16, 160))
        if style == "outline":
            d.text((cx, cy), text, font=f, fill=fill[:3] + (0,), anchor="mm", stroke_width=max(2, int(px * 0.045)), stroke_fill=fill, **ml)
        else:
            d.text((cx, cy), text, font=f, fill=fill, anchor="mm", **ml)
        if text:
            boxes.append((key, d.textbbox((cx, cy), text, font=f, anchor="mm", **ml)))
    elif t == "badge":
        r = e["size"] * u
        fillc = tuple(int(e["color"][i:i + 2], 16) for i in (1, 3, 5)) if e["color"] else team
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fillc + (255,), outline=(255, 255, 255, 255), width=max(3, int(r * 0.085)))
        ink = tuple(int(e["ink"][i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        px = r * 1.15
        f = font(8, px)
        while px > 8 and f.getlength(e["text"]) > r * 1.35:
            px *= 0.94
            f = font(8, px)
        d.text((cx, cy + r * 0.04), e["text"], font=f, fill=ink, anchor="mm")
        boxes.append((key, (cx - r, cy - r, cx + r, cy + r)))
    elif t == "box":
        w, h = e["w"] * W, e["h"] * u
        rect = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        col = tuple(int(e["color"][i:i + 2], 16) for i in (1, 3, 5)) + (int(255 * e["opacity"]),)
        if e["round"]:
            d.rounded_rectangle(rect, radius=min(h / 2, u * 0.018), fill=col)
        else:
            d.rectangle(rect, fill=col)
        if e["accent"]:
            d.rectangle((rect[0], rect[1], rect[0] + max(3, u * 0.0096), rect[3]), fill=team + (255,))
        boxes.append((key, rect))
    elif t == "rule":
        w, th = e["w"] * W, max(1.0, e["thick"] * u)
        col = tuple(int(e["color"][i:i + 2], 16) for i in (1, 3, 5)) + (235,)
        d.rectangle((cx - w / 2, cy - th / 2, cx + w / 2, cy + th / 2), fill=col)
        boxes.append((key, (cx - w / 2, cy - max(th, u * 0.012) / 2, cx + w / 2, cy + max(th, u * 0.012) / 2)))
    elif t == "stripes":
        w, h = e["w"] * W, e["h"] * u
        x0, y0 = cx - w / 2, cy - h / 2
        n = len(e["colors"])
        a = int(255 * e["opacity"])
        for i, col in enumerate(e["colors"]):
            rgb = tuple(int(col[j:j + 2], 16) for j in (1, 3, 5))
            if e["dir"] == "h":  # bands one above the other, running across
                d.rectangle((x0, y0 + h * i / n, x0 + w, y0 + h * (i + 1) / n), fill=rgb + (a,))
            else:  # bands side by side, running up and down
                d.rectangle((x0 + w * i / n, y0, x0 + w * (i + 1) / n, y0 + h), fill=rgb + (a,))
        boxes.append((key, (x0, y0, x0 + w, y0 + h)))
    elif t == "logo":
        art = logos(e["logo"]) if logos else None
        lw = max(4, int(e["size"] * W))
        if art is None:  # (no logo chosen: a dashed place for it while editing is drawn by the page)
            boxes.append((key, (cx - lw / 2, cy - lw / 2, cx + lw / 2, cy + lw / 2)))
            return
        lh = max(1, int(lw * art.height / art.width))
        piece = art.resize((lw, lh), Image.LANCZOS)
        lay.alpha_composite(piece, (int(cx - lw / 2), int(cy - lh / 2)))
        boxes.append((key, (cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2)))


# Starting from a ready-made layout -----------------------------------------------------------

BEHIND_TITLE = {"gameday", "mvp", "name", "goal", "teamcolor", "champions", "cover"}


def from_layout(p: dict, words: list[dict], W: int, H: int, u: float) -> list[dict]:
    """A ready-made layout as custom pieces (its words where they were, its panels and bands), to change freely."""
    t = p["template"]
    els: list[dict] = []
    n = 0

    def add(**kw):
        nonlocal n
        n += 1
        els.append({"id": f"e{n}", "behind": False, **kw})

    if t == "spotlight":  # its card, as a piece: the photo in it, the player breaking out of its top
        cy0, cy1 = max(u * 0.2, H * 0.14), H - u * 0.2
        add(type="card", x=0.5, y=(cy0 + cy1) / 2 / H, w=0.82, h=(cy1 - cy0) / H)
    if t == "final":
        add(type="box", x=0.5, y=(H - u * 0.18) / H, w=0.86, h=0.2, color="#0a0c10", opacity=0.66, accent=True)
    if t == "matchday":
        add(type="box", x=0.5, y=(u * 0.15) / H, w=1.1, h=0.2, color=p.get("color", "#1f2a44"), opacity=0.92, round=False, behind=True)
    if t == "cinematic":  # its letterbox bars
        add(type="box", x=0.5, y=0.05, w=1.1, h=0.1, color="#000000", opacity=0.94, round=False, behind=True)
        add(type="box", x=0.5, y=1 - max(0.17, u * 0.17 / H) / 2, w=1.1, h=max(0.17, u * 0.17 / H), color="#000000",
            opacity=0.94, round=False, behind=True)
    if t == "card":  # its nameplate
        add(type="box", x=0.5, y=(H - u * 0.1) / H, w=1.1, h=u * 0.2 / H, color=p.get("color", "#1f2a44"), opacity=0.95,
            round=False, behind=True)
    moves = p.get("moves") or {}
    seen = set()
    for w in words:
        k = w["key"]
        if k == "logo":  # (the logo is placed below, as its own piece)
            continue
        if k in seen:  # a word drawn in parts (a first name over a last name): one piece, the whole word
            continue
        seen.add(k)
        parts = [x for x in words if x["key"] == k]
        if len(parts) > 1:
            w = {**w, "x0": min(x["x0"] for x in parts), "x1": max(x["x1"] for x in parts),
                 "y0": (min(x["y0"] for x in parts) + max(x["y1"] for x in parts)) / 2 - (w["y1"] - w["y0"]) / 2,
                 "y1": (min(x["y0"] for x in parts) + max(x["y1"] for x in parts)) / 2 + (w["y1"] - w["y0"]) / 2}
        text = p.get(k, "")
        if k == "home_score":
            text = f"{p.get('home_score', '')}  –  {p.get('away_score', '')}"
        if not text:
            continue
        rows = str(text).count("\n") + 1  # (a word on several lines: its size is one line's)
        hpx = (w["y1"] - w["y0"]) * H / (1 + 1.12 * (rows - 1))
        size = max(0.015, hpx / 0.74 / u)
        own = (p.get("colors") or {}).get(k)
        if k == "number" and t in ("spotlight", "card"):
            add(type="badge", x=(w["x0"] + w["x1"]) / 2, y=(w["y0"] + w["y1"]) / 2, text=text, size=0.076, color=own or "")
            continue
        if k in ("title", "home_score", "name") or (t == "matchday" and k == "away") or size > 0.09:
            style = "bold" if size < 0.04 else "heavy"
        else:
            style = "clean" if k in ("line", "home", "away") else "bold"
        if t == "goal" and k == "title":
            style = "outline"
        color = own or ("#d4af37" if (t == "champions" and k == "title") or (t == "card" and k == "line") else "#ffffff")
        if t == "jersey" and k == "number":  # the giant number, in the team color, behind the player
            color, style = own or p.get("color", "#1f2a44"), "heavy"
        own = {k2: v for k2, v in (("angle", w.get("r") or (moves.get(k) or {}).get("r")), ("font", (moves.get(k) or {}).get("f"))) if v}
        add(type="text", x=(w["x0"] + w["x1"]) / 2, y=(w["y0"] + w["y1"]) / 2, text=text, style=style, size=round(size, 4),
            color=color, behind=(k == "title" and t in BEHIND_TITLE) or (t in ("jersey", "split") and k == "number"), **own)
    if t == "champions":
        line = next((w for w in words if w["key"] == "line"), None)
        if line:
            yy = (line["y0"] + line["y1"]) / 2
            for xx in (0.17, 0.83):
                add(type="rule", x=xx, y=yy, w=0.2, color=(p.get("colors") or {}).get("title", "#d4af37"))
    if p.get("logo"):  # where the layout had it
        from photo_presets.poster import LOGO_AT
        where = {"gameday": "br", "mvp": "br", **LOGO_AT}.get(t, "tl")
        lw = u * (0.088 if where == "bc" else 0.104)
        x = {"tl": 0.05 * W + lw / 2, "tr": W - 0.05 * W - lw / 2, "br": W - 0.05 * W - lw / 2,
             "band": W - 0.05 * W - lw / 2, "bc": W / 2}[where]
        y = {"tl": u * 0.035 + lw / 2, "tr": u * 0.035 + lw / 2, "br": H - u * 0.1, "band": u * 0.15,
             "bc": H - u * 0.045 - lw / 2}[where]
        add(type="logo", logo=p["logo"], x=x / W, y=y / H, size=round(lw / W, 4))
    return clean(els)
