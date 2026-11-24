"""Field sets: the player stays as they are, the ground is the photo's own grass relit, lines land in
the photo's perspective, and everything behind the field is replaced."""
from types import SimpleNamespace

import numpy as np

from photo_presets import fields, presets


def photo():
    h, w = 400, 600
    img = np.zeros((h, w, 3), np.float32)
    img[:160] = (0.55, 0.7, 0.9)  # sky
    img[160:] = (0.25, 0.55, 0.2)  # grass from row 160 down
    a = np.zeros((h, w), np.float32)
    a[120:360, 280:320] = 1.0  # a player standing at row 360
    img[a > 0] = (0.1, 0.1, 0.3)
    scene = SimpleNamespace(feet=(0.5, 0.9), subject_height=0.6, people_mask=None)
    return img, a, scene, np.full((w,), 160.0, np.float32)


def test_the_player_is_kept_and_the_sky_is_replaced():
    img, a, scene, hz = photo()
    for name, (_, style) in fields.LOOKS.items():
        out = fields.place(img, a, scene, style, 7, hz)
        assert out.shape == img.shape and np.isfinite(out).all()
        inner = np.zeros_like(a, bool)
        inner[140:340, 292:308] = True  # (the player's middle: their edges take the rim light and the wrap)
        assert np.abs(out[inner] - img[inner]).max() < 0.25, name  # the player is theirs
        assert np.abs(out[20:100] - img[20:100]).mean() > 0.1, name  # the old sky is gone


def test_a_line_runs_out_from_under_the_player():
    img, a, scene, hz = photo()
    out = fields.place(img, a, scene, {**fields.LOOKS["Kneel Line"][1], "ambient": 1.0}, 7, hz)
    below = out[385, 250:350].mean(-1)
    assert below.max() - np.median(below) > 0.15  # a bright line in the grass in front of the feet
    assert abs(int(np.argmax(below)) + 250 - 300) < 30  # under the player


def test_field_looks_are_grouped_and_need_the_cut_out():
    from photo_presets import pipeline
    groups = presets.grouped(presets.STARTERS)
    assert set(groups[presets.FIELD]) == set(fields.LOOKS) and len(fields.LOOKS) >= 10
    assert "Gray Day Stadium" not in fields.LOOKS
    for look in fields.LOOKS:
        assert pipeline.needs_cutout(presets.STARTERS[look])
