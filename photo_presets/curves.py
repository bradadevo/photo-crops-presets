"""Tone curves, as in Lightroom's point curve: points (input, output) on 0-255, joined by a smooth line
that never overshoots between points (monotone cubic), so a curve never makes a band or a reversal.

- The RGB curve changes brightness only: colors keep their hue and their saturation doesn't jump as
  contrast goes up (Lightroom added "Refine Saturation" for the same reason). Skin stays natural.
- The Red, Green and Blue curves change their own channel: that is how curves color grade.
- Each curve can be on the whole photo, the players or the background (the cut-out, soft edged).

A curve is kept as text, "x,y;x,y;...", so it saves with the other adjustments; "" is a straight line.
"""
from __future__ import annotations

import numpy as np

LEVELS = 1024
CHANNELS = ("rgb", "r", "g", "b")
PARTS = ("all", "player", "bg")


def parse(text: str) -> list[tuple[float, float]]:
    """Points from text, sorted, on 0-255; a straight line (or anything unreadable) gives []."""
    pts = []
    for part in (text or "").split(";"):
        try:
            x, y = (float(v) for v in part.split(","))
        except ValueError:
            continue
        pts.append((min(255.0, max(0.0, x)), min(255.0, max(0.0, y))))
    pts = sorted(dict(pts).items())  # (one point per input)
    if len(pts) < 2 or all(abs(x - y) < 1e-6 for x, y in pts):
        return []
    return pts


def text(points: list[tuple[float, float]]) -> str:
    return ";".join(f"{round(x)},{round(y)}" for x, y in points)


def table(points: list[tuple[float, float]]) -> np.ndarray | None:
    """The curve as a lookup table (LEVELS entries, 0-1), or None for a straight line."""
    if not points:
        return None
    xs = np.array([p[0] for p in points], np.float64) / 255
    ys = np.array([p[1] for p in points], np.float64) / 255
    t = np.linspace(0, 1, LEVELS)
    if len(xs) == 2:
        out = np.interp(t, xs, ys)
    else:
        d = np.diff(ys) / np.maximum(np.diff(xs), 1e-9)  # (Fritsch-Carlson: monotone between points)
        m = np.empty_like(ys)
        m[0], m[-1] = d[0], d[-1]
        m[1:-1] = np.where(d[:-1] * d[1:] > 0, 2 / (1 / np.where(d[:-1] == 0, 1e-9, d[:-1]) + 1 / np.where(d[1:] == 0, 1e-9, d[1:])), 0)
        i = np.clip(np.searchsorted(xs, t) - 1, 0, len(xs) - 2)
        h = xs[i + 1] - xs[i]
        s = np.clip((t - xs[i]) / np.maximum(h, 1e-9), 0, 1)
        h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
        out = h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1]
        out = np.where(t < xs[0], ys[0], np.where(t > xs[-1], ys[-1], out))  # (flat past the end points)
    return np.clip(out, 0, 1).astype(np.float32)


def _look_up(x: np.ndarray, lut: np.ndarray) -> np.ndarray:
    pos = np.clip(x, 0, 1) * (LEVELS - 1)
    i = np.minimum(pos.astype(np.int32), LEVELS - 2)
    f = pos - i
    return lut[i] * (1 - f) + lut[i + 1] * f


def apply(out: np.ndarray, curves: dict[str, str], weight: np.ndarray | None = None) -> np.ndarray:
    """The curves (channel -> text) on a picture (floats 0-1); weight (0-1 per pixel): where they apply."""
    luts = {c: table(parse(curves.get(c, ""))) for c in CHANNELS}
    if all(v is None for v in luts.values()):
        return out
    new = out
    if luts["rgb"] is not None:
        lum = np.clip(out[..., 0] * 0.299 + out[..., 1] * 0.587 + out[..., 2] * 0.114, 0, 1)
        to = _look_up(lum, luts["rgb"])
        ratio = to / np.maximum(lum, 1e-4)
        new = out * ratio[..., None]
        # (brightened past white: toward white, not off-hue; and the very darkest lifted evenly: a faded black is gray)
        over = np.max(new, axis=-1, keepdims=True)
        new = np.where(over > 1, new + (1 - new) * np.clip((over - 1) / np.maximum(over, 1e-4), 0, 1), new)
        a = np.clip(1 - lum / 0.08, 0, 1)[..., None]  # (near black the change is added evenly: a ratio can't lift black)
        new = new * (1 - a) + (out + (to - lum)[..., None]) * a
        new = np.clip(new, 0, 1)
    if any(luts[c] is not None for c in "rgb"):
        new = new.copy()
        for k, c in enumerate("rgb"):
            if luts[c] is not None:
                new[..., k] = _look_up(new[..., k], luts[c])
    if weight is not None:
        w = np.clip(weight, 0, 1)[..., None].astype(np.float32)
        new = out * (1 - w) + new * w
    return new.astype(np.float32)


# Ready-made curves, named by the situation they're for (channel -> points), and where each goes.
SITUATIONS = {
    "flat": ("Flat, overcast light", "More contrast for a gray day: deeper shadows, brighter highlights", "all",
             {"rgb": [(0, 0), (64, 52), (192, 206), (255, 255)]}),
    "punchy": ("Punchy action", "A strong S: bold, high-energy contrast", "all",
               {"rgb": [(0, 0), (60, 42), (128, 128), (196, 216), (255, 255)]}),
    "pop": ("Make the player pop", "Contrast on the players only; the background stays as it is", "player",
            {"rgb": [(0, 0), (64, 54), (192, 210), (255, 255)]}),
    "night": ("Night game", "The background into deep blacks, its lights kept; the players untouched", "bg",
              {"rgb": [(0, 0), (60, 34), (140, 120), (255, 255)]}),
    "faded": ("Faded film", "Lifted blacks and a soft S: a matte, film look", "all",
              {"rgb": [(0, 26), (70, 66), (190, 200), (255, 246)]}),
    "teal_orange": ("Cool shadows, warm highlights", "Color grading with the Red and Blue curves", "all",
                    {"r": [(0, 0), (70, 62), (190, 200), (255, 255)], "b": [(0, 0), (70, 80), (190, 180), (255, 255)]}),
}


def flatness(img: np.ndarray) -> float:
    """How flat the light is: the brightness spread from the 5th to the 95th percentile (0-1).
    A gray, overcast photo is about 0.45 or less; a sunny or well-lit one 0.65 or more."""
    lum = img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114
    lo, hi = np.percentile(lum, [5, 95])
    return float(hi - lo)
