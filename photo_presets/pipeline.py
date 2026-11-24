"""Running a look (a recipe of steps) on a photo.

A recipe is plain JSON:

    {"name": "Grit & Glory", "protect_faces": true,
     "steps": [{"op": "bw", "contrast": 1.5},
               {"op": "texture", "asset": "generated:grit", "blend": "overlay", "opacity": 0.45}]}

Every step names an operation from the registry (OPS). New operations are
added with the @op decorator, here, in effects.py, or in a plugin file in
~/.config/photo-crops-presets/plugins/ (any .py there is loaded at start).

Operations marked protect=True (textures, overlays, grit, glow...) fade away
from faces when the recipe keeps faces clean; color looks (LUTs, B&W, neon)
apply to the whole photo.

Layers: any step can run on the whole photo ("layer": "all"), on the players
only ("subject") or on everything behind them ("background"), using the
players' cut-out (see scene.py). Depth effects (overlays, fog, rain) default
to the background layer: they sit behind the players and in front of the
field, a 3D sandwich in a 2D photo. Without a cut-out, they cover the photo.

Quick adjustments: a recipe's "adjust" (see ADJUST) is applied last, over
the finished look: how strongly the look shows, the player's and the
background's brightness, warmth, and an automatic fill light for a player
darker than the scene around them. They are kept apart from the look (see
finish), so the app can change them instantly.

Skin: color-shifting steps (LUTs, neon, duotone, split-toning) leave skin
tones their own color when the recipe protects skin ("skin_protect", 0-1):
skin takes the look's brightness but keeps its hue.
"""

import importlib.util
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from photo_presets.assets import Library
from photo_presets.scene import Scene, resized

TIMING = bool(os.environ.get("ALLPRO_TIMING"))  # print how long each step takes
PLUGIN_DIR = Path.home() / ".config" / "photo-crops-presets" / "plugins"


class MissingAsset(Exception):
    pass


@dataclass
class Context:
    library: Library
    scene: Scene
    seed: int = 0
    notes: list[str] = field(default_factory=list)
    alpha: np.ndarray | None = None  # the players' cut-out at this image's size, when there is one
    original: np.ndarray | None = None  # the photo before any step (floats), for steps that trace it
    memo: dict | None = None  # results slow steps may reuse (the AI drawings), shared across sizes
    memo_key: tuple | None = None  # what this photo and look are, for the memo


@dataclass
class Op:
    name: str
    fn: Callable[[np.ndarray, dict, Context], np.ndarray]
    protect: bool
    label: str
    defaults: dict
    layer: str = "all"
    color_shift: bool = False
    cutout: bool = False  # uses the players' cut-out itself (ctx.alpha), whatever its layer


OPS: dict[str, Op] = {}


LAYERS = ("all", "subject", "background")
DEFAULT_SKIN_PROTECT = 0.7
# Skin tones in YCrCb (the human skin-tone vector, all skin colors): center and spread
SKIN_CR, SKIN_CB = (153.0, 15.0), (110.0, 14.0)
SKIN_LUMA = (25, 245)


def op(name: str, protect: bool = False, label: str = "", layer: str = "all", color_shift: bool = False,
       cutout: bool = False, **defaults):
    """Registers an operation: fn(image floats HxWx3 in 0-1, params, context) -> image.
    layer is where it runs unless a step says otherwise; color_shift marks
    looks that skin protection applies to; cutout marks operations that use
    the players' cut-out themselves (so it is traced for them)."""
    def register(fn):
        OPS[name] = Op(name, fn, protect, label or name.replace("_", " "), defaults, layer, color_shift, cutout)
        return fn
    return register


def step_layer(step: dict) -> str:
    operation = OPS.get(step.get("op", ""))
    layer = step.get("layer", operation.layer if operation else "all")
    return layer if layer in LAYERS else "all"


def needs_cutout(recipe: dict) -> bool:
    from photo_presets import effects  # noqa: F401
    adj = adjustments(recipe)
    return (bool(adj["subject"] or adj["background"] or adj["auto_fill"] or any(adj[k] for k in PLAYER_KEYS + CURVE_PART_KEYS) or adj["face_light"])
            or any(step_layer(s) != "all" or getattr(OPS.get(s.get("op", "")), "cutout", False)
                   for s in recipe.get("steps", [])))


# Quick adjustments --------------------------------------------------------------------

