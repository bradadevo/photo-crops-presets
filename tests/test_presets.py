import json
from pathlib import Path

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
    # faces may take the look's overall tone, but none of its texture
    change = np.asarray(clean, np.int16)[center] - original
    assert (change - change.mean(axis=(0, 1))).std() < 4  # a smooth tone shift, no grain
    assert np.abs(np.asarray(dirty, np.int16)[center] - original).std() > 10
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


def test_gimmicky_overlays_are_left_out(tmp_path):
    folder = tmp_path / "overlays"
    folder.mkdir()
    for name in ("Confetti", "Electricity", "Cartoon FX", "Glitch", "Fireworks", "Smoke"):
        Image.new("RGBA", (10, 10), (255, 255, 255, 255)).save(folder / f"{name}.png")
    lib = Library(Sources([], [], [], [], [str(folder)], []))
    assert lib.ids()["overlay"] == ["overlay:Smoke"]


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


# Premium: layers, skin, clarity, bloom, split toning, depth -------------------------------

def half_matte(h=90, w=120):
    """A 'player' filling the left half."""
    m = np.zeros((h, w), np.float32)
    m[:, : w // 2] = 1
    return m


def test_player_and_background_layers_are_edited_apart(empty_library):
    img = Image.new("RGB", (120, 90), (120, 120, 120))
    scene = Scene(matte=half_matte())
    recipe = {"steps": [{"op": "exposure", "stops": -1, "layer": "background"},
                        {"op": "exposure", "stops": 0.5, "layer": "subject"}]}
    out = np.asarray(pipeline.render(img, recipe, empty_library, scene)[0], np.int16)
    assert out[45, 20, 0] > 140          # player brighter
    assert out[45, 100, 0] < 70          # background darker
    assert pipeline.needs_cutout(recipe)
    assert not pipeline.needs_cutout({"steps": [{"op": "bw"}]})


def test_fog_and_rain_sit_behind_the_player(empty_library):
    img = Image.new("RGB", (120, 90), (40, 60, 40))
    scene = Scene(matte=half_matte())
    for step in ({"op": "fog", "density": 1.0, "height": 1.0}, {"op": "rain", "amount": 1.0}):
        out = np.asarray(pipeline.render(img, {"protect_faces": False, "steps": [step]}, empty_library, scene)[0], np.int16)
        assert np.array_equal(out[:, :60], np.asarray(img, np.int16)[:, :60]), step["op"]  # player untouched
        assert np.abs(out[:, 60:] - np.asarray(img, np.int16)[:, 60:]).max() > 10, step["op"]


def test_fog_is_thicker_low_in_the_frame(empty_library):
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    out = np.asarray(pipeline.render(img, {"steps": [{"op": "fog", "density": 1.0, "height": 0.6, "layer": "all"}]},
                                     empty_library, Scene())[0], np.float32)
    assert out[90:].mean() > out[:10].mean() + 30


def test_skin_keeps_its_color_under_a_color_look(empty_library):
    skin = (196, 140, 110)
    img = Image.new("RGB", (60, 60), skin)
    scene = Scene(people_mask=np.full((60, 60), 255, np.uint8))
    look = [{"op": "duotone", "dark": "#00ffff", "light": "#00ffff", "amount": 1.0}]
    kept = np.asarray(pipeline.render(img, {"skin_protect": 1.0, "steps": look}, empty_library, scene)[0], np.float32)
    lost = np.asarray(pipeline.render(img, {"skin_protect": 0.0, "steps": look}, empty_library, scene)[0], np.float32)
    def hue_ratio(a):
        return a[30, 30, 0] / max(a[30, 30, 2], 1)
    assert abs(hue_ratio(kept) - skin[0] / skin[2]) < 0.15     # still skin colored
    assert hue_ratio(lost) < 0.2                               # turned cyan


def test_split_tone_cools_shadows_and_warms_highlights(empty_library):
    ramp = np.repeat(np.linspace(10, 245, 100, dtype=np.uint8)[None, :, None], 3, axis=2).repeat(10, axis=0)
    out = np.asarray(pipeline.render(Image.fromarray(ramp), {"skin_protect": 0, "steps": [
        {"op": "split_tone", "amount": 1.0, "compress_blacks": 0.5}]}, empty_library, Scene())[0], np.int16)
    dark, light = out[5, 5], out[5, 95]
    assert dark[2] > dark[0]       # blue over red in the shadows
    assert light[0] > light[2]     # red over blue in the highlights
    assert out[5, 0].mean() > ramp[5, 0].mean()  # blacks lifted (compressed)


def test_specular_bloom_glows_highlights_without_touching_midtones(empty_library):
    a = np.full((300, 300, 3), 110, np.uint8)
    a[148:152, 148:152] = 255              # a small specular point
    out = np.asarray(pipeline.render(Image.fromarray(a), {"protect_faces": False, "steps": [
        {"op": "specular_bloom", "amount": 1.0, "threshold": 0.8, "size": 0.05}]}, empty_library, Scene())[0], np.int16)
    assert out[150, 156].mean() > 113      # halo next to the highlight
    assert abs(out[10, 10].mean() - 110) <= 2  # far midtones unchanged
    assert out.max() <= 255


def test_athletic_clarity_adds_micro_contrast_but_leaves_flat_areas(empty_library):
    rng = np.random.default_rng(0)
    a = np.full((100, 100, 3), 128, np.float32)
    a[:, :50] += rng.normal(0, 8, (100, 50, 1))
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    out = np.asarray(pipeline.render(img, {"protect_faces": False, "steps": [
        {"op": "athletic_clarity", "amount": 1.0}]}, empty_library, Scene())[0], np.float32)
    before = np.asarray(img, np.float32)
    assert out[:, 5:45].std() > before[:, 5:45].std() * 1.1   # texture stronger
    assert abs(out[:, 70:].mean() - 128) < 1.5                  # flat area unchanged


def test_cutout_keeps_only_pieces_touching_the_players(monkeypatch):
    import sys
    import types
    from photo_presets import scene as scene_mod
    traced = np.zeros((80, 80), np.uint8)
    traced[10:70, 10:30] = 255   # the player
    traced[10:30, 55:75] = 255   # a sign in the background
    fake = types.SimpleNamespace(remove=lambda img, session=None, only_mask=True: Image.fromarray(traced))
    monkeypatch.setitem(sys.modules, "rembg", fake)
    monkeypatch.setattr(scene_mod, "_session", lambda: None)
    yolo = np.zeros((80, 80), np.uint8)
    yolo[20:60, 12:28] = 255
    alpha = scene_mod.cutout(Image.new("RGB", (80, 80)), yolo)
    assert alpha[40, 20] == 1.0 and alpha[20, 65] == 0.0


def test_preset_form_round_trips_every_starter():
    from photo_presets import presetform

    def key(recipe):
        return sorted((s["op"], pipeline.step_layer(s)) for s in recipe["steps"])
    for name, recipe in presets.STARTERS.items():
        rebuilt = presetform.to_recipe(presetform.from_recipe(recipe))
        assert key(rebuilt) == key(recipe), name


def test_the_ball_joins_the_player_layer():
    from photo_presets.scene import with_balls
    matte = np.zeros((100, 100), np.float32)
    out = with_balls(matte, [(0.8, 0.2, 0.05)])
    assert out[20, 80] == 1.0 and out[80, 20] == 0.0


def test_bloom_skips_pale_colored_kits(empty_library):
    a = np.full((300, 300, 3), 60, np.uint8)
    a[100:200, 20:90] = (175, 226, 229)    # pale teal goalie shirt in sun
    a[100:200, 110:180] = 250              # a big sunlit white area
    a[148:152, 240:244] = 255              # a real specular point
    out = np.asarray(pipeline.render(Image.fromarray(a), {"protect_faces": False, "steps": [
        {"op": "specular_bloom", "amount": 1.0, "threshold": 0.8, "size": 0.05}]}, empty_library, Scene())[0], np.int16)
    assert out[150, 96].mean() - 60 < 3        # no halo beside the shirt
    assert out[150, 186].mean() - 60 < 6       # little beside the big white area
    assert out[150, 249].mean() - 60 > 4       # a glow beside the real highlight


def test_background_blur_does_not_smear_the_player_into_a_halo(empty_library):
    a = np.full((100, 120, 3), 40, np.uint8)
    a[:, :60] = 250                                   # bright player on the left half
    scene = Scene(matte=half_matte())
    out = np.asarray(pipeline.render(Image.fromarray(a), {"protect_faces": False, "steps": [
        {"op": "lens_blur", "radius": 0.05}]}, empty_library, scene)[0], np.int16)
    assert out[50, 64].mean() < 50                    # background beside the player stays dark


def test_faces_follow_a_strong_tone_change_without_its_texture(empty_library):
    img = Image.new("RGB", (200, 200), (90, 90, 90))
    scene = Scene(faces=[(0.5, 0.5, 0.1)])
    # a strong wash (screen white) plus grit: the face must follow the wash, not stay a dark oval
    recipe = {"protect_faces": True, "steps": [
        {"op": "texture", "asset": "generated:grit", "blend": "screen", "opacity": 0.9}]}
    out = np.asarray(pipeline.render(img, recipe, empty_library, scene)[0], np.float32)
    face, around = out[95:105, 95:105], out[20:40, 20:40]
    assert face.mean() > 90 + 30                     # the face follows the wash: no dark patch
    assert face.std() < around.std() * 0.5           # but no texture on the face


def test_face_protection_stops_at_the_player_outline(empty_library):
    img = Image.new("RGB", (200, 200), (90, 90, 90))
    outline = np.zeros((200, 200), np.uint8)
    outline[80:200, 80:120] = 255            # the player's body and head, narrow
    scene = Scene(faces=[(0.5, 0.5, 0.12)], subject_mask=outline)
    recipe = {"steps": [{"op": "texture", "asset": "generated:grit", "blend": "overlay", "opacity": 1.0}]}
    out = np.asarray(pipeline.render(img, recipe, empty_library, scene)[0], np.int16)
    beside_head = out[95:105, 60:70]         # inside the face circle but off the player
    assert beside_head.std() > 5             # gets the texture like the rest of the background


def test_high_key_lifts_dull_photos_more_and_keeps_grass_from_going_white(empty_library):
    def lift(level, color=None):
        a = np.full((60, 60, 3), level, np.uint8)
        if color:
            a[:] = color
        out, _ = pipeline.render(Image.fromarray(a), {"protect_faces": False, "steps": [
            {"op": "high_key", "amount": 0.6}]}, empty_library, Scene())
        return np.asarray(out, np.int16).mean() - a.mean()
    assert lift(80) > lift(150) > 0          # a dull photo is lifted more than a bright one
    assert lift(0) < 2                       # blacks stay deep
    grass = np.full((60, 60, 3), (193, 193, 130), np.uint8)
    out, _ = pipeline.render(Image.fromarray(grass), {"protect_faces": False, "steps": [
        {"op": "high_key", "amount": 0.6}]}, empty_library, Scene())
    assert np.asarray(out).min(axis=(0, 1))[2] < 200   # sunlit grass keeps its color


def test_studio_backdrop_replaces_only_the_background(empty_library):
    img = Image.new("RGB", (80, 80), (120, 200, 90))
    matte = np.zeros((80, 80), np.float32)
    matte[20:60, 30:50] = 1
    recipe = {"protect_faces": False, "steps": [{"op": "backdrop", "top": "#3d86c6", "bottom": "#000000", "glow": 0}]}
    out = np.asarray(pipeline.render(img, recipe, empty_library, Scene(matte=matte))[0], np.int16)
    assert (out[40, 40] == (120, 200, 90)).all()        # the player is untouched
    assert out[2, 5, 2] > out[2, 5, 1] and out[78, 5].max() < 20   # blue at the top, black at the bottom
    same, notes = pipeline.render(img, recipe, empty_library, Scene())
    assert np.asarray(same).tolist() == np.asarray(img).tolist() and notes   # no cut-out: skipped, with a note


def test_several_presets_run_on_every_photo(monkeypatch):
    e = engine.Engine.__new__(engine.Engine)
    calls = []
    monkeypatch.setattr(e, "_one", 
                        lambda path, crop, recipe, seed: calls.append((path.name, recipe["name"])) or engine.Result(
                            path, crop, recipe, seed, None, None))
    ticks = []
    e.presets([Path("a.jpg"), Path("b.jpg")], ["Color Pop", "Dark Mono"], progress=lambda d, t, _: ticks.append((d, t)))
    assert calls == [("a.jpg", "Color Pop"), ("a.jpg", "Dark Mono"), ("b.jpg", "Color Pop"), ("b.jpg", "Dark Mono")]
    assert ticks[-1] == (4, 4)


def test_smoke_sits_behind_the_player_except_floor_smoke_in_front(empty_library):
    img = Image.new("RGB", (200, 200), (20, 20, 20))
    matte = np.zeros((200, 200), np.float32)
    matte[40:190, 80:120] = 1
    scene = Scene(feet=(0.5, 0.95), subject_height=0.75, matte=matte)

    def run(place, front):
        out, _ = pipeline.render(img, {"protect_faces": False, "steps": [
            {"op": "smoke_cloud", "color": "#ffffff", "place": place, "amount": 1.0, "front": front}]},
            empty_library, scene)
        return np.asarray(out, np.int16)
    sides = run("sides", 0.0)
    assert sides[:, :80].max() > 120                      # clouds beside the player
    assert (sides[40:190, 80:120] == 20).all()            # the player is untouched
    assert run("floor", 1.0)[180:190, 80:120].max() > 40  # floor smoke rolls over the feet


def test_vignette_around_the_player_follows_the_outline(empty_library):
    img = Image.new("RGB", (200, 200), (200, 200, 200))
    matte = np.zeros((200, 200), np.float32)
    matte[50:150, 20:60] = 1   # a player at the left
    out = np.asarray(pipeline.render(img, {"protect_faces": False, "steps": [
        {"op": "subject_vignette", "amount": 0.8, "spread": 0.3}]}, empty_library, Scene(matte=matte))[0], np.int16)
    assert out[100, 40].mean() > 190            # the player keeps their light
    assert out[100, 190].mean() < 80            # far from them is dark
    assert out[100, 70].mean() > out[100, 130].mean()   # it falls off with distance from the player


def test_stadium_lights_shine_at_the_sides_behind_the_player(empty_library):
    img = Image.new("RGB", (400, 300), (10, 10, 10))
    matte = np.zeros((300, 400), np.float32)
    matte[60:290, 180:220] = 1
    scene = Scene(feet=(0.5, 0.95), subject_height=0.75, matte=matte)
    out = np.asarray(pipeline.render(img, {"protect_faces": False, "steps": [
        {"op": "stadium_lights", "height": 0.7, "amount": 1.0, "layer": "background"}]},
        empty_library, scene)[0], np.int16)
    y = int(0.95 * 300 - 0.7 * 0.75 * 300)
    assert out[y - 10:y + 10, 20:70].max() > 200 and out[y - 10:y + 10, 330:380].max() > 200  # both banks
    assert (out[60:290, 180:220] == 10).all()           # the player is untouched
    assert out[5, 200].mean() < 60                      # the sky between stays dark


def test_pop_art_paints_the_player_in_neon_and_tones_the_background(empty_library):
    rng = np.random.default_rng(0)
    img = Image.fromarray((rng.random((200, 200, 3)) * 80 + 90).astype(np.uint8))   # dull, mid-gray photo
    matte = np.zeros((200, 200), np.float32)
    matte[30:190, 70:130] = 1
    scene = Scene(feet=(0.5, 0.95), subject_height=0.8, matte=matte)
    out = np.asarray(pipeline.render(img, {"protect_faces": False, "steps": [{"op": "pop_art"}]},
                                     empty_library, scene)[0], np.int16)
    player, background = out[60:160, 85:115], out[10:60, 5:40]
    chroma = lambda a: (a.max(axis=-1) - a.min(axis=-1)).mean()
    assert chroma(player) > 80                                   # vivid neon paint
    assert background.mean() < 0.7 * 135 and chroma(background) < chroma(player) / 2   # darker, muted tone
    assert background[..., 0].mean() > background[..., 2].mean()   # warm (sepia), not cold


def test_paint_splatter_lands_around_the_player(empty_library):
    img = Image.new("RGB", (300, 300), (20, 20, 20))
    matte = np.zeros((300, 300), np.float32)
    matte[40:290, 130:170] = 1
    scene = Scene(feet=(0.5, 0.95), subject_height=0.8, matte=matte)
    out = np.asarray(pipeline.render(img, {"protect_faces": False, "steps": [
        {"op": "paint_splatter", "front": 0.0}]}, empty_library, scene)[0], np.int16)
    painted = (np.abs(out - 20).max(axis=-1) > 30)
    assert painted[:, :130].mean() + painted[:, 170:].mean() > 0.02   # paint around the player
    assert not painted[60:280, 135:165].any()                         # none over them with front 0
