"""Delivering finished photos: sizes for Instagram and print, your name and
copyright in every file, and an optional watermark for client proofs.

Sizes crop to their shape around the players (never cutting into them when
the shape allows), then resize. Web sizes get a light output sharpening, as
pros do after shrinking a photo; print sizes are exact pixels at 300 ppi
(enlarged if the photo is smaller, which the export notes).

Credit (your name, copyright, contact) is written where Lightroom, Photo
Mechanic, Finder, Photos and print labs look: EXIF Artist and Copyright, and
XMP (Dublin Core creator and rights, IPTC creator contact).
"""

import json
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from photo_presets import enlarge

CONFIG = Path.home() / ".config" / "photo-crops-presets" / "delivery.json"
FONT = "/System/Library/Fonts/Avenir Next.ttc"  # index 0 is Bold, 5 Medium

FULL = "full"


@dataclass(frozen=True)
class Size:
    key: str
    label: str
    width: int  # pixels (for prints, the long or short side follows the photo; see target)
    height: int
    web: bool  # sharpen after shrinking
    portrait: bool | None = None  # fixed shape; None = turns to match the photo

    def target(self, w: int, h: int) -> tuple[int, int]:
        """The pixel size for a photo of w x h."""
        tw, th = self.width, self.height
        landscape = w > h if self.portrait is None else not self.portrait
        if landscape != (tw > th):
            tw, th = th, tw
        return tw, th


SIZES = {s.key: s for s in [
    Size("ig_portrait", "Instagram post 4:5 (1080 x 1350)", 1080, 1350, True, True),
    Size("ig_square", "Instagram square (1080 x 1080)", 1080, 1080, True, True),
    Size("ig_story", "Instagram story / reel cover 9:16 (1080 x 1920)", 1080, 1920, True, True),
    Size("wide", "Wide 16:9 for YouTube, X, Facebook (1920 x 1080)", 1920, 1080, True, False),
    Size("print_4x6", "Print 4 x 6 in (1200 x 1800, 300 ppi)", 1200, 1800, False),
    Size("print_5x7", "Print 5 x 7 in (1500 x 2100, 300 ppi)", 1500, 2100, False),
    Size("print_8x10", "Print 8 x 10 in (2400 x 3000, 300 ppi)", 2400, 3000, False),
    Size("print_11x14", "Print 11 x 14 in (3300 x 4200, 300 ppi)", 3300, 4200, False),
]}
SHORT = {"ig_portrait": "ig-4x5", "ig_square": "ig-square", "ig_story": "ig-story", "wide": "wide-16x9", "print_4x6": "4x6",
         "print_5x7": "5x7", "print_8x10": "8x10", "print_11x14": "11x14"}


def crop_box(w: int, h: int, aspect: float, focus: tuple[float, float],
             keep: tuple[float, float, float, float] | None = None) -> tuple[int, int, int, int]:
    """The largest box of this aspect (width / height) in a w x h photo,
    centered on the focus (shares), moved so it holds the keep box (shares:
    the players) whenever it is big enough to."""
    if w / h > aspect:
        cw, ch = round(h * aspect), h
    else:
        cw, ch = w, round(w / aspect)
    fx, fy = focus[0] * w, focus[1] * h
    x0, y0 = fx - cw / 2, fy - ch / 2
    if keep:
        kx0, ky0, kx1, ky1 = keep[0] * w, keep[1] * h, keep[2] * w, keep[3] * h
        if kx1 - kx0 <= cw:
            x0 = min(max(x0, kx1 - cw), kx0)
        if ky1 - ky0 <= ch:
            y0 = min(max(y0, ky1 - ch), ky0)
    x0 = int(round(min(max(x0, 0), w - cw)))
    y0 = int(round(min(max(y0, 0), h - ch)))
    return x0, y0, x0 + cw, y0 + ch


def sized(arr: np.ndarray, size: Size, focus: tuple[float, float],
          keep: tuple[float, float, float, float] | None = None) -> tuple[np.ndarray, float]:
    """The picture (floats 0-1) cropped and resized for this size, and how
    much it was enlarged (1 or less = no enlarging)."""
    h, w = arr.shape[:2]
    tw, th = size.target(w, h)
    x0, y0, x1, y1 = crop_box(w, h, tw / th, focus, keep)
    part = arr[y0:y1, x0:x1]
    grow = tw / (x1 - x0)
    out = enlarge.fit(part, (tw, th))  # (a real enlargement: the AI detail enlarger)
    if size.web and grow < 1:
        blur = cv2.GaussianBlur(out, (0, 0), 0.8)
        out = out + (out - blur) * 0.35
    return np.clip(out, 0, 1).astype(np.float32), grow


# Credit ------------------------------------------------------------------------------

