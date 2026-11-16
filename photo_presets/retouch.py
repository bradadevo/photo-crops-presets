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
WORK_EDGE = 1280
CONTEXT = 1.0  # context around each area, as a multiple of its size
MIN_CONTEXT = 96
FEATHER = 3
GRAIN_BOOST = 1.2
CHROMA_GRAIN = 0.4
DETAIL_SIGMA = 5.0  # px: the texture borrowed is everything finer than this (grass blades, not the light)
SHARP_GROUND = 6.0  # texture strength (0-255) above which the ground is sharp enough to need it

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


def _match_seam(tile: np.ndarray, filled: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """The fill's light and color nudged to meet the photo around it, so no edge shows:
    the difference along a thin ring just outside the hole, spread smoothly inside it."""
    ring = (cv2.dilate(hole.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) & ~hole
    if ring.sum() < 20:
        return filled
    diff = (tile - filled) * ring[..., None]
    sigma = max(3.0, np.sqrt(hole.sum()) * 0.25)
    spread = cv2.GaussianBlur(diff, (0, 0), sigma)
    weight = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), sigma)[..., None]
    return filled + np.where(hole[..., None], spread / np.maximum(weight, 1e-3), 0)


def _high(a: np.ndarray, sigma: float = 1.4) -> np.ndarray:
    return a - cv2.GaussianBlur(a, (0, 0), sigma)


