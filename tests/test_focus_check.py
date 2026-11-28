"""The Assessor's focus check: edge width tells sharp from blurred (and isn't fooled by a plain area),
the subject is the person the camera follows (or the one picked), and a subject left soft while the
background is sharp is called out with when and why."""
import cv2
import numpy as np

from photo_presets.clipcheck import focus
from photo_presets.clipcheck.focus import Sample, Sampled, Thing


def _checker(h=400, w=400, square=20):
    y, x = np.mgrid[:h, :w]
    return (((y // square + x // square) % 2) * 160 + 40).astype(np.uint8)


def test_edge_width_tells_sharp_from_blurred():
    sharp = _checker()
    soft = cv2.GaussianBlur(sharp, (0, 0), 3)
    *_, ws = focus.edge_widths(sharp)
    *_, wb = focus.edge_widths(soft)
    assert np.median(ws) <= 3
    assert np.median(wb) >= 2.5 * np.median(ws)


def test_a_plain_area_gives_no_edges_rather_than_looking_blurred():
    flat = np.full((300, 300), 30, np.uint8)  # (a plain black shirt)
    flat = (flat + np.random.default_rng(1).normal(0, 2, flat.shape)).clip(0, 255).astype(np.uint8)
    *_, w = focus.edge_widths(flat)
    assert len(w) == 0


def _clip(subject_widths, best=3.0, subject_heights=None, step=0.25, duration=None, truck=True):
    """A made-up measured clip: one person the camera follows (in the middle, getting bigger), one
    small bystander at the side, a sharp truck behind, and the sharpest tiles high in the frame."""
    n = len(subject_widths)
    hs = subject_heights or [0.3 + 0.5 * i / max(1, n - 1) for i in range(n)]
    samples = []
    for i, (w, hgt) in enumerate(zip(subject_widths, hs)):
        top = 0.95 - hgt
        tiles = [[None] * 11 for _ in range(focus.ROWS)]
        tiles[0][3] = tiles[0][4] = tiles[1][3] = best  # (trees high in the frame: farther away)
        tiles[4][9] = best * 1.8
        people = [Thing((0.45, top, 0.55, 0.95), w, 500), Thing((0.9, 0.5, 0.93, 0.6), best * 1.1, 80)]
        objects = [Thing((0.7, 0.4, 0.85, 0.6), best * 1.2, 400, "truck")] if truck else []
        samples.append(Sample(round(0.125 + i * step, 3), people, objects, tiles, best))
    return Sampled(samples, 3840, 2160, duration or (n * step))


def test_the_subject_is_the_person_the_camera_follows():
    s = _clip([3.2] * 12)
    tr = focus.pick_track(s)
    assert all(p == 0 for _, p in tr) and len(tr) == 12


def test_a_picked_person_becomes_the_subject():
    s = _clip([3.2] * 12)
    tr = focus.pick_track(s, {"t": 1.0, "x": 0.915, "y": 0.55})
    assert all(p == 1 for _, p in tr)


def test_focus_left_behind_an_approaching_subject_is_called_out_with_when_and_why():
    widths = [4.0] * 4 + [3.3] * 2 + [5.5 + i * 0.6 for i in range(30)]  # (sharpest early, far away; then ever softer)
    s = _clip(widths)
    a = focus.analyze(s)
    runs = [r for r in a["runs"] if r["kind"] == "focus"]
    assert runs and runs[-1]["cause"] == "behind" and runs[-1]["coming"]
    assert runs[-1]["named"] == "truck"
    label, detail = focus.run_text(runs[-1])
    assert label == "Subject out of focus" and "behind them" in detail and "came closer" in detail
    assert "out of focus for" in a["finding"] and "set once" in a["finding"] and "far away" in a["finding"]
    assert any(row[0] == "Focus mode" and "AF-C" in row[1] for row in a["advice"])
    assert any("Lock on early" in h for h in a["habits"])


def test_a_sharp_subject_is_said_to_be_sharp_and_gets_no_advice():
    a = focus.analyze(_clip([3.1] * 20))
    assert not a["runs"] and a["finding"].startswith("Focus: your subject stayed sharp") and not a["advice"]


def test_everything_soft_at_once_is_not_blamed_on_focus_behind_the_subject():
    s = _clip([3.2] * 8 + [9.0] * 6 + [3.2] * 8)
    for smp in s.samples[8:14]:
        smp.best = 8.5  # (the whole frame went soft: a swing or the lens hunting)
    a = focus.analyze(s, camera_speed=lambda t: 30.0 if 2.0 <= t <= 3.5 else 0.0)
    kinds = [(r["kind"], r["cause"]) for r in a["runs"]]
    assert kinds == [("frame", "swing")]
    assert focus.run_text(a["runs"][0])[0] == "Whole picture soft"


def _lens(mode, positions, every=0.25):
    return focus.lens_from({"focus_mode": mode, "focus_series": positions, "series_every_s": every})


def test_camera_data_autofocus_with_a_still_lens_says_the_camera_chose_the_background():
    widths = [4.0] * 4 + [3.3] * 2 + [5.5 + i * 0.6 for i in range(30)]
    s = _clip(widths)
    lens = _lens("Autofocus (wide area)", [100] * 5 + [900] * 31)  # (moved once early, then held still)
    a = focus.analyze(s, lens=lens)
    assert "on autofocus (wide area), but" in a["finding"]
    assert "didn't move at all from 0:01.2" in a["finding"] and "AF-S or manual" not in a["finding"]
    assert not any(row[0] == "Focus mode" for row in a["advice"])
    area = next(row for row in a["advice"] if row[0] == "Focus area")
    assert "instead of Wide" in area[1] and "picked the background" in area[2]


def test_camera_data_manual_focus_is_said_plainly():
    widths = [4.0] * 4 + [3.3] * 2 + [5.5 + i * 0.6 for i in range(30)]
    a = focus.analyze(_clip(widths), lens=_lens("Manual focus", [500] * 36))
    assert "manual focus" in a["finding"] and "AF-S" not in a["finding"]
    assert any(row[0] == "Focus mode" and "instead of manual" in row[1] for row in a["advice"])


def test_camera_data_confirms_the_lens_hunting():
    s = _clip([3.2] * 8 + [9.0] * 6 + [3.2] * 8)
    for smp in s.samples[8:14]:
        smp.best = 8.5
    lens = _lens("Autofocus (wide area)", [100] * 8 + [300, 500, 200, 400, 350, 100] + [100] * 8)
    a = focus.analyze(s, camera_speed=lambda t: 0.0, lens=lens)
    assert [(r["kind"], r["cause"]) for r in a["runs"]] == [("frame", "hunting")]
    assert "lens refocusing here" in focus.run_text(a["runs"][0])[1]


def test_no_camera_data_keeps_the_old_wording():
    assert focus.lens_from({}) is None and focus.moved(None, 0, 1) is None
