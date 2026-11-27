"""Backgrounds made on this Mac (no stock images): a night stadium, a powder-smoke burst, a storm sky,
studio backdrops and a split signature texture, each in the team's color. Used to replace a photo's
background behind the player, and by the poster themes.

compose(...) puts the player in front of a new background the way a retoucher would: the old
background's color taken out of the player's edge (no green fringe from the grass), a touch of the new
background's light wrapping around the edge, and the player's color nudged toward the new light."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

NAMES = ["Stadium Lights", "Powder Smoke", "Storm Sky", "Studio Grey", "Team Studio", "Signature Split",
         "Night Field", "Clean White"]
ABOUT = {
    "Stadium Lights": "A night stadium out of focus: floodlights, haze and the pitch",
    "Powder Smoke": "A burst of powder smoke in the team color on black, with light slashes",
    "Storm Sky": "Dramatic storm clouds with a floodlight breaking through",
    "Studio Grey": "A classic grey studio backdrop, softly lit",
    "Team Studio": "A studio backdrop in the team color, glowing behind the player",
    "Signature Split": "Half black-and-white texture, half team color, split on the diagonal",
    "Night Field": "The pitch at night under one big light, the stands dark",
    "Clean White": "A clean, bright white studio (for cut-outs and cards)",
}


def _rgb(hexcolor: str) -> np.ndarray:
    h = (hexcolor or "#1f2a44").lstrip("#")
    try:
        return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
    except ValueError:
        return np.array([0.12, 0.16, 0.27], np.float32)


def noise(h: int, w: int, seed: int = 0, octaves: int = 6, base: int = 4) -> np.ndarray:
    """Smooth fractal noise (0-1): clouds, smoke and texture."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        g = rng.random((max(2, int(n * h / max(h, w))) + 1, n + 1)).astype(np.float32)
        out += cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC) * amp
        total += amp
        amp *= 0.55
    out /= total
    return np.clip((out - out.min()) / max(1e-6, out.max() - out.min()), 0, 1)


def _radial(h, w, cx, cy, rx, ry) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.sqrt(((x / w - cx) / rx) ** 2 + ((y / h - cy) / ry) ** 2)


def _glow(h, w, cx, cy, r, strength=1.0) -> np.ndarray:
    d = _radial(h, w, cx, cy, r, r * w / h)
    return np.exp(-d ** 2 * 2.2) * strength


