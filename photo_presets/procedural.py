"""Textures generated on this Mac: grit, grain, scratches, smoke, paper, dust.

Each is a gray image (H, W) in 0-1 centered on mid-gray where it should do
nothing in overlay-style blends, and is the same for the same seed.
"""

import cv2
import numpy as np


def _noise(rng: np.random.Generator, h: int, w: int, scale: float) -> np.ndarray:
    """Smooth noise with features about `scale` pixels across."""
    sh, sw = max(2, int(h / scale)), max(2, int(w / scale))
    small = rng.random((sh, sw)).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def fractal(rng: np.random.Generator, h: int, w: int, base: float, octaves: int = 5) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for i in range(octaves):
        out += amp * _noise(rng, h, w, max(2.0, base / 2 ** i))
        total += amp
        amp *= 0.5
    out /= total
    return (out - out.min()) / max(float(out.max() - out.min()), 1e-6)


def _normalize(t: np.ndarray) -> np.ndarray:
    return np.clip(0.5 + (t - t.mean()) / max(float(t.std()) * 4, 1e-6), 0, 1).astype(np.float32)


def grain(rng, h, w):
    g = rng.normal(0, 1, (h, w)).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 0.7)
    return _normalize(g)


def grit(rng, h, w):
    """Speckled, uneven wear: coarse blotches plus sharp specks."""
    blotch = fractal(rng, h, w, max(h, w) / 6)
    specks = (rng.random((h, w)) > 0.985).astype(np.float32)
    specks = cv2.GaussianBlur(specks, (0, 0), 0.8) * 3
    t = 0.6 * blotch + 0.4 * (1 - np.clip(specks, 0, 1)) + 0.15 * rng.normal(0, 1, (h, w))
    return _normalize(t)


def scratches(rng, h, w):
    t = np.full((h, w), 0.5, np.float32)
    for _ in range(int(25 + rng.integers(0, 40))):
        x0, y0 = int(rng.integers(0, w)), int(rng.integers(0, h))
        angle = rng.normal(np.pi / 2, 0.25)
        length = rng.uniform(0.1, 0.6) * h
        x1, y1 = int(x0 + np.cos(angle) * length), int(y0 + np.sin(angle) * length)
        shade = float(rng.choice([0.15, 0.85]))
        cv2.line(t, (x0, y0), (x1, y1), shade, max(1, int(rng.integers(1, 3) * max(h, w) / 2000)), cv2.LINE_AA)
    return cv2.GaussianBlur(t, (0, 0), 0.6)


def smoke(rng, h, w):
    s = fractal(rng, h, w, max(h, w) / 3, octaves=6)
    s = cv2.GaussianBlur(s, (0, 0), max(h, w) / 300)
    return np.clip(s ** 1.6 * 1.3, 0, 1).astype(np.float32)


def paper(rng, h, w):
    fibers = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), sigmaX=6, sigmaY=0.8)
    t = 0.7 * fractal(rng, h, w, max(h, w) / 4) + 0.3 * (fibers - fibers.min()) / max(float(np.ptp(fibers)), 1e-6)
    return _normalize(t)


def dust(rng, h, w):
    t = np.full((h, w), 0.5, np.float32)
    n = int(h * w / 4000)
    ys, xs = rng.integers(0, h, n), rng.integers(0, w, n)
    t[ys, xs] = rng.choice([0.0, 1.0], n)
    return cv2.GaussianBlur(t, (0, 0), max(1.0, max(h, w) / 1500))


KINDS = {"grain": grain, "grit": grit, "scratches": scratches, "smoke": smoke, "paper": paper, "dust": dust}


def make(kind: str, h: int, w: int, seed: int = 0) -> np.ndarray:
    """Generated at up to 1600 px on the long edge and scaled up, so big
    exports stay fast; grain is made at full size so it stays fine."""
    rng = np.random.default_rng(seed)
    if kind == "grain":
        return grain(rng, h, w)
    scale = min(1.0, 1600 / max(h, w))
    sh, sw = max(8, int(h * scale)), max(8, int(w * scale))
    t = KINDS[kind](rng, sh, sw)
    return cv2.resize(t, (w, h), interpolation=cv2.INTER_LINEAR) if (sh, sw) != (h, w) else t