ADJUST = {
    "strength": 1.0,     # how much of the look shows: 0 = the photo as it was, 1 = the full look
    "subject": 0.0,      # the player's brightness, in stops (+1 doubles the light)
    "background": 0.0,   # the background's brightness, in stops
    "warmth": 0.0,       # -1 cooler (blue) to +1 warmer (amber)
    "auto_fill": False,  # lift a player who is darker than the scene around them
    "exposure": 0.0,     # the whole picture's brightness, in stops
    "contrast": 0.0,     # -1 flatter to +1 punchier
    "highlights": 0.0,   # -1 brings back bright areas (a white kit, the sky), +1 brightens them
    "shadows": 0.0,      # +1 opens up dark areas, -1 deepens them
    "saturation": 0.0,   # -1 black and white to +1 twice as colorful
    "tint": 0.0,         # -1 greener to +1 more magenta (with warmth: the white balance)
    # Advanced: clarity and punch
    "vibrance": 0.0,     # more color where it is dull, skin kept natural
    "clarity": 0.0,      # midtone punch (local contrast)
    "texture": 0.0,      # fine detail: fabric, hair, grass
    "dehaze": 0.0,       # cuts haze and glare (- adds a soft haze)
    "whites": 0.0,       # the brightest tones up or down
    "blacks": 0.0,       # the darkest tones: - deeper, + lifted
    # Advanced: the player and the background (the cut-out)
    "p_clarity": 0.0, "p_vibrance": 0.0, "p_warmth": 0.0, "p_sharpen": 0.0,
    "face_light": 0.0,   # brighter faces (0-1)
    "rim_light": 0.0,    # a soft glow around the player's edge (0-1)
    "bg_blur": 0.0,      # the background soft, like a fast lens (0-1)
    "bg_saturation": 0.0, "bg_warmth": 0.0,
    # Advanced: color
    **{f"mix_{c}_{x}": 0.0 for c in ("red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta") for x in "hsl"},
    "kit_color": "",     # a picked kit color (#rrggbb), made richer by kit_pop
    "kit_pop": 0.0,
    "grade_sh_hue": 210.0, "grade_sh": 0.0, "grade_mid_hue": 30.0, "grade_mid": 0.0, "grade_hi_hue": 40.0, "grade_hi": 0.0,
    # Advanced: finishing
    "noise": 0.0,        # noise reduction (0-1)
    "sharpen": 0.0,      # a final crispness (0-1)
    "vignette": 0.0,     # - darker corners, + lighter
    # Tone curves (see curves.py): points "x,y;x,y" on 0-255, on the whole photo, the players or the background
    **{f"curve_{part}_{ch}": "" for part in ("all", "player", "bg") for ch in ("rgb", "r", "g", "b")},
}
MIX_HUES = {"red": 0, "orange": 30, "yellow": 58, "green": 115, "aqua": 180, "blue": 222, "purple": 272, "magenta": 318}
PLAYER_KEYS = ("p_clarity", "p_vibrance", "p_warmth", "p_sharpen", "rim_light", "bg_blur", "bg_saturation", "bg_warmth")
CURVE_PART_KEYS = tuple(f"curve_{part}_{ch}" for part in ("player", "bg") for ch in ("rgb", "r", "g", "b"))  # (need the cut-out)
FILL_MAX = 0.75  # the most the automatic fill light adds, in stops
FILL_RATIO = 0.85  # it lifts a player until they are this bright next to the background


def adjustments(recipe: dict) -> dict:
    a = recipe.get("adjust") or {}
    return {k: type(v)(a.get(k, v)) for k, v in ADJUST.items()}


def adjusted(recipe: dict) -> bool:
    return adjustments(recipe) != ADJUST


def with_adjust(recipe: dict, adj: dict) -> dict:
    """A copy of the recipe with these adjustments (left out when they change nothing)."""
    out = {k: v for k, v in recipe.items() if k != "adjust"}
    adj = {**ADJUST, **adj}
    changed = {k: v for k, v in adj.items() if v != ADJUST[k]}
    if changed:
        out["adjust"] = changed
    return out


def _brighten(a: np.ndarray, stops: float) -> np.ndarray:
    out = a * 2 ** stops
    return np.where(out > 0.9, 0.9 + 0.1 * np.tanh((out - 0.9) / 0.1), out) if stops > 0 else out


