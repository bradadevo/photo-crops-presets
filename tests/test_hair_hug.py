"""The hair pass trimmed to Apple's tighter outline of the people (no halo of background around the hair):
it only ever takes away; a head Apple's outline doesn't hold soundly is left as before; a Mac without it
gets the cut-out as before."""
import numpy as np
from PIL import Image

from photo_presets import apple_person, scene


def _head_setup(monkeypatch):
    h, w = 400, 400
    img = Image.fromarray(np.full((h, w, 3), 120, np.uint8))
    yy, xx = np.mgrid[0:h, 0:w]
    matte = np.zeros((h, w), np.float32)
    matte[200:400, 150:250] = 1.0  # the player's body
    matte[((xx - 200) ** 2 + (yy - 174) ** 2) < 31 ** 2] = 1.0  # their head, a little generous (the first cut-out)
    faces = [(0.5, 0.45, 0.06)]  # x, y, radius (shares of the width): the head's square is centered at (200, 174)

    def fake_remove(crop, session=None, only_mask=True):  # the hair model: the head, with a halo around it
        cw, ch = crop.size
        m = np.zeros((ch, cw), np.uint8)
        yy, xx = np.mgrid[0:ch, 0:cw]
        m[((xx - cw / 2) ** 2 + (yy - ch / 2) ** 2) < (0.36 * cw) ** 2] = 255
        return Image.fromarray(m)
    import rembg
    monkeypatch.setattr(rembg, "remove", fake_remove)
    monkeypatch.setattr(scene, "_heads_session", lambda: None)
    return img, matte, faces


def _hug(matte):
    """Apple's outline: the body, and the head hugged tighter than the hair model's halo (radius 31)."""
    h, w = matte.shape
    yy, xx = np.mgrid[0:h, 0:w]
    hug = np.zeros_like(matte)
    hug[200:400, 150:250] = 1.0
    hug[((xx - 200) ** 2 + (yy - 174) ** 2) < 28 ** 2] = 1.0
    return hug


def test_the_hair_trim_only_takes_away(monkeypatch):
    img, matte, faces = _head_setup(monkeypatch)
    before = scene.refine_heads(img, matte, faces)
    after = scene.refine_heads(img, matte, faces, hug=_hug(matte))
    assert (after <= before + 1e-5).all()  # (never anything added)
    assert after.sum() < before.sum()  # (the halo trimmed)
    assert after[164:184, 190:210].min() > 0.9  # (the face itself kept whole)


def test_a_head_apples_outline_misses_is_left_as_before(monkeypatch):
    img, matte, faces = _head_setup(monkeypatch)
    before = scene.refine_heads(img, matte, faces)
    empty = np.zeros_like(matte)  # (Apple's outline missed this player: photo 4 of the PSG test)
    assert np.array_equal(scene.refine_heads(img, matte, faces, hug=empty), before)
    faint = np.full_like(matte, 0.3)  # (or made them see-through: photo 6)
    assert np.array_equal(scene.refine_heads(img, matte, faces, hug=faint), before)


def test_without_apples_outline_the_cut_out_is_made_as_before(monkeypatch):
    img, matte, faces = _head_setup(monkeypatch)
    sc = scene.Scene(subject_mask=matte > 0, faces=list(faces))
    monkeypatch.setattr(scene, "cutout", lambda image, subject: matte.copy())
    monkeypatch.setattr(apple_person, "available", lambda: False)
    off = scene._made_matte(img, scene.Scene(subject_mask=matte > 0, faces=list(faces)))
    plain = scene.with_balls(scene.refine_heads(img, matte, faces), [])
    assert np.allclose(off, plain)
    monkeypatch.setattr(apple_person, "outline", lambda image: _hug(matte))
    monkeypatch.setattr(apple_person, "available", lambda: True)
    on = scene._made_matte(img, sc)
    assert (on <= off + 1e-5).all() and on.sum() < off.sum()


def test_apples_outline_is_checked_once_and_never_fails():
    assert isinstance(apple_person.available(), bool)
    m = apple_person.outline(Image.new("RGB", (64, 48), (90, 140, 60)))  # (nobody in it: an empty outline or None)
    assert m is None or (m.shape == (48, 64) and m.dtype == np.float32)


def test_the_cut_out_models_are_let_go_a_while_after_the_last_cut_out(monkeypatch, tmp_path):
    """They hold about 10 GB between runs: kept while an event is being cut out, let go after."""
    import time
    monkeypatch.setenv("ALLPROPHOTO_STATE", str(tmp_path))
    monkeypatch.setattr(scene, "IDLE_RELEASE", 0.2)
    monkeypatch.setattr(scene, "_made_matte", lambda image, sc: sc.subject_mask.astype(np.float32))
    monkeypatch.setattr(scene, "_matte_session", object())  # (as if loaded)
    monkeypatch.setattr(scene, "_head_session", object())
    img = Image.fromarray(np.full((60, 80, 3), 120, np.uint8))
    subject = np.zeros((60, 80), bool)
    subject[10:50, 20:60] = True
    scene.Prepared(None, img, scene.Scene(subject_mask=subject), None).ensure_matte()
    assert scene._matte_session is not None  # (kept right after: the next photo may follow)
    time.sleep(0.5)
    assert scene._matte_session is None and scene._head_session is None
    with scene.MODEL_LOCK:  # (one running when the minute is up: let go after it, not under it)
        monkeypatch.setattr(scene, "_matte_session", object())
        scene.release_cutout()
        assert scene._matte_session is not None
    time.sleep(0.5)
    assert scene._matte_session is None
