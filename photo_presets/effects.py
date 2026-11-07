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


@op("lut", label="LUT color", color_shift=True, asset="", strength=1.0, guard_shadows=True)
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


@op("neon", label="Neon split-tone", color_shift=True, shadows="#5b1aff", highlights="#00f0ff", amount=0.6, saturation=1.5)
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


@op("duotone", label="Duotone", color_shift=True, dark="#0b1d3a", light="#ffb347", amount=1.0)
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


@op("overlay", protect=True, label="Impact overlay", layer="background", asset="", place="ball", blend="screen", opacity=0.9, size=0.8)
def overlay(a, p, ctx):
    """An effect with transparency (smoke, sparks...) centered on the ball,
    the player's feet, the middle, or a random spot; size is a share of the
    player's height. Behind the players by default (layer "background")."""
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


# Premium: clarity, bloom, split toning, depth ----------------------------------------------

def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


@op("athletic_clarity", protect=False, label="Athletic clarity", amount=0.6, radius=0.004, fine=0.6)
def athletic_clarity(a, p, ctx):
    """Frequency separation on brightness: the fine band (jersey weave, sweat,
    turf blades) and a medium band (folds, muscle) are boosted, limited so
    edges get no halos, and weighted to the midtones so blacks and whites stay put."""
    long_edge = max(a.shape[:2])
    lum = _luma(a)
    s1 = max(0.8, 0.0012 * long_edge)
    s2 = max(s1 * 2, float(p["radius"]) * long_edge)
    low1 = cv2.GaussianBlur(lum, (0, 0), s1)
    low2 = cv2.GaussianBlur(lum, (0, 0), s2)
    fine_w = float(p["fine"])
    detail = (lum - low1) * fine_w + (low1 - low2) * (1 - fine_w)
    detail = 0.08 * np.tanh(detail / 0.08)  # no halos on strong edges
    midtones = 4 * lum * (1 - lum)
    new = np.clip(lum + 2.0 * float(p["amount"]) * detail * midtones, 0, 1)
    return a * ((new + 1e-3) / (lum + 1e-3))[..., None]


@op("specular_bloom", protect=True, label="Specular bloom", amount=0.5, threshold=0.8, size=0.02)
def specular_bloom(a, p, ctx):
    """Only the brightest, near-white highlights (sun on skin, sweat, shiny
    kit) glow: a soft, layered (volumetric) halo at three sizes, added with
    screen so nothing clips, and the very top rolled off so midtones are not
    blown out."""
    lum = _luma(a)
    chroma = a.max(axis=2) - a.min(axis=2)
    # True speculars are small, near-white points. Pale colored kits, and big
    # bright areas such as a sunlit white-striped shirt, would otherwise glow
    # as a halo around the whole player, so both are left out
    spec = _smoothstep(float(p["threshold"]), 1.0, lum) * (1 - np.clip(chroma / 0.15, 0, 1))
    size = float(p["size"]) * max(a.shape[:2])
    area = cv2.GaussianBlur(spec, (0, 0), max(2.0, 0.5 * size))
    spec = spec * np.clip(1 - (area - 0.15) / 0.35, 0, 1)
    src = a * spec[..., None]
    bloom = sum(w * cv2.GaussianBlur(src, (0, 0), max(1.0, size * k))
                for w, k in ((0.5, 0.25), (0.3, 0.6), (0.2, 1.4)))
    out = blend(a, np.clip(bloom * 3.0, 0, 1), "screen", float(p["amount"]))
    top = 0.92  # soft roll-off above this, so bloom never blows the highlights out
    return np.where(out > top, top + (1 - top) * np.tanh((out - top) / (1 - top)), out)


def _hex_lab(color: str) -> np.ndarray:
    rgb = _hex(color).reshape(1, 1, 3).astype(np.float32)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[0, 0]


@op("split_tone", label="Split toning", color_shift=True, shadows="#1f4e79", highlights="#ffb347", amount=0.5,
    balance=0.0, compress_blacks=0.3)