def fill_light(before: np.ndarray, alpha: np.ndarray | None) -> float:
    """Stops of fill light for a player darker than the scene around them
    (backlit, or in shade), measured on the photo before the look; 0 otherwise.

    It compares the player's lit side with the background's, within this
    photo, so it lifts poor light, not anyone's natural skin tone or kit."""
    if alpha is None:
        return 0.0
    lum = before[..., 0] * 0.299 + before[..., 1] * 0.587 + before[..., 2] * 0.114
    player, behind = lum[alpha > 0.6], lum[alpha < 0.1]
    if player.size < 200 or behind.size < 200:
        return 0.0
    p, b = np.percentile(player, 75), np.percentile(behind, 75)
    return float(np.clip(np.log2(FILL_RATIO * b / max(p, 0.02)), 0.0, FILL_MAX))


def finish(before: np.ndarray, look: np.ndarray, recipe: dict, alpha: np.ndarray | None,
           faces: list | None = None) -> tuple[np.ndarray, list[str]]:
    """The look with the recipe's quick adjustments applied (floats 0-1). faces: (x, y, radius) shares
    (x and radius of the width, y of the height), for Face light."""
    adj = adjustments(recipe)
    if adj == ADJUST:
        return look, []
    notes = []
    out = before + (look - before) * float(np.clip(adj["strength"], 0, 1))
    subject, background = adj["subject"], adj["background"]
    if adj["auto_fill"]:
        fill = fill_light(before, alpha)
        subject += fill
        if fill:
            notes.append(f"fill light on the player +{fill:.2f} stops")
    if subject or background:
        if alpha is None:
            notes.append("no player cut-out here, so the player/background brightness was skipped")
        else:
            a = alpha[..., None]
            out = _brighten(out, background) * (1 - a) + _brighten(out, subject) * a
    if adj["dehaze"]:
        out = _dehaze(out, adj["dehaze"])
    out = tone(out, adj)
    out = tone_curves(out, adj, alpha, notes)
    if adj["clarity"] or adj["texture"]:
        out = _local_contrast(out, adj["clarity"], adj["texture"])
    if adj["warmth"]:
        k = 0.08 * adj["warmth"]
        out = out * np.array([1 + k, 1 + k * 0.25, 1 - k], np.float32)
    if adj["tint"]:
        k = 0.06 * adj["tint"]
        out = out * np.array([1 + k * 0.5, 1 - k, 1 + k * 0.5], np.float32)
    if adj["saturation"]:
        lum = (out[..., 0] * 0.299 + out[..., 1] * 0.587 + out[..., 2] * 0.114)[..., None]
        out = lum + (out - lum) * (1 + adj["saturation"])
    out = advanced(out, adj, alpha, faces, notes)
    return np.clip(out, 0, 1).astype(np.float32), notes


# Advanced adjustments ---------------------------------------------------------------------------

