"""Artist techniques: each runs, keeps the picture's shapes, and draws faces gently."""

import numpy as np

from photo_presets import technique as T


def face_like(h=120, w=100):
    a = np.full((h, w, 3), 0.75, np.float32)  # skin
    a[35:45, 25:40] = 0.08  # an eye in deep shadow
    a[35:45, 60:75] = 0.08
    a[80:88, 35:65] = 0.3  # the mouth
    return a


def test_every_technique_runs_and_keeps_the_size():
    a = np.random.default_rng(0).random((90, 120, 3)).astype(np.float32)
    for kind in ["oil", "knife", "graphite", "charcoal", "pen", "colored_pencil", "cel", "comic"]:
        out = T.render(a, kind, 400, np.random.default_rng(1))
        assert out.shape == a.shape and np.isfinite(out).all() and 0 <= out.min() and out.max() <= 1.0001, kind


def test_portrait_rules_keep_faces_free_of_black_shapes():
    a = face_like()
    for kind in ["cel", "comic"]:
        plain = T.render(a, kind, 400, np.random.default_rng(1))
        gentle = T.render(a, kind, 400, np.random.default_rng(1), portrait=True)
        assert gentle[38:42, 28:37].mean() > plain[38:42, 28:37].mean() + 0.05, kind  # the eye shadow lifted
    lit = T.render(a, "graphite", 400, np.random.default_rng(1), portrait=True)
    assert lit[60:75, 20:80].mean() > 0.85  # lit skin left almost bare paper


def test_kuwahara_keeps_edges():
    a = np.zeros((60, 60, 3), np.float32)
    a[:, 30:] = 1.0
    out = T.kuwahara(a + np.random.default_rng(2).normal(0, 0.05, a.shape).astype(np.float32), 3)
    assert out[:, :26].mean() < 0.1 and out[:, 34:].mean() > 0.9  # flattened, the edge still sharp
