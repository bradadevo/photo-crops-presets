"""Random exploration: a different, outside-the-box look for every variation.

Each random look is an ordinary recipe built from a seed: one color look
(one of your LUTs, a neon split-tone, a B&W channel mix or a duotone), then
a random mix of detail, textures with random blend modes, an impact overlay
on the ball or the player's feet, lighting and edge effects. The recipe is
shown with every result, so any look you like can be saved as a preset.
"""

import numpy as np

from photo_presets.assets import Library

NEON_PAIRS = [("#5b1aff", "#00f0ff"), ("#ff007a", "#00ffd5"), ("#1a2bff", "#ff8a00"), ("#7a00ff", "#d4ff00"),
              ("#00163a", "#ff3d6e"), ("#2b0040", "#00ff87")]
DUOTONES = [("#0b1d3a", "#ffb347"), ("#1f0033", "#ff4fd8"), ("#0a2a1a", "#c8ff5a"), ("#1b1b1b", "#e8d5b0"),
            ("#00264d", "#7fdbff")]
TEXTURE_BLENDS = ["overlay", "soft_light", "multiply", "screen", "hard_light"]
LEAK_COLORS = ["#ff7a1a", "#ff2e63", "#ffd166", "#7b2ff7", "#00c2ff"]


def _r(rng, lo, hi, digits=2):
    return round(float(rng.uniform(lo, hi)), digits)


def recipe(seed: int, library: Library) -> dict:
    rng = np.random.default_rng(seed)
    ids = library.ids()
    steps = []

    color = rng.choice(["lut", "neon", "bw", "duotone"], p=[0.45, 0.2, 0.2, 0.15] if ids["lut"] else [0, 0.4, 0.35, 0.25])
    if color == "lut":
        steps.append({"op": "lut", "asset": str(rng.choice(ids["lut"])), "strength": _r(rng, 0.6, 1.0)})
    elif color == "neon":
        s, h = NEON_PAIRS[rng.integers(len(NEON_PAIRS))]
        steps.append({"op": "neon", "shadows": s, "highlights": h, "amount": _r(rng, 0.45, 0.85)})
    elif color == "bw":
        w = rng.dirichlet([2, 2, 1])
        steps.append({"op": "bw", "red": round(float(w[0]), 2), "green": round(float(w[1]), 2),
                      "blue": round(float(w[2]), 2), "contrast": _r(rng, 1.1, 1.7)})
    else:
        d, l = DUOTONES[rng.integers(len(DUOTONES))]
        steps.append({"op": "duotone", "dark": d, "light": l, "amount": _r(rng, 0.6, 1.0)})

    if rng.random() < 0.5:
        steps.append({"op": "contrast", "amount": _r(rng, 0.15, 0.45)})
    if rng.random() < 0.4:
        steps.append({"op": "high_pass", "radius": _r(rng, 0.003, 0.01, 4), "amount": _r(rng, 0.4, 0.9)})
    textures = ids["texture"]
    for _ in range(int(rng.integers(0, 3))):
        steps.append({"op": "texture", "asset": str(rng.choice(textures)),
                      "blend": str(rng.choice(TEXTURE_BLENDS)), "opacity": _r(rng, 0.15, 0.5)})
    if ids["overlay"] and rng.random() < 0.45:
        steps.append({"op": "overlay", "asset": str(rng.choice(ids["overlay"])),
                      "place": str(rng.choice(["ball", "feet", "random"], p=[0.5, 0.35, 0.15])),
                      "blend": str(rng.choice(["normal", "linear_dodge", "screen"])),
                      "opacity": _r(rng, 0.75, 1.0), "size": _r(rng, 0.7, 1.4)})
    if rng.random() < 0.25:
        steps.append({"op": "light_leak", "color": str(rng.choice(LEAK_COLORS)),
                      "corner": str(rng.choice(["top_left", "top_right", "bottom_left", "bottom_right"])),
                      "amount": _r(rng, 0.3, 0.7)})
    if rng.random() < 0.3:
        steps.append({"op": "glow", "amount": _r(rng, 0.2, 0.5)})
    if rng.random() < 0.3:
        steps.append({"op": "spotlight", "amount": _r(rng, 0.2, 0.45)})
    if rng.random() < 0.5:
        steps.append({"op": "grain", "amount": _r(rng, 0.1, 0.35)})
    if rng.random() < 0.25:
        steps.append({"op": "edge_distress", "amount": _r(rng, 0.3, 0.8),
                      "color": str(rng.choice(["#000000", "#ffffff"]))})
    if rng.random() < 0.6:
        steps.append({"op": "vignette", "amount": _r(rng, 0.2, 0.5)})
    return {"name": f"Random {seed}", "protect_faces": True, "steps": steps}
