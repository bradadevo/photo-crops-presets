"""Edits on a picture after its look: straightening and cropping, parts, text,
white balance, the light sliders, and the brush for removing distractions."""

import numpy as np
import pytest

from photo_presets import edits, pipeline, retouch


def _ramp(h=60, w=90):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.stack([x / w, y / h, np.full((h, w), 0.5, np.float32)], -1)


def test_crop_takes_shares_of_the_picture():
    arr = _ramp()
    out = edits.geometry(arr, {"crop": [0.5, 0.0, 1.0, 0.5]})
    assert out.shape[:2] == (30, 45)
    assert out[0, 0, 0] == pytest.approx(45 / 90)
    assert edits.final_size(90, 60, {"crop": [0.5, 0.0, 1.0, 0.5]}) == (45, 30)


def test_straightening_fills_every_corner():
    arr = np.ones((60, 90, 3), np.float32)
    arr[:, :, 1] = 0  # magenta everywhere: an empty corner would show black
    out = edits.straighten(arr, 8)
    assert out.shape == arr.shape
    assert out[0, 0].sum() > 1.5 and out[-1, -1].sum() > 1.5
    assert edits.cover_scale(90, 60, 0) == 1 and edits.cover_scale(90, 60, 8) > 1


def test_the_middle_stays_put_and_points_follow_the_crop():
    assert edits.map_point(0.5, 0.5, 90, 60, {"angle": 5}) == pytest.approx((0.5, 0.5))
    assert edits.map_point(0.75, 0.25, 90, 60, {"crop": [0.5, 0, 1, 0.5]}) == pytest.approx((0.5, 0.5))
    assert edits.map_box((0.6, 0.6, 0.9, 0.9), 90, 60, {"crop": [0, 0, 0.5, 0.5]}) is None  # cropped away


def test_a_part_changes_only_where_its_mask_is():
    arr = np.full((40, 40, 3), 0.4, np.float32)
    mask = np.zeros((40, 40), np.float32)
    mask[:, 20:] = 1
    out = edits.adjust_part(arr, mask, {"exposure": 1.0})
    assert out[:, :5].mean() == pytest.approx(0.4, abs=0.01)
    assert out[:, 35:].mean() > 0.7


def test_text_is_drawn_where_it_is_placed():
    arr = np.zeros((200, 300, 3), np.float32)
    out = edits.draw_texts(arr, [{"text": "GO", "x": 0.25, "y": 0.5, "size": 0.12, "style": "bold", "color": "#ffffff"}])
    left, right = out[:, :150].max(), out[:, 150:].max()
    assert left > 0.9 and right < 0.1
    banner = edits.draw_texts(arr, [{"text": "3 - 1", "x": 0.5, "y": 0.5, "size": 0.1, "style": "banner"}])
    assert banner.max() > 0.9
    assert edits.draw_texts(arr, [{"text": "  "}]) is arr


def test_white_balance_makes_the_clicked_color_neutral():
    arr = np.zeros((50, 50, 3), np.float32)
    arr[:] = (0.75, 0.70, 0.55)  # a white kit in warm light
    warmth, tint = edits.white_balance(arr, 0.5, 0.5, 0.0, 0.0)
    recipe = {"adjust": {"warmth": warmth, "tint": tint}}
    out, _ = pipeline.finish(arr, arr, recipe, None)
    r, g, b = out[25, 25]
    assert abs(r - b) < 0.02 and abs(g - (r + b) / 2) < 0.03


def test_light_sliders():
    arr = _ramp()
    def run(**adj):
        return pipeline.finish(arr, arr, {"adjust": adj}, None)[0]
    assert run(exposure=1).mean() > arr.mean()
    lum = lambda a: a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    assert lum(run(contrast=1)).std() > lum(arr).std()
    dark = np.full((40, 40, 3), 0.08, np.float32)
    assert pipeline.finish(dark, dark, {"adjust": {"shadows": 1}}, None)[0].mean() > 0.1
    bright = np.full((40, 40, 3), 0.92, np.float32)
    assert pipeline.finish(bright, bright, {"adjust": {"highlights": -1}}, None)[0].mean() < 0.9
    grey = run(saturation=-1)
    assert np.allclose(grey[..., 0], grey[..., 1], atol=1e-4)


def test_the_brush_becomes_a_mask_of_the_photo():
    mask = retouch.stroke_mask([{"pts": [[0.1, 0.5], [0.4, 0.5]], "r": 0.05}], 200, 100)
    assert mask[50, 20:80].all() and not mask[5].any()
    assert retouch.stroke_mask([{"pts": [[0.5, 0.5]], "r": 0.02}], 200, 100)[50, 100]


def test_edits_are_tidied():
    e = edits.clean({"angle": 0, "crop": [0, 0, 1, 1], "texts": [{"text": "x", "style": "nope", "size": 9}]})
    assert "angle" not in e and "crop" not in e
    assert e["texts"][0]["style"] == "clean" and e["texts"][0]["size"] == 0.4
