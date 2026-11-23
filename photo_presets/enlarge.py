"""Enlarging a tight crop without the soft, smeared look: the photo-trained Real-ESRGAN model (free,
runs on the Mac) draws the crop at 4x with clean edges in hair, skin, numbers and kit, then it's fitted
to the size asked for. A little of the plain enlargement is mixed back in so skin keeps its real
texture (no plastic look). Faces are sharpened with the rest of the picture, from what's there: it
isn't a face generator and never invents features.

Used whenever an export makes a crop bigger than its own pixels (an Instagram size from a tight crop,
a print, or the culling's "enlarge" choice). Without the model (or past the size it can do in good
time), plain Lanczos enlarging is used, as before.
"""

from __future__ import annotations

import os

import numpy as np

MODEL = "RealESRGAN_x4plus.pth"  # BSD-3 licence, photo-trained
MODEL_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/" + MODEL
USE_AI = os.environ.get("VSDP_AI_ENLARGE", "1") != "0"  # (tests switch it off)
MIN_GROW = 1.15  # smaller enlargements: plain resizing is already clean
MAX_PIXELS = 4_000_000  # bigger crops: plain enlarging (the model would take minutes)
KEEP_REAL = 0.2  # share of the plain enlargement mixed back in (real skin texture)
TILE, PAD = 384, 16

_model = None


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _load():
    global _model
    if _model is None:
        import spandrel
        from photo_crops.people import CACHE_DIR
        path = CACHE_DIR / MODEL
        if not path.exists():
            import urllib.request
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(MODEL_URL, tmp)
            tmp.rename(path)
        _model = spandrel.ModelLoader().load_from_file(str(path)).to(_device()).eval()
    return _model


def ai_4x(img: np.ndarray) -> np.ndarray:
    """The picture (floats 0-1, RGB) at 4x by the model, in tiles (overlapped, so no seams)."""
    import torch
    m, dev = _load(), _device()
    h, w = img.shape[:2]
    out = np.zeros((h * 4, w * 4, 3), np.float32)
    half = dev == "mps"  # (half precision on the Mac's graphics chip: 1.6x faster, the same picture to within 3/255)
    m = m.half() if half else m.float()
    with torch.no_grad():
        for y in range(0, h, TILE):
            for x in range(0, w, TILE):
                ya, xa = max(0, y - PAD), max(0, x - PAD)
                yb, xb = min(h, y + TILE + PAD), min(w, x + TILE + PAD)
                t = torch.from_numpy(np.ascontiguousarray(img[ya:yb, xa:xb, :3], np.float32)).permute(2, 0, 1)[None].to(dev)
                r = m(t.half() if half else t)[0].permute(1, 2, 0).clamp(0, 1).float().cpu().numpy()
                ye, xe = min(h, y + TILE), min(w, x + TILE)
                out[y * 4:ye * 4, x * 4:xe * 4] = r[(y - ya) * 4:(ye - ya) * 4, (x - xa) * 4:(xe - xa) * 4]
    return out


def fit(img: np.ndarray, size: tuple[int, int], report: list | None = None) -> np.ndarray:
    """The picture (floats 0-1, RGB) at size (w, h). Shrinking or a small enlargement: plain resizing.
    A real enlargement: the AI detail enlarger (plain enlarging if it can't run). report, when given,
    gets {"grow", "ai", "why"} for any enlargement, so the export can say what was done."""
    import cv2
    h, w = img.shape[:2]
    grow = max(size[0] / w, size[1] / h)
    plain = cv2.resize(img, size, interpolation=cv2.INTER_AREA if grow < 1 else cv2.INTER_LANCZOS4)
    plain = np.clip(plain, 0, 1).astype(np.float32)
    def note(ai: bool, why: str = ""):
        if report is not None and grow > 1.05:
            report.append({"grow": round(grow, 2), "ai": ai, "why": why})

    why = ("only slightly enlarged: plain enlarging is already clean" if grow < MIN_GROW
           else "a large crop: plain enlarging (the AI would take minutes)" if w * h > MAX_PIXELS
           else "the AI enlarger is switched off" if not USE_AI
           else "" if img.ndim == 3 and img.shape[2] == 3 else "not a color picture")
    if why:
        note(False, why)
        return plain
    try:
        big = ai_4x(img)
    except Exception:  # no model, no download, out of memory: plain enlarging still works
        note(False, "the AI enlarger couldn't run on this Mac")
        return plain
    interp = cv2.INTER_AREA if big.shape[1] >= size[0] else cv2.INTER_LANCZOS4
    sharp = np.clip(cv2.resize(big, size, interpolation=interp), 0, 1)
    note(True)
    return ((1 - KEEP_REAL) * sharp + KEEP_REAL * plain).astype(np.float32)


def fit_pil(im, size: tuple[int, int], report: list | None = None):
    """fit() for a PIL picture (RGB)."""
    from PIL import Image
    if im.size == tuple(size):
        return im
    arr = np.asarray(im.convert("RGB"), np.float32) / 255
    out = Image.fromarray((fit(arr, size, report) * 255).round().astype(np.uint8))
    return out.convert(im.mode) if im.mode != "RGB" else out


def summary(items: list[dict]) -> str:
    """One plain line on what an export enlarged, and how ("" when nothing was enlarged)."""
    if not items:
        return ""
    ai = [x for x in items if x["ai"]]
    plain = [x for x in items if not x["ai"]]
    parts = []
    if ai:
        top = max(ai, key=lambda x: x["grow"])
        parts.append(f"AI detail enlarger sharpened {len(ai)} file{'s' if len(ai) != 1 else ''} "
                     f"(up to {top['grow']:.1f}x: {top['photo']}, {top['size']})")
    if plain:
        whys = sorted({x["why"] for x in plain})
        parts.append(f"{len(plain)} enlarged the plain way ({'; '.join(whys)})")
    return ". ".join(parts)
