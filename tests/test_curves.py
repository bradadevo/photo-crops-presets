import numpy as np
from photo_presets import curves as C

def ramp():
    v = np.linspace(0, 1, 256, dtype=np.float32)
    rng = np.random.default_rng(1)
    img = rng.random((64, 64, 3), dtype=np.float32)
    return v, img

def test_straight_line_changes_nothing():
    _, img = ramp()
    assert C.apply(img, {"rgb": "0,0;255,255"}) is img
    assert C.apply(img, {"rgb": ""}) is img
    assert C.parse("junk") == []

def test_every_situation_is_smooth_and_never_reverses():
    for key, (_, _, _, ch) in C.SITUATIONS.items():
        for c, pts in ch.items():
            t = C.table(pts)
            assert (np.diff(t) >= -1e-6).all(), key
            assert np.abs(np.diff(t, 2)).max() < 0.01, key  # (no kinks)

def test_s_curve_adds_contrast_and_keeps_hue():
    _, img = ramp()
    out = C.apply(img, {"rgb": C.text(C.SITUATIONS["flat"][3]["rgb"])})
    lum = lambda a: a @ np.array([0.299, 0.587, 0.114], np.float32)
    assert lum(out).std() > lum(img).std()
    skin = np.array([[[0.80, 0.55, 0.42]]], np.float32)
    o = C.apply(skin, {"rgb": C.text(C.SITUATIONS["punchy"][3]["rgb"])})[0, 0]
    assert abs(o[0] / o[1] - 0.80 / 0.55) < 0.02 and abs(o[1] / o[2] - 0.55 / 0.42) < 0.02  # (hue and saturation kept)

def test_faded_black_is_gray_and_smooth_near_black():
    v = np.linspace(0, 0.2, 400, dtype=np.float32)
    img = np.stack([v, v, v], -1)[None]
    out = C.apply(img, {"rgb": C.text(C.SITUATIONS["faded"][3]["rgb"])})[0]
    assert abs(out[0, 0] - C.SITUATIONS["faded"][3]["rgb"][0][1] / 255) < 0.01 and np.ptp(out[0]) < 1e-5
    assert (np.diff(out[:, 0]) > -1e-5).all() and np.abs(np.diff(out[:, 0], 2)).max() < 0.002

def test_channel_curve_only_moves_its_channel_and_weight_limits_it():
    _, img = ramp()
    out = C.apply(img, {"b": "0,0;128,160;255,255"})
    assert np.allclose(out[..., :2], img[..., :2]) and out[..., 2].mean() > img[..., 2].mean()
    w = np.zeros(img.shape[:2], np.float32); w[:, 32:] = 1
    o2 = C.apply(img, {"b": "0,0;128,160;255,255"}, w)
    assert np.allclose(o2[:, :32], img[:, :32]) and np.allclose(o2[:, 32:], out[:, 32:])


def test_curves_in_the_edit_pipeline_after_the_tone_and_only_where_asked():
    from photo_presets import pipeline
    _, img = ramp()
    flat = C.text(C.SITUATIONS["flat"][3]["rgb"])
    alpha = np.zeros(img.shape[:2], np.float32); alpha[:, 32:] = 1
    whole, _ = pipeline.finish(img, img, {"adjust": {"curve_all_rgb": flat}}, alpha)
    assert np.allclose(whole, C.apply(img, {"rgb": flat}), atol=1e-6)
    players, _ = pipeline.finish(img, img, {"adjust": {"curve_player_rgb": flat}}, alpha)
    assert np.allclose(players[:, :32], img[:, :32], atol=1e-6) and not np.allclose(players[:, 32:], img[:, 32:])
    _, notes = pipeline.finish(img, img, {"adjust": {"curve_bg_rgb": flat}}, None)
    assert any("curves were skipped" in n for n in notes)
    assert pipeline.needs_cutout({"adjust": {"curve_bg_rgb": flat}}) and not pipeline.needs_cutout({"adjust": {"curve_all_rgb": flat}})