def _borrow_detail(tile: np.ndarray, filled: np.ndarray, hole: np.ndarray, seed: int = 0) -> np.ndarray:
    """The fill's fine texture (grass blades, gravel, leaves) sampled from the ground around
    the hole: the fill model gets shapes and light right but smooths fine texture, and made-up
    noise looks like noise. Patches of the photo's own fine detail are taken from nearby,
    never where a strong edge is (an arm, a line, a post), and blended keeping their strength."""
    ys, xs = np.nonzero(hole)
    if not len(ys):
        return filled
    th, tw = hole.shape
    bh = ys.max() - ys.min() + 1
    patch = int(np.clip(bh // 6, 16, 44)) // 2 * 2
    hp = _high(tile, DETAIL_SIGMA)
    reach = int(max(30, bh * 0.6))
    near = (cv2.dilate(hole.astype(np.uint8), np.ones((2 * reach + 1, 2 * reach + 1), np.uint8)) > 0) & ~(
        cv2.dilate(hole.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
    if near.sum() < patch * patch * 6:
        return filled
    # strong edges, judged a little blurred so grass blades do not count as edges
    lum = cv2.GaussianBlur(tile.mean(2), (0, 0), 3.0)
    edges = np.hypot(cv2.Sobel(lum, cv2.CV_32F, 1, 0), cv2.Sobel(lum, cv2.CV_32F, 0, 1))
    strong = (edges > np.percentile(edges[near], 93)).astype(np.float32)
    # patch corners: the patch is all nearby ground, with almost no strong edge in it
    in_near = cv2.boxFilter(near.astype(np.float32), -1, (patch, patch), anchor=(0, 0), normalize=True,
                            borderType=cv2.BORDER_CONSTANT)
    edgy = cv2.boxFilter(strong, -1, (patch, patch), anchor=(0, 0), normalize=True, borderType=cv2.BORDER_CONSTANT)
    # and about as busy as the typical ground here (no stand-out clumps on a soft background)
    energy = np.sqrt(cv2.boxFilter((hp ** 2).mean(2), -1, (patch, patch), anchor=(0, 0), normalize=True,
                                   borderType=cv2.BORDER_CONSTANT))
    ok = (in_near > 0.98) & (edgy < 0.03)
    if ok.sum() < 20:
        return filled
    typical = float(np.median(energy[ok]))
    if typical < SHARP_GROUND:  # soft, out-of-focus ground: the fill alone matches it
        return filled
    if np.percentile(energy[ok], 90) > 2.2 * typical:  # uneven texture: borrowing would show as patches
        return filled
    ok &= (energy > 0.6 * typical) & (energy < 2.0 * typical)
    oy, ox = np.nonzero(ok[: th - patch, : tw - patch])
    if len(oy) < 20:
        return filled
    rng = np.random.default_rng(seed)
    win = np.outer(np.hanning(patch + 2)[1:-1], np.hanning(patch + 2)[1:-1]).astype(np.float32)[..., None]
    detail = np.zeros_like(tile)
    weight = np.zeros((th, tw, 1), np.float32)
    step = patch // 2
    for y in range(max(0, ys.min() - step), min(th - patch, ys.max()) + 1, step):
        for x in range(max(0, xs.min() - step), min(tw - patch, xs.max()) + 1, step):
            if not hole[y:y + patch, x:x + patch].any():
                continue
            # from plain ground close by (grass gets coarser toward the camera)
            d = (oy - y) ** 2 + (ox - x) ** 2
            close = np.argpartition(d, min(40, len(d) - 1))[:40]
            k = close[rng.integers(len(close))]
            sy, sx = oy[k], ox[k]
            detail[y:y + patch, x:x + patch] += hp[sy:sy + patch, sx:sx + patch] * win
            weight[y:y + patch, x:x + patch] += win * win
    detail = detail / np.sqrt(np.maximum(weight, 1e-3))  # keeps the texture's strength where patches overlap
    have = float(np.sqrt((detail[hole] ** 2).mean()))
    detail *= min(1.0, 1.5 * typical / max(have, 1e-3))  # each patch keeps its own strength, within reason
    inside = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 1.5)[..., None]
    return filled - _high(filled, DETAIL_SIGMA) * inside + detail * inside


def fill(arr: np.ndarray, mask: np.ndarray, work_edge: int = WORK_EDGE) -> tuple[np.ndarray, np.ndarray]:
    """Every masked area of an RGB uint8 image filled. Returns the image and
    the weight each pixel was replaced with (0-1), to carry the change to a
    16-bit copy. Near the picture's edge the context is mirrored, so the fill
    has something to go on there too."""
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
        # mirrored context where the tile meets the picture's edge
        mt, mb, ml, mr = pad - (y - Y0), pad - (Y1 - y - bh), pad - (x - X0), pad - (X1 - x - bw)
        mt, mb, ml, mr = (max(0, min(v, s_ - 1)) for v, s_ in ((mt, tile.shape[0]), (mb, tile.shape[0]),
                                                               (ml, tile.shape[1]), (mr, tile.shape[1])))
        big = cv2.copyMakeBorder(tile, mt, mb, ml, mr, cv2.BORDER_REFLECT_101)
        big_hole = cv2.copyMakeBorder(hole.astype(np.uint8), mt, mb, ml, mr, cv2.BORDER_CONSTANT, value=0)
        if mt or mb or ml or mr:  # the mirrored hole is filled too (it would mirror the object back)
            big_hole = np.maximum(big_hole, cv2.copyMakeBorder(hole.astype(np.uint8), mt, mb, ml, mr,
                                                               cv2.BORDER_REFLECT_101))
        scale = min(1.0, work_edge / max(big.shape[:2]))
        th = max(8, int(big.shape[0] * scale) // 8 * 8)
        tw = max(8, int(big.shape[1] * scale) // 8 * 8)
        small = cv2.resize(big, (tw, th), interpolation=cv2.INTER_AREA)
        small_hole = cv2.resize(big_hole, (tw, th), interpolation=cv2.INTER_NEAREST) > 0
        small_hole = cv2.dilate(small_hole.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        done = cv2.resize(_run(small, small_hole), (big.shape[1], big.shape[0]), interpolation=cv2.INTER_CUBIC)
        filled = done[mt:mt + tile.shape[0], ml:ml + tile.shape[1]].astype(np.float32)
        filled = _match_seam(tile.astype(np.float32), filled, hole)
        filled = _borrow_detail(tile.astype(np.float32), filled, hole, seed=i)
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


# Understanding what to remove ---------------------------------------------------------------------

GROW = 0.035  # the edge taken with an object, as a share of its height (hair, motion blur, halo)


def people(img) -> list[np.ndarray]:
    """Each person's outline (bool, the image's size), from the people detector."""
    from photo_presets.scene import detector, TEAM, GOALIE, OPPONENT
    found, _ = detector().find(img, None, {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"})
    out = []
    for p in found:
        if p.mask is not None:
            out.append(cv2.resize(p.mask.astype(np.uint8), img.size, interpolation=cv2.INTER_NEAREST) > 0)
    return out


def _shadow(arr: np.ndarray, body: np.ndarray, others: np.ndarray) -> np.ndarray:
    """The cast shadow touching a person's feet (darker than the ground around it), so it goes with them."""
    h, w = body.shape
    ys, xs = np.nonzero(body)
    if not len(ys):
        return body
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    ph = y1 - y0 + 1
    X0, X1 = max(0, int(x0 - 1.6 * ph)), min(w, int(x1 + 1.6 * ph))
    Y0, Y1 = max(0, int(y1 - 0.15 * ph)), min(h, int(y1 + 0.35 * ph))
    if Y1 <= Y0 or X1 <= X0:
        return body
    lum = cv2.cvtColor(arr[Y0:Y1, X0:X1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    ground = cv2.medianBlur(lum.astype(np.uint8), 31 if min(lum.shape) > 40 else 3).astype(np.float32)
    dark = (lum < 0.7 * np.maximum(ground, 1)) & ~others[Y0:Y1, X0:X1]
    dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    feet = np.zeros_like(dark)
    fy = int(y1 - Y0)
    fx0, fx1 = int(x0 - X0), int(x1 - X0) + 1
    feet[max(0, fy - max(2, int(0.06 * ph))):fy + 2, max(0, fx0):fx1] = 1
    n, lab = cv2.connectedComponents(np.maximum(dark, feet))
    keep = set(np.unique(lab[feet > 0]).tolist()) - {0}
    if not keep:
        return body
    shadow = np.isin(lab, list(keep)) & (dark > 0)
    if shadow.sum() > 3 * body.sum():  # not a shadow: a dark patch of ground
        return body
    out = body.copy()
    out[Y0:Y1, X0:X1] |= shadow
    return out


def what_to_remove(img, strokes: list[dict], points: list[list[float]], protect: np.ndarray | None = None,
                   found: list[np.ndarray] | None = None, segment=None) -> np.ndarray:
    """What a removal takes (bool, the image's size): what was brushed, and for each click
    (and each person mostly brushed over) the whole person or object, its edge and its
    shadow. protect (the players kept, 0-1): never taken unless brushed over directly.
    found: the people's outlines (else detected); segment(img, x, y) -> bool: an object's
    outline (else SAM)."""
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    brush = stroke_mask(strokes, w, h)
    if found is None:
        found = people(img) if (points or brush.any()) else []
    everyone = np.zeros((h, w), bool)
    for m in found:
        everyone |= m
    picked = np.zeros((h, w), bool)
    objects = []
    for x, y in points:
        px, py = int(np.clip(x * w, 0, w - 1)), int(np.clip(y * h, 0, h - 1))
        hit = [m for m in found if m[max(0, py - 2):py + 3, max(0, px - 2):px + 3].any()]
        if hit:
            objects.append((min(hit, key=lambda m: m.sum()), True))  # the one in front, if two overlap
            continue
        obj = (segment or _segment)(img, x, y)
        if obj is not None and obj.any() and obj.sum() < 0.3 * w * h:
            objects.append((obj, False))
        else:  # nothing clear there (open grass, sky): a small patch
            disc = np.zeros((h, w), np.uint8)
            cv2.circle(disc, (px, py), max(4, int(0.02 * w)), 1, -1)
            objects.append((disc > 0, False))
    if brush.any():
        for m in found:  # a person mostly brushed over: all of them
            cover = (m & brush).sum()
            if cover and (cover > 0.35 * m.sum() or cover > 0.5 * brush.sum()):
                objects.append((m, True))
    for obj, person in objects:
        if person:
            obj = _shadow(arr, obj, everyone & ~obj)
        ys = np.nonzero(obj)[0]
        grow = max(3, int(GROW * (ys.max() - ys.min() + 1))) if len(ys) else 3
        picked |= cv2.dilate(obj.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1,) * 2)) > 0
    if protect is not None:
        keep = cv2.dilate((protect > 0.5).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        picked &= ~keep
    return picked | brush


def _segment(img, x: float, y: float) -> np.ndarray | None:
    from photo_presets.scene import segment
    m = segment(img, x, y, (img.height, img.width))
    return m > 0.5 if m is not None else None
