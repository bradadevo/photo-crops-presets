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
