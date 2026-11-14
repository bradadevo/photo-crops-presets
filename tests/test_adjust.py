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
    eng._cutouts[("x.jpg", "none", None)] = (matte * 255).astype(np.uint8)
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


# 16-bit and color ------------------------------------------------------------------------

def test_gradients_are_dithered_not_banded():
    """A slow dark glow covering under 3 levels across 300 px: dithering turns
    its 2-3 flat bands into a fine mix, so the average follows the true ramp."""
    ramp = np.tile(np.linspace(0.02, 0.03, 300, dtype=np.float32)[None, :, None], (40, 1, 3))
    out = np.asarray(pipeline.to_image(ramp), np.float32) / 255
    columns = out.mean(axis=(0, 2))
    assert np.abs(columns - ramp[0, :, 0]).max() < 0.6 / 255
    assert len(np.unique(out[..., 0][:, 150])) >= 2  # mixed, not one flat band
    assert np.array_equal(out[..., 0], out[..., 2])  # grays stay gray


def test_untouched_pixels_keep_their_values():
    a = np.random.default_rng(3).integers(0, 256, (50, 50, 3), np.uint8)
    assert np.array_equal(np.asarray(pipeline.to_image(pipeline.to_array(Image.fromarray(a)))), a)


def test_16_bit_input_and_tiff_export(tmp_path):
    from photo_crops import images
    import tifffile
    fine = (np.linspace(0, 65535, 64 * 48 * 3) % 65536).astype(np.uint16).reshape(48, 64, 3)
    arr = pipeline.to_array(fine)
    assert arr.dtype == np.float32 and abs(arr.max() - fine.max() / 65535) < 1e-6
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "SONY", "ILCE-7M4"
    exif.get_ifd(0x8769)[0x9003] = "2026:11:08 10:30:00"
    dest = tmp_path / "x.tif"
    images.save_tiff16(arr, dest, exif.tobytes())
    back = tifffile.imread(dest)
    assert back.dtype == np.uint16 and np.abs(back.astype(int) - fine).max() <= 1
    with tifffile.TiffFile(dest) as t:
        tags = t.pages[0].tags
        assert tags["Make"].value == "SONY" and "2026:11:08" in tags["DateTime"].value
        assert len(tags["InterColorProfile"].value) > 100
    assert images.load(dest).fine is not None  # read back with its 16 bits


def test_saved_jpegs_carry_srgb_and_other_profiles_are_converted(tmp_path):
    from photo_crops import images
    from PIL import ImageCms
    dest = tmp_path / "a.jpg"
    images.save_jpeg(Image.new("RGB", (8, 8), (200, 40, 40)), dest, None)
    assert Image.open(dest).info.get("icc_profile") == images.srgb_profile()
    assert images.to_srgb(Image.new("RGB", (4, 4), (200, 40, 40)), None).getpixel((0, 0)) == (200, 40, 40)
    # an iPhone-style Display P3 photo: its orange is more saturated than the same numbers in sRGB
    p3 = tmp_path / "p3.jpg"
    Image.new("RGB", (8, 8), (230, 120, 40)).save(p3, quality=100, icc_profile=_display_p3())
    r, g, b = images.load(p3).image.getpixel((0, 0))
    assert r > 240 and b < 30  # converted: redder and deeper than the raw numbers


def _display_p3() -> bytes:
    """A Display P3 profile (from macOS when present, else built: P3 primaries, sRGB curve)."""
    mac = Path("/System/Library/ColorSync/Profiles/Display P3.icc")
    if mac.exists():
        return mac.read_bytes()
    import pytest
    pytest.skip("no Display P3 profile on this machine")


# Fixing the cut-out ----------------------------------------------------------------------

def test_clicks_add_and_take_out_objects(monkeypatch):
    from photo_presets import scene
    h, w = 60, 80

    def fake_segment(img, x, y, size):  # the object under a click: a 10 px square around it
        m = np.zeros(size, np.float32)
        cy, cx = int(y * size[0]), int(x * size[1])
        m[max(0, cy - 5):cy + 5, max(0, cx - 5):cx + 5] = 1
        return m

    monkeypatch.setattr(scene, "segment", fake_segment)
    auto = np.zeros((h, w), np.float32)
    auto[20:40, 30:50] = 1  # the automatic cut-out: one player
    subject = (auto * 255).astype(np.uint8)
    p = scene.Prepared(Path("x.jpg"), Image.new("RGB", (w, h)), scene.Scene(subject_mask=subject), None)
    p._auto = (auto, subject)
    p.ensure_matte()
    assert p.scene.matte[30, 40] == 1 and p.scene.matte[10, 10] == 0
    p.set_fixes([scene.Fix(10 / w, 10 / h, True), scene.Fix(40 / w, 30 / h, False)])
    assert p.scene.matte[10, 10] == 1  # a teammate added
    assert p.scene.matte[30, 40] == 0 and p.scene.matte[22, 32] == 1  # a piece taken out, the rest kept
    assert p.scene.subject_mask[10, 10] == 255
    p.set_fixes([])
    assert np.array_equal(p.scene.matte, auto)  # back to automatic


def test_fixes_stay_with_the_photo(monkeypatch, tmp_path):
    from photo_presets import scene
    calls = []

    def fake_prepare(path, crop="none"):
        calls.append(path)
        return scene.Prepared(path, Image.new("RGB", (40, 30)), scene.Scene(), None)

    monkeypatch.setattr(engine, "prepare", fake_prepare)
    monkeypatch.setattr(scene, "segment", lambda img, x, y, size: np.ones(size, np.float32))
    eng = engine.Engine(library(tmp_path))
    r = engine.Result(Path("a.jpg"), "none", {"name": "T", "steps": []}, 0, Image.new("RGB", (40, 30)),
                      Image.new("RGB", (40, 30)), [], None)
    eng.set_fixes(r, [scene.Fix(0.5, 0.5)])
    assert eng.cutout(r).min() > 0.9
    for i in range(engine.PREPARED_CACHE + 1):  # push the photo out of the cache
        eng.prepared(Path(f"other{i}.jpg"), "none")
    p = eng.prepared(Path("a.jpg"), "none")  # prepared again: its fixes come back
    assert p.fixes == [scene.Fix(0.5, 0.5)] and p.ensure_matte().min() > 0.9
