"""The custom poster: pieces placed freely, any of them behind the players."""

import numpy as np

from photo_presets import custom_poster, poster


def test_pieces_are_cleaned_and_kept_in_range():
    els = custom_poster.clean([
        {"type": "text", "text": "SEMIS", "style": "nope", "size": 9, "x": 3, "color": "red"},
        {"type": "box", "w": 0.5, "h": 0.2, "opacity": 2},
        {"type": "bogus"},
        {"type": "badge", "text": "123456"},
    ])
    assert [e["type"] for e in els] == ["text", "box", "badge"]
    t = els[0]
    assert t["style"] == "bold" and t["size"] == 0.5 and t["x"] == 1.2 and t["color"] == "#ffffff"
    assert els[1]["opacity"] == 1.0 and els[2]["text"] == "1234"


def test_a_piece_behind_the_players_is_hidden_by_them_and_one_in_front_is_not():
    arr = np.full((500, 400, 3), 0.2, np.float32)
    matte = np.zeros((500, 400), np.float32)
    matte[100:500, 120:280] = 1  # a player in the middle
    big = {"type": "box", "w": 1.0, "h": 0.2, "x": 0.5, "y": 0.5, "color": "#ff0000", "opacity": 1.0}
    for behind, expect_red in ((True, False), (False, True)):
        p = poster.clean({"template": "custom", "fade_top": 0, "fade_bottom": 0, "elements": [dict(big, behind=behind)]})
        out = poster.compose(arr, matte, p, None)
        h, w = out.shape[:2]
        mid = out[h // 2, w // 2]
        assert (mid[0] > 0.8 and mid[1] < 0.2) == expect_red


def test_every_layout_can_become_a_custom_one_with_its_words():
    for t in poster.TEMPLATES:
        if t == "custom":
            continue
        c = poster.customized({"template": t})
        assert c["template"] == "custom"
        texts = " ".join(e.get("text", "") for e in c["elements"])
        title = poster.DEFAULTS[t].get("title")
        if title:
            assert title in texts
        assert {w["key"] for w in poster.words(c)} == {f"el:{e['id']}" for e in c["elements"] if e["type"] != "logo"} | \
            {f"el:{e['id']}" for e in c["elements"] if e["type"] == "logo"}
