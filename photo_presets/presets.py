"""Saved looks ("presets"): named recipes, kept in
~/.config/photo-crops-presets/presets.json. A few starter presets come built
in; saving one with the same name replaces it for you."""

import copy
import json
from pathlib import Path

PRESETS_FILE = Path.home() / ".config" / "photo-crops-presets" / "presets.json"

STARTERS: dict[str, dict] = {
    "Grit & Glory": {"protect_faces": True, "steps": [
        {"op": "bw", "red": 0.6, "green": 0.3, "blue": 0.1, "contrast": 1.5},
        {"op": "high_pass", "radius": 0.006, "amount": 0.8},
        {"op": "overlay", "asset": "overlay:Smoke", "place": "feet", "blend": "normal", "opacity": 0.85, "size": 1.4,
         "layer": "background"},
        {"op": "texture", "asset": "generated:grit", "blend": "overlay", "opacity": 0.45},
        {"op": "edge_distress", "amount": 0.5},
        {"op": "vignette", "amount": 0.35},
    ]},
    "Friday Night Lights": {"protect_faces": True, "steps": [
        {"op": "lut", "asset": "lut:Friday Night Lights", "strength": 0.9},
        {"op": "spotlight", "amount": 0.3},
        {"op": "glow", "amount": 0.3},
        {"op": "grain", "amount": 0.15},
        {"op": "vignette", "amount": 0.4},
    ]},
    "Neon Rush": {"protect_faces": True, "steps": [
        {"op": "neon", "shadows": "#5b1aff", "highlights": "#00f0ff", "amount": 0.7},
        {"op": "high_pass", "radius": 0.005, "amount": 0.5},
        {"op": "specular_bloom", "amount": 0.5, "threshold": 0.8},
        {"op": "glow", "amount": 0.4, "threshold": 0.65},
        {"op": "vignette", "amount": 0.3},
    ]},
    "Hall of Famer": {"protect_faces": True, "steps": [
        {"op": "lut", "asset": "lut:Hall of Famer", "strength": 0.85},
        {"op": "texture", "asset": "texture:Paper1_Still", "blend": "multiply", "opacity": 0.25},
        {"op": "grain", "amount": 0.25},
        {"op": "vignette", "amount": 0.3},
    ]},
    "Stadium Night": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "split_tone", "shadows": "#1f4e79", "highlights": "#ffb347", "amount": 0.6, "compress_blacks": 0.4},
        {"op": "exposure", "stops": -0.7, "layer": "background"},
        {"op": "lens_blur", "radius": 0.004, "layer": "background"},
        {"op": "fog", "density": 0.45, "height": 0.6, "layer": "background"},
        {"op": "exposure", "stops": 0.15, "layer": "subject"},
        {"op": "athletic_clarity", "amount": 0.7, "layer": "subject"},
        {"op": "specular_bloom", "amount": 0.45, "threshold": 0.82},
        {"op": "vignette", "amount": 0.4},
    ]},
    "Rain Game": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "split_tone", "shadows": "#20435c", "highlights": "#d9c7a3", "amount": 0.5, "compress_blacks": 0.3},
        {"op": "saturation", "amount": 0.6, "layer": "background"},
        {"op": "exposure", "stops": -0.6, "layer": "background"},
        {"op": "rain", "amount": 0.6, "angle": 10, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.6, "layer": "subject"},
        {"op": "vignette", "amount": 0.35},
    ]},
    "Clean Pro": {"protect_faces": True, "steps": [
        {"op": "clean", "strength": "light"},
    ]},
    # Editorial looks (clean, no textures), after pro academy/MLS NEXT photography
    "Color Pop": {"protect_faces": True, "steps": [
        {"op": "bw", "red": 0.3, "green": 0.35, "blue": 0.35, "contrast": 1.2, "layer": "background"},
        {"op": "high_key", "amount": 0.35, "layer": "background"},
        {"op": "fog", "color": "#f4f4f4", "density": 0.3, "height": 0.9, "layer": "background"},
        {"op": "saturation", "amount": 1.2, "layer": "subject"},
        {"op": "athletic_clarity", "amount": 0.5, "layer": "subject"},
        {"op": "contrast", "amount": 0.15},
    ]},
    "Studio Backdrop": {"protect_faces": True, "steps": [
        {"op": "backdrop", "top": "#3d86c6", "bottom": "#000000", "glow": 0.5, "layer": "background"},
        {"op": "exposure", "stops": -0.15, "layer": "subject"},
        {"op": "athletic_clarity", "amount": 0.6, "layer": "subject"},
        {"op": "contrast", "amount": 0.2},
        {"op": "grain", "amount": 0.1},
    ]},
    "Shallow Focus": {"protect_faces": True, "steps": [
        {"op": "lens_blur", "radius": 0.012, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.5, "layer": "subject"},
        {"op": "saturation", "amount": 1.15},
        {"op": "contrast", "amount": 0.2},
        {"op": "vignette", "amount": 0.35},
    ]},
    "Bright & Airy": {"protect_faces": True, "steps": [
        {"op": "high_key", "amount": 0.55},
        {"op": "lens_blur", "radius": 0.006, "layer": "background"},
        {"op": "saturation", "amount": 0.8, "layer": "background"},
        {"op": "saturation", "amount": 1.2, "layer": "subject"},
        {"op": "athletic_clarity", "amount": 0.5, "layer": "subject"},
    ]},
    "Mono Editorial": {"protect_faces": True, "steps": [
        {"op": "bw", "red": 0.3, "green": 0.35, "blue": 0.35, "contrast": 1.35},
        {"op": "high_key", "amount": 0.45},
        {"op": "athletic_clarity", "amount": 0.6},
    ]},
    "Vivid Pro": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "high_key", "amount": 0.25},
        {"op": "saturation", "amount": 1.3},
        {"op": "contrast", "amount": 0.2},
        {"op": "lens_blur", "radius": 0.004, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.6, "layer": "subject"},
    ]},
    "Silver Mono": {"protect_faces": True, "steps": [
        {"op": "bw", "red": 0.3, "green": 0.35, "blue": 0.35, "contrast": 1.1},
        {"op": "high_key", "amount": 0.2},
        {"op": "lens_blur", "radius": 0.005, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.5, "layer": "subject"},
    ]},
    "Punch Mono": {"protect_faces": True, "steps": [
        {"op": "bw", "red": 0.3, "green": 0.35, "blue": 0.35, "contrast": 1.6},
        {"op": "athletic_clarity", "amount": 0.8},
    ]},
    "Dark Mono": {"protect_faces": True, "steps": [
        {"op": "bw", "red": 0.4, "green": 0.45, "blue": 0.15, "contrast": 1.4},
        {"op": "exposure", "stops": -1.6, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.6, "layer": "subject"},
        {"op": "vignette", "amount": 0.5},
    ]},
    "Muted Portrait": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "saturation", "amount": 0.75},
        {"op": "split_tone", "shadows": "#2a3d3d", "highlights": "#e8c9a8", "amount": 0.35, "compress_blacks": 0.4},
        {"op": "exposure", "stops": -0.5, "layer": "background"},
        {"op": "lens_blur", "radius": 0.008, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.4, "layer": "subject"},
    ]},
    "Night Portrait": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "exposure", "stops": -1.3, "layer": "background"},
        {"op": "lens_blur", "radius": 0.006, "layer": "background"},
        {"op": "saturation", "amount": 0.7, "layer": "background"},
        {"op": "saturation", "amount": 1.15, "layer": "subject"},
        {"op": "athletic_clarity", "amount": 0.6, "layer": "subject"},
        {"op": "contrast", "amount": 0.2},
        {"op": "vignette", "amount": 0.4},
    ]},
}


def load_all() -> dict[str, dict]:
    """Starters, then your saved presets (yours win on the same name)."""
    out = copy.deepcopy(STARTERS)
    try:
        out.update(json.loads(PRESETS_FILE.read_text()))
    except (OSError, ValueError):
        pass
    return out


def _saved() -> dict[str, dict]:
    try:
        return json.loads(PRESETS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save(name: str, recipe: dict) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Give the preset a name")
    if not isinstance(recipe.get("steps"), list):
        raise ValueError("A preset needs a list of steps")
    saved = _saved()
    saved[name] = {k: v for k, v in recipe.items() if k != "name"}
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(saved, indent=1))


def delete(name: str) -> bool:
    """Deletes your saved preset; a starter comes back as built in."""
    saved = _saved()
    if name not in saved:
        return False
    del saved[name]
    PRESETS_FILE.write_text(json.dumps(saved, indent=1))
    return True
