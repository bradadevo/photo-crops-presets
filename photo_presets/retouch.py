"""Removing distractions from a photo (a bottle, a pole, a parent on the
sideline) with LaMa, a free object-removal model, run on this Mac.

You brush over what should go; LaMa fills it from its surroundings. Each
removal is a list of brush strokes in shares of the photo, so it applies to
the full-size photo (and its 16-bit copy) whatever size you brushed it at.
The photo is cleaned before anything else, so every look, crop and export
of it is made from the clean photo.

LaMa works best at a moderate size, so each area is cleaned in a tile with
plenty of context, at most WORK_EDGE pixels, then scaled back and given grain
matching the photo around it (from ai-versions' inpaint.py).
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import numpy as np

CACHE_DIR = Path.home() / ".cache" / "photo-crops"
LAMA_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
LAMA_FILE = CACHE_DIR / "big-lama.pt"
SHARED = Path.home() / ".cache" / "ai-versions" / "big-lama.pt"  # already downloaded by ai-versions
WORK_EDGE = 1024
CONTEXT = 1.0  # context around each area, as a multiple of its size
MIN_CONTEXT = 96
FEATHER = 3
GRAIN_BOOST = 1.2
CHROMA_GRAIN = 0.4

_model = None


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _lama():
    global _model
    if _model is None:
        import torch
        path = LAMA_FILE if LAMA_FILE.exists() else SHARED if SHARED.exists() else None
        if path is None:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = LAMA_FILE.with_suffix(".part")
            urllib.request.urlretrieve(LAMA_URL, tmp)  # about 200 MB, once
            tmp.rename(LAMA_FILE)
            path = LAMA_FILE
        _model = torch.jit.load(str(path), map_location=_device()).eval()
    return _model


def _run(tile: np.ndarray, mask: np.ndarray) -> np.ndarray:
    import torch
    dev = _device()
    image = torch.from_numpy(tile).permute(2, 0, 1)[None].float().to(dev) / 255
    hole = torch.from_numpy(mask.astype(np.float32))[None, None].to(dev)
    with torch.no_grad():
        out = _lama()(image, hole)
    return (out[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)


def _high_pass(a: np.ndarray) -> np.ndarray:
    return a - cv2.GaussianBlur(a, (0, 0), 2)


def _add_grain(filled: np.ndarray, original: np.ndarray, hole: np.ndarray, seed: int) -> np.ndarray:
    ring = (cv2.dilate(hole.astype(np.uint8), np.ones((61, 61), np.uint8)) > 0) & ~hole
    if not ring.any() or not hole.any():
        return filled
    target = float(_high_pass(original)[ring].std())
    have = float(_high_pass(filled)[hole].std())
    extra = np.sqrt(max(target ** 2 - have ** 2, 0.0))
    if extra < 0.5:
        return filled
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, filled.shape[:2])[..., None] + CHROMA_GRAIN * rng.normal(0, 1, filled.shape)
    noise = noise.astype(np.float32)
    noise -= cv2.GaussianBlur(noise, (0, 0), 1.2)
    noise *= GRAIN_BOOST * extra / max(float(noise.std()), 1e-6)
    return np.clip(filled + noise, 0, 255)


def fill(arr: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Every masked area of an RGB uint8 image filled. Returns the image and
    the weight each pixel was replaced with (0-1), to carry the change to a
    16-bit copy."""
    out = arr.copy()
    h, w = mask.shape
    weights = np.zeros((h, w), np.float32)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    for i in range(1, count):
        x, y, bw, bh = stats[i, :4]
        pad = max(MIN_CONTEXT, int(CONTEXT * max(bw, bh)))
        X0, Y0, X1, Y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
        tile = out[Y0:Y1, X0:X1]
        hole = labels[Y0:Y1, X0:X1] == i
        scale = min(1.0, WORK_EDGE / max(tile.shape[:2]))
        th = max(8, int(tile.shape[0] * scale) // 8 * 8)
        tw = max(8, int(tile.shape[1] * scale) // 8 * 8)
        small = cv2.resize(tile, (tw, th), interpolation=cv2.INTER_AREA)
        small_hole = cv2.resize(hole.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST) > 0
        small_hole = cv2.dilate(small_hole.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        filled = cv2.resize(_run(small, small_hole), (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_CUBIC)
        filled = _add_grain(filled.astype(np.float32), tile.astype(np.float32), hole, seed=i)
        weight = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), FEATHER)
        weight = np.maximum(weight, hole.astype(np.float32))
        out[Y0:Y1, X0:X1] = np.clip(tile * (1 - weight[..., None]) + filled * weight[..., None], 0, 255).astype(np.uint8)
        weights[Y0:Y1, X0:X1] = np.maximum(weights[Y0:Y1, X0:X1], weight)
    return out, weights


def stroke_mask(strokes: list[dict], w: int, h: int) -> np.ndarray:
    """Brush strokes ({"pts": [[x, y], ...], "r": radius}, all shares of the
    photo's width and height; r of its width) as a mask of w x h."""
    mask = np.zeros((h, w), np.uint8)
    for s in strokes:
        pts = np.array([[p[0] * w, p[1] * h] for p in s.get("pts", [])], np.float32)
        if not len(pts):
            continue
        r = max(1, int(round(float(s.get("r", 0.02)) * w)))
        if len(pts) == 1:
            cv2.circle(mask, tuple(int(v) for v in pts[0]), r, 1, -1, cv2.LINE_AA)
        else:
            cv2.polylines(mask, [pts.astype(np.int32)], False, 1, thickness=2 * r, lineType=cv2.LINE_AA)
            for p in (pts[0], pts[-1]):
                cv2.circle(mask, tuple(int(v) for v in p), r, 1, -1, cv2.LINE_AA)
    return mask > 0


def apply(photo, removals: list[list[dict]]):
    """The photo (photo_crops.images.Photo) with each removal filled in, in order."""
    if not removals:
        return photo
    from PIL import Image
    arr = np.asarray(photo.image.convert("RGB")).copy()
    fine = None if photo.fine is None else photo.fine.astype(np.float32)
    h, w = arr.shape[:2]
    for strokes in removals:
        mask = stroke_mask(strokes, w, h)
        if not mask.any():
            continue
        arr, weight = fill(arr, mask)
        if fine is not None:
            fh, fw = fine.shape[:2]
            wgt = weight if (fh, fw) == (h, w) else cv2.resize(weight, (fw, fh), interpolation=cv2.INTER_LINEAR)
            src = arr if (fh, fw) == (h, w) else cv2.resize(arr, (fw, fh), interpolation=cv2.INTER_CUBIC)
            fine = fine * (1 - wgt[..., None]) + src.astype(np.float32) * 257.0 * wgt[..., None]
    photo.image = Image.fromarray(arr)
    if fine is not None:
        photo.fine = np.clip(fine, 0, 65535).astype(np.uint16)
    return photo