def _slashes(h, w, color, seed=3, count=7) -> np.ndarray:
    """Bright diagonal bands of light at the sides (a classic sports-banner energy)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w, 3), np.float32)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    for i in range(count):
        side = i % 2
        x0 = (rng.uniform(-0.05, 0.22) if side == 0 else rng.uniform(0.78, 1.05)) * w
        width = rng.uniform(0.012, 0.045) * w
        slope = rng.uniform(0.35, 0.6) * (1 if side == 0 else -1)
        d = np.abs((x - x0) - (y - h / 2) * slope)
        band = np.clip(1 - d / width, 0, 1) ** 1.5
        fade = np.clip(1 - np.abs(y / h - rng.uniform(0.3, 0.7)) / rng.uniform(0.35, 0.6), 0, 1)
        tint = color * 0.6 + 0.4 if i % 3 else np.ones(3, np.float32)
        out += (band * fade)[..., None] * tint * rng.uniform(0.5, 0.95)
    return out


MAKE_EDGE = 2048  # backgrounds are soft: made at most this big, then scaled up (fast at any size)


def make(name: str, w: int, h: int, color: str = "#1f2a44", seed: int = 7) -> np.ndarray:
    """The background (floats 0-1, h x w x 3), in the team color."""
    if max(w, h) > MAKE_EDGE:
        k = MAKE_EDGE / max(w, h)
        small = _make(name, max(2, round(w * k)), max(2, round(h * k)), color, seed)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return _make(name, w, h, color, seed)


def _make(name: str, w: int, h: int, color: str, seed: int) -> np.ndarray:
    c = _rgb(color)
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    lift = c + (1 - c) * 0.35  # the team color, lighter (for light and smoke)
    if name == "Stadium Lights":
        sky = (0.02 + 0.10 * (1 - y)) * (0.5 + c) + np.zeros((h, w, 3), np.float32)
        out = sky.copy()
        rng = np.random.default_rng(seed)
        for row, yy in enumerate((0.16, 0.26)):
            for i in range(9):
                xx = (i + 0.5) / 9 + rng.uniform(-0.03, 0.03)
                size = (0.03 + 0.012 * row) * rng.uniform(0.8, 1.3)
                out += _glow(h, w, xx, yy + 0.05 * abs(xx - 0.5), size, rng.uniform(0.6, 1.0))[..., None] * (0.75 + 0.25 * lift)
                out += _glow(h, w, xx, yy + 0.05 * abs(xx - 0.5), size * 3.5, 0.12)[..., None] * (0.6 + 0.4 * lift)  # bloom
        out += _glow(h, w, 0.5, 0.25, 0.6, 0.35)[..., None] * lift
        haze = noise(h, w, seed, 5, 3)[..., None]
        out += haze * 0.12 * (y < 0.75) * lift
        grass = np.array([0.08, 0.32, 0.12], np.float32)
        field = np.clip((y - 0.68) / 0.32, 0, 1)
        tex = noise(h, w, seed + 1, 6, 30)[..., None]
        out = out * (1 - field) + (grass * (0.7 + 0.5 * tex) * (0.6 + 0.6 * field)) * field
        out = cv2.GaussianBlur(out, (0, 0), max(1.0, w * 0.006))
    elif name == "Powder Smoke":
        out = np.zeros((h, w, 3), np.float32) + 0.015
        cloud = noise(h, w, seed, 7, 3)
        burst = np.clip(1 - _radial(h, w, 0.5, 0.42, 0.5, 0.45), 0, 1) ** 1.2
        smoke = c + (1 - c) * 0.55  # (the team color, light enough to read as powder even when it's navy)
        puff = np.clip(cloud * 2.2 - 0.55, 0, 1) * burst
        out += puff[..., None] * smoke * 1.1
        out += (np.clip(cloud - 0.5, 0, 1) * 2.4 * burst)[..., None] * 0.55  # bright wisps
        out += _glow(h, w, 0.5, 0.4, 0.32, 0.35)[..., None] * smoke
        out += _slashes(h, w, c, seed)
        out *= (1 - 0.6 * np.clip(_radial(h, w, 0.5, 0.5, 0.75, 0.75) - 0.4, 0, 1))[..., None]
    elif name == "Storm Sky":
        cloud = noise(h, w, seed, 7, 3)
        dark = np.array([0.10, 0.12, 0.18], np.float32) * (0.6 + 0.6 * c / max(c.max(), 1e-3) * 0.4)
        light = np.array([0.62, 0.66, 0.76], np.float32)
        out = dark + (light - dark) * (cloud[..., None] ** 1.6) * (1.1 - y * 0.6)
        out += _glow(h, w, 0.22, 0.08, 0.28, 0.9)[..., None] * np.array([1.0, 0.95, 0.85], np.float32)
        for i in range(5):
            out += _glow(h, w, 0.12 + i * 0.045, 0.06 + i * 0.012, 0.018, 0.9)[..., None]
        ground = np.clip((y - 0.8) / 0.2, 0, 1)
        out = out * (1 - ground * 0.7)
        out *= (1 - 0.5 * np.clip(_radial(h, w, 0.5, 0.45, 0.7, 0.7) - 0.45, 0, 1))[..., None]
    elif name in ("Studio Grey", "Team Studio", "Clean White"):
        base = {"Studio Grey": np.array([0.42, 0.43, 0.45], np.float32), "Team Studio": c * 0.9 + 0.05,
                "Clean White": np.array([0.97, 0.97, 0.97], np.float32)}[name]
        mottle = noise(h, w, seed, 6, 4)[..., None]
        center = np.clip(1 - _radial(h, w, 0.5, 0.42, 0.62, 0.62), 0, 1)[..., None]
        out = base * (0.55 + 0.6 * center) * (0.92 + 0.16 * mottle)
        if name == "Clean White":
            out = np.clip(0.88 + 0.12 * center + 0.03 * (mottle - 0.5), 0, 1) * np.ones(3, np.float32)
    elif name == "Signature Split":
        tex = noise(h, w, seed, 7, 6)
        grey = (0.18 + 0.5 * tex ** 1.4)[..., None] * np.ones(3, np.float32)
        cracks = np.clip(1 - np.abs(noise(h, w, seed + 5, 6, 4) - 0.5) * 90, 0, 1) ** 2  # thin, lightning-like veins
        cracks = cv2.GaussianBlur(cracks, (0, 0), 0.8) * 1.4
        grey += cracks[..., None] * 0.6
        team = c * (0.35 + 0.65 * noise(h, w, seed + 2, 6, 3)[..., None]) + cracks[..., None] * lift * 0.5
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        right = ((xx / w) - 0.62 - (0.5 - yy / h) * 0.55 > 0).astype(np.float32)
        right = cv2.GaussianBlur(right, (0, 0), 1.2)[..., None]
        out = grey * (1 - right) + team * right
        line = np.abs((xx / w) - 0.62 - (0.5 - yy / h) * 0.55) < 0.004
        out[line] = 0.95
    elif name == "Night Field":
        out = np.zeros((h, w, 3), np.float32) + 0.02
        out += _glow(h, w, 0.5, 0.0, 0.55, 1.0)[..., None] * np.array([0.9, 0.92, 1.0], np.float32) * 0.8
        field = np.clip((y - 0.55) / 0.45, 0, 1)
        grass = np.array([0.06, 0.24, 0.1], np.float32) * (0.6 + 0.6 * noise(h, w, seed, 6, 40)[..., None])
        pool = np.clip(1 - _radial(h, w, 0.5, 0.85, 0.55, 0.25), 0, 1)[..., None]
        out = out * (1 - field) + grass * (0.25 + 1.2 * pool) * field
        stands = (y < 0.55) * (y > 0.3) * 0.04 * noise(h, w, seed + 3, 4, 20)[..., None]
        out += stands * lift
    else:
        out = np.zeros((h, w, 3), np.float32) + c
    return np.clip(out, 0, 1).astype(np.float32)


def from_image(path: Path, w: int, h: int) -> np.ndarray:
    """Your own background picture, filling w x h (cut to fit, centered)."""
    from photo_crops import images
    img = images.load(Path(path)).image.convert("RGB")
    s = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x0, y0 = (img.width - w) // 2, (img.height - h) // 2
    return np.asarray(img.crop((x0, y0, x0 + w, y0 + h))).astype(np.float32) / 255


def _soft(a: np.ndarray, sigma: float) -> np.ndarray:
    """A wide blur, done small and scaled back up (the same look, many times faster)."""
    h, w = a.shape[:2]
    k = min(1.0, 1024 / max(h, w))
    if k >= 1.0 or sigma * k < 2:
        return cv2.GaussianBlur(a, (0, 0), sigma)
    small = cv2.resize(a, (max(2, round(w * k)), max(2, round(h * k))), interpolation=cv2.INTER_AREA)
    return cv2.resize(cv2.GaussianBlur(small, (0, 0), sigma * k), (w, h), interpolation=cv2.INTER_LINEAR)


def _old_background(img: np.ndarray, a: np.ndarray) -> np.ndarray:
    """The old background's color reaching in under the player's edge (filled in from around it)."""
    bg = (a < 0.08).astype(np.float32)
    k = max(3, int(max(img.shape[:2]) * 0.01))
    num = _soft(img * bg[..., None], k)
    den = _soft(bg, k)
    if den.ndim == 2:
        den = den[..., None]
    return num / np.maximum(den, 1e-4)


def compose(img: np.ndarray, matte: np.ndarray, bg: np.ndarray, blur: float = 0.0, dim: float = 0.0,
            match: float = 0.35, wrap: float = 0.5, shadow: float = 1.0) -> np.ndarray:
    """The player (img where matte is 1) in front of a new background bg (same size, floats 0-1).
    blur: the new background out of focus (0-1); dim: darker (0-1); match: the player's color nudged
    toward the new light (0-1); wrap: the new background's light around the player's edge (0-1)."""
    h, w = img.shape[:2]
    a = np.clip(matte, 0, 1).astype(np.float32)
    if a.shape != (h, w):
        a = cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)
    if blur:
        bg = _soft(bg, max(0.5, blur * w * 0.012))
    if dim:
        bg = bg * (1 - 0.75 * dim)
    A = a[..., None]
    # the player's edge without the old background's color in it (decontaminated)
    edge = (a > 0.02) & (a < 0.98)
    fg = img.copy()
    if edge.any():
        old = _old_background(img, a)
        clean = np.clip((img - (1 - A) * old) / np.maximum(A, 0.08), 0, 1)
        fg = np.where(edge[..., None], clean, img)
    # the player's color toward the new light (only a little: their own color stays theirs)
    if match:
        light = bg.mean((0, 1))
        own = (img * A).sum((0, 1)) / max(A.sum(), 1e-6)
        gain = np.clip((light / max(light.mean(), 1e-3)) / np.maximum(own / max(own.mean(), 1e-3), 1e-3), 0.85, 1.15)
        fg = fg * (1 + (gain - 1) * match * 0.6)
    if shadow:  # a soft shadow on the ground under their feet (when the feet are in the picture)
        rows = np.nonzero((a > 0.5).any(1))[0]
        if len(rows) and rows.max() < h * 0.985:
            foot = rows.max()
            cols = np.nonzero(a[max(0, foot - int(h * 0.04)):foot + 1] > 0.5)[1]
            if len(cols):
                sh = np.zeros((h, w), np.float32)
                cx, half = (cols.min() + cols.max()) / 2, max(8, (cols.max() - cols.min()) * 0.75)
                cv2.ellipse(sh, (int(cx), int(foot)), (int(half), max(3, int(half * 0.16))), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
                sh = _soft(sh, max(2.0, half * 0.25))
                bg = bg * (1 - (sh * 0.55 * shadow)[..., None])
    out = fg * A + bg * (1 - A)
    # light wrap: the new background's light spilling a little around the player's edge
    if wrap:
        rim = np.clip(_soft(1 - a, max(1.0, w * 0.004)) * a, 0, 1)[..., None]
        out = out + _soft(bg, max(1.0, w * 0.01)) * rim * wrap * 0.6
    return np.clip(out, 0, 1).astype(np.float32)
