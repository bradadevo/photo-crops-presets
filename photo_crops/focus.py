"""Where the camera focused: read from the Sony maker note.

Sony stores the focus point as FocusLocation (tag 0x2027: frame width,
frame height, x, y). JPEG maker notes start with a "SONY DSC" header; ARW
maker notes do not. Other cameras, or files without it, give None.
"""

import struct
from pathlib import Path

FOCUS_LOCATION = 0x2027
EXIF_IFD = 0x8769
MAKER_NOTE = 0x927C
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 8: 2, 9: 4, 10: 8}


def _tiff(data: bytes) -> bytes:
    if data[:2] in (b"II", b"MM"):
        return data  # a TIFF-based RAW file
    i = data.find(b"Exif\0\0")
    if i < 0:
        raise ValueError("no EXIF")
    return data[i + 6:]


def _ifd(t: bytes, offset: int, e: str) -> dict[int, bytes]:
    count = struct.unpack(e + "H", t[offset:offset + 2])[0]
    out = {}
    for k in range(count):
        start = offset + 2 + 12 * k
        tag, typ, n, value = struct.unpack(e + "HHI4s", t[start:start + 12])
        size = TYPE_SIZES.get(typ, 1) * n
        out[tag] = value[:size] if size <= 4 else t[struct.unpack(e + "I", value)[0]:][:size]
    return out


def focus_point(path: Path, image_size: tuple[int, int]) -> tuple[float, float] | None:
    """The focus point in the loaded image's pixels, or None."""
    try:
        with open(path, "rb") as f:
            t = _tiff(f.read(4_000_000 if path.suffix.lower() in (".jpg", ".jpeg") else -1))
        e = "<" if t[:2] == b"II" else ">"
        ifd0 = _ifd(t, struct.unpack(e + "I", t[4:8])[0], e)
        exif = _ifd(t, struct.unpack(e + "I", ifd0[EXIF_IFD])[0], e)
        note = exif[MAKER_NOTE]
        start = t.find(note[:32])
        maker = _ifd(t, start + (12 if note.startswith(b"SONY") else 0), e)
        w, h, x, y = struct.unpack(e + "4H", maker[FOCUS_LOCATION][:8])
    except (OSError, ValueError, KeyError, struct.error):
        return None
    if not (w and h and 0 < x <= w and 0 < y <= h):
        return None
    return x * image_size[0] / w, y * image_size[1] / h