@dataclass
class Credit:
    creator: str = ""
    copyright: str = ""  # empty: "© <year> <creator>"
    contact: str = ""  # email, website or handle

    def notice(self, year: int | None = None) -> str:
        if self.copyright.strip():
            return self.copyright.strip()
        if not self.creator.strip():
            return ""
        return f"© {year or datetime.now().year} {self.creator.strip()}"

    @property
    def empty(self) -> bool:
        return not (self.creator.strip() or self.copyright.strip() or self.contact.strip())

    def save(self) -> None:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls) -> "Credit":
        try:
            data = json.loads(CONFIG.read_text())
            return cls(**{k: str(v) for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()


def _ascii(text: str) -> str:
    """Text for EXIF, which only holds plain ASCII: © as (c), accents dropped."""
    import unicodedata
    text = text.replace("©", "(c)")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def credited_exif(exif: bytes | None, credit: Credit, year: int | None = None) -> bytes | None:
    """The photo's EXIF with your name (Artist) and copyright added (the
    full text, with ©, is in the XMP)."""
    if credit.empty:
        return exif
    data = Image.Exif()
    if exif:
        try:
            data.load(exif)
        except Exception:
            pass
    if credit.creator.strip():
        data[0x013B] = _ascii(credit.creator.strip())
    if credit.notice(year):
        data[0x8298] = _ascii(credit.notice(year))
    return data.tobytes()


def xmp(credit: Credit, year: int | None = None) -> bytes | None:
    """An XMP packet with your name, copyright and contact (Dublin Core,
    XMP Rights and IPTC Core, as Lightroom and Photo Mechanic write them)."""
    if credit.empty:
        return None
    creator, notice, contact = (escape(credit.creator.strip()), escape(credit.notice(year)),
                                escape(credit.contact.strip()))
    email = contact if "@" in contact and " " not in contact and not contact.startswith("@") else ""
    url = contact if contact and not email else ""
    parts = []
    if creator:
        parts.append(f"<dc:creator><rdf:Seq><rdf:li>{creator}</rdf:li></rdf:Seq></dc:creator>")
    if notice:
        parts.append(f'<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{notice}</rdf:li></rdf:Alt></dc:rights>')
        parts.append("<xmpRights:Marked>True</xmpRights:Marked>")
    if email or url:
        info = (f"<Iptc4xmpCore:CiEmailWork>{email}</Iptc4xmpCore:CiEmailWork>" if email else "") + \
               (f"<Iptc4xmpCore:CiUrlWork>{url}</Iptc4xmpCore:CiUrlWork>" if url else "")
        parts.append(f'<Iptc4xmpCore:CreatorContactInfo rdf:parseType="Resource">{info}'
                     "</Iptc4xmpCore:CreatorContactInfo>")
    body = "".join(parts)
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/" '
            'xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/">'
            f"{body}</rdf:Description></rdf:RDF></x:xmpmeta>"
            '<?xpacket end="w"?>').encode("utf-8")


# Watermark ---------------------------------------------------------------------------

CORNER, ACROSS = "corner", "across"


@dataclass
class Watermark:
    text: str
    style: str = CORNER  # "corner": small, bottom right; "across": large, repeated, for proofs
    opacity: float = 0.5
    extra: dict = field(default_factory=dict)


def _font(size: int, bold: bool = True):
    try:
        return ImageFont.truetype(FONT, size, index=0 if bold else 5)
    except OSError:
        return ImageFont.load_default(size)


def watermark(arr: np.ndarray, mark: Watermark) -> np.ndarray:
    """The picture (floats 0-1) with the watermark."""
    text = " ".join((mark.text or "").split())
    if not text:
        return arr
    h, w = arr.shape[:2]
    layer = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(layer)
    if mark.style == ACROSS:
        size = max(12, int(min(w, h) * 0.075))
        font = _font(size)
        tile = Image.new("L", (w * 2, h * 2), 0)
        tdraw = ImageDraw.Draw(tile)
        step_x = int(tdraw.textlength(text, font=font) + size * 2.5)
        step_y = int(size * 4)
        for row, y in enumerate(range(0, h * 2, step_y)):
            for x in range(-step_x + (row % 2) * step_x // 2, w * 2, step_x):
                tdraw.text((x, y), text, font=font, fill=255)
        tile = tile.rotate(30, resample=Image.BICUBIC)
        layer = tile.crop((w // 2, h // 2, w // 2 + w, h // 2 + h))
        alpha = np.asarray(layer, np.float32) / 255 * mark.opacity * 0.6
        return arr * (1 - alpha[..., None]) + alpha[..., None]
    lines = textwrap.wrap(text, 40)[:2]
    size = max(10, int(min(w, h) * 0.028))
    font = _font(size, bold=False)
    margin = int(min(w, h) * 0.03)
    gap = int(size * 1.2)
    y = h - margin - gap * len(lines)
    shadow = Image.new("L", (w, h), 0)
    sdraw = ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        x = w - margin - draw.textlength(line, font=font)
        sdraw.text((x + 1, y + i * gap + 2), line, font=font, fill=255)
        draw.text((x, y + i * gap), line, font=font, fill=255)
    a = np.asarray(layer, np.float32)[..., None] / 255 * mark.opacity * 1.6
    s = cv2.GaussianBlur(np.asarray(shadow, np.float32), (0, 0), max(1.0, size * 0.08))[..., None] / 255
    out = arr * (1 - np.clip(s * mark.opacity, 0, 1) * 0.6)
    return np.clip(out * (1 - np.clip(a, 0, 1)) + np.clip(a, 0, 1), 0, 1).astype(np.float32)
