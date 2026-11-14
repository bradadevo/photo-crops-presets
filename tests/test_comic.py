"""AI illustration helpers: framing, background matching, detail spots (no model needed)."""

import numpy as np

from photo_presets import comic, engine
from photo_presets.scene import Scene


def scene_with(box, w=1000, h=800, balls=()):
    m = np.zeros((h, w), np.uint8)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = 255
    return Scene(subject_mask=m, balls=list(balls), hands=[(0.5, 0.5, 0.01)])


def test_frames_are_portraits_around_the_players_and_ball():
    s = scene_with((450, 300, 550, 600))
    x0, y0, x1, y1 = engine.frame_box(s, 1000, 800, 0.8, 0.8)
    assert abs((x1 - x0) / (y1 - y0) - 0.8) < 0.01
    assert x0 <= 450 and x1 >= 550 and y0 <= 300 and y1 >= 600
    assert abs((600 - 300) / (y1 - y0) - 0.8) < 0.02  # they fill 80% of the height
    with_ball = scene_with((450, 300, 550, 600), balls=[(0.62, 0.72, 0.02)])
    bx0, by0, bx1, by1 = engine.frame_box(with_ball, 1000, 800, 0.8, 0.8)
    assert bx1 >= 0.64 * 1000 and by1 >= 0.72 * 800 + 0.02 * 1000  # the ball stays in
    assert engine.frame_box(Scene(), 1000, 800, 0.8, 0.8) is None


def test_clicks_map_between_frame_and_photo():
    frame = (0.2, 0.1, 0.6, 0.9)
    x, y = engine.from_frame(frame, 0.5, 0.5)
    assert (round(x, 6), round(y, 6)) == (0.4, 0.5)
    assert tuple(round(v, 6) for v in engine.to_frame(frame, x, y)) == (0.5, 0.5)
    assert engine.from_frame(None, 0.3, 0.7) == (0.3, 0.7)


def test_the_drawings_paper_is_matched_to_the_backdrop():
    alpha = np.zeros((100, 100), np.float32)
    alpha[30:70, 40:60] = 1
    look = np.full((100, 100, 3), 0.95, np.float32)  # the backdrop
    drawn = np.full((100, 100, 3), 0.85, np.float32)  # the model's own, greyer paper
    drawn[30:70, 40:60] = 0.2  # the player
    drawn[50, 20] = 0.4  # a real paint mark past the outline
    out = comic._match_background(drawn, look, alpha)
    assert abs(out[5, 5, 0] - 0.95) < 0.02  # paper: the backdrop's tone (no halo)
    assert abs(out[50, 50, 0] - 0.2) < 0.02  # the player untouched
    assert out[50, 20, 0] < 0.6  # the paint mark still shows


def test_hands_follow_a_crop():
    s = scene_with((450, 300, 550, 600))
    cropped = s.in_crop((250, 200, 750, 800), (1000, 800))
    (x, y, r), = cropped.hands
    assert abs(x - 0.5) < 1e-6 and abs(y - (400 - 200) / 600) < 1e-6 and abs(r - 0.02) < 1e-6


def test_line_detail_calms_texture():
    rng = np.random.default_rng(0)
    photo = np.clip(0.5 + rng.normal(0, 0.08, (200, 200, 3)), 0, 1).astype(np.float32)  # grass-like texture
    photo[50:150, 80:120] = 0.1  # a leg
    busy = (comic.line_art(photo, None, 1.0) > 0).mean()
    calm = (comic.line_art(photo, None, 0.3) > 0).mean()
    assert calm < busy / 2 and calm > 0


def test_the_hair_pass_refines_only_the_head_and_never_grows(monkeypatch):
    """Curly hair: the close-up trace opens gaps between curls, but it is used only
    around the head and never reaches past the first cut-out."""
    import sys
    import types
    from PIL import Image
    from photo_presets import scene
    W = H = 400
    img = Image.new("RGB", (W, H), (90, 140, 60))
    first = np.zeros((H, W), np.float32)
    first[100:400, 150:250] = 1  # body and a smooth blob of a head
    first[60:100, 160:240] = 1

    def fake_remove(crop, session=None, only_mask=True):  # the close-up: a head with gaps between curls
        w, h = crop.size
        m = np.zeros((h, w), np.uint8)
        m[h // 4:, w // 4:3 * w // 4] = 255
        m[h // 4:h // 4 + 6, w // 2 - 3:w // 2 + 3] = 0  # a gap between curls
        m[:, :2] = 255  # something far off to the side, not attached
        return Image.fromarray(m)
    monkeypatch.setitem(sys.modules, "rembg", types.SimpleNamespace(remove=fake_remove))
    monkeypatch.setattr(scene, "_session", lambda: None)
    out = scene.refine_heads(img, first, [(0.5, 0.25, 0.05)])
    assert out[350, 200] == 1 and out[300, 160] == 1  # the body untouched
    assert out.max() <= 1 and (out <= np.maximum(first, 0) + 1e-6)[first == 0][: 10].all()
    grown = (out > 0.05) & (first < 0.05)
    assert grown.sum() < 0.02 * (first > 0).sum()  # it does not grow past the first cut-out
    assert out[:, :5].max() == 0  # the far-off piece is not added
