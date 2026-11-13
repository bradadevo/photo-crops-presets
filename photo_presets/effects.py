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


# Editorial ---------------------------------------------------------------------

# High key lifts a photo whose middle brightness is below this the most
HIGH_KEY_TARGET = 0.6

@op("high_key", label="High key (bright and airy)", amount=0.5)
def high_key(a, p, ctx):
    """Bright, airy editorial tone: midtones lifted, pale colorless areas (an
    overcast sky) rolled into clean white, blacks kept deep. It adapts to the
    photo: a sunny, already bright photo is lifted far less than a dull one,
    and colored areas (grass, kits) never go white."""
    lum = _luma(a)
    median = float(np.median(lum))
    amount = float(p["amount"]) * float(np.clip((HIGH_KEY_TARGET - median) / 0.2, 0.15, 1.0))
    lifted = 1 - (1 - lum) ** (1 + 1.5 * amount)
    new = lum + (lifted - lum) * _smoothstep(0.05, 0.45, lum)
    out = a * ((new + 1e-3) / (lum + 1e-3))[..., None]
    chroma = out.max(axis=2) - out.min(axis=2)
    pale = 1 - _smoothstep(0.08, 0.2, chroma)
    white = _smoothstep(0.8, 0.98, new) * pale * amount * 0.7
    return np.clip(out + (1 - out) * white[..., None], 0, 1)


@op("backdrop", label="Studio backdrop", layer="background", top="#3d86c6", bottom="#000000", glow=0.5, amount=1.0)
def backdrop(a, p, ctx):
    """Replaces the background with a smooth studio gradient (top color into
    bottom color) lit from above the player, like a portrait backdrop."""
    if ctx.alpha is None and p.get("layer", "background") == "background":
        ctx.notes.append("Studio backdrop skipped: no player cut-out here")
        return a
    h, w = a.shape[:2]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    grad = _hex(p["top"]) * (1 - y ** 0.8) + _hex(p["bottom"]) * y ** 0.8
    grad = np.broadcast_to(grad, (h, w, 3)).copy()
    cx = ctx.scene.feet[0] if ctx.scene.feet else 0.5
    yy, xx = np.ogrid[:h, :w]
    d2 = ((xx / w - cx) / 0.45) ** 2 + ((yy / h) / 0.35) ** 2
    light = float(p["glow"]) * np.exp(-d2).astype(np.float32)
    grad += (1 - grad) * light[..., None] * 0.8
    grad += np.random.default_rng(ctx.seed).normal(0, 0.004, (h, w, 1)).astype(np.float32)  # no banding
    return a + (np.clip(grad, 0, 1) - a) * float(p["amount"])


# Studio smoke and light ---------------------------------------------------------

SMOKE_PLACES = ["sides", "behind", "floor", "sides_floor"]


def _player(scene, h: int, w: int) -> tuple[float, float, float]:
    """The main player's feet (x, y) and height, in pixels."""
    if scene.feet:
        return scene.feet[0] * w, scene.feet[1] * h, scene.subject_height * h
    return w / 2, h * 0.95, h * 0.7


