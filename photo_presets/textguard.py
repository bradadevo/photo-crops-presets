"""Keeping AI drawings honest about text: no invented numbers or letters, and the
photo's real text (sponsor, crest, numbers) readable instead of garbled.

Image models cannot write: on a jersey they invent numbers that are not there
and turn a sponsor's name into gibberish, even when told not to. So after a
drawing is made, text is looked for in it and in the photo with the Mac's own
text detection (Apple Vision, free, on this Mac):
- text in the drawing where the photo has none was invented: it is painted
  out from the drawing around it;
- text in the photo is brought back from the photo, softly blended, so it reads
  as it really does (the look's later steps then paint it like the rest).
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

Box = tuple[int, int, int, int]


def find_text(img: np.ndarray) -> list[Box]:
    """Where text is (words, numbers, single letters), as pixel boxes. img: floats
    0-1 or uint8, (H, W, 3). Empty when Vision is not available."""
    try:
        import Vision
        from Foundation import NSData
    except ImportError:
        return []
    arr = img if img.dtype == np.uint8 else (np.clip(img, 0, 1) * 255).astype(np.uint8)
    h, w = arr.shape[:2]
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    boxes: list[Box] = []
    detect = Vision.VNDetectTextRectanglesRequest.alloc().init()
    detect.setReportCharacterBoxes_(False)
    read = Vision.VNRecognizeTextRequest.alloc().init()
    read.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    read.setUsesLanguageCorrection_(False)
    read.setMinimumTextHeight_(0.01)
    ok, _ = handler.performRequests_error_([detect, read], None)
    if not ok:
        return []
    for req in (detect, read):
        for ob in req.results() or []:
            r = ob.boundingBox()  # normalized, origin at the bottom left
            x0, y0 = r.origin.x * w, (1 - r.origin.y - r.size.height) * h
            x1, y1 = x0 + r.size.width * w, y0 + r.size.height * h
            boxes.append((int(max(0, x0)), int(max(0, y0)), int(min(w, x1)), int(min(h, y1))))
    return [b for b in boxes if b[2] - b[0] >= 3 and b[3] - b[1] >= 3]


def _overlaps(a: Box, b: Box, pad: float = 0.25) -> bool:
    px, py = (a[2] - a[0]) * pad, (a[3] - a[1]) * pad
    return not (a[2] + px < b[0] or b[2] < a[0] - px or a[3] + py < b[1] or b[3] < a[1] - py)


def _soft_box(shape, box: Box, grow: float, feather: float) -> np.ndarray:
    h, w = shape[:2]
    bw, bh = box[2] - box[0], box[3] - box[1]
    g = max(2, int(max(bw, bh) * grow))
    m = np.zeros((h, w), np.float32)
    m[max(0, box[1] - g):min(h, box[3] + g), max(0, box[0] - g):min(w, box[2] + g)] = 1
    f = max(1.0, min(bw, bh) * feather)
    return cv2.GaussianBlur(m, (0, 0), f)


def honest_text(drawn: np.ndarray, photo: np.ndarray, alpha: np.ndarray | None, look: np.ndarray | None = None,
                max_share: float = 0.35) -> tuple[np.ndarray, int, int]:
    """The drawing with invented text painted out and the photo's real text put
    back. drawn, photo: floats 0-1, (H, W, 3), the same part of the picture; text
    is found in the photo, and put back from look (the look underneath the drawing,
    so a black-and-white look gets it in black and white), else the photo.
    alpha: the players (text outside them is left alone). Boxes taller or wider
    than max_share of the part are not text on a kit and are left alone.
    Returns the drawing and how many invented and real pieces were handled."""
    h, w = drawn.shape[:2]

    def on_players(b: Box) -> bool:
        if (b[3] - b[1]) > max_share * h or (b[2] - b[0]) > max_share * w:
            return False
        if alpha is None:
            return True
        return float(alpha[b[1]:b[3], b[0]:b[2]].mean()) > 0.5

    real = [b for b in find_text(photo) if on_players(b)]
    seen = [b for b in find_text(drawn) if on_players(b)]
    invented = [b for b in seen if not any(_overlaps(b, r) for r in real)]
    out = drawn.copy()
    if invented:
        hole = np.zeros((h, w), np.uint8)
        for b in invented:
            g = max(2, int(max(b[2] - b[0], b[3] - b[1]) * 0.15))
            hole[max(0, b[1] - g):b[3] + g, max(0, b[0] - g):b[2] + g] = 255
        u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
        radius = max(3, int(np.sqrt(hole.mean() / 255 * h * w) * 0.05))
        filled = cv2.inpaint(u8, hole, radius, cv2.INPAINT_TELEA).astype(np.float32) / 255
        m = cv2.GaussianBlur(hole.astype(np.float32) / 255, (0, 0), 2.0)[..., None]
        out = out * (1 - m) + filled * m
    for b in real:
        m = _soft_box(out.shape, b, 0.12, 0.25)[..., None]
        if alpha is not None:
            m = m * np.clip(alpha, 0, 1)[..., None]
        out = out * (1 - m) + (photo if look is None else look) * m
    return out, len(invented), len(real)
