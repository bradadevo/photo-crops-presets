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
    return (bool(adj["subject"] or adj["background"] or adj["auto_fill"])
            or any(step_layer(s) != "all" or getattr(OPS.get(s.get("op", "")), "cutout", False)
                   for s in recipe.get("steps", [])))


# Quick adjustments --------------------------------------------------------------------

ADJUST = {
    "strength": 1.0,     # how much of the look shows: 0 = the photo as it was, 1 = the full look
    "subject": 0.0,      # the player's brightness, in stops (+1 doubles the light)
    "background": 0.0,   # the background's brightness, in stops
    "warmth": 0.0,       # -1 cooler (blue) to +1 warmer (amber)
    "auto_fill": False,  # lift a player who is darker than the scene around them
}
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


def finish(before: np.ndarray, look: np.ndarray, recipe: dict, alpha: np.ndarray | None) -> tuple[np.ndarray, list[str]]:
    """The look with the recipe's quick adjustments applied (floats 0-1)."""
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
    if adj["warmth"]:
        k = 0.08 * adj["warmth"]
        out = out * np.array([1 + k, 1 + k * 0.25, 1 - k], np.float32)
    return np.clip(out, 0, 1).astype(np.float32), notes


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
    return np.maximum(core, cv2.GaussianBlur(soft, (0, 0), max(1.0, biggest * 0.35)))


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
    done, more = finish(before, to_array(look_img), recipe, alpha)
    return to_image(done), look_img, notes + more


def render_fine(img: Image.Image | np.ndarray, recipe: dict, library: Library, scene: Scene,
                seed: int = 0, memo: dict | None = None, memo_key: tuple | None = None) -> tuple[np.ndarray, list[str]]:
    """The finished photo as floats 0-1, never rounded to 8 bits on the way:
    for full-size exports (pass the 16-bit image when there is one)."""
    before, look, alpha, notes = _steps(img, recipe, library, scene, seed, memo, memo_key)
    if not adjusted(recipe):
        return look, notes
    done, more = finish(before, look, recipe, alpha)
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
