"""The Check tab: problem moments, fixes and the comparison (no AI anywhere)."""
import json

import numpy as np
import pytest
from PIL import Image

from photo_presets.clipcheck import fixes, moments
from photo_presets.clipcheck.video import PictureStats


def _stats(n=300, fps=30.0, **over):
    t = [i * 2 / fps for i in range(n)]
    base = dict(samples=n, every=2, still_share=0.5, slow_share=0.3, fast_share=0.2, fastest_pan=40, sharp_still=800,
                sharp_slow=600, sharp_fast=300, grain_still=1.0, pan_sharpness_loss=0.6, brightness=[120.0] * n,
                brightness_swing=0, times=t, sharpness=[800.0] * n, speed=[1.0] * n, shake=[1.0] * n)
    base.update(over)
    return PictureStats(**base)


def test_moments_point_at_soft_pans_brightness_jumps_and_shaky_stretches():
    n = 300
    speed, sharp, bright, shake = [1.0] * n, [800.0] * n, [120.0] * n, [1.0] * n
    for i in range(30, 60):  # a fast, soft pan at 2-4 s
        speed[i], sharp[i] = 40.0, 200.0
    for i in range(150, n):  # the light jumps at 10 s
        bright[i] = 190.0
    for i in range(220, 260):  # a shaky hand at about 15-17 s
        shake[i] = 35.0
    ms = moments.find(_stats(speed=speed, sharpness=sharp, brightness=bright, shake=shake), 30, 20)
    kinds = {m.kind: m for m in ms}
    assert {"soft_pan", "jump", "shaky"} <= set(kinds)
    assert 1.8 <= kinds["soft_pan"].start <= 2.2 and kinds["jump"].start < 10.1 < kinds["jump"].end
    assert "brighter" in kinds["jump"].detail
    assert moments.find(_stats(), 30, 20) == []  # a clean clip has none


def test_brightness_is_only_offered_when_clearly_off_and_gently():
    assert fixes.exposure_for(0.5) == 0
    assert 0 < fixes.exposure_for(0.25) <= 1.5 and fixes.exposure_for(0.85) < 0
    assert fixes.cast_name([1.0, 0.9, 1.05]) == "a green" and fixes.cast_name([0.85, 1, 1.2]) == "a red"


def test_evening_pulls_each_frame_toward_the_trend_and_keeps_black_and_white():
    bright = [0.4] * 200 + [0.7] * 5 + [0.4] * 200  # a flash of brightness
    luts = fixes.evening(bright, 30, 0.6)
    assert luts[202][128] < 110 and luts[10][128] == 128
    assert all(l[0] == 0 and l[255] == 255 for l in luts)


def test_steadying_corrects_jitter_but_follows_a_pan():
    rng = np.random.default_rng(1)
    moves = np.zeros((300, 3))
    moves[:, 0] = 10 + rng.normal(0, 6, 300)  # a steady pan with a shaky hand
    corr, zoom = fixes.steadying(moves, 3840, 2160, 30, 0.6)
    smoothed = np.diff(np.cumsum(moves[:, 0]) + corr[:, 0])
    assert np.std(smoothed) < np.std(moves[:, 0]) * 0.6 and 1.0 < zoom <= 1.08


def test_photo_fixes_change_only_what_is_switched_on():
    rgb = (np.random.default_rng(0).normal(50, 4, (120, 160, 3))).clip(0, 255).astype(np.uint8)  # dark and grainy
    assert np.array_equal(fixes.apply_photo(rgb, {}), rgb)
    brighter = fixes.apply_photo(rgb, {"exposure": {"on": True, "value": 1.0}})
    cleaner = fixes.apply_photo(rgb, {"grain": {"on": True, "value": 1.0}})
    assert brighter.shape == rgb.shape and brighter.mean() > rgb.mean() + 10
    assert cleaner.std() < rgb.std() * 0.7 and abs(cleaner.mean() - rgb.mean()) < 2


