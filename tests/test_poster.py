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


def test_each_players_name_and_number_go_where_the_layout_has_them():
    from photo_presets import poster
    p = poster.with_player(poster.clean({"template": "spotlight"}), name="AIDEN", number="11")
    assert p["title"] == "AIDEN" and p["number"] == "11"
    c = poster.customized({"template": "spotlight"})
    c2 = poster.with_player(c, name="MATEO", number="9")
    texts = {e.get("text") for e in c2["elements"]}
    assert "MATEO" in texts and "9" in texts and "LINCOLN" not in texts
    assert poster.clean({"template": "spotlight", "family": "abc"})["family"] == "abc"


def test_the_photo_and_the_logo_can_be_placed_by_hand():
    import numpy as np
    from photo_presets import poster
    from PIL import Image
    logo = Image.new("RGBA", (40, 40), (255, 0, 0, 255))
    p = poster.clean({"template": "gameday", "logo_at": {"x": 0.25, "y": 0.5, "size": 0.2}, "pic": {"x": 0.1, "zoom": 2}})
    out = poster.compose(np.full((500, 400, 3), 0.3, np.float32), None, p, logo)
    h, w = out.shape[:2]
    assert out[h // 2, w // 4, 0] > 0.9 and out[h // 2, w // 4, 1] < 0.1  # the logo where it was put
    box = next(b for b in poster.words(p, True, logo) if b["key"] == "logo")
    assert abs((box["x0"] + box["x1"]) / 2 - 0.25) < 0.01


def test_a_piece_added_to_a_layout_can_go_behind_the_player():
    """Stripes added to a ready-made layout: on top by default, behind the player when asked."""
    import numpy as np
    from photo_presets import poster
    arr = np.full((500, 400, 3), 0.5, np.float32)
    matte = np.zeros((500, 400), np.float32)
    matte[100:450, 150:250] = 1.0  # the player in the middle
    stripe = {"id": "s1", "type": "stripes", "colors": ["#ff0000", "#ff0000"], "dir": "h", "w": 1.1, "h": 0.1,
              "x": 0.5, "y": 0.5, "opacity": 1.0}
    base = {"template": "gameday", "shape": "post", "title": "", "line": ""}
    front = poster.compose(arr, matte, {**base, "extras": [stripe]})
    behind = poster.compose(arr, matte, {**base, "extras": [{**stripe, "behind": True}]})
    h, w = front.shape[:2]
    mid, side = front[h // 2, w // 2], front[h // 2, w // 10]
    assert mid[0] > 0.8 and mid[1] < 0.2  # on top: red over the player
    assert behind[h // 2, w // 2][0] < 0.7  # behind: the player shows in front
    assert behind[h // 2, w // 10][0] > 0.8 and side[0] > 0.8  # beside the player: the stripe either way


# -- any word in any font, any word or piece at any angle -------------------------------------------

def test_fonts_all_load_and_match_the_page():
    import re
    from pathlib import Path
    from photo_presets import fonts
    for k in fonts.FONTS:
        assert fonts.load(k, 40) is not None, k
        assert fonts.font_file(k)[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"), k
    js = (Path(fonts.__file__).parent / "studio/web/edit.js").read_text()
    block = js[js.index("const FONTS = ["):js.index("]];", js.index("const FONTS = [")) + 3]
    assert re.findall(r'\["([a-z-]+)", "([^"]+)"\]', block) == [(k, v[0]) for k, v in fonts.FONTS.items()]
    assert fonts.angle_ok(190) == -170 and fonts.angle_ok("x") == 0 and fonts.load("nope", 20) is None


def test_layout_word_font_and_angle():
    from photo_presets import poster
    p = poster.clean({"template": "gameday", "moves": {"title": {"r": 30, "f": "script"}, "line": {"f": "comic"}}})
    assert p["moves"] == {"title": {"x": 0, "y": 0, "s": 1, "r": 30.0, "f": "script"}}  # (no such font: dropped)
    w = {x["key"]: x for x in poster.words(p)}
    assert w["title"]["r"] == 30.0 and "r" not in w["line"]
    arr = np.full((500, 400, 3), 0.4, np.float32)
    flat = poster.compose(arr, None, poster.clean({"template": "gameday"}))
    turned = poster.compose(arr, None, p)
    assert np.abs(flat - turned).mean() > 0.003


def test_custom_piece_angle_and_font():
    from photo_presets import custom_poster, poster
    els = custom_poster.clean([{"type": "stripes", "angle": 45, "x": 0.5, "y": 0.5, "w": 0.6, "h": 0.1},
                               {"type": "text", "text": "HI", "font": "impact", "angle": -90},
                               {"type": "card", "angle": 20}])
    assert els[0]["angle"] == 45 and els[1]["font"] == "impact" and els[1]["angle"] == -90 and "angle" not in els[2]
    arr = np.full((500, 400, 3), 0.4, np.float32)
    base = {"template": "custom", "fade_top": 0, "fade_bottom": 0}
    flat = poster.compose(arr, None, poster.clean({**base, "elements": [{**els[0], "angle": 0}]}))
    diag = poster.compose(arr, None, poster.clean({**base, "elements": [els[0]]}))
    H, W = flat.shape[:2]
    # a diagonal band: it reaches above and below where the flat one sits, in its middle column
    col = lambda img: np.abs(img[:, W // 2 - 60] - 0.4).sum(1) > 0.05
    assert col(diag).sum() > col(flat).sum() * 1.2
    assert poster.words(poster.clean({**base, "elements": [els[0]]}))[0]["r"] == 45


def test_photo_text_font_and_angle():
    from photo_presets import edits
    e = edits.clean({"texts": [{"text": "GO", "font": "didot", "angle": 400, "size": 0.1}, {"text": "x", "font": "bad"}]})
    assert e["texts"][0]["font"] == "didot" and e["texts"][0]["angle"] == 40 and "font" not in e["texts"][1]
    arr = np.zeros((300, 300, 3), np.float32)
    a = edits.draw_texts(arr, [{**e["texts"][0], "angle": 0}])
    b = edits.draw_texts(arr, e["texts"][:1])
    assert a.max() > 0.5 and b.max() > 0.5 and not np.allclose(a, b)


def test_customize_keeps_a_words_font_and_angle_and_a_split_name_is_one_piece():
    from photo_presets import poster
    p = poster.clean({"template": "smoke", "moves": {"name": {"r": 15, "f": "brush"}}})
    els = poster.customized(p)["elements"]
    names = [e for e in els if e["type"] == "text" and e["text"] == p["name"]]
    assert len(names) == 1 and names[0]["angle"] == 15 and names[0]["font"] == "brush"


def test_each_layout_keeps_its_own_word_changes():
    from photo_presets import poster
    p = poster.clean({"template": "smoke", "kept_moves": {"storm": {"title": {"r": 5, "f": "impact"}}, "nope": {"title": {"r": 1}}}})
    assert p["kept_moves"] == {"storm": {"title": {"x": 0, "y": 0, "s": 1, "r": 5.0, "f": "impact"}}}
    assert poster.customized(p)["kept_moves"] == p["kept_moves"]


def test_a_word_in_parts_turns_as_one():
    """Smoke Burst's name is two parts (first name, last name): turned, they keep their places
    relative to each other, around the whole name's middle."""
    import cv2
    from photo_presets import poster
    arr = np.zeros((1000, 800, 3), np.float32)
    flat = poster.compose(arr, None, poster.clean({"template": "smoke", "line": "", "title": ""}))
    turned = poster.compose(arr, None, poster.clean({"template": "smoke", "line": "", "title": "", "moves": {"name": {"r": 90}}}))
    H, W = flat.shape[:2]
    a = cv2.rotate(flat.max(2), cv2.ROTATE_90_CLOCKWISE)  # the flat name turned as one picture
    b = turned.max(2)
    mid = poster.middles(poster.words(poster.clean({"template": "smoke", "line": "", "title": ""})))["name"]
    # where the whole name's middle lands: compare the ink around it
    ys, xs = np.nonzero(b > 0.5)
    assert len(ys) and abs(xs.mean() / W - mid[0]) < 0.06 and abs(ys.mean() / H - mid[1]) < 0.12
    assert a.shape[0] == W  # (sanity)
