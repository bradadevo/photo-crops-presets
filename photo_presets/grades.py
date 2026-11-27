"""VS Digital Pro's own pro color grades, made here as real 3D LUTs (.cube files, 33 points a side) so
the same look works in VS Digital Pro, Final Cut Pro, Lightroom or Photoshop. Each grade is a short
list of film-style moves: a tone curve, matte blacks, a highlight roll-off, split toning, and
color moves by hue (the pitch's greens, skin, sky and kit blues), always kind to skin.

    uv run python -m photo_presets.grades     # writes them into photo_presets/luts_builtin/
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).parent / "luts_builtin"
N = 33  # points along each side of the cube

# Hue angles (degrees) in YCbCr's color plane, for the hues sports photos care about
SKIN, RED, YELLOW, GREEN, TEAL, BLUE = 130.0, 103.0, 175.0, -141.0, -68.0, -13.0
GRASS = -168.0  # a sunny pitch: between yellow and green (a + shift greens it, a - shift yellows it)


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float64)


def _ycc(rgb):
    y = rgb @ np.array([0.2126, 0.7152, 0.0722])
    return y, (rgb[:, 2] - y) / 1.8556, (rgb[:, 0] - y) / 1.5748


def _rgb(y, cb, cr):
    r = y + 1.5748 * cr
    b = y + 1.8556 * cb
    g = (y - 0.2126 * r - 0.0722 * b) / 0.7152
    return np.stack([r, g, b], 1)


def _band(angle, center, width=32.0):
    d = (angle - center + 180.0) % 360.0 - 180.0
    return np.exp(-0.5 * (d / width) ** 2)


def _curve(x, contrast=0.0, pivot=0.45):
    """A filmic S-curve: contrast > 0 deepens shadows and brightens highlights around pivot."""
    if not contrast:
        return x
    k = 1.0 + 4.0 * contrast
    lo = pivot * (np.clip(x, 0, None) / pivot) ** k
    hi = 1 - (1 - pivot) * (np.clip(1 - x, 0, None) / (1 - pivot)) ** k
    return np.where(x < pivot, lo, hi)


def grade(rgb: np.ndarray, g: dict) -> np.ndarray:
    """One grade on an (n, 3) array of colors in 0..1."""
    x = rgb.astype(np.float64).copy()
    x = x * 2.0 ** g.get("exposure", 0.0)
    # bleach bypass: the black-and-white copy laid over the color (silvery, harsh, less color)
    if g.get("bleach"):
        y = (x @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
        over = np.where(x < 0.5, 2 * x * y, 1 - 2 * (1 - x) * (1 - y))
        x = x + (over - x) * g["bleach"]
        x = y + (x - y) * (1 - 0.5 * g["bleach"])
    # tone curve on each channel (film's contrast) and the soft highlight roll-off
    # (mostly on brightness, so contrast doesn't turn skin orange; a little per channel, like film)
    x = np.clip(x, 0, 1)
    c, pv = g.get("contrast", 0.0), g.get("pivot", 0.45)
    y0 = (x @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
    by_light = x * (_curve(y0, c, pv) / np.maximum(y0, 1e-4))
    x = 0.7 * by_light + 0.3 * _curve(x, c, pv)
    if g.get("rolloff"):
        k = g["rolloff"]
        x = np.where(x > 0.75, 0.75 + (x - 0.75) * (1 - k * (x - 0.75) / 0.5), x)
    y, cb, cr = _ycc(np.clip(x, 0, 1))
    ang = np.degrees(np.arctan2(cr, cb))
    chroma = np.hypot(cb, cr)
    # color by hue: (center, hue shift in degrees, saturation x, lightness +)
    shift = np.zeros_like(y)
    sat = np.ones_like(y)
    light = np.zeros_like(y)
    for center, dh, ds, dl, *w in g.get("hues", []):
        b = _band(ang, center, w[0] if w else 32.0) * np.clip(chroma / 0.04, 0, 1)
        shift += b * dh
        sat *= 1 + b * (ds - 1)
        light += b * dl
    sat *= g.get("saturation", 1.0)
    # less color in the deep shadows and the brightest highlights (how film behaves)
    sat *= 1 - g.get("shadow_desat", 0.0) * np.clip(1 - y / 0.25, 0, 1)
    sat *= 1 - g.get("highlight_desat", 0.0) * np.clip((y - 0.8) / 0.2, 0, 1)
    # skin keeps its own color whatever the grade does around it
    skin = _band(ang, SKIN, 22.0) * np.clip(chroma / 0.03, 0, 1) * np.clip(1 - np.abs(y - 0.55) / 0.4, 0, 1)
    keep = g.get("skin_keep", 0.6) * skin
    sat = sat + (1 - sat) * keep * (sat < 1) + (np.minimum(sat, 1.12) - sat) * keep * (sat > 1)
    shift *= 1 - keep
    a = np.radians(ang + shift)
    chroma = chroma * sat
    y = y + light * chroma
    x = _rgb(y, chroma * np.cos(a), chroma * np.sin(a))
    # split toning: shadows and highlights each pulled toward a color (skin spared)
    lum = np.clip(x @ np.array([0.2126, 0.7152, 0.0722]), 0, 1)[:, None]
    for key, weight in (("shadows", (1 - lum) ** 2), ("highlights", lum ** 2)):
        if key in g:
            color, amount = g[key]
            c = _hex(color)
            tint = c - (c @ np.array([0.2126, 0.7152, 0.0722]))
            x = x + tint * weight * amount * (1 - 0.6 * skin[:, None])
    # matte: lifted blacks (and softened whites) like a printed film
    lift, gain = g.get("lift", 0.0), g.get("gain", 1.0)
    x = lift + x * (gain - lift)
    return np.clip(x, 0, 1)


def cube(g: dict, title: str) -> str:
    r = np.linspace(0, 1, N)
    b, gg, rr = np.meshgrid(r, r, r, indexing="ij")  # .cube order: red changes fastest
    rgb = np.stack([rr.ravel(), gg.ravel(), b.ravel()], 1)
    out = grade(rgb, g)
    lines = [f'TITLE "{title}"', "# VS Digital Pro pro color grade", f"LUT_3D_SIZE {N}", "DOMAIN_MIN 0.0 0.0 0.0",
             "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in out]
    return "\n".join(lines) + "\n"


# The grades. Names are VS Digital Pro's own.
GRADES: dict[str, dict] = {
    # a premium broadcast look: rich, deep and clean, cool shadows, warm skin, the pitch a true green
    "VS Prime Time": {"contrast": 0.14, "rolloff": 0.5, "saturation": 1.04, "shadow_desat": 0.3,
                       "hues": [(GRASS, 12, 0.85, -0.04, 26), (BLUE, 0, 1.1, 0.0), (RED, 0, 1.06, 0.0)],
                       "shadows": ("#1d3a55", 0.10), "highlights": ("#ffe2c0", 0.04)},
    # late-afternoon sun: amber highlights, a soft roll-off, gently teal shadows (the grass stays green)
    "VS Golden Hour": {"contrast": 0.1, "rolloff": 0.6, "saturation": 0.98,
                        "hues": [(GRASS, 16, 0.78, -0.02, 26), (YELLOW, 0, 0.85, 0.0), (BLUE, 0, 0.9, 0.0)],
                        "shadows": ("#24464f", 0.10), "highlights": ("#ffb256", 0.2), "lift": 0.015, "exposure": 0.04},
    # a night match under the lights: cool and deep, the kits glowing, skin still skin
    "VS Night Match": {"exposure": -0.2, "contrast": 0.2, "saturation": 0.95, "shadow_desat": 0.5,
                        "hues": [(GRASS, 30, 0.6, -0.06, 30), (BLUE, -5, 1.2, 0.02), (TEAL, 0, 1.1, 0.0)],
                        "shadows": ("#0d2440", 0.24), "highlights": ("#d8ecff", 0.06), "rolloff": 0.5},
    # the big-film look: teal shadows and background, warm skin and highlights
    "VS Blockbuster": {"contrast": 0.16, "saturation": 1.0, "rolloff": 0.5,
                        "hues": [(GRASS, 45, 0.7, -0.04, 34), (BLUE, -20, 1.05, 0.0), (YELLOW, -8, 0.9, 0.0)],
                        "shadows": ("#0f4c5c", 0.2), "highlights": ("#ffb070", 0.1)},
    # silvery, harsh and gritty: the bleach-bypass film process
    "VS Bleach Bypass": {"exposure": -0.2, "bleach": 0.55, "contrast": 0.08, "saturation": 0.85, "skin_keep": 0.4,
                          "hues": [(GRASS, 10, 0.8, 0.0, 30)], "shadows": ("#1e2a30", 0.06), "rolloff": 0.6},
    # soft film stock: pastel, warm, lifted blacks, natural greens
    "VS Film Stock": {"contrast": 0.06, "rolloff": 0.7, "saturation": 0.92, "highlight_desat": 0.3,
                       "hues": [(GRASS, 14, 0.8, 0.02, 28), (BLUE, 8, 0.88, 0.02), (RED, 4, 0.95, 0.0)],
                       "shadows": ("#2c3e44", 0.08), "highlights": ("#ffe1bd", 0.07), "lift": 0.05, "gain": 0.97},
    # old slide film: saturated reds and blues, deep contrast, a vintage warmth
    "VS Heritage Chrome": {"contrast": 0.2, "saturation": 1.04, "shadow_desat": 0.2, "rolloff": 0.4,
                            "hues": [(RED, -4, 1.18, -0.03), (BLUE, 6, 1.2, -0.03), (GRASS, 18, 0.8, -0.05, 28),
                                     (YELLOW, 0, 0.85, 0.0)],
                            "highlights": ("#ffe9c4", 0.06), "shadows": ("#231a14", 0.06)},
    # crisp and cold: clean whites, steel-blue shadows, less color
    "VS Ice Cold": {"contrast": 0.12, "saturation": 0.8, "skin_keep": 0.75, "rolloff": 0.5,
                     "hues": [(GRASS, 30, 0.6, 0.0, 30), (BLUE, -8, 1.1, 0.02), (YELLOW, 0, 0.7, 0.0)],
                     "shadows": ("#24435f", 0.16), "highlights": ("#e6f2ff", 0.08)},
    # the pitch at its best: deep, rich greens, punchy kits, true skin
    "VS Lush Pitch": {"contrast": 0.14, "saturation": 1.05, "rolloff": 0.5,
                       "hues": [(GRASS, 14, 0.98, -0.13, 26), (YELLOW, 8, 0.85, 0.0), (BLUE, 0, 1.1, 0.0)],
                       "shadows": ("#14281c", 0.05)},
    # the modern magazine look: muted, matte and calm
    "VS Matte Editorial": {"contrast": 0.1, "saturation": 0.78, "highlight_desat": 0.2, "rolloff": 0.5,
                            "hues": [(GRASS, 12, 0.7, 0.0, 28), (BLUE, 0, 0.85, 0.0)],
                            "shadows": ("#2a3236", 0.08), "highlights": ("#f6ebdc", 0.05), "lift": 0.07, "gain": 0.96},
}


def write_all(folder: Path = HERE) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, g in GRADES.items():
        p = folder / f"{name}.cube"
        p.write_text(cube(g, name))
        out.append(p)
    return out


if __name__ == "__main__":
    for p in write_all():
        print(p)
