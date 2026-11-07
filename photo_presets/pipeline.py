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
"""

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from photo_presets.assets import Library
from photo_presets.scene import Scene

PLUGIN_DIR = Path.home() / ".config" / "photo-crops-presets" / "plugins"


class MissingAsset(Exception):
    pass


@dataclass
class Context:
    library: Library
    scene: Scene
    seed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class Op:
    name: str
    fn: Callable[[np.ndarray, dict, Context], np.ndarray]
    protect: bool
    label: str
    defaults: dict


OPS: dict[str, Op] = {}


def op(name: str, protect: bool = False, label: str = "", **defaults):
    """Registers an operation: fn(image floats HxWx3 in 0-1, params, context) -> image."""
    def register(fn):
        OPS[name] = Op(name, fn, protect, label or name.replace("_", " "), defaults)
        return fn
    return register


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
    ctx = Context(library, scene, seed)
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
            out = out * (1 - mask[..., None]) + arr * mask[..., None]
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
