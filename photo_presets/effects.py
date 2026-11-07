"""The built-in operations. Each takes the image as floats (H, W, 3) in 0-1."""

import cv2
import numpy as np
from PIL import Image

from photo_presets import luts
from photo_presets.blend import blend
from photo_presets.pipeline import Context, MissingAsset, op


def _luma(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def _hex(color: str) -> np.ndarray:
    c = color.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255.0


def _u8(a: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))


def _name(asset: str, kind: str) -> str:
    k, _, name = asset.partition(":")
    if k != kind or not name:
        raise MissingAsset(f"{asset!r} is not a {kind}")
    return name


# Color ------------------------------------------------------------------------

# A LUT may not darken pixels below this brightness (fully protected at black),
# so dark skin and dark kits keep their detail (from match-cull)
SHADOW_GUARD_END = 0.5


@op("lut", label="LUT color", asset="", strength=1.0, guard_shadows=True)
def lut(a, p, ctx: Context):
    name = _name(p["asset"], "lut")
    if name not in ctx.library.luts:
        raise MissingAsset(f"LUT {name!r} not found")
    looked = np.asarray(luts.apply_lut(_u8(a), luts.load(ctx.library.lut_path(name))), np.float32) / 255.0
    out = a + (looked - a) * float(p["strength"])
    if p["guard_shadows"]:
        lum_in, lum_out = _luma(a), _luma(out)
        guard = np.clip(1 - lum_in / SHADOW_GUARD_END, 0, 1) ** 0.5
        out = out + (a - out) * np.where(lum_out < lum_in, guard, 0.0)[..., None]
    return out


@op("neon", label="Neon split-tone", shadows="#5b1aff", highlights="#00f0ff", amount=0.6, saturation=1.5)
def neon(a, p, ctx):
    lum = _luma(a)[..., None]
    tint = _hex(p["shadows"]) * (1 - lum) + _hex(p["highlights"]) * lum
    out = blend(a, tint, "overlay", float(p["amount"]))
    return saturation(out, {"amount": p["saturation"]}, ctx)


@op("bw", label="B&W channel mix", red=0.45, green=0.4, blue=0.15, contrast=1.3, tint="")
def bw(a, p, ctx):
    weights = np.array([p["red"], p["green"], p["blue"]], np.float32)
    weights = weights / max(float(weights.sum()), 1e-6)
    gray = np.clip(a @ weights, 0, 1)
    gray = np.clip(0.5 + (gray - 0.5) * float(p["contrast"]), 0, 1)
    out = np.repeat(gray[..., None], 3, axis=2)
    if p["tint"]:
        out = blend(out, np.broadcast_to(_hex(p["tint"]), out.shape), "soft_light", 0.5)
    return out


@op("duotone", label="Duotone", dark="#0b1d3a", light="#ffb347", amount=1.0)
def duotone(a, p, ctx):
    lum = _luma(a)[..., None]
    tone = _hex(p["dark"]) * (1 - lum) + _hex(p["light"]) * lum
    return a + (tone - a) * float(p["amount"])


@op("contrast", label="Contrast", amount=0.3)
def contrast(a, p, ctx):
    s = a * a * (3 - 2 * a)  # smooth S-curve
    return a + (s - a) * float(p["amount"]) * 2


@op("saturation", label="Saturation", amount=1.2)
def saturation(a, p, ctx):
    gray = _luma(a)[..., None]
    return gray + (a - gray) * float(p["amount"])


@op("clean", label="Clean pro edit (photo-crops)", strength="light")
def clean(a, p, ctx):
    from photo_crops import edit
    return np.asarray(edit.apply(_u8(a), None, p["strength"]), np.float32) / 255.0


# Detail and texture ----------------------------------------------------------------

@op("high_pass", protect=True, label="High-pass detail", radius=0.006, amount=0.7, blend="overlay")
def high_pass(a, p, ctx):
    """radius is a share of the image's long edge, so previews and exports match."""
    sigma = max(1.0, float(p["radius"]) * max(a.shape[:2]))
    hp = np.clip(a - cv2.GaussianBlur(a, (0, 0), sigma) + 0.5, 0, 1)
    gray = np.repeat(_luma(hp)[..., None], 3, axis=2)
    return blend(a, gray, p["blend"], float(p["amount"]))


@op("texture", protect=True, label="Texture", asset="generated:grit", blend="overlay", opacity=0.4)
def texture(a, p, ctx):
    if not ctx.library.has(p["asset"]):
        raise MissingAsset(f"texture {p['asset']!r} not found")
    h, w = a.shape[:2]
    return blend(a, ctx.library.texture(p["asset"], h, w, ctx.seed), p["blend"], float(p["opacity"]))


@op("grain", protect=True, label="Film grain", amount=0.2)
def grain(a, p, ctx):
    h, w = a.shape[:2]
    return blend(a, ctx.library.texture("generated:grain", h, w, ctx.seed), "overlay", float(p["amount"]))


