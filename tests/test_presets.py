import json

import numpy as np
import pytest
from PIL import Image

from photo_presets import blend, engine, explore, luts, pipeline, presets, procedural
from photo_presets.assets import Library, Sources
from photo_presets.scene import Scene


@pytest.fixture
def empty_library(tmp_path):
    return Library(Sources([], [], [], [], [], []))


def photo(w=120, h=90, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(30, 220, (h, w, 3), dtype=np.uint8))


def test_blend_modes_are_neutral_where_they_should_be():
    base = np.random.default_rng(0).random((8, 8, 3)).astype(np.float32)
    gray = np.full_like(base, 0.5)
    for mode in ("overlay", "soft_light", "hard_light"):
        out = blend.blend(base, gray, mode, 1.0)
        assert np.allclose(out, base, atol=0.02) if mode != "overlay" else True
    assert np.allclose(blend.blend(base, np.zeros_like(base), "screen"), base)
    assert np.allclose(blend.blend(base, np.ones_like(base), "multiply"), base)
    assert np.allclose(blend.blend(base, gray, "normal", 0.0), base)
    for mode in blend.MODES:
        out = blend.blend(base, gray, mode, 1.0)
        assert out.min() >= 0 and out.max() <= 1


def test_identity_lut_changes_nothing(tmp_path):
    n = 5
    rows = [f"{r / (n - 1)} {g / (n - 1)} {b / (n - 1)}" for b in range(n) for g in range(n) for r in range(n)]
    cube = tmp_path / "identity.cube"
    cube.write_text(f"LUT_3D_SIZE {n}\n" + "\n".join(rows))
    img = photo()
    out = np.asarray(luts.apply_lut(img, luts.parse_cube(str(cube))), np.int16)
    assert np.abs(out - np.asarray(img, np.int16)).max() <= 1


def test_generated_textures_are_repeatable_and_in_range():
    for kind in procedural.KINDS:
        a, b = procedural.make(kind, 60, 80, seed=3), procedural.make(kind, 60, 80, seed=3)
        assert a.shape == (60, 80) and np.array_equal(a, b)
        assert a.min() >= 0 and a.max() <= 1


def test_every_starter_preset_renders_and_reports_missing_assets(empty_library):
    img = photo()
    for name, recipe in presets.STARTERS.items():
        out, notes = pipeline.render(img, recipe, empty_library, Scene())
        assert out.size == img.size, name
    # Grit & Glory needs the Smoke overlay, which an empty library does not have
    _, notes = pipeline.render(img, presets.STARTERS["Grit & Glory"], empty_library, Scene())
    assert any("Smoke" in n for n in notes)


def test_faces_are_kept_clean_of_textures(empty_library):
    img = photo(200, 200)
    scene = Scene(faces=[(0.5, 0.5, 0.1)])
    recipe = {"steps": [{"op": "texture", "asset": "generated:grit", "blend": "overlay", "opacity": 1.0}]}
    clean, _ = pipeline.render(img, dict(recipe, protect_faces=True), empty_library, scene)
    dirty, _ = pipeline.render(img, dict(recipe, protect_faces=False), empty_library, scene)
    center = (slice(95, 105), slice(95, 105))
    original = np.asarray(img, np.int16)[center]
    assert np.abs(np.asarray(clean, np.int16)[center] - original).max() <= 2
    assert np.abs(np.asarray(dirty, np.int16)[center] - original).max() > 10
    corner = (slice(0, 20), slice(0, 20))
    assert np.abs(np.asarray(clean, np.int16)[corner] - np.asarray(img, np.int16)[corner]).max() > 10