def split_tone(a, p, ctx):
    """Rich cool tones pushed into the (slightly lifted, compressed) blacks and
    warm, energetic tones into the highlights, in Lab so brightness is kept."""
    lab = cv2.cvtColor(np.clip(a, 0, 1).astype(np.float32), cv2.COLOR_RGB2LAB)
    L = lab[..., 0] / 100.0
    bal = float(p["balance"])  # -1 more shadow tint ... +1 more highlight tint
    w_sh = (1 - _smoothstep(0.0, 0.55 + 0.25 * bal, L)) * (1 - max(0.0, bal))
    w_hi = _smoothstep(0.45 + 0.25 * bal, 1.0, L) * (1 + min(0.0, bal))
    sh, hi = _hex_lab(p["shadows"]), _hex_lab(p["highlights"])
    amount = float(p["amount"])
    for c in (1, 2):
        lab[..., c] += amount * (sh[c] * w_sh + hi[c] * w_hi) * 0.6
    lift = float(p["compress_blacks"]) * 8.0  # Lab lightness units lifted at black
    lab[..., 0] = lift + lab[..., 0] * (100 - lift) / 100
    return np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)


@op("exposure", label="Exposure", stops=0.3)
def exposure(a, p, ctx):
    out = a * 2 ** float(p["stops"])
    return np.where(out > 0.9, 0.9 + 0.1 * np.tanh((out - 0.9) / 0.1), out)


@op("lens_blur", label="Lens blur", layer="background", radius=0.006)
def lens_blur(a, p, ctx):
    """Background blur that leaves the players' own colors out (when they are
    cut out), so a bright shirt does not smear into a halo around them."""
    sigma = max(0.5, float(p["radius"]) * max(a.shape[:2]))
    if ctx.alpha is None or p.get("layer", "background") != "background":
        return cv2.GaussianBlur(a, (0, 0), sigma)
    keep = 1 - ctx.alpha
    blurred = cv2.GaussianBlur(a * keep[..., None], (0, 0), sigma)
    weight = cv2.GaussianBlur(keep, (0, 0), sigma)[..., None]
    return np.where(weight > 1e-3, blurred / np.maximum(weight, 1e-3), a)


@op("fog", label="Fog / stadium haze", layer="background", color="#d9dee6", density=0.5, height=0.65)
def fog(a, p, ctx):
    """Drifting haze, thickest low in the frame (height = how far up it reaches),
    behind the players by default."""
    from photo_presets import procedural
    h, w = a.shape[:2]
    puffs = procedural.make("smoke", h, w, ctx.seed)
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    reach = float(p["height"])
    vertical = _smoothstep(1 - reach, 1.0, y) * 0.7 + 0.3 * _smoothstep(1 - reach - 0.2, 1.0, y)
    alpha = np.clip((0.35 + 0.65 * puffs) * vertical * float(p["density"]), 0, 1)
    return a + (np.broadcast_to(_hex(p["color"]), a.shape) - a) * alpha[..., None]


@op("rain", label="Rain", layer="background", amount=0.5, angle=12.0)
def rain(a, p, ctx):
    """Falling rain streaks (screen), behind the players by default."""
    h, w = a.shape[:2]
    rng = np.random.default_rng(ctx.seed)
    scale = min(1.0, 1600 / max(h, w))
    sh, sw = max(16, int(h * scale)), max(16, int(w * scale))
    density = 0.0012 + 0.003 * float(p["amount"])
    drops = (rng.random((sh, sw)) < density).astype(np.float32) * rng.uniform(0.35, 0.9, (sh, sw)).astype(np.float32)
    length = max(15, int(max(sh, sw) * 0.05)) | 1
    kernel = np.zeros((length, length), np.float32)
    angle = np.radians(float(p["angle"]))
    c = length // 2
    dx, dy = np.sin(angle) * c, np.cos(angle) * c
    cv2.line(kernel, (int(c - dx), int(c - dy)), (int(c + dx), int(c + dy)), 1.0, 1, cv2.LINE_AA)
    kernel *= np.linspace(0.3, 1.0, length, dtype=np.float32)[:, None]  # streaks fade toward their tail
    streaks = cv2.GaussianBlur(cv2.filter2D(drops, -1, kernel), (0, 0), 0.6)
    streaks = cv2.resize(np.clip(streaks, 0, 1), (w, h), interpolation=cv2.INTER_LINEAR)
    layer = np.repeat(streaks[..., None], 3, axis=2) * np.array([0.85, 0.9, 1.0], np.float32)
    return blend(a * (1 - 0.12 * float(p["amount"])), layer, "screen", float(p["amount"]))