def _billows(rng, h: int, w: int, scale: float) -> np.ndarray:
    """Billowing smoke detail: fractal noise, swirled (domain-warped)."""
    from photo_presets import procedural
    n = procedural.fractal(rng, h, w, scale, octaves=6)
    shift = scale * 0.5
    wx = (procedural.fractal(rng, h, w, scale * 0.8, octaves=3) - 0.5) * shift
    wy = (procedural.fractal(rng, h, w, scale * 0.8, octaves=3) - 0.5) * shift
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(n, gx + wx, gy + wy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _blob(h, w, cx, cy, rx, ry):
    y, x = np.ogrid[:h, :w]
    return np.exp(-(((x - cx) / max(rx, 1)) ** 2) - (((y - cy) / max(ry, 1)) ** 2)).astype(np.float32)


@op("smoke_cloud", label="Smoke clouds", color="#ffffff", color2="", place="sides", amount=0.85, size=1.0,
    front=0.0)
def smoke_cloud(a, p, ctx):
    """Billowing studio smoke shaped around the player: at both sides, behind,
    along the floor, or sides and floor. With a second color, the left cloud
    takes the first color and the right cloud the second (team colors).
    The clouds sit behind the players (when they are cut out); front (0-1) lets
    the floor smoke roll in front of their feet too."""
    h, w = a.shape[:2]
    scale = min(1.0, 1400 / max(h, w))
    sh, sw = max(16, int(h * scale)), max(16, int(w * scale))
    fx, fy, ph = (v * scale for v in _player(ctx.scene, h, w))
    size = float(p["size"])
    rng = np.random.default_rng(ctx.seed + 17)
    # big swirling shapes plus fine wisps
    billow = 0.6 * _billows(rng, sh, sw, max(sh, sw) / 4) + 0.4 * _billows(rng, sh, sw, max(sh, sw) / 12)
    billow = (billow - billow.min()) / max(float(np.ptp(billow)), 1e-6)
    mid = fy - 0.6 * ph
    left = _blob(sh, sw, fx - 0.45 * ph * size, mid, 0.3 * ph * size, 0.5 * ph * size)
    right = _blob(sh, sw, fx + 0.45 * ph * size, mid, 0.3 * ph * size, 0.5 * ph * size)
    floor = np.minimum(1.0, 1.3 * _blob(sh, sw, fx, fy, 1.6 * ph * size, 0.2 * ph * size))
    place = p["place"]
    clouds = []  # (envelope, color, may cover the players)
    second = p.get("color2") or p["color"]
    if place in ("sides", "sides_floor"):
        clouds += [(left, p["color"], False), (right, second, False)]
    if place == "behind":
        clouds.append((_blob(sh, sw, fx, mid, 0.55 * ph * size, 0.6 * ph * size), p["color"], False))
    if place in ("floor", "sides_floor"):
        clouds.append((floor, p["color"], True))
    behind = 1 - ctx.alpha if ctx.alpha is not None and p.get("layer", "all") == "all" else 1.0
    out = a
    for envelope, color, in_front in clouds:
        density = np.clip((envelope * (0.2 + 1.3 * billow ** 1.5) - 0.25) * 2.0, 0, 1)
        density = cv2.resize(density, (w, h), interpolation=cv2.INTER_LINEAR)
        # lit tops and shadowed folds give the cloud volume
        relief = np.clip(0.5 + (billow - cv2.GaussianBlur(billow, (0, 0), max(sh, sw) / 80)) * 4, 0, 1)
        shade = cv2.resize(0.5 + 0.35 * billow + 0.35 * relief, (w, h), interpolation=cv2.INTER_LINEAR)
        smoke = np.clip(_hex(color) * shade[..., None], 0, 1)
        cover = behind + (1 - behind) * float(p["front"]) if in_front else behind
        out = out + (smoke - out) * (density * cover * float(p["amount"]))[..., None]
    return out


@op("stage_lights", label="Stage lights", layer="background", count=2, amount=0.8)
def stage_lights(a, p, ctx):
    """Bright studio lights along the top of the frame, above the player."""
    h, w = a.shape[:2]
    fx, _, _ = _player(ctx.scene, h, w)
    count = max(1, int(p["count"]))
    spread = 0.36 * w
    xs = [fx] if count == 1 else [fx - spread / 2 + spread * i / (count - 1) for i in range(count)]
    light = np.zeros((h, w), np.float32)
    r = 0.03 * w
    for x in xs:
        light = np.maximum(light, _blob(h, w, x, 0.035 * h, r, r) ** 0.25 * 0.95)  # the lamp
        light += 0.35 * _blob(h, w, x, 0.035 * h, 4 * r, 4 * r)              # its glow
    layer = np.repeat(np.clip(light, 0, 1)[..., None], 3, axis=2) * np.array([1.0, 0.97, 0.9], np.float32)
    return blend(a, layer, "screen", float(p["amount"]))


@op("stadium_lights", label="Stadium light banks", layer="background", height=0.7, amount=0.9,
    color="#fff3dc")
def stadium_lights(a, p, ctx):
    """Two banks of stadium floodlights (grids of bright lamps with a big glow)
    near the left and right edges, at the player's shoulder height (height:
    share of the player's height above their feet)."""
    h, w = a.shape[:2]
    fx, fy, ph = _player(ctx.scene, h, w)
    y = float(np.clip(fy - float(p["height"]) * ph, 0.12 * h, 0.6 * h))
    bw, bh = 0.16 * w, 0.05 * w
    lamps = np.zeros((h, w), np.float32)
    glow = np.zeros((h, w), np.float32)
    rows, cols = 4, 11
    dot = max(2, int(0.36 * bw / cols))
    for cx in (0.11 * w, 0.89 * w):
        for r in range(rows):
            for c in range(cols):
                x = cx - bw / 2 + bw * (c + 0.5) / cols
                cv2.circle(lamps, (int(x), int(y - bh / 2 + bh * (r + 0.5) / rows)), dot, 1.0, -1, cv2.LINE_AA)
        glow += 0.3 * _blob(h, w, cx, y, 0.8 * bw, 1.4 * bh)    # the hot core
        glow += 0.3 * _blob(h, w, cx, y, 2.0 * bw, 4.0 * bh)    # haze lit around it
    # each bulb shines with a small halo of its own
    lamps = np.maximum(lamps, cv2.GaussianBlur(lamps, (0, 0), dot * 1.2) * 0.9)
    light = np.clip(lamps + glow, 0, 1)
    layer = light[..., None] * _hex(p["color"])
    return blend(a, layer, "screen", float(p["amount"]))


@op("subject_vignette", label="Vignette around the player", amount=0.6, spread=0.3)
def subject_vignette(a, p, ctx):
    """Darkens away from the player's own outline (not the frame's center), so
    the light falls off around them wherever they are. Spread: how far out
    (share of the frame) the darkening takes to build."""
    from photo_presets.scene import resized
    h, w = a.shape[:2]
    scale = min(1.0, 800 / max(h, w))
    sh, sw = max(8, int(h * scale)), max(8, int(w * scale))
    mask = ctx.alpha if ctx.alpha is not None else ctx.scene.subject_mask
    mask = resized(mask, sh, sw)
    if mask is None or mask.max() < 0.5:
        return spotlight(a, {"amount": p["amount"]}, ctx)
    dist = cv2.distanceTransform((mask < 0.5).astype(np.uint8), cv2.DIST_L2, 5) / max(sh, sw)
    fall = _smoothstep(0.0, max(float(p["spread"]), 0.01), dist)
    fall = cv2.resize(cv2.GaussianBlur(fall, (0, 0), max(sh, sw) / 60), (w, h), interpolation=cv2.INTER_LINEAR)
    return a * (1 - float(p["amount"]) * fall)[..., None]


# Neon pop art ------------------------------------------------------------------

# Indigo shadows, then violet, cyan, pink, salmon and yellow-green highlights (a neon paint gradient)
POP_PALETTE = "#24157a,#5b3dff,#2fc6ff,#ff4fa8,#ff8f5a,#e6ff4d,#fbffd2"


def _palette(colors: str) -> np.ndarray:
    return np.stack([_hex(c.strip()) for c in colors.split(",") if c.strip()])


def _gradient_map(t: np.ndarray, palette: np.ndarray) -> np.ndarray:
    pos = np.clip(t, 0, 1) * (len(palette) - 1)
    i = np.minimum(pos.astype(np.int32), len(palette) - 2)
    f = (pos - i)[..., None]
    return palette[i] * (1 - f) + palette[i + 1] * f


def _art_mask(ctx, h, w) -> np.ndarray:
    """Where the art goes: the player's cut-out, or the whole photo without one."""
    return ctx.alpha if ctx.alpha is not None else np.ones((h, w), np.float32)


@op("pop_art", label="Neon pop art (player)", palette=POP_PALETTE, levels=7, mottle=0.35, lines=0.6,
    outline="#ff6f7d", glow=0.7, shading=0.45, background="#9a6a44", background_amount=0.85, amount=1.0)
def pop_art(a, p, ctx):
    """The player as a neon pop-art painting: brightness mapped onto a neon
    gradient, mottled like brush strokes and posterized into paint bands, with
    painted contour lines and a glowing outline. The background (with a
    cut-out) turns a dark, low-color tone of `background` (sepia brown by default)."""
    from photo_presets import procedural
    h, w = a.shape[:2]
    scale = min(1.0, 1600 / max(h, w))
    sh, sw = max(16, int(h * scale)), max(16, int(w * scale))
    small = cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA)
    lum = _luma(small)
    # even out the player's tones so every part reaches across the gradient
    lum8 = (np.clip(lum, 0, 1) * 255).astype(np.uint8)
    lum = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(6, 6)).apply(lum8).astype(np.float32) / 255
    lum = cv2.bilateralFilter(lum, 9, 0.15, 6)  # flatter, painted areas
    rng = np.random.default_rng(ctx.seed + 31)
    mottle = procedural.fractal(rng, sh, sw, max(sh, sw) / 14, octaves=4)
    t = np.clip(lum * 0.85 + 0.08 + (mottle - 0.5) * 2 * float(p["mottle"]), 0, 1)
    levels = max(2, int(p["levels"]))
    banded = np.round(t * (levels - 1)) / (levels - 1)
    t = cv2.GaussianBlur(banded * 0.75 + t * 0.25, (0, 0), 0.8)
    art = _gradient_map(t, _palette(p["palette"]))
    # keep the photo's shading (eyes, folds, the face's shape) under the paint
    shade = cv2.GaussianBlur(lum, (0, 0), 1.0)
    art = art * (1 - float(p["shading"]) + float(p["shading"]) * 1.6 * shade[..., None])
    # painted contour lines along the strong edges inside the player
    edges = cv2.Canny((cv2.GaussianBlur(lum, (0, 0), 1.2) * 255).astype(np.uint8), 40, 110).astype(np.float32) / 255
    edges = cv2.GaussianBlur(cv2.dilate(edges, np.ones((2, 2), np.uint8)), (0, 0), 0.7)
    art = art + (_hex(p["outline"]) - art) * (np.clip(edges * 1.5, 0, 1) * float(p["lines"]))[..., None]
    art = cv2.resize(art, (w, h), interpolation=cv2.INTER_LINEAR)
    mask = _art_mask(ctx, h, w)[..., None]
    out = a + (art - a) * mask * float(p["amount"])
    if ctx.alpha is not None and float(p["background_amount"]) > 0:  # the background in one dark tone
        tone = _luma(a)[..., None] ** 1.2 * _hex(p["background"]) * 1.3 + np.array([0.05, 0.03, 0.02], np.float32)
        out = out + (tone - out) * (1 - mask) * float(p["background_amount"])
    if ctx.alpha is not None and float(p["glow"]) > 0:  # a glowing outline around the player
        m = (ctx.alpha > 0.5).astype(np.uint8)
        k = max(3, int(0.004 * max(h, w)) | 1)
        ring = cv2.dilate(m, np.ones((k, k), np.uint8)).astype(np.float32) - cv2.erode(m, np.ones((k, k), np.uint8))
        ring = cv2.GaussianBlur(ring, (0, 0), k * 0.6)
        halo = cv2.GaussianBlur(ring, (0, 0), k * 3) * 0.6
        light = np.clip(ring + halo, 0, 1)[..., None] * _hex(p["outline"])
        out = blend(np.clip(out, 0, 1), light, "screen", float(p["glow"]))
    return out


