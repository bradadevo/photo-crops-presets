"""Backgrounds for illustration looks, drawn on this Mac: speed lines,
halftone dots, sunsets, night lights, studio and paper.

Each replaces the background behind the players (their cut-out), with the
players' edge colors cleaned of the old background, so no halo shows.
"""

import cv2
import numpy as np

from photo_presets.pipeline import Context, MissingAsset, op
from photo_presets.procedural import fractal
from photo_presets.watercolor import _palette, defringe, paper


def _players(ctx: Context):
    if ctx.alpha is None or float(ctx.alpha.max()) < 0.5:
        raise MissingAsset("no player cut-out in this photo")
    alpha = np.clip(ctx.alpha, 0, 1).astype(np.float32)
    ys, xs = np.nonzero(alpha > 0.5)
    return alpha, (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2, float(max(np.ptp(xs), np.ptp(ys)))


def _gradient(h, w, colors, angle=90.0):
    pal = _palette(colors)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.deg2rad(angle)
    t = (xx / w - 0.5) * np.cos(a) + (yy / h - 0.5) * np.sin(a)
    t = (t - t.min()) / max(float(t.max() - t.min()), 1e-6) * (len(pal) - 1)
    i = np.clip(t.astype(int), 0, len(pal) - 2) if len(pal) > 1 else np.zeros_like(t, int)
    f = (t - i)[..., None]
    if len(pal) == 1:
        return np.broadcast_to(pal[0], (h, w, 3)).astype(np.float32)
    return (pal[i] * (1 - f) + pal[i + 1] * f).astype(np.float32)


@op("art_backdrop", cutout=True, label="Illustration background (speed lines, halftone, sunset, lights, paper)",
    kind="speedlines", colors="#ffffff,#dde6f0", ink="#1b1b1b", amount=1.0)
def art_backdrop(a, p, ctx: Context):
    alpha, cx, cy, ph = _players(ctx)
    h, w = alpha.shape
    rng = np.random.default_rng(ctx.seed + 61)
    kind = p["kind"]
    amount = float(p["amount"])
    ink = _palette(p["ink"])[0]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "speedlines":  # manga focus lines rushing toward the players
        out = _gradient(h, w, p["colors"])
        ang = np.arctan2(yy - cy, xx - cx)
        n = 180
        streak = (fractal(rng, 1, n * 4, 2.0, 2)[0] > 0.62).astype(np.float32)
        idx = ((ang + np.pi) / (2 * np.pi) * n * 4).astype(int) % (n * 4)
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / ph
        lines = streak[idx] * np.clip((dist - 0.45) * 2.2, 0, 1)
        out = out * (1 - (lines * amount * 0.85)[..., None] * (1 - ink[None, None]))
    elif kind == "halftone":  # pop-art Ben-Day dots, bigger toward one corner
        out = _gradient(h, w, p["colors"], 45)
        step = max(6, int(max(h, w) / 70))
        gy, gx = (yy % step) - step / 2, ((xx + (yy // step % 2) * step / 2) % step) - step / 2
        size = (0.15 + 0.4 * (xx / w * 0.5 + (1 - yy / h) * 0.5)) * step
        dots = np.clip(size - np.sqrt(gx ** 2 + gy ** 2), 0, 1)
        out = out * (1 - (dots * amount * 0.6)[..., None] * (1 - ink[None, None]))
    elif kind == "bokeh":  # night lights: soft, glowing circles on a dark gradient
        out = _gradient(h, w, p["colors"])
        glow = np.zeros((h, w, 3), np.float32)
        lights = _palette(p["ink"]) if "," in p["ink"] else np.array([[1.0, 0.85, 0.55], [0.6, 0.8, 1.0]], np.float32)
        for _ in range(int(60 * amount)):
            r = max(h, w) * rng.uniform(0.01, 0.05)
            m = np.zeros((h, w), np.float32)
            cv2.circle(m, (int(rng.uniform(0, w)), int(rng.uniform(0, h * 0.75))), int(r), 1.0, -1, cv2.LINE_AA)
            m = cv2.GaussianBlur(m, (0, 0), r * 0.15) * rng.uniform(0.2, 0.7)
            glow += m[..., None] * lights[rng.integers(len(lights))][None, None]
        out = 1 - (1 - out) * (1 - np.clip(glow, 0, 1))
    elif kind == "sunset":  # a painted sky: warm gradient with soft clouds
        out = _gradient(h, w, p["colors"])
        clouds = np.clip((fractal(rng, h, w, max(h, w) * 0.15, 5) - 0.5) * 3, 0, 1) * (yy / h < 0.7)
        out = out * (1 - clouds[..., None] * 0.25 * amount) + clouds[..., None] * 0.15 * amount
    else:  # "paper": cream drawing paper with a little tooth
        out = paper(rng, h, w, 0.2) * _palette(p["colors"])[0][None, None] / 0.985
    m = alpha[..., None]
    return np.clip(out * (1 - m) + defringe(a, alpha) * m, 0, 1).astype(np.float32)