def test_the_check_tab_checks_a_photo_compares_and_exports(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from photo_presets.studio import check
    monkeypatch.setattr(check, "HOME", tmp_path)
    monkeypatch.setattr(check, "LIST_FILE", tmp_path / "check.json")
    monkeypatch.setattr(check, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(check, "FALLBACK_OUT", tmp_path / "out")
    monkeypatch.setattr(check, "_STATE", tmp_path)
    monkeypatch.setattr(check, "F", check.Files())
    paths = []
    for i, level in enumerate((40, 140)):
        p = tmp_path / f"shot{i}.jpg"
        Image.fromarray((np.random.default_rng(i).random((300, 400, 3)) * 50 + level).astype(np.uint8)).save(p)
        paths.append(str(p))
    app = FastAPI(); app.include_router(check.router)
    c = TestClient(app)
    ids = c.post("/api/check/add", json={"paths": paths}).json()["added"]
    for _ in range(100):
        if all(f["state"] == "done" for f in c.get("/api/check/state").json()["files"]):
            break
        import time; time.sleep(0.1)
    d = c.get(f"/api/check/file/{ids[0]}").json()
    assert d["state"] == "done" and d["camera"] and d["fixes"]
    assert next(f for f in d["fixes"] if f["id"] == "exposure")["on"]  # the dark one: brighten it
    assert c.get(f"/img/check/{ids[0]}/view.jpg?fixed=1").status_code == 200
    cmp = c.post("/api/check/compare", json={"ids": ids}).json()
    assert cmp["groups"][0]["name"] == "How it came out"
    bright = next(r for g in cmp["groups"] for r in g["rows"] if r["label"] == "Average brightness")
    assert not bright["same"] and bright["better"] == "mid"
    out = c.post("/api/check/export", json={"ids": ids, "format": "both"}).json()
    assert len(out["files"]) == 2 and all(str(tmp_path) in f for f in out["files"])
    r = c.post(f"/api/check/file/{ids[0]}/fix").json()
    for _ in range(100):
        job = next(f for f in c.get("/api/check/state").json()["files"] if f["id"] == ids[0]).get("job")
        if job and job["state"] != "now":
            break
        import time; time.sleep(0.1)
    assert job["state"] == "done" and str(tmp_path) in r["dest"]
    assert json.loads((tmp_path / "check.json").read_text())[0]["fixed"]


def test_recommendations_in_short_and_across_files():
    from photo_presets.clipcheck import recommend
    fine = recommend.for_file(["No problems found.", "Focus: on the eyes"], [], [], [])
    assert fine["level"] == "good" and fine["items"] == []
    fix = {"label": "Recover bright areas", "why": "The sky is pure white in places."}
    shutter = ["Shutter speed", "1/1000 or faster", "Freezes running players."]
    iso = ["ISO", "Auto, up to 6400", "Keeps the shutter fast in shade."]
    busy = recommend.for_file(["Motion blur on the player.", "Bright areas lost."], [fix], [shutter, iso], ["Half-press to focus.", "Shoot in bursts."])
    assert busy["level"] == "attention"
    assert [x["when"] for x in busy["items"]] == ["now", "next", "next", "habit"]  # fix now first, then next time, then one habit
    assert busy["items"][0]["title"] == "Fix this file: Recover bright areas"
    files = [
        {"name": "a.mp4", "kind": "video", "findings": ["No problems found."], "fixes_on": [], "settings": [], "habits": []},
        {"name": "b.mp4", "kind": "video", "findings": ["Motion blur."], "fixes_on": [fix], "settings": [shutter], "habits": ["Half-press to focus."]},
        {"name": "c.mp4", "kind": "video", "findings": ["Motion blur.", "Too dark."], "fixes_on": [fix], "settings": [shutter, iso], "habits": []},
    ]
    s = recommend.across(files)
    assert s["good"] == ["a.mp4"] and s["fix"] == ["b.mp4"] and s["attention"] == ["c.mp4"]
    assert s["changes"][0]["setting"] == "Shutter speed" and s["changes"][0]["count"] == 2
    assert s["fixes"][0] == {"label": "Recover bright areas", "count": 2}
    assert s["worst"][0]["name"] == "c.mp4"
    assert s["headline"].startswith("1 of 3 ready to use") and "shutter speed (2 of 3)" in s["headline"]
    assert recommend.across([])["headline"] == "Nothing checked yet."


def test_fixed_copies_made_at_once_never_share_a_name(tmp_path):
    """A JPEG and its RAW (one name) fixed together: the name is taken the moment it is chosen."""
    from photo_presets.clipcheck import fixes
    a = fixes.fixed_path(str(tmp_path / "DSC1.JPG"), tmp_path / "fb", ".jpg")
    b = fixes.fixed_path(str(tmp_path / "DSC1.ARW"), tmp_path / "fb", ".jpg")
    assert a != b and a.exists() and b.exists() and b.name == "DSC1 fixed 2.jpg"
