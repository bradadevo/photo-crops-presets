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
        {"op": "overlay", "asset": "overlay:Smoke", "place": "feet", "blend": "normal", "opacity": 0.85, "size": 1.4},
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
        {"op": "overlay", "asset": "overlay:Electricity", "place": "ball", "blend": "linear_dodge", "opacity": 1.0, "size": 0.9},
        {"op": "glow", "amount": 0.4, "threshold": 0.65},
        {"op": "vignette", "amount": 0.3},
    ]},
    "Hall of Famer": {"protect_faces": True, "steps": [
        {"op": "lut", "asset": "lut:Hall of Famer", "strength": 0.85},
        {"op": "texture", "asset": "texture:Paper1_Still", "blend": "multiply", "opacity": 0.25},
        {"op": "grain", "amount": 0.25},
        {"op": "vignette", "amount": 0.3},
    ]},
    "Clean Pro": {"protect_faces": True, "steps": [
        {"op": "clean", "strength": "light"},
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
