"""How long each look takes to make, so the app can say so before you start.

Each preset has a time measured on this Mac (a 24 MP game photo, preview size,
models already loaded). Real runs then teach it: every look you make updates
its preset's time (a running average, kept in timings.json), so the numbers
follow your Mac and your photos. Two one-off costs come on top: getting a photo
ready (reading it, finding the players, cutting them out) and, for the first AI
illustration look of a session, loading the drawing models.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG = Path("~/.config/photo-crops-presets").expanduser()
LEARNED = CONFIG / "timings.json"

PHOTO_READY = 4.0  # seconds to get a photo ready (read it, find the players), once per photo
CUT_OUT = 18.0  # seconds to cut out its players, once per photo, for the looks that need it
MODEL_LOAD = 60.0  # seconds to load the AI drawing models, once per session
QUICK, CUTOUT, DRAWN = 2.0, 4.0, 20.0  # guesses for a look with no time yet

# measured on an M5 MacBook Pro (seconds per photo, preview size; 24 MP JPEG, models loaded)
MEASURED: dict[str, float] = {
    "Grit & Glory": 0.7,
    "Friday Night Lights": 0.5,
    "Neon Rush": 0.8,
    "Hall of Famer": 0.5,
    "Stadium Night": 0.7,
    "Rain Game": 0.5,
    "Clean Pro": 0.5,
    "Color Pop": 0.5,
    "Studio Backdrop": 0.5,
    "Shallow Focus": 0.5,
    "Bright & Airy": 0.5,
    "Mono Editorial": 0.5,
    "Vivid Pro": 0.5,
    "Silver Mono": 0.5,
    "Punch Mono": 0.5,
    "Dark Mono": 0.5,
    "Muted Portrait": 0.5,
    "Night Portrait": 0.5,
    "Smoke Studio": 0.5,
    "Color Smoke": 0.5,
    "Stadium Smoke": 0.5,
    "Neon Pop Art": 0.6,
    "Neon Pop Art Sharp": 0.8,
    "Neon Pop Art Sharp Black": 0.9,
    "Neon Splash": 0.5,
    "Neon Streaks": 0.5,
    "Player Vignette": 0.5,
    "Watercolor Ink & Wash": 24.7,
    "Watercolor Rainbow Silhouette": 0.7,
    "Watercolor Team Splash": 25.0,
    "Watercolor Stadium": 24.9,
    "Anime Sky Hero": 21.6,
    "Anime Sunset": 21.6,
    "Anime Speed Lines": 22.0,
    "Anime Night Lights": 22.8,
    "Oil Dark Studio": 20.7,
    "Oil Golden Hour": 21.2,
    "Oil Palette Knife": 21.8,
    "Oil Old Master": 19.9,
    "Comic Hero Burst": 21.7,
    "Comic Pop Art": 22.2,
    "Comic Noir Ink": 21.7,
    "Manga Action": 22.0,
    "Pencil Graphite": 21.9,
    "Pencil Charcoal": 22.0,
    "Pencil Colored": 21.9,
    "Pen and Ink": 22.0,
}


def uses_ai(recipe: dict) -> bool:
    """Does the look draw with the AI model (comic_redraw)?"""
    return any(st.get("op") == "comic_redraw" for st in recipe.get("steps", []))


def _guess(recipe: dict) -> float:
    from . import pipeline
    if uses_ai(recipe):
        return DRAWN
    return CUTOUT if pipeline.needs_cutout(recipe) else QUICK


def _learned() -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(LEARNED.read_text()).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def seconds(name: str, recipe: dict) -> float:
    """About how long one photo takes in this look (ready photo, models loaded)."""
    return _learned().get(name) or MEASURED.get(name) or _guess(recipe)


def learn(name: str, took: float) -> None:
    """A real look's time, folded into its preset's average."""
    if not name or took <= 0:
        return
    known = _learned()
    old = known.get(name) or MEASURED.get(name)
    known[name] = round(took if old is None else 0.6 * old + 0.4 * took, 1)
    try:
        CONFIG.mkdir(parents=True, exist_ok=True)
        LEARNED.write_text(json.dumps(known, indent=1, sort_keys=True))
    except OSError:
        pass


def models_loaded() -> bool:
    from . import comic
    return bool(comic._pipes)


def run_seconds(looks: list[tuple[str, dict]], photos: int, ready: int = 0) -> float:
    """A whole run: each (name, recipe) look, plus getting `photos` photos ready
    (`ready` of them already are) and loading the models if an AI look needs them."""
    from . import pipeline
    total = sum(seconds(n, r) for n, r in looks) + PHOTO_READY * max(0, photos - ready)
    if any(pipeline.needs_cutout(r) for _, r in looks):
        total += CUT_OUT * max(0, photos - ready)
    if any(uses_ai(r) for _, r in looks) and not models_loaded():
        total += MODEL_LOAD
    return total


def say(sec: float) -> str:
    """'about 20 s', 'about 3 min'."""
    if sec < 10:
        return f"about {max(1, round(sec))} s"
    if sec < 90:
        return f"about {round(sec / 5) * 5} s"
    return f"about {round(sec / 60)} min"