def _lum(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    out = cv2.GaussianBlur(a, (0, 0), max(0.5, float(sigma)))
    return out[..., None] if a.ndim == 3 and out.ndim == 2 else out  # (keeps a single channel's axis)


def _dehaze(out: np.ndarray, k: float) -> np.ndarray:
    """Haze lifts the dark tones toward a bright gray: taken back out where it is (+), or added (-)."""
    if k < 0:
        return out * (1 + 0.3 * k) - 0.3 * k * 0.82
    dark = _blur(np.clip(out.min(axis=2), 0, 1), out.shape[1] / 80)  # how hazy each area is
    air = float(np.percentile(_lum(out), 99.5))
    t = np.clip(1 - 0.85 * k * dark / max(air, 0.2), 0.35, 1)[..., None]
    return np.clip((out - air) / t + air, 0, 1.2)


def _local_contrast(out: np.ndarray, clarity: float, texture: float) -> np.ndarray:
    """Clarity: midtone punch over large areas; texture: fine detail. On brightness, so colors keep their hue."""
    lum = np.clip(_lum(out), 0, 1)
    new = lum.copy()
    w = out.shape[1]
    if clarity:
        mid = np.clip(1 - np.abs(lum - 0.5) * 2, 0, 1) ** 0.7  # (spares the deepest shadows and brightest highlights)
        new = new + clarity * 0.7 * (lum - _blur(lum, w / 90)) * mid
    if texture:
        new = new + texture * 1.2 * (lum - _blur(lum, w / 700))
    return out * (np.clip(new, 0, 1.2) / np.maximum(lum, 0.004))[..., None]


def _hsv(out: np.ndarray):
    """Hue (degrees), saturation (0-1) and value of each pixel."""
    hsv = cv2.cvtColor(np.clip(out, 0, 1).astype(np.float32), cv2.COLOR_RGB2HSV)
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def _band(hue: np.ndarray, center: float, width: float) -> np.ndarray:
    d = np.abs((hue - center + 180) % 360 - 180)
    return np.clip(1 - d / width, 0, 1)


def _skin(hue: np.ndarray, sat: np.ndarray) -> np.ndarray:
    return _band(hue, 25, 22) * np.clip(1 - np.abs(sat - 0.4) / 0.35, 0, 1)


def _vibrance(out: np.ndarray, k: float) -> np.ndarray:
    """More color where it is dull (less where it is already rich), skin kept natural."""
    h, s, _ = _hsv(out)
    lum = _lum(out)[..., None]
    gain = k * (1 - s) ** 1.5 * (1 - 0.7 * _skin(h, s)) if k > 0 else k * np.ones_like(s)
    return lum + (out - lum) * (1 + gain)[..., None]


def _hue_rgb(hue: float) -> np.ndarray:
    """A fully saturated color of this hue, with its brightness taken out (to add as a tint)."""
    c = cv2.cvtColor(np.array([[[hue % 360, 1.0, 1.0]]], np.float32), cv2.COLOR_HSV2RGB)[0, 0]
    return c - (c[0] * 0.299 + c[1] * 0.587 + c[2] * 0.114)


def _mixer(out: np.ndarray, adj: dict) -> np.ndarray:
    """Each color on its own: its hue moved, its color stronger or weaker, it lighter or darker."""
    moves = {c: (adj[f"mix_{c}_h"], adj[f"mix_{c}_s"], adj[f"mix_{c}_l"]) for c in MIX_HUES}
    moves = {c: m for c, m in moves.items() if any(m)}
    if not moves:
        return out
    h, s, v = _hsv(out)
    shift, sat, light = np.zeros_like(h), np.ones_like(h), np.ones_like(h)
    weight = np.clip(s / 0.12, 0, 1)  # (grays have no color to change)
    for c, (dh, ds, dl) in moves.items():
        b = _band(h, MIX_HUES[c], 45) * weight
        shift += b * dh * 30
        sat *= 1 + b * ds
        light *= 1 + b * dl * 0.45
    hsv = np.stack([(h + shift) % 360, np.clip(s * sat, 0, 1), np.clip(v * light, 0, 1)], -1).astype(np.float32)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)


def _kit_pop(out: np.ndarray, color: str, k: float) -> np.ndarray:
    """The kit's color (picked on the picture) richer and deeper, nothing else."""
    try:
        rgb = np.array([[[int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]]], np.float32)
    except (ValueError, IndexError):
        return out
    kh, ks, _ = (x[0, 0] for x in _hsv(rgb))
    h, s, v = _hsv(out)
    if ks < 0.12:  # a white or black kit: its brightness, crisper
        b = np.clip(1 - np.abs(v - float(_lum(rgb)[0, 0])) / 0.18, 0, 1) * np.clip(1 - s / 0.2, 0, 1)
        lum = _lum(out)
        return out * (1 + b * k * 0.25 * np.sign(lum - 0.5))[..., None]
    b = _band(h, float(kh), 24) * np.clip(s / 0.15, 0, 1)
    hsv = np.stack([h, np.clip(s * (1 + b * k * 0.8), 0, 1), np.clip(v * (1 - b * max(k, 0) * 0.12), 0, 1)], -1)
    return cv2.cvtColor(hsv.astype(np.float32), cv2.COLOR_HSV2RGB)


def _grade(out: np.ndarray, adj: dict) -> np.ndarray:
    """Color grading: the shadows, midtones and highlights each tinted toward a hue."""
    lum = np.clip(_lum(out), 0, 1)[..., None]
    for key, weight in (("sh", (1 - lum) ** 2), ("mid", 1 - np.abs(lum - 0.5) * 2), ("hi", lum ** 2)):
        amt = adj[f"grade_{key}"]
        if amt:
            out = out + _hue_rgb(adj[f"grade_{key}_hue"]) * weight * amt * 0.22
    return out


def _sharpened(out: np.ndarray, k: float, radius: float) -> np.ndarray:
    lum = _lum(out)
    detail = lum - _blur(lum, radius)
    return out + (k * 1.4 * detail)[..., None]