@op("overlay", protect=True, label="Impact overlay", asset="", place="ball", blend="screen", opacity=0.9, size=0.8)
def overlay(a, p, ctx):
    """An effect with transparency (smoke, sparks...) centered on the ball,
    the player's feet, the middle, or a random spot; size is a share of the
    player's height."""
    name = _name(p["asset"], "overlay")
    if name not in ctx.library.overlays:
        raise MissingAsset(f"overlay {name!r} not found")
    rgba = ctx.library.overlay(name).convert("RGBA")
    h, w = a.shape[:2]
    scene = ctx.scene
    side = int(max(16, float(p["size"]) * scene.subject_height * h))
    layer = np.asarray(rgba.resize((side, side), Image.Resampling.BILINEAR), np.float32) / 255.0
    place = p["place"]
    if place == "ball" and scene.balls:
        cx, cy = scene.balls[0][0] * w, scene.balls[0][1] * h
    elif place in ("ball", "feet") and scene.feet:
        cx, cy = scene.feet[0] * w, scene.feet[1] * h - side * 0.25
    elif place == "random":
        rng = np.random.default_rng(ctx.seed)
        cx, cy = rng.uniform(0.15, 0.85) * w, rng.uniform(0.3, 0.9) * h
    else:
        cx, cy = w / 2, h / 2
    x0, y0 = int(cx - side / 2), int(cy - side / 2)
    ox0, oy0 = max(0, -x0), max(0, -y0)
    x1, y1 = min(w, x0 + side), min(h, y0 + side)
    if x1 <= max(0, x0) or y1 <= max(0, y0):
        return a
    out = a.copy()
    region = out[max(0, y0):y1, max(0, x0):x1]
    piece = layer[oy0:oy0 + region.shape[0], ox0:ox0 + region.shape[1]]
    out[max(0, y0):y1, max(0, x0):x1] = blend(region, piece[..., :3], p["blend"], float(p["opacity"]), piece[..., 3])
    return out


# Lighting and edges -----------------------------------------------------------------

@op("vignette", label="Vignette", amount=0.35)
def vignette(a, p, ctx):
    h, w = a.shape[:2]
    y, x = np.ogrid[:h, :w]
    d = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    return a * (1 - float(p["amount"]) * np.clip(d, 0, 1) ** 2)[..., None]


@op("spotlight", label="Spotlight on the player", amount=0.35)
def spotlight(a, p, ctx):
    h, w = a.shape[:2]
    scene = ctx.scene
    cx, cy = (scene.feet[0] * w, (scene.feet[1] - scene.subject_height / 2) * h) if scene.feet else (w / 2, h / 2)
    radius = max(scene.subject_height * h * 0.9, 1)
    y, x = np.ogrid[:h, :w]
    d = np.clip(np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / radius, 0, 1.5)
    light = 1 - float(p["amount"]) * np.clip(d - 0.5, 0, 1)
    return a * light[..., None]


@op("light_leak", protect=True, label="Light leak", color="#ff7a1a", corner="top_right", amount=0.5)
def light_leak(a, p, ctx):
    h, w = a.shape[:2]
    corners = {"top_left": (0, 0), "top_right": (w, 0), "bottom_left": (0, h), "bottom_right": (w, h)}
    cx, cy = corners.get(p["corner"], (w, 0))
    y, x = np.ogrid[:h, :w]
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / np.hypot(w, h)
    glow = np.clip(1 - d / 0.6, 0, 1) ** 2
    layer = np.broadcast_to(_hex(p["color"]), a.shape) * glow[..., None]
    return blend(a, layer, "screen", float(p["amount"]))


@op("glow", protect=True, label="Glow", amount=0.35, threshold=0.7)
def glow(a, p, ctx):
    bright = np.clip((a - float(p["threshold"])) / max(1 - float(p["threshold"]), 1e-3), 0, 1)
    halo = cv2.GaussianBlur(bright, (0, 0), max(a.shape[:2]) * 0.01)
    return blend(a, halo, "screen", float(p["amount"]))


@op("edge_distress", protect=True, label="Edge distressing", amount=0.5, color="#000000")
def edge_distress(a, p, ctx):
    """Rough, worn edges: the border is eaten away by uneven noise into a color."""
    from photo_presets import procedural
    h, w = a.shape[:2]
    rng = np.random.default_rng(ctx.seed)
    y, x = np.ogrid[:h, :w]
    edge = np.minimum(np.minimum(x / w, (w - 1 - x) / w), np.minimum(y / h, (h - 1 - y) / h))
    width = 0.02 + 0.08 * float(p["amount"])
    rough = procedural.fractal(rng, h, w, max(h, w) / 40) * 0.6 + rng.random((h, w)).astype(np.float32) * 0.15
    eaten = np.clip((width - edge) / width + rough - 0.6, 0, 1)
    eaten = cv2.GaussianBlur(eaten.astype(np.float32), (0, 0), 1.0)
    return a + (np.broadcast_to(_hex(p["color"]), a.shape) - a) * eaten[..., None]
