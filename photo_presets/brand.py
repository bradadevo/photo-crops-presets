"""Your brand kit: logos (a team crest, a sponsor, your own photography mark) kept
ready to put on pictures.

A logo can arrive any way: a PNG with a clear background, a JPG on white, or a
screenshot of it. Its background is taken away: kept when the file already has
one clear, keyed out when it sits on a plain color (the soft, anti-aliased edge
cleaned of that color), else cut out like a player. Then it is trimmed to its
edges. On a picture it is placed by its middle (shares of the picture), its
width a share of the picture's width, and shown as it is, in white or black, or
"auto": a one-color mark white on a dark spot and black on a light one, a crest
as it is.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

COLORS = ("auto", "original", "white", "black")
CLEAR = 0.05  # a share of the logo's pixels clear enough: it already has a transparent background
PLAIN = 0.06  # how alike the edge must be (0-1) to count as a plain background color


def folder(base: Path) -> Path:
    d = base / "logos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def listing(base: Path) -> list[dict]:
    out = []
    for meta in sorted(folder(base).glob("*.json")):
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        if (meta.with_suffix(".png")).exists():
            if "flat" not in data:
                data["flat"] = flat(Image.open(meta.with_suffix(".png")).convert("RGBA"))
            out.append(data)
    return out


def flat(logo: Image.Image) -> bool:
    """A one-color mark (lettering, a silhouette): fine all white or all black. A crest
    with its own light and dark parts is not: made one color it would be a blank shape."""
    small = logo.copy()
    small.thumbnail((256, 256))
    a = np.asarray(small).astype(np.float32) / 255
    solid = a[..., 3] > 0.8
    if solid.sum() < 20:
        return True
    lum = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    colors = a[..., :3][solid]
    return float(lum[solid].std()) < 0.12 and float(colors.std(0).max()) < 0.12  # one shade and one color


DRAW_EDGE = 2400  # a drawn logo (SVG, PDF, Illustrator) is made this many pixels on its long side
FILE_TYPES = ".png .jpg .jpeg .webp .heic .gif .tif .tiff .bmp .svg .svgz .pdf .ai"


class NotALogo(ValueError):
    """The file could not be read as a logo (the message says what to use instead)."""


def open_any(data: bytes, filename: str = "") -> Image.Image:
    """A logo file of any kind as a picture: a photo format, or drawn (SVG, PDF, an Illustrator
    .ai file), drawn sharp at DRAW_EDGE px with its clear background kept."""
    name = filename.lower()
    head = data[:512].lstrip()
    if name.endswith((".svg", ".svgz")) or head.startswith((b"<svg", b"<?xml")) or data[:2] == b"\x1f\x8b" and name.endswith(".svgz"):
        return _svg(data)
    if data[:5] == b"%PDF-" or name.endswith((".pdf", ".ai")):
        return _pdf(data)
    if name.endswith((".eps", ".ps")) or data[:4] in (b"%!PS", b"\xc5\xd0\xd3\xc6"):
        raise NotALogo("EPS files can't be read here. Save the logo as SVG, PDF or PNG and add that instead.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception:
        raise NotALogo("That file is not a picture. Use a PNG, JPG, SVG, PDF or a screenshot of the logo.")


def _svg(data: bytes) -> Image.Image:
    import gzip
    import resvg_py
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    text = data.decode("utf-8", errors="replace")
    try:
        first = bytes(resvg_py.svg_to_bytes(svg_string=text))
        w, h = Image.open(io.BytesIO(first)).size
        side = {"width": DRAW_EDGE} if w >= h else {"height": DRAW_EDGE}
        img = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=text, **side))))
        img.load()
    except Exception:
        raise NotALogo("That SVG could not be drawn. Try saving it again as SVG, PDF or PNG.")
    return img.convert("RGBA")


def _pdf(data: bytes) -> Image.Image:
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(data)
        page = doc[0]
        w, h = page.get_size()
        scale = DRAW_EDGE / max(w, h, 1)
        img = page.render(scale=scale, fill_color=(0, 0, 0, 0), may_draw_forms=True).to_pil()
    except Exception:
        raise NotALogo("That PDF or Illustrator file could not be read. Save it with PDF compatibility on, "
                       "or as SVG or PNG.")
    return img.convert("RGBA")


def transparent(img: Image.Image) -> Image.Image:
    """The logo with its background taken away and trimmed to its edges (RGBA)."""
    rgba = img.convert("RGBA")
    a = np.asarray(rgba).astype(np.float32) / 255
    if (a[..., 3] < 0.9).mean() > CLEAR:  # already has a clear background
        return _trim(rgba)
    rgb = a[..., :3]
    h, w = rgb.shape[:2]
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(edge, axis=0)
    if np.abs(edge - bg).max(1).mean() < PLAIN:  # a plain background: key it out
        dist = np.abs(rgb - bg).max(2)
        alpha = np.clip((dist - 0.04) / 0.18, 0, 1)
        # the soft edge pixels hold some background: take it back out of their color
        safe = np.maximum(alpha, 1e-3)[..., None]
        fg = np.clip((rgb - (1 - alpha[..., None]) * bg) / safe, 0, 1)
        out = np.dstack([fg, alpha])
        return _trim(Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA"))
    from rembg import remove  # a busy background: cut the logo out
    from photo_presets.scene import MODEL_LOCK, _let_go_later, _session
    with MODEL_LOCK:  # (the players' cut-out model: one at a time)
        mask = np.asarray(remove(img.convert("RGB"), session=_session(), only_mask=True), np.float32) / 255
    _let_go_later()  # (its 10 GB back to the Mac a minute later)
    out = np.dstack([rgb, mask])
    return _trim(Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA"))


def _trim(img: Image.Image) -> Image.Image:
    a = np.asarray(img)[..., 3]
    ys, xs = np.nonzero(a > 8)
    if not len(ys):
        return img
    pad = max(2, int(0.02 * max(img.size)))
    box = (max(0, xs.min() - pad), max(0, ys.min() - pad), min(img.width, xs.max() + 1 + pad),
           min(img.height, ys.max() + 1 + pad))
    return img.crop(box)


def add(base: Path, img: Image.Image, name: str) -> dict:
    """A new logo in the kit: made transparent, kept as PNG with its name."""
    logo = transparent(img)
    logo.thumbnail((2400, 2400))
    lid = uuid.uuid4().hex[:10]
    d = folder(base)
    logo.save(d / f"{lid}.png")
    meta = {"id": lid, "name": name, "width": logo.width, "height": logo.height, "flat": flat(logo)}
    (d / f"{lid}.json").write_text(json.dumps(meta))
    return meta


def remove_logo(base: Path, lid: str) -> None:
    """Taken out of the kit, kept aside (so Undo can bring it back)."""
    aside = folder(base) / ".removed"
    aside.mkdir(exist_ok=True)
    for ext in (".png", ".json"):
        p = folder(base) / f"{lid}{ext}"
        if p.exists():
            p.replace(aside / p.name)


def restore_logo(base: Path, lid: str) -> bool:
    aside = folder(base) / ".removed"
    back = False
    for ext in (".png", ".json"):
        p = aside / f"{lid}{ext}"
        if p.exists():
            p.replace(folder(base) / p.name)
            back = True
    return back


def load(base: Path, lid: str) -> Image.Image | None:
    p = folder(base) / f"{lid}.png"
    return Image.open(p).convert("RGBA") if p.exists() else None


def colored(logo: Image.Image, color: str) -> Image.Image:
    """The logo as it is, or all white, or all black (its shape kept)."""
    if color not in ("white", "black"):
        return logo
    a = np.asarray(logo)
    v = 255 if color == "white" else 0
    alpha = a[..., 3]
    if not flat(logo):  # a crest with its own light and dark parts: one color, the light parts see-through
        rgb = a[..., :3].astype(np.float32) / 255
        lum = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
        ink = np.clip((0.82 - lum) / 0.5, 0, 1)  # dark ink solid, white parts clear
        alpha = (alpha.astype(np.float32) * ink + 0.5).astype(np.uint8)
    out = np.dstack([np.full(a.shape[:2] + (3,), v, np.uint8), alpha])
    return Image.fromarray(out, "RGBA")


def auto_color(arr: np.ndarray, box: tuple[int, int, int, int]) -> str:
    """White on a dark spot of the picture, black on a light one."""
    x0, y0, x1, y1 = box
    spot = arr[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
    if not spot.size:
        return "white"
    lum = float((spot[..., 0] * 0.299 + spot[..., 1] * 0.587 + spot[..., 2] * 0.114).mean())
    return "black" if lum > 0.62 else "white"


def draw(arr: np.ndarray, placements: list[dict] | None, base: Path) -> np.ndarray:
    """The logos placed on the picture (floats 0-1): {"id", "x", "y" (its middle, shares),
    "size" (its width, a share of the picture's width), "color", "opacity"}."""
    if not placements:
        return arr
    h, w = arr.shape[:2]
    out = arr.astype(np.float32)
    for pl in placements:
        logo = load(base, pl.get("id", ""))
        if logo is None:
            continue
        lw = max(4, int(float(pl.get("size", 0.16)) * w))
        lh = max(1, round(lw * logo.height / logo.width))
        x0 = int(round(float(pl.get("x", 0.85)) * w - lw / 2))
        y0 = int(round(float(pl.get("y", 0.88)) * h - lh / 2))
        color = pl.get("color", "auto")
        if color == "auto":  # a crest shows as it is; a one-color mark goes white or black to read
            color = auto_color(out, (x0, y0, x0 + lw, y0 + lh)) if flat(logo) else "original"
        art = np.asarray(colored(logo, color).resize((lw, lh), Image.LANCZOS)).astype(np.float32) / 255
        # the part of the logo inside the picture
        X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(w, x0 + lw), min(h, y0 + lh)
        if X1 <= X0 or Y1 <= Y0:
            continue
        piece = art[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
        a = piece[..., 3:4] * float(np.clip(pl.get("opacity", 1.0), 0, 1))
        out[Y0:Y1, X0:X1] = out[Y0:Y1, X0:X1] * (1 - a) + piece[..., :3] * a
    return np.clip(out, 0, 1)


def clean(placements) -> list[dict]:
    out = []
    for pl in placements or []:
        if not pl.get("id"):
            continue
        out.append({"id": str(pl["id"])[:20], "x": float(np.clip(float(pl.get("x", 0.85)), -0.2, 1.2)),
                    "y": float(np.clip(float(pl.get("y", 0.88)), -0.2, 1.2)),
                    "size": float(np.clip(float(pl.get("size", 0.16)), 0.02, 0.9)),
                    "color": pl.get("color") if pl.get("color") in COLORS else "auto",
                    "opacity": float(np.clip(float(pl.get("opacity", 1.0)), 0.05, 1.0))})
    return out[:6]


CORNERS = {"br": (0.88, 0.9), "bl": (0.12, 0.9), "tr": (0.88, 0.1), "tl": (0.12, 0.1), "bc": (0.5, 0.9)}


def corner_place(corner: str, size: float, logo_aspect: float, pic_w: int, pic_h: int) -> tuple[float, float]:
    """Where a logo's middle goes to sit in a corner with a margin (shares of the picture)."""
    margin = 0.035
    lw = size
    lh = size * pic_w / pic_h / max(logo_aspect, 1e-3)  # its height as a share of the picture's height
    cx = {"l": margin + lw / 2, "r": 1 - margin - lw / 2, "c": 0.5}[corner[1]]
    cy = {"t": margin * pic_w / pic_h + lh / 2, "b": 1 - margin * pic_w / pic_h - lh / 2}[corner[0]]
    return cx, cy
