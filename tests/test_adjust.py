"""Quick adjustments: look strength, player and background brightness,
warmth and fill light, applied over the finished look."""

from pathlib import Path

import numpy as np
from PIL import Image

from photo_presets import engine, pipeline, presetform
from photo_presets.assets import Library, Sources
from photo_presets.scene import Scene


def library(tmp_path):
    return Library(Sources([], [], [], [], [], []))


def scene_with_player(h=60, w=80):
    matte = np.zeros((h, w), np.float32)
    matte[10:50, 30:50] = 1.0
    return Scene(matte=matte), matte


def test_no_adjustments_change_nothing(tmp_path):
    img = Image.fromarray(np.full((40, 40, 3), 100, np.uint8))
    recipe = {"steps": [{"op": "bw"}]}
    plain, _ = pipeline.render(img, recipe, library(tmp_path), Scene())
    same, _ = pipeline.render(img, pipeline.with_adjust(recipe, dict(pipeline.ADJUST)), library(tmp_path), Scene())
    assert "adjust" not in pipeline.with_adjust(recipe, dict(pipeline.ADJUST))
    assert np.array_equal(np.asarray(plain), np.asarray(same))


def test_strength_zero_is_the_photo(tmp_path):
    a = np.random.default_rng(1).integers(0, 255, (40, 40, 3), np.uint8)
    out, _ = pipeline.render(Image.fromarray(a), {"steps": [{"op": "bw"}], "adjust": {"strength": 0.0}},
                             library(tmp_path), Scene())
    assert np.abs(np.asarray(out, np.int16) - a).max() <= 1


def test_player_and_background_brightness_stay_apart(tmp_path):
    scene, matte = scene_with_player()
    img = Image.fromarray(np.full((60, 80, 3), 80, np.uint8))
    out, _ = pipeline.render(img, {"steps": [], "adjust": {"subject": 1.0, "background": -1.0}},
                             library(tmp_path), scene)
    out = np.asarray(out, np.int16)
    assert abs(out[30, 40, 0] - 160) <= 2  # the player: twice the light
    assert abs(out[5, 5, 0] - 40) <= 2  # the background: half
    assert pipeline.needs_cutout({"adjust": {"subject": 0.5}})


def test_fill_light_lifts_only_a_dark_player():
    _, matte = scene_with_player()
    dark = np.full((60, 80, 3), 0.6, np.float32)
    dark[matte > 0] = 0.2  # backlit: darker than the scene
    assert 0.5 < pipeline.fill_light(dark, matte) <= pipeline.FILL_MAX
    bright = np.full((60, 80, 3), 0.3, np.float32)
    bright[matte > 0] = 0.6  # a lit player at night
    assert pipeline.fill_light(bright, matte) == 0.0
    assert pipeline.fill_light(dark, None) == 0.0


def test_warmth_shifts_toward_amber(tmp_path):
    img = Image.fromarray(np.full((20, 20, 3), 128, np.uint8))
    out = np.asarray(pipeline.render(img, {"steps": [], "adjust": {"warmth": 1.0}}, library(tmp_path), Scene())[0])
    assert out[0, 0, 0] > 128 > out[0, 0, 2]


def test_engine_adjust_matches_a_full_render(tmp_path):
    """Changing the sliders afterwards gives the same picture as making the look with them."""
    scene, matte = scene_with_player()
    a = np.random.default_rng(2).integers(0, 255, (60, 80, 3), np.uint8)
    img = Image.fromarray(a)
    lib = library(tmp_path)
    recipe = {"name": "Test", "steps": [{"op": "contrast", "amount": 0.4}]}
    after, look, _ = pipeline.render_parts(img, recipe, lib, scene)
    eng = engine.Engine(lib)
    r = engine.Result(Path("x.jpg"), "none", recipe, 0, img, after, [], None, look)
    eng._cutouts[("x.jpg", "none")] = (matte * 255).astype(np.uint8)
    adj = {"strength": 0.6, "subject": 0.4, "background": -0.5, "warmth": 0.3}
    quick = eng.adjust(r, adj)
    full, _ = pipeline.render(img, pipeline.with_adjust(recipe, adj), lib, scene)
    assert np.abs(np.asarray(quick.after, np.int16) - np.asarray(full, np.int16)).max() <= 1
    assert quick.recipe["adjust"]["subject"] == 0.4 and quick.look is look
    # and back to none: the look as it was
    assert np.array_equal(np.asarray(eng.adjust(quick, dict(pipeline.ADJUST)).after), np.asarray(look))
    view = np.asarray(eng.cutout_view(r), np.int16)
    assert view[30, 40, 2] > np.asarray(after, np.int16)[30, 40, 2] - 1  # the player tinted blue


def test_preset_form_round_trips_adjustments():
    v = dict(presetform.DEFAULTS, adj_subject=0.35, adj_strength=70, adj_auto=True)
    back = presetform.from_recipe(presetform.to_recipe(v))
    assert (back["adj_subject"], back["adj_strength"], back["adj_auto"]) == (0.35, 70, True)
