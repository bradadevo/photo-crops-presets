"""The fonts any word can be set in (on the photo, in a layout, on a custom poster): the Mac's own,
picked for sports posters. The page shows the same faces (each served as its own font file), so what
you see while editing is what's exported. Also: drawing something turned to any angle.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFont

SYS = "/System/Library/Fonts/"
BRAND = str(Path(__file__).parent / "studio" / "web" / "fonts") + "/"  # VS Digital Pro's own (open fonts, in the app)
SUPP = SYS + "Supplemental/"

# key: (name shown, file, face index in it)
FONTS: dict[str, tuple[str, str, int]] = {
    "vs-display": ("VS Display", BRAND + "BigShouldersDisplay-900.ttf", 0),
    "vs-tech": ("VS Tech", BRAND + "ChakraPetch-700.ttf", 0),
    "avenir-heavy": ("Avenir Heavy", SYS + "Avenir Next.ttc", 8),
    "avenir-bold": ("Avenir Bold", SYS + "Avenir Next.ttc", 0),
    "avenir-light": ("Avenir Light", SYS + "Avenir Next.ttc", 10),
    "condensed": ("Condensed", SYS + "Avenir Next Condensed.ttc", 8),
    "sport-italic": ("Sport Italic", SYS + "Avenir Next Condensed.ttc", 9),
    "futura": ("Futura", SUPP + "Futura.ttc", 2),
    "futura-tall": ("Futura Tall", SUPP + "Futura.ttc", 4),
    "impact": ("Impact", SUPP + "Impact.ttf", 0),
    "din": ("DIN Condensed", SUPP + "DIN Condensed Bold.ttf", 0),
    "gill-light": ("Gill Sans Light", SUPP + "GillSans.ttc", 7),
    "rockwell": ("Varsity Slab", SUPP + "Rockwell.ttc", 2),
    "copperplate": ("Copperplate", SUPP + "Copperplate.ttc", 2),
    "didot": ("Didot", SUPP + "Didot.ttc", 2),
    "bodoni": ("Bodoni", SUPP + "Bodoni 72.ttc", 2),
    "baskerville": ("Baskerville Italic", SUPP + "Baskerville.ttc", 3),
    "script": ("Script", SUPP + "SnellRoundhand.ttc", 2),
    "brush": ("Brush Script", SUPP + "Brush Script.ttf", 0),
}


def name_ok(key) -> bool:
    return isinstance(key, str) and key in FONTS


def load(key: str | None, px: float) -> ImageFont.FreeTypeFont | None:
    """The font at px pixels (None when there's no such font, or this Mac doesn't have it)."""
    if not name_ok(key):
        return None
    _, path, index = FONTS[key]
    try:
        return ImageFont.truetype(path, max(6, int(px)), index=index)
    except OSError:
        return None


@lru_cache(maxsize=32)
def font_file(key: str) -> bytes | None:
    """The face as a font file of its own (a .ttc holds several), for the page to show it."""
    if not name_ok(key):
        return None
    _, path, index = FONTS[key]
    try:
        import logging
        logging.getLogger("fontTools").setLevel(logging.ERROR)  # (old Mac fonts' dates: harmless)
        from fontTools.ttLib import TTCollection, TTFont
        font = TTCollection(path).fonts[index] if path.endswith(".ttc") else TTFont(path)
        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue()
    except Exception:
        return None


def angle_ok(v, default: float = 0.0) -> float:
    """An angle in degrees, clockwise, between -180 and 180."""
    try:
        a = float(v)
    except (TypeError, ValueError):
        return default
    if a != a:  # (not a number)
        return default
    a = (a + 180.0) % 360.0 - 180.0
    return round(a, 1)


def turned(layer: Image.Image, angle: float, center: tuple[float, float]) -> Image.Image:
    """A clear RGBA layer turned clockwise by angle degrees around center (the same size)."""
    if not angle:
        return layer
    return layer.rotate(-angle, resample=Image.BICUBIC, center=center)