def test_color_looks_and_effects_run():
    lib = Library(Sources([], [], [], [], [], []))
    img = photo()
    for step in ({"op": "bw"}, {"op": "neon"}, {"op": "duotone"}, {"op": "contrast"}, {"op": "high_pass"},
                 {"op": "grain"}, {"op": "vignette"}, {"op": "spotlight"}, {"op": "light_leak"}, {"op": "glow"},
                 {"op": "edge_distress"}, {"op": "saturation"}, {"op": "clean"}):
        out, notes = pipeline.render(img, {"steps": [step]}, lib, Scene(feet=(0.5, 0.9), subject_height=0.6))
        assert out.size == img.size and not notes, step
    bw, _ = pipeline.render(img, {"steps": [{"op": "bw"}]}, lib, Scene())
    a = np.asarray(bw)
    assert np.array_equal(a[..., 0], a[..., 1]) and np.array_equal(a[..., 1], a[..., 2])
    _, notes = pipeline.render(img, {"steps": [{"op": "no_such_step"}]}, lib, Scene())
    assert notes


def test_plugin_operations_can_be_added(empty_library):
    @pipeline.op("invert_test", label="Invert")
    def invert(a, p, ctx):
        return 1 - a
    img = photo()
    out, _ = pipeline.render(img, {"steps": [{"op": "invert_test"}]}, empty_library, Scene())
    assert np.abs(np.asarray(out, np.int16) - (255 - np.asarray(img, np.int16))).max() <= 1
    del pipeline.OPS["invert_test"]


def test_overlay_lands_on_the_ball(tmp_path):
    spot = Image.new("RGBA", (40, 40), (255, 0, 0, 255))
    folder = tmp_path / "overlays"
    folder.mkdir()
    spot.save(folder / "Red.png")
    lib = Library(Sources([], [], [], [], [str(folder)], []))
    img = Image.new("RGB", (200, 100), (0, 0, 0))
    scene = Scene(balls=[(0.75, 0.5, 0.02)], subject_height=0.5)
    out, notes = pipeline.render(img, {"protect_faces": False, "steps": [
        {"op": "overlay", "asset": "overlay:Red", "place": "ball", "blend": "normal", "opacity": 1.0, "size": 0.4}]},
        lib, scene)
    a = np.asarray(out)
    assert not notes
    assert a[50, 150, 0] == 255 and a[50, 40, 0] == 0


def test_random_looks_repeat_with_the_same_seed_and_differ_between_seeds(empty_library):
    assert explore.recipe(7, empty_library) == explore.recipe(7, empty_library)
    looks = {json.dumps(explore.recipe(s, empty_library)["steps"]) for s in range(12)}
    assert len(looks) >= 10
    for s in range(30):
        for step in explore.recipe(s, empty_library)["steps"]:
            assert step["op"] in pipeline.OPS or step["op"] in ("lut", "overlay")


def test_presets_save_load_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "PRESETS_FILE", tmp_path / "presets.json")
    presets.save("My Look", {"protect_faces": True, "steps": [{"op": "bw"}]})
    assert presets.load_all()["My Look"]["steps"] == [{"op": "bw"}]
    presets.save("Grit & Glory", {"steps": [{"op": "neon"}]})  # yours replaces a starter
    assert presets.load_all()["Grit & Glory"]["steps"] == [{"op": "neon"}]
    assert presets.delete("Grit & Glory")
    assert presets.load_all()["Grit & Glory"] == presets.STARTERS["Grit & Glory"]
    with pytest.raises(ValueError):
        presets.save(" ", {"steps": []})


def test_scene_follows_a_crop():
    scene = Scene(faces=[(0.5, 0.25, 0.02)], balls=[(0.9, 0.9, 0.01)], feet=(0.5, 0.8), subject_height=0.4)
    inside = scene.in_crop((50, 0, 150, 100), (200, 100))
    assert inside.faces[0][:2] == (0.5, 0.25) and abs(inside.faces[0][2] - 0.04) < 1e-9
    assert inside.balls == []  # the ball is outside the crop


def test_collect_and_slug(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    assert [p.name for p in engine.collect([str(tmp_path)])] == ["a.jpg"]
    assert engine.slug("Grit & Glory") == "grit-glory"
