"""New backgrounds behind the player, and the expert cut-out tools (brush, refine edge, soft/shift)."""
import numpy as np

from photo_presets import backgrounds, edits, scene


def test_every_background_is_made_at_any_size_in_the_team_color():
    for name in backgrounds.NAMES:
        a = backgrounds.make(name, 120, 150, "#b3121a")
        assert a.shape == (150, 120, 3) and 0 <= a.min() and a.max() <= 1
    big = backgrounds.make("Storm Sky", 3000, 4000)
    assert big.shape == (4000, 3000, 3)


def test_the_player_stays_and_the_background_changes_without_a_fringe():
    img = np.zeros((200, 200, 3), np.float32)
    img[...] = [0.2, 0.7, 0.2]  # grass
    img[50:150, 70:130] = [0.8, 0.1, 0.1]  # the player (red)
    matte = np.zeros((200, 200), np.float32)
    matte[50:150, 70:130] = 1.0
    matte[50:150, 68:70] = 0.5  # a soft edge: half player, half grass, as a camera records it
    img[50:150, 68:70] = 0.5 * np.array([0.8, 0.1, 0.1]) + 0.5 * np.array([0.2, 0.7, 0.2])
    bg = np.zeros((200, 200, 3), np.float32) + [0.1, 0.1, 0.6]
    out = backgrounds.compose(img, matte, bg, wrap=0.0, match=0.0, shadow=0.0)
    assert np.allclose(out[100, 100], [0.8, 0.1, 0.1], atol=0.02)  # the player as they were
    assert np.allclose(out[10, 10], [0.1, 0.1, 0.6], atol=0.02)  # the new background
    assert out[100, 69, 1] < 0.2  # the soft edge: no green from the old grass left in it


def test_a_background_is_kept_in_the_edits_only_when_it_is_one_we_know():
    e = edits.clean({"background": {"src": "Storm Sky", "blur": 2, "color": "#123456"}})
    assert e["background"]["src"] == "Storm Sky" and e["background"]["blur"] == 1.0 and edits.edited(e)
    assert "background" not in edits.clean({"background": {"src": "file:../../etc/passwd"}})
    assert edits.clean({"background": {"src": "file:My Stadium.jpg"}})["background"]["src"] == "file:My Stadium.jpg"


def test_cutout_fixes_are_saved_and_read_back_old_and_new():
    old = scene.Fix.from_json([0.4, 0.5, True])
    stroke = scene.Fix(0.1, 0.2, False, "brush", ((0.1, 0.2), (0.3, 0.4)), 0.02)
    assert old == scene.Fix(0.4, 0.5, True)
    assert scene.Fix.from_json(stroke.to_json()) == stroke
    assert old.to_json() == [0.4, 0.5, True]


def test_brush_soft_and_shift_change_the_cutout():
    m = scene.brush_mask([(0.5, 0.5)], 0.1, (100, 100))
    assert m[50, 50] > 0.95 and m[5, 5] == 0
    disk = np.zeros((200, 200), np.float32)
    disk[60:140, 60:140] = 1
    grown = scene.tune_edge(disk, 0, 1.0)
    shrunk = scene.tune_edge(disk, 0, -1.0)
    soft = scene.tune_edge(disk, 1.0, 0)
    assert grown.sum() > disk.sum() > shrunk.sum()
    assert 0.1 < soft[60, 100] < 0.9  # the edge feathered


def test_refine_edge_brings_in_hair_and_keeps_the_grass_out():
    h = w = 200
    I = np.full((h, w, 3), [0.4, 0.7, 0.3], np.float32)
    yy, xx = np.mgrid[:h, :w]
    I[(xx - 100) ** 2 + (yy - 100) ** 2 < 60 ** 2] = [0.15, 0.1, 0.08]
    for k in range(64, 140, 8):
        I[30:42, k:k + 2] = [0.15, 0.1, 0.08]  # strands of hair above the head
    coarse = ((xx - 100) ** 2 + (yy - 100) ** 2 < 55 ** 2).astype(np.float32)
    out = scene.refine_edge(coarse, I, scene.brush_mask([(0.4, 0.2), (0.6, 0.2)], 0.08, (h, w)), 8)
    assert out[36, 80] > 0.8 and out[36, 84] < 0.2 and out[100, 100] == 1.0 and out[10, 10] == 0.0
