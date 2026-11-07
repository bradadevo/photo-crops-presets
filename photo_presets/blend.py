"""Photoshop-style blend modes on float images (0-1)."""

import numpy as np


def _soft_light(a, b):
    return np.where(b <= 0.5, a - (1 - 2 * b) * a * (1 - a),
                    a + (2 * b - 1) * (np.where(a <= 0.25, ((16 * a - 12) * a + 4) * a, np.sqrt(a)) - a))


MODES = {
    "normal": lambda a, b: b,
    "multiply": lambda a, b: a * b,
    "screen": lambda a, b: 1 - (1 - a) * (1 - b),
    "overlay": lambda a, b: np.where(a <= 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b)),
    "soft_light": _soft_light,
    "hard_light": lambda a, b: np.where(b <= 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b)),
    "color_dodge": lambda a, b: np.minimum(1, a / np.maximum(1 - b, 1e-3)),
    "color_burn": lambda a, b: 1 - np.minimum(1, (1 - a) / np.maximum(b, 1e-3)),
    "linear_dodge": lambda a, b: np.minimum(1, a + b),
    "difference": lambda a, b: np.abs(a - b),
    "lighten": np.maximum,
    "darken": np.minimum,
}


def blend(base: np.ndarray, layer: np.ndarray, mode: str = "normal", opacity: float = 1.0,
          alpha: np.ndarray | None = None) -> np.ndarray:
    """base and layer are (H, W, 3) or broadcastable floats in 0-1; alpha (H, W)
    is the layer's own transparency."""
    mixed = np.clip(MODES[mode](base, layer), 0, 1)
    weight = opacity if alpha is None else opacity * alpha[..., None]
    return base + (mixed - base) * weight
