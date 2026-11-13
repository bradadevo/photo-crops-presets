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

Skin: color-shifting steps (LUTs, neon, duotone, split-toning) leave skin
tones their own color when the recipe protects skin ("skin_protect", 0-1):
skin takes the look's brightness but keeps its hue.
"""

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from photo_presets.assets import Library
from photo_presets.scene import Scene, resized

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
    return any(step_layer(s) != "all" or getattr(OPS.get(s.get("op", "")), "cutout", False)
               for s in recipe.get("steps", []))


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


def render(img: Image.Image, recipe: dict, library: Library, scene: Scene, seed: int = 0) -> tuple[Image.Image, list[str]]:
    """The photo with the recipe's steps applied, and notes on any step skipped."""
    from photo_presets import effects  # noqa: F401  (registers the built-in operations)
    load_plugins()
    arr = np.asarray(img.convert("RGB"), np.float32) / 255.0
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
    ctx = Context(library, scene, seed, alpha=alpha)
    warned = False
    for i, step in enumerate(recipe.get("steps", [])):
        operation = OPS.get(step.get("op", ""))
        if operation is None:
            ctx.notes.append(f"unknown step {step.get('op')!r} skipped")
            continue
        params = {**operation.defaults, **step}
        ctx.seed = seed * 1000 + i
        try:
            out = operation.fn(arr, params, ctx)
        except (MissingAsset, KeyError) as e:
            ctx.notes.append(f"{operation.label} skipped: {e}")
            continue
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
    return Image.fromarray((arr * 255 + 0.5).astype(np.uint8)), ctx.notes


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