def _player_parts(out: np.ndarray, adj: dict, alpha: np.ndarray, faces: list | None) -> np.ndarray:
    a = alpha[..., None]
    H, W = out.shape[:2]
    if adj["bg_blur"]:  # the background soft (the player's colors kept out of it: no halo)
        keep = 1 - a
        sigma = adj["bg_blur"] * W / 70
        soft = _blur(out * keep, sigma) / np.maximum(_blur(keep, sigma), 1e-3)
        out = out * (1 - keep) + np.where(keep > 0, soft, out) * keep
    if adj["bg_saturation"] or adj["bg_warmth"]:
        bg = out
        if adj["bg_saturation"]:
            lum = _lum(bg)[..., None]
            bg = lum + (bg - lum) * (1 + adj["bg_saturation"])
        if adj["bg_warmth"]:
            k = 0.08 * adj["bg_warmth"]
            bg = bg * np.array([1 + k, 1 + k * 0.25, 1 - k], np.float32)
        out = out * a + bg * (1 - a)
    if adj["p_clarity"] or adj["p_vibrance"] or adj["p_warmth"] or adj["p_sharpen"]:
        pl = out
        if adj["p_clarity"]:
            pl = _local_contrast(pl, adj["p_clarity"], 0)
        if adj["p_vibrance"]:
            pl = _vibrance(pl, adj["p_vibrance"])
        if adj["p_warmth"]:
            k = 0.08 * adj["p_warmth"]
            pl = pl * np.array([1 + k, 1 + k * 0.25, 1 - k], np.float32)
        if adj["p_sharpen"]:
            pl = _sharpened(pl, adj["p_sharpen"], max(1.0, W / 1200))
        out = out * (1 - a) + pl * a
    if adj["rim_light"]:  # light around the player's edge, like a stadium backlight
        glow = np.clip(_blur(alpha, W / 160) - alpha * 0.85, 0, 1)
        edge = np.clip(alpha - _blur(alpha, W / 400), 0, 1) * 2
        light = np.clip(glow * 0.9 + edge * 0.6, 0, 1)[..., None] * adj["rim_light"]
        out = 1 - (1 - out) * (1 - light * np.array([1.0, 0.97, 0.9], np.float32) * 0.8)
    return out


def _face_light(out: np.ndarray, k: float, faces: list, alpha: np.ndarray | None) -> np.ndarray:
    H, W = out.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    m = np.zeros((H, W), np.float32)
    for x, y, r in faces:
        rr = max(4.0, r * W * 1.25)
        m = np.maximum(m, np.exp(-(((xx - x * W) ** 2 + (yy - y * H) ** 2) / (2 * rr * rr))))
    if alpha is not None:
        m = m * np.clip(alpha * 1.5, 0, 1)
    lifted = _brighten(out, k * 0.7)
    lum = _lum(out)[..., None]
    lifted = lifted + k * 0.12 * (1 - np.clip(lum / 0.5, 0, 1)) * (1 - lifted)  # (shadows on the face open up most)
    return out * (1 - m[..., None]) + lifted * m[..., None]


def _denoise(out: np.ndarray, k: float) -> np.ndarray:
    """Grain and color speckle smoothed, edges kept (strong color noise first: it is the ugliest)."""
    img = np.clip(out, 0, 1).astype(np.float32)
    ycc = cv2.cvtColor(img, cv2.COLOR_RGB2YCrCb)
    W = img.shape[1]
    ycc[..., 1:] = ycc[..., 1:] * (1 - k) + _blur(ycc[..., 1:], max(1.0, W / 500) * (0.5 + k)) * k
    y = ycc[..., 0]
    smooth = cv2.bilateralFilter(y, d=0, sigmaColor=0.02 + 0.06 * k, sigmaSpace=max(1.5, W / 900) * (1 + k))
    ycc[..., 0] = y * (1 - k * 0.85) + smooth * k * 0.85
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)


def _vignette(out: np.ndarray, k: float) -> np.ndarray:
    H, W = out.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 1.414
    edge = np.clip((d - 0.35) / 0.65, 0, 1) ** 1.8
    if k < 0:
        return out * (1 + k * 0.7 * edge)[..., None]
    return 1 - (1 - out) * (1 - k * 0.5 * edge)[..., None]


