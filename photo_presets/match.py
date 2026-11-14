"""Matching a game: every photo's exposure and white balance evened out to
one reference photo, so a gallery looks like one shoot, not changing light.

Each photo is measured on its own (before any look): its middle brightness,
and the color cast of its near-neutral tones (white kits, lines, haze, clouds;
a green field or a blue sky does not count). The correction is applied before
the look, as a recipe's "match" ({"stops": s, "gains": [r, g, b]}), so the look
then treats every photo alike. It is deliberately gentle (most of the
difference, within limits): content changes brightness too (more sky, a dark
crowd), so the aim is to even out the light, not to force every frame to one
number.
"""

import math

import numpy as np
from PIL import Image

STRENGTH = 0.75  # the share of the measured difference that is corrected
MAX_STOPS = 0.75
MAX_GAIN = 0.08  # each color channel moves at most 8%
NEUTRAL_SAT = 0.18  # near-neutral: colors this close to gray
MIN_NEUTRAL = 0.01  # share of the photo that must be near-neutral to judge its white balance


def measure(img: Image.Image) -> dict:
    """A photo's middle brightness and its near-neutral color (r, g, b, as shares of their mean)."""
    small = img.convert("RGB").copy()
    small.thumbnail((512, 512))
    a = np.asarray(small, np.float32) / 255
    luma = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    lit = luma < 0.97
    median = float(np.median(luma[lit])) if lit.any() else float(np.median(luma))
    hi, lo = a.max(axis=2), a.min(axis=2)
    sat = (hi - lo) / np.maximum(hi, 1e-3)
    neutral = (sat < NEUTRAL_SAT) & (luma > 0.2) & (luma < 0.92)
    cast = None
    if neutral.mean() >= MIN_NEUTRAL:
        rgb = a[neutral].mean(axis=0)
        cast = (rgb / rgb.mean()).tolist()
    return {"median": max(median, 0.01), "cast": cast}


def correction(reference: dict, photo: dict) -> dict | None:
    """The match taking photo toward reference, or None when they already agree."""
    stops = float(np.clip(math.log2(reference["median"] / photo["median"]) * STRENGTH, -MAX_STOPS, MAX_STOPS))
    gains = [1.0, 1.0, 1.0]
    if reference["cast"] and photo["cast"]:
        raw = np.array(reference["cast"]) / np.array(photo["cast"])
        raw = 1 + (raw - 1) * STRENGTH
        raw = raw / (raw @ np.array([0.299, 0.587, 0.114]))  # keep the brightness; only the color moves
        gains = np.clip(raw, 1 - MAX_GAIN, 1 + MAX_GAIN).round(4).tolist()
    if abs(stops) < 0.03 and max(abs(g - 1) for g in gains) < 0.005:
        return None
    return {"stops": round(stops, 3), "gains": gains}


def apply(arr: np.ndarray, match: dict | None) -> np.ndarray:
    """The picture (floats 0-1) with a match applied; highlights roll off instead of clipping."""
    if not match:
        return arr
    out = arr * np.asarray(match.get("gains", [1, 1, 1]), np.float32) * 2 ** float(match.get("stops", 0))
    out = np.where(out > 0.9, 0.9 + 0.1 * np.tanh((out - 0.9) / 0.1), out)
    return np.clip(out, 0, 1).astype(np.float32)


def mean_difference(images: list[Image.Image]) -> float:
    """How far apart the photos' middle brightness is (in stops, mean from their median): for reports."""
    m = [math.log2(measure(i)["median"]) for i in images]
    return float(np.mean(np.abs(np.array(m) - np.median(m)))) if m else 0.0

