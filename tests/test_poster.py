"""Posters: the layouts, their shapes, and the player in front of the title."""

import numpy as np

from photo_presets import edits, poster


def _picture():
    arr = np.zeros((600, 900, 3), np.float32)
    arr[:] = (0.2, 0.5, 0.2)  # grass
    matte = np.zeros((600, 900), np.float32)
    matte[60:560, 380:520] = 1  # a player
    arr[matte > 0] = (0.9, 0.1, 0.1)  # in red
    return arr, matte


def test_every_layout_has_its_shape():
    arr, matte = _picture()
    for t in poster.TEMPLATES:
        for shape, aspect in poster.SHAPES.items():
            p = poster.clean({"template": t, "shape": shape})
            out = poster.compose(arr, matte, p)
            h, w = out.shape[:2]
            assert abs(w / h - aspect) < 0.01, (t, shape)
            assert (w, h) == poster.size_for(900, 600, p)
            assert 0 <= out.min() and out.max() <= 1


def test_the_player_stands_in_front_of_the_title():
    arr, matte = _picture()
    out = poster.compose(arr, matte, poster.clean({"template": "mvp"}))
    h, w = out.shape[:2]
    top = out[: int(h * 0.25)]
    red = (top[..., 0] > 0.7) & (top[..., 1] < 0.3)
    white = top.min(2) > 0.9
    assert red.any() and white.any()  # the player's red over the white title


def test_poster_edits_change_the_finished_size():
    e = edits.clean({"poster": {"template": "gameday", "shape": "story"}})
    w, h = edits.final_size(900, 600, e)
    assert abs(w / h - 9 / 16) < 0.01
    assert edits.clean({"poster": {"template": "nope"}}) == {}


def test_every_new_layout_draws_its_words_and_keeps_its_size():
    import numpy as np
    from photo_presets import poster
    arr = np.full((400, 300, 3), 0.4, np.float32)
    matte = np.zeros((400, 300), np.float32)
    matte[120:380, 100:200] = 1
    for name in ("name", "goal", "teamcolor", "matchday", "champions"):
        p = poster.clean({"template": name, "shape": "story"})
        out = poster.compose(arr, matte, p, None)
        assert out.shape[:2] == poster.size_for(300, 400, p)[::-1]
        assert out.max() > 0.8  # its title is drawn


def test_each_poster_word_can_be_found_even_when_asked_at_once():
    from concurrent.futures import ThreadPoolExecutor
    from photo_presets import poster
    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(lambda _: poster.words({"template": "gameday"}), range(16)))
    assert all([w["key"] for w in f] == ["title", "line"] for f in found)
    assert poster.words({"template": "gameday", "line": ""})[0]["key"] == "title"  # a word taken off is not there
    assert len(poster.words({"template": "gameday", "line": ""})) == 1


def test_any_poster_word_takes_its_own_color():
    import numpy as np
    from photo_presets import poster
    arr = np.full((400, 300, 3), 0.3, np.float32)
    p = poster.clean({"template": "champions", "colors": {"title": "#c8102e", "nope": "#000000", "line": "red"}})
    assert p["colors"] == {"title": "#c8102e"}  # only real words, only real colors
    out = poster.compose(arr, None, p, None)
    w = poster.words(p)[0]
    H, W = out.shape[:2]
    top = out[int(w["y0"] * H):int(w["y1"] * H), int(w["x0"] * W):int(w["x1"] * W)].reshape(-1, 3)
    red = top[(top[:, 0] > 0.6) & (top[:, 1] < 0.2)]
    assert len(red) > 50  # the title is drawn red, not gold


def test_spotlight_number_is_a_solid_badge_in_front_by_default():
    from photo_presets import poster
    p = poster.clean({"template": "spotlight"})
    assert p["number_style"] == "badge"
    keys = [w["key"] for w in poster.words(p)]
    assert keys[-1] == "number"  # drawn last: in front of everything
    assert poster.clean({"template": "spotlight", "number_style": "behind"})["number_style"] == "behind"


def test_words_and_banners_fit_the_shape_and_the_size_slider():
    from photo_presets import poster
    def banner_height(shape, size=1.0):
        p = poster.clean({"template": "final", "shape": shape, "size": size})
        boxes = {w["key"]: w for w in poster.words(p)}
        return boxes["home_score"]["y1"] - boxes["home_score"]["y0"]  # the score's share of the poster's height
    assert banner_height("story") < banner_height("post") * 0.8  # a tall story: a smaller share of its height
    assert banner_height("post", 0.7) < banner_height("post") * 0.8  # the slider shrinks them
    assert poster.clean({"template": "final", "size": 9})["size"] == 1.5  # within its range
    assert poster.size_for(1000, 1000, poster.clean({"template": "gameday", "shape": "wide"}))[0] > 1000 * 1.5 * 0.5


def test_a_poster_can_be_laid_out_for_any_export_shape():
    from photo_presets import poster
    p = poster.clean({"template": "gameday", "shape": "story", "aspect": 0.8})
    w, h = poster.size_for(800, 1000, p)
    assert abs(w / h - 0.8) < 0.01


def test_words_typed_for_another_layout_are_kept_for_coming_back():
    from photo_presets import poster
    p = poster.clean({"template": "gameday", "kept": {"final": {"home_score": "5", "away_score": "2", "bogus": "x"}, "nope": {"title": "x"}}})
    assert p["kept"] == {"final": {"home_score": "5", "away_score": "2"}}
