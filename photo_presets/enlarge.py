"""Enlarging a tight crop without the soft, smeared look: the photo-trained Real-ESRGAN model (free,
runs on the Mac) draws the crop at 4x with clean edges in hair, skin, numbers and kit, then it's fitted
to the size asked for. A little of the plain enlargement is mixed back in so skin keeps its real
texture (no plastic look). Faces are never redrawn or invented: the model only sharpens what's there.

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
    with torch.no_grad():
        for y in range(0, h, TILE):
            for x in range(0, w, TILE):
                ya, xa = max(0, y - PAD), max(0, x - PAD)
                yb, xb = min(h, y + TILE + PAD), min(w, x + TILE + PAD)
                t = torch.from_numpy(np.ascontiguousarray(img[ya:yb, xa:xb, :3], np.float32)).permute(2, 0, 1)
                r = m(t[None].to(dev))[0].permute(1, 2, 0).clamp(0, 1).float().cpu().numpy()
                ye, xe = min(h, y + TILE), min(w, x + TILE)
                out[y * 4:ye * 4, x * 4:xe * 4] = r[(y - ya) * 4:(ye - ya) * 4, (x - xa) * 4:(xe - xa) * 4]
    return out


def fit(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """The picture (floats 0-1, RGB) at size (w, h). Shrinking or a small enlargement: plain resizing.
    A real enlargement: the AI detail enlarger (plain enlarging if it can't run)."""
    import cv2
    h, w = img.shape[:2]
    grow = max(size[0] / w, size[1] / h)
    plain = cv2.resize(img, size, interpolation=cv2.INTER_AREA if grow < 1 else cv2.INTER_LANCZOS4)
    plain = np.clip(plain, 0, 1).astype(np.float32)
    if not USE_AI or grow < MIN_GROW or w * h > MAX_PIXELS or img.ndim != 3 or img.shape[2] != 3:
        return plain
    try:
        big = ai_4x(img)
    except Exception:  # no model, no download, out of memory: plain enlarging still works
        return plain
    interp = cv2.INTER_AREA if big.shape[1] >= size[0] else cv2.INTER_LANCZOS4
    sharp = np.clip(cv2.resize(big, size, interpolation=interp), 0, 1)
    return ((1 - KEEP_REAL) * sharp + KEEP_REAL * plain).astype(np.float32)


def fit_pil(im, size: tuple[int, int]):
    """fit() for a PIL picture (RGB)."""
    from PIL import Image
    if im.size == tuple(size):
        return im
    arr = np.asarray(im.convert("RGB"), np.float32) / 255
    out = Image.fromarray((fit(arr, size) * 255).round().astype(np.uint8))
    return out.convert(im.mode) if im.mode != "RGB" else out