def advanced(out: np.ndarray, adj: dict, alpha: np.ndarray | None, faces: list | None, notes: list) -> np.ndarray:
    """The Advanced sliders, in a pro order: color, then the player and background, then the finish."""
    if adj["vibrance"]:
        out = _vibrance(out, adj["vibrance"])
    out = _mixer(out, adj)
    if adj["kit_pop"] and adj["kit_color"]:
        out = _kit_pop(out, adj["kit_color"], adj["kit_pop"])
    if adj["grade_sh"] or adj["grade_mid"] or adj["grade_hi"]:
        out = _grade(out, adj)
    if any(adj[k] for k in PLAYER_KEYS):
        if alpha is None:
            notes.append("no player cut-out here, so the player and background settings were skipped")
        else:
            out = _player_parts(out, adj, alpha, faces)
    if adj["face_light"]:
        if faces:
            out = _face_light(out, adj["face_light"], faces, alpha)
        else:
            notes.append("no faces found here, so Face light was skipped")
    if adj["noise"]:
        out = _denoise(out, adj["noise"])
    if adj["sharpen"]:
        out = _sharpened(out, adj["sharpen"], max(0.8, out.shape[1] / 1600))
    if adj["vignette"]:
        out = _vignette(out, adj["vignette"])
    return out


def tone(out: np.ndarray, adj: dict) -> np.ndarray:
    """Exposure, contrast, highlights and shadows, on brightness (colors keep their hue)."""
    ev, con, hi, sh = adj["exposure"], adj["contrast"], adj["highlights"], adj["shadows"]
    wh, bl = adj.get("whites", 0.0), adj.get("blacks", 0.0)
    if not (ev or con or hi or sh or wh or bl):
        return out
    if ev:
        out = _brighten(out, ev)
    lum = np.clip(out[..., 0] * 0.299 + out[..., 1] * 0.587 + out[..., 2] * 0.114, 0, 1)
    new = lum.copy()
    if sh or hi:
        # on the brightness of the area (not each pixel), so detail is kept
        area = cv2.GaussianBlur(lum, (0, 0), max(2.0, lum.shape[1] / 300))
        dark = np.clip(1 - area / 0.5, 0, 1) ** 1.5
        bright = np.clip((area - 0.5) / 0.5, 0, 1) ** 1.5
        new = new + sh * 0.35 * dark * (1 - new) * np.clip(new / 0.04, 0, 1) + hi * 0.3 * bright * np.where(hi < 0, new, 1 - new)
    if con:
        mid = 0.5
        curve = mid + (new - mid) * (1 + con * 0.6)
        new = np.where(con > 0, new + (np.clip(curve, 0, 1) - new) * np.clip(4 * new * (1 - new), 0, 1) ** 0.5, curve)
    if wh:  # the brightest tones (the top quarter) up or down
        new = new + wh * 0.25 * np.clip((new - 0.5) / 0.5, 0, 1) ** 2
    if bl:  # the darkest tones: - deeper, + lifted
        new = new + bl * 0.12 * np.clip(1 - new / 0.45, 0, 1) ** 2
    ratio = np.clip(new, 0, 1.2) / np.maximum(lum, 0.004)
    return out * np.clip(ratio, 0, 4)[..., None]


def tone_curves(out: np.ndarray, adj: dict, alpha: np.ndarray | None, notes: list) -> np.ndarray:
    """The tone curves, right after the basic tone (as in Lightroom): the whole photo's, then the
    players' and the background's (soft edged, from the cut-out)."""
    from photo_presets import curves
    for part in curves.PARTS:
        chans = {ch: adj[f"curve_{part}_{ch}"] for ch in curves.CHANNELS if adj[f"curve_{part}_{ch}"]}
        if not chans:
            continue
        if part == "all":
            out = curves.apply(out, chans)
        elif alpha is None:
            notes.append("no player cut-out here, so the players' and background's curves were skipped")
        else:
            out = curves.apply(out, chans, alpha if part == "player" else 1 - alpha)
    return out


DITHER_TILE = 256


