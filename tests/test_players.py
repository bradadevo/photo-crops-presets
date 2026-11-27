"""Finding a player: sure, asked about, or not them; and the best of each burst."""

from datetime import datetime, timedelta

import numpy as np

from photo_presets import players


def _kit(color):
    h = np.zeros(192, np.float32)
    h[color] = 1
    return h


def _face(seed):
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def test_rules():
    me = players.Sighting((0, 0, 1, 1), face=_face(1), kit=_kit(5), face_px=80)
    same_face = players.Sighting((0, 0, 1, 1), face=_face(1) + 0.2 * _face(2), kit=_kit(5))
    other_team = players.Sighting((0, 0, 1, 1), face=_face(1), kit=_kit(90))
    stranger = players.Sighting((0, 0, 1, 1), face=_face(3), kit=_kit(5))
    assert players.likeness(me, same_face)[0] == "sure"
    assert players.likeness(me, other_team)[0] == "no"
    assert players.likeness(me, stranger)[0] == "no"
    numbered = players.Sighting((0, 0, 1, 1), number="7", kit=_kit(5))
    assert players.likeness(players.Sighting((0, 0, 1, 1), number="7", kit=_kit(5)), numbered)[0] == "sure"
    assert players.likeness(players.Sighting((0, 0, 1, 1), number="9", kit=_kit(5)), numbered)[0] == "no"


def test_a_no_answer_rules_out_look_alikes():
    me = players.Sighting((0, 0, 1, 1), face=_face(1), kit=_kit(5))
    near = _face(1) * 0.5 + _face(4) * 0.6
    maybe = players.Sighting((0, 0, 1, 1), face=near / np.linalg.norm(near), kit=_kit(5))
    status = players.likeness(me, maybe)[0]
    assert status in ("maybe", "sure")
    assert players.likeness(me, maybe, no=[maybe.face])[0] == "no"


def test_one_best_per_burst():
    t0 = datetime(2026, 11, 7, 10, 0, 0)
    me = players.Sighting((0, 0, 0.2, 0.5), face=_face(1), kit=_kit(5), sharp=100, facing=True)
    scans = []
    for i, (dt, sharp) in enumerate([(0, 50), (0.5, 200), (60, 80)]):
        s = players.Sighting((0, 0, 0.2, 0.5), face=_face(1), kit=_kit(5), sharp=sharp, facing=True)
        scans.append(players.Scan(f"p{i}.jpg", t0 + timedelta(seconds=dt), (100, 100), [s]))
    found = players.find(scans, me)
    best = [h["path"] for h in found if h["best"]]
    assert sorted(best) == ["p1.jpg", "p2.jpg"]  # the sharper of the burst, and the photo a minute later
