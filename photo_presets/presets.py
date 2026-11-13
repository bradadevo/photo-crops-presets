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
    # Studio smoke portraits (team colors: change them in the preset manager)
    "Smoke Studio": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "backdrop", "top": "#4a1712", "bottom": "#c0161f", "glow": 0.35, "layer": "background"},
        {"op": "smoke_cloud", "color": "#f4f1ee", "place": "sides_floor", "amount": 0.85, "size": 1.0, "front": 0.6},
        {"op": "stage_lights", "count": 2, "amount": 0.8, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.5, "layer": "subject"},
        {"op": "contrast", "amount": 0.15},
    ]},
    "Color Smoke": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "exposure", "stops": -2.2, "layer": "background"},
        {"op": "saturation", "amount": 0.5, "layer": "background"},
        {"op": "smoke_cloud", "color": "#2340ff", "color2": "#d9a520", "place": "sides", "amount": 0.9, "size": 1.1},
        {"op": "athletic_clarity", "amount": 0.6, "layer": "subject"},
        {"op": "contrast", "amount": 0.2},
        {"op": "subject_vignette", "amount": 0.4, "spread": 0.35},
    ]},
    "Stadium Smoke": {"protect_faces": True, "skin_protect": 0.8, "steps": [
        {"op": "exposure", "stops": -2.0, "layer": "background"},
        {"op": "saturation", "amount": 0.35, "layer": "background"},
        {"op": "lens_blur", "amount": 0.006, "layer": "background"},
        {"op": "smoke_cloud", "color": "#d9d9d9", "place": "sides_floor", "amount": 0.85, "size": 1.25, "front": 0.7},
        {"op": "stadium_lights", "height": 0.7, "amount": 0.9, "color": "#fff3dc"},
        {"op": "athletic_clarity", "amount": 0.5, "layer": "subject"},
        {"op": "contrast", "amount": 0.15},
        {"op": "subject_vignette", "amount": 0.3, "spread": 0.4}]},
    "Neon Pop Art": {"protect_faces": False, "skin_protect": 0.0, "steps": [
        {"op": "exposure", "stops": -1.1, "layer": "background"},
        {"op": "lens_blur", "radius": 0.008, "layer": "background"},
        {"op": "pop_art", "levels": 7, "mottle": 0.35, "lines": 0.6, "glow": 0.7, "background": "#9a6a44",
         "background_amount": 0.85},
        {"op": "paint_splatter", "amount": 0.85, "strokes": 0.7, "front": 0.25},
        {"op": "grain", "amount": 0.1}]},
    "Neon Pop Art Sharp": {"protect_faces": False, "skin_protect": 0.0, "steps": [
        {"op": "exposure", "stops": -1.7, "layer": "background"},
        {"op": "lens_blur", "radius": 0.006, "layer": "background"},
        {"op": "pop_art", "crisp": 1.0, "levels": 9, "mottle": 0.12, "lines": 0.8, "glow": 0.6,
         "palette": "#1a0e5c,#4a2fd6,#2fb4ff,#ff3f9a,#ff7a3a,#e2f53c",
         "background": "#9a6a44", "background_amount": 0.9},
        {"op": "paint_splatter", "amount": 0.95, "strokes": 0.7, "front": 0.25, "whips": 1.0}]},
    "Neon Splash": {"protect_faces": False, "skin_protect": 0.0, "steps": [
        {"op": "neon_lineart", "darkness": 0.6, "lines": 1.0, "detail": 0.6, "rim": 1.0, "glow": 0.5},
        {"op": "paint_burst", "amount": 0.9, "size": 1.0, "direction": 0.0},
        {"op": "paint_splatter", "amount": 0.5, "strokes": 0.0, "front": 0.0, "whips": 0.25,
         "palette": "#ff2d95,#ff6a2a,#ffd23f,#7dff4a,#22e6ff,#b14dff",
         "stroke_colors": "#ff2d95,#ffd23f,#22e6ff,#7dff4a"}]},
    "Ice Cream Drip": {"protect_faces": True, "steps": [
        {"op": "high_key", "amount": 0.25, "layer": "background"},
        {"op": "saturation", "amount": 0.85, "layer": "background"},
        {"op": "athletic_clarity", "amount": 0.4, "layer": "subject"},
        {"op": "saturation", "amount": 1.15, "layer": "subject"},
        {"op": "drip", "amount": 0.8, "length": 1.0, "gloss": 0.8, "front": 0.0}]},
    "Player Vignette": {"protect_faces": True, "steps": [
        {"op": "subject_vignette", "amount": 0.6, "spread": 0.3},
        {"op": "contrast", "amount": 0.1},
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


# How the app lists the starters: in groups, each with a one-line description
BOLD, EDITORIAL, STUDIO, MINE = "Bold and dramatic", "Clean editorial", "Studio, smoke and lights", "My presets"
GROUPS = [BOLD, EDITORIAL, STUDIO, MINE]
ABOUT: dict[str, tuple[str, str]] = {
    "Grit & Glory": (BOLD, "Gritty black and white with smoke at the feet and rough edges"),
    "Friday Night Lights": (BOLD, "A night-game color grade, a soft spotlight on the player and film grain"),
    "Neon Rush": (BOLD, "Purple and cyan neon colors with a glow on the highlights"),
    "Hall of Famer": (BOLD, "Vintage color, a paper texture and grain, like a classic trading card"),
    "Stadium Night": (BOLD, "Blue-and-amber night tones, a darker hazy background and a crisp player"),
    "Rain Game": (BOLD, "Cool, moody color with rain falling behind the player"),
    "Clean Pro": (EDITORIAL, "The clean pro edit only: balanced brightness and color, nothing added"),
    "Color Pop": (EDITORIAL, "The player stays in color; the background turns soft black and white"),
    "Studio Backdrop": (EDITORIAL, "Replaces the background with a blue-to-black studio backdrop"),
    "Shallow Focus": (EDITORIAL, "Blurs the background like a fast portrait lens"),
    "Bright & Airy": (EDITORIAL, "Light, bright and clean, with a softly blurred background"),
    "Mono Editorial": (EDITORIAL, "Bright, clean black and white"),
    "Vivid Pro": (EDITORIAL, "Rich, saturated color with crisp detail and natural skin"),
    "Silver Mono": (EDITORIAL, "Soft, silvery black and white"),
    "Punch Mono": (EDITORIAL, "High-contrast black and white with strong detail"),
    "Dark Mono": (EDITORIAL, "Black and white with a near-black background"),
    "Muted Portrait": (EDITORIAL, "Soft, muted film tones with a darker, blurred background"),
    "Night Portrait": (EDITORIAL, "A dark, blurred background so the player glows"),
    "Smoke Studio": (STUDIO, "Red studio backdrop, white smoke at the sides and feet, lights above"),
    "Color Smoke": (STUDIO, "Night background with two-color smoke bombs (blue and gold)"),
    "Stadium Smoke": (STUDIO, "Night stadium with smoke at the sides and feet and floodlights"),
    "Neon Pop Art": (BOLD, "The player as a neon pop-art painting with paint splatters, on a dark sepia background"),
    "Neon Pop Art Sharp": (BOLD, "Neon Pop Art with crisp, screen-print edges and thin ink lines"),
    "Neon Splash": (BOLD, "The player as glowing neon line art on black, with a paint explosion behind them"),
    "Ice Cream Drip": (STUDIO, "Glossy melting ice cream (vanilla, strawberry, mint, chocolate) dripping behind the player"),
    "Player Vignette": (STUDIO, "Darkens the photo gently outward from the player's outline"),
}


def describe(name: str, recipe: dict | None = None) -> str:
    """A preset's one-line description: the one you saved, else the starter's."""
    if recipe and recipe.get("description"):
        return str(recipe["description"])
    return ABOUT.get(name, (MINE, ""))[1]


def grouped(all_presets: dict[str, dict] | None = None) -> dict[str, list[str]]:
    """Preset names by group (your own presets last, under My presets)."""
    out: dict[str, list[str]] = {g: [] for g in GROUPS}
    for name in all_presets if all_presets is not None else load_all():
        out[ABOUT.get(name, (MINE, ""))[0]].append(name)
    return out