def _dither(h: int, w: int) -> np.ndarray:
    """A fixed, fine noise pattern, the same every time (so the same look
    always gives the same picture). It is under half a level and the same in
    every color: a pixel the look did not change keeps its exact value, and
    grays stay gray; only in-between values are spread, which breaks bands."""
    global _DITHER
    if _DITHER is None:
        rng = np.random.default_rng(0)
        _DITHER = ((rng.random((DITHER_TILE, DITHER_TILE, 1), np.float32) - 0.5) * 0.98)
    reps = (-(-h // DITHER_TILE), -(-w // DITHER_TILE), 1)
    return np.tile(_DITHER, reps)[:h, :w]


_DITHER = None


def matched(arr: np.ndarray, recipe: dict) -> np.ndarray:
    """The photo with its game match applied (see match.py), before the look."""
    from photo_presets import match
    return match.apply(arr, recipe.get("match"))


def to_image(arr: np.ndarray) -> Image.Image:
    """An 8-bit picture from floats 0-1, dithered: a smooth glow, sky or
    shadow gradient comes out smooth instead of in visible bands."""
    h, w = arr.shape[:2]
    return Image.fromarray(np.clip(np.clip(arr, 0, 1) * 255 + 0.5 + _dither(h, w), 0, 255).astype(np.uint8))


def to_array(img: Image.Image | np.ndarray) -> np.ndarray:
    """Floats 0-1 from a picture, or from a 16-bit (uint16) or float array."""
    if isinstance(img, np.ndarray):
        if img.dtype == np.uint16:
            return img.astype(np.float32) / 65535.0
        if img.dtype == np.uint8:
            return img.astype(np.float32) / 255.0
        return img.astype(np.float32)
    return np.asarray(img.convert("RGB"), np.float32) / 255.0


def skin_mask(arr: np.ndarray, people: np.ndarray | None) -> np.ndarray:
    """How skin-toned each pixel is (0-1), inside people's outlines when known."""
    ycc = cv2.cvtColor((np.clip(arr, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2YCrCb).astype(np.float32)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    d = ((cr - SKIN_CR[0]) / SKIN_CR[1]) ** 2 + ((cb - SKIN_CB[0]) / SKIN_CB[1]) ** 2
    m = np.exp(-np.maximum(d - 1, 0) / 2) * ((y > SKIN_LUMA[0]) & (y < SKIN_LUMA[1]))  # full within one spread
    if people is not None:
        grow = max(3, int(max(arr.shape[:2]) * 0.01)) | 1
        m *= cv2.dilate(people, np.ones((grow, grow), np.uint8))
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.5)


def _wide_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """A wide Gaussian blur, done on a smaller copy (same result for smooth
    tone changes, far faster on full-size photos)."""
    scale = min(1.0, 4.0 / sigma)
    if scale >= 1.0:
        return cv2.GaussianBlur(a, (0, 0), sigma)
    h, w = a.shape[:2]
    small = cv2.resize(a, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma * scale)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _keep_skin(before: np.ndarray, after: np.ndarray, skin: np.ndarray, amount: float) -> np.ndarray:
    """Skin keeps its own color but takes the look's brightness."""
    def lum(a):
        return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    relit = before * ((lum(after) + 1e-3) / (lum(before) + 1e-3))[..., None]
    return after + (np.clip(relit, 0, 1) - after) * (skin * amount)[..., None]


def face_mask(scene: Scene, h: int, w: int) -> np.ndarray | None:
    """1 on faces (fully clean in the inner three quarters), fading softly to 0 around them."""
    if not scene.faces:
        return None
    soft = np.zeros((h, w), np.float32)
    core = np.zeros((h, w), np.float32)
    for x, y, r in scene.faces:
        center, radius = (int(x * w), int(y * h)), max(2, int(r * w))
        cv2.circle(soft, center, radius, 1.0, -1)
        cv2.circle(core, center, max(1, int(radius * 0.75)), 1.0, -1)
    biggest = max(r for _, _, r in scene.faces) * w
    return np.maximum(core, np.clip(_wide_blur(soft, max(1.0, biggest * 0.35)), 0, 1))


def render(img: Image.Image, recipe: dict, library: Library, scene: Scene, seed: int = 0,
           memo: dict | None = None, memo_key: tuple | None = None) -> tuple[Image.Image, list[str]]:
    """The photo with the recipe's steps and quick adjustments applied, and notes on any step skipped."""
    after, _, notes = render_parts(img, recipe, library, scene, seed, memo, memo_key)
    return after, notes


def render_parts(img: Image.Image, recipe: dict, library: Library, scene: Scene, seed: int = 0,
                 memo: dict | None = None, memo_key: tuple | None = None) -> tuple[Image.Image, Image.Image, list[str]]:
    """The finished photo, the look before its quick adjustments (so they can
    be changed without making the look again), and notes."""
    before, look, alpha, notes = _steps(img, recipe, library, scene, seed, memo, memo_key)
    look_img = to_image(look)
    if not adjusted(recipe):
        return look_img, look_img, notes
    # adjust the 8-bit look, exactly as a later change to the adjustments does
    done, more = finish(before, to_array(look_img), recipe, alpha, scene.faces)
    return to_image(done), look_img, notes + more


def render_fine(img: Image.Image | np.ndarray, recipe: dict, library: Library, scene: Scene,
                seed: int = 0, memo: dict | None = None, memo_key: tuple | None = None) -> tuple[np.ndarray, list[str]]:
    """The finished photo as floats 0-1, never rounded to 8 bits on the way:
    for full-size exports (pass the 16-bit image when there is one)."""
    before, look, alpha, notes = _steps(img, recipe, library, scene, seed, memo, memo_key)
    if not adjusted(recipe):
        return look, notes
    done, more = finish(before, look, recipe, alpha, scene.faces)
    return done, notes + more


def _steps(img, recipe: dict, library: Library, scene: Scene, seed: int, memo: dict | None = None,
           memo_key: tuple | None = None):
    """The photo before, after the recipe's steps (floats), its cut-out, and notes."""
    from photo_presets import effects  # noqa: F401  (registers the built-in operations)
    load_plugins()
    arr = matched(to_array(img), recipe)  # evened out with the rest of its game, when matched
    before = arr
    h, w = arr.shape[:2]
    mask = face_mask(scene, h, w) if recipe.get("protect_faces", True) else None
    outline = resized(scene.subject_mask, h, w)
    if mask is not None and outline is not None:
        # protection stops at the players' outline, so no ring forms on the background around a head
        mask = mask * cv2.GaussianBlur(outline, (0, 0), max(1.0, 0.003 * max(h, w)))
    face_sigma = max(2.0, max((r for _, _, r in scene.faces), default=0.02) * w * 0.6)
    alpha = resized(scene.matte, h, w)
    skin_amount = float(recipe.get("skin_protect", DEFAULT_SKIN_PROTECT))
    skin = None
    if skin_amount > 0 and any(OPS.get(s.get("op", ""), None) and OPS[s["op"]].color_shift
                               for s in recipe.get("steps", [])):
        people = resized(scene.people_mask, h, w)
        skin = skin_mask(arr, None if people is None else (people > 0.5).astype(np.float32))
    ctx = Context(library, scene, seed, alpha=alpha, original=before, memo=memo, memo_key=memo_key)
    warned = False
    for i, step in enumerate(recipe.get("steps", [])):
        operation = OPS.get(step.get("op", ""))
        if operation is None:
            ctx.notes.append(f"unknown step {step.get('op')!r} skipped")
            continue
        params = {**operation.defaults, **step}
        ctx.seed = seed * 1000 + i
        started = time.perf_counter()
        try:
            out = operation.fn(arr, params, ctx)
        except (MissingAsset, KeyError) as e:
            ctx.notes.append(f"{operation.label} skipped: {e}")
            continue
        took = time.perf_counter() - started
        if TIMING:
            print(f"  step {operation.name}: {took:.1f}s", flush=True)
        if operation.protect and mask is not None:
            # Faces get the step's overall tone and color change but none of its
            # texture, so they stay clean without standing out as patches
            smooth = _wide_blur(out - arr, face_sigma)
            out = out * (1 - mask[..., None]) + (arr + smooth) * mask[..., None]
        if operation.color_shift and skin is not None:
            out = _keep_skin(arr, out, skin, skin_amount)
        layer = step_layer(step)
        if layer != "all":
            if alpha is None:
                if "layer" in step and not warned:  # depth effects quietly cover the photo
                    ctx.notes.append("no player cut-out here, so player/background steps covered the whole photo")
                    warned = True
            elif layer == "subject":
                out = arr + (out - arr) * alpha[..., None]
            else:
                out = out + (arr - out) * alpha[..., None]
        arr = np.clip(out, 0, 1).astype(np.float32)
    return before, arr, alpha, ctx.notes


_plugins_loaded = False


def load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    if not PLUGIN_DIR.is_dir():
        return
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"photo_presets_plugin_{path.stem}", path)
        if spec and spec.loader:
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