@op("paint_splatter", label="Paint splatter and strokes", palette="#ff4fa8,#2fc6ff,#ff8f5a,#e6ff4d,#7a5cff",
    stroke_colors="#ff6f7d,#ff8f5a,#ff4fa8,#2fc6ff", amount=0.85, strokes=0.7, front=0.25)
def paint_splatter(a, p, ctx):
    """Paint splatters, sprays and swooping brush strokes around the player in
    neon colors: mostly behind them; front (0-1) lets some land over their edges."""
    h, w = a.shape[:2]
    scale = min(1.0, 1800 / max(h, w))
    sh, sw = max(16, int(h * scale)), max(16, int(w * scale))
    fx, fy, ph = (v * scale for v in _player(ctx.scene, h, w))
    cy = fy - ph * 0.5
    rng = np.random.default_rng(ctx.seed + 47)
    colors = _palette(p["palette"])
    paint = np.zeros((sh, sw, 3), np.float32)
    cover = np.zeros((sh, sw), np.float32)

    def dab(layer, x, y, r, color, alpha):
        m = np.zeros((sh, sw), np.float32)
        cv2.circle(m, (int(x), int(y)), max(1, int(r)), 1.0, -1, cv2.LINE_AA)
        layer[0][:] = layer[0] + (color - layer[0]) * (m * alpha)[..., None]
        layer[1][:] = np.maximum(layer[1], m * alpha)

    layer = (paint, cover)
    # splatter clusters around the player, each a blob with a spray of droplets
    for _ in range(int(30 * float(p["amount"])) + 6):
        ang = rng.uniform(0, 2 * np.pi)
        dist = ph * rng.uniform(0.15, 0.6)
        x, y = fx + np.cos(ang) * dist * 0.8, cy + np.sin(ang) * dist
        color = colors[rng.integers(len(colors))]
        # an irregular splat: overlapping lobes and a few flung streaks, never a clean disc
        r0 = ph * rng.uniform(0.006, 0.016)
        alpha = rng.uniform(0.7, 1.0)
        for _ in range(rng.integers(4, 9)):
            dab(layer, x + rng.normal(0, r0 * 0.8), y + rng.normal(0, r0 * 0.8), r0 * rng.uniform(0.3, 0.9), color, alpha)
        for _ in range(rng.integers(0, 3)):  # flicked paint: a streak that thins out, ending in a drop
            b = rng.uniform(0, 2 * np.pi)
            length = r0 * rng.uniform(2, 4.5)
            m = np.zeros((sh, sw), np.float32)
            for k in range(4):
                a0, a1 = length * k / 4, length * (k + 1) / 4
                p0 = (int(x + np.cos(b) * a0), int(y + np.sin(b) * a0))
                p1 = (int(x + np.cos(b) * a1), int(y + np.sin(b) * a1))
                cv2.line(m, p0, p1, 1.0, max(1, int(r0 * 0.4 * (1 - k / 4.5))), cv2.LINE_AA)
            cv2.circle(m, (int(x + np.cos(b) * length), int(y + np.sin(b) * length)), max(1, int(r0 * 0.25)), 1.0, -1,
                       cv2.LINE_AA)
            paint[:] = paint + (color - paint) * (m * alpha)[..., None]
            cover[:] = np.maximum(cover, m * alpha)
        for _ in range(rng.integers(25, 70)):
            d = abs(rng.normal(0, ph * 0.09))
            b = rng.uniform(0, 2 * np.pi)
            dab(layer, x + np.cos(b) * d, y + np.sin(b) * d, ph * rng.uniform(0.0012, 0.005), color,
                rng.uniform(0.5, 1.0))
    # fine speckle over the whole area around the player
    n = int(2500 * float(p["amount"]))
    xs = fx + rng.normal(0, ph * 0.45, n)
    ys = cy + rng.normal(0, ph * 0.45, n)
    for x, y in zip(xs, ys):
        if 0 <= x < sw and 0 <= y < sh:
            c = colors[rng.integers(len(colors))]
            r = max(1, int(ph * rng.uniform(0.001, 0.003)))
            cv2.circle(paint, (int(x), int(y)), r, c.tolist(), -1, cv2.LINE_AA)
            cv2.circle(cover, (int(x), int(y)), r, float(rng.uniform(0.5, 0.9)), -1, cv2.LINE_AA)
    # swooping brush strokes: thin arcs sweeping around the player
    strokes = np.zeros((sh, sw), np.float32)
    stroke_color = np.zeros((sh, sw, 3), np.float32)
    stroke_colors = _palette(p["stroke_colors"])
    for _ in range(int(26 * float(p["strokes"]))):
        c = stroke_colors[rng.integers(len(stroke_colors))]
        axes = (int(ph * rng.uniform(0.3, 0.8)), int(ph * rng.uniform(0.12, 0.55)))
        center = (int(fx + rng.normal(0, ph * 0.22)), int(cy + rng.normal(0, ph * 0.22)))
        start = rng.uniform(0, 360)
        thick = max(1, int(ph * rng.uniform(0.003, 0.009)))
        m = np.zeros((sh, sw), np.float32)
        cv2.ellipse(m, center, axes, rng.uniform(0, 180), start, start + rng.uniform(40, 120), 1.0, thick,
                    cv2.LINE_AA)
        m *= rng.uniform(0.6, 1.0)
        stroke_color = stroke_color + (c - stroke_color) * m[..., None]
        strokes = np.maximum(strokes, m)
    paint = paint * (1 - strokes[..., None]) + stroke_color * strokes[..., None]
    cover = np.maximum(cover, strokes)
    paint = cv2.resize(paint, (w, h), interpolation=cv2.INTER_LINEAR)
    cover = cv2.resize(cover, (w, h), interpolation=cv2.INTER_LINEAR)
    behind = 1 - ctx.alpha if ctx.alpha is not None else np.ones((h, w), np.float32)
    where = behind + (1 - behind) * float(p["front"])
    return a + (paint - a) * (np.clip(cover, 0, 1) * where * float(p["amount"]))[..., None]
