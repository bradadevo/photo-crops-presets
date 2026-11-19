"""The Culling tab: pass 1's ranking and marks, bursts, taste learning, the export's crops and edits,
RAW+JPEG pairing, and the API (your marks win over pass 1's; the Trash and back)."""

from pathlib import Path

import numpy as np
from PIL import Image

from photo_presets.cull import ai, enhance, export, files, rank, taste


def m(sharp=1000.0, people=3, ball=False, eyes=0.4, face_px=80, light=0.5, focus=True, t_hash=0, height=0.4):
    return {"sharp": sharp, "subject": (0.3, 0.2, 0.6, 0.8), "group": (0.2, 0.2, 0.7, 0.8), "subject_height": height,
            "people": people, "ball": ball, "subject_light": light, "white": 0.0, "focus_on_subject": focus,
            "faces": [{"px": face_px, "eyes": eyes, "quality": 0.3, "main": True, "box": (0.4, 0.2, 0.45, 0.27)}],
            "hash": t_hash, "crops": {}}


def test_pass1_keeps_sharp_moments_and_rejects_soft_and_closed_eyes():
    items = [("sharp", 0.0, m(sharp=1200, ball=True)), ("soft", 10.0, m(sharp=200)),
             ("eyes", 20.0, m(sharp=1100, eyes=0.08)), ("ok", 30.0, m(sharp=1000)), ("ok2", 40.0, m(sharp=950))]
    r = rank.rank(items)
    rank.suggest(r)
    assert r["sharp"].suggest == "keep" and "ball" in r["sharp"].why
    assert r["soft"].suggest == "reject" and "blur" in r["soft"].issues and "soft" in r["soft"].why
    assert r["eyes"].suggest == "reject" and "eyes" in r["eyes"].issues
    assert r["sharp"].score > r["soft"].score


def test_bursts_keep_only_their_best_frame_and_the_keep_count_holds():
    items = [(f"b{i}", 100 + i * 0.2, m(sharp=900 + i * 50, t_hash=i)) for i in range(5)]  # one burst
    items += [(f"s{i}", 200 + i * 30, m(sharp=1000, t_hash=1 << (i * 9))) for i in range(4)]  # four moments
    r = rank.rank(items)
    assert len({r[f"b{i}"].burst for i in range(5)}) == 1 and r["b4"].burst_best and r["b0"].burst_size == 5
    rank.suggest(r)
    assert [i for i in range(5) if r[f"b{i}"].suggest == "keep"] == [4]
    assert "near copy" in r["b1"].why
    r2 = rank.rank(items)
    rank.suggest(r2, keep=2)
    assert sum(x.suggest == "keep" for x in r2.values()) == 2
    assert rank.parse_keep("10%", 200) == 20 and rank.parse_keep("", 50) is None and rank.parse_keep("30", 5) == 30


def test_pass1_is_less_sure_near_the_line():
    items = [(f"p{i}", i * 10.0, m(sharp=600 + i * 100, t_hash=1 << i)) for i in range(8)]
    r = rank.rank(items)
    rank.suggest(r, keep=4)
    kept = sorted((x for x in r.values() if x.suggest == "keep"), key=lambda x: x.score)
    assert kept[0].sure < kept[-1].sure  # the last one in is the least sure


def test_taste_learns_your_keeps(tmp_path):
    t = taste.Taste(tmp_path / "taste.json")
    rng = np.random.default_rng(0)
    for i in range(40):
        likes_ball = i % 2 == 0
        f = {"sharp": 0.8, "face": 0.5, "size": 0.5, "ball": 1.0 if likes_ball else 0.0, "players": 0.6,
             "light": 0.8, "focus": 1.0, "eyes_open": 1.0}
        f["sharp"] += rng.normal(0, 0.05)
        t.learn(f"p{i}", f, {}, kept=likes_ball)
    t.save()
    again = taste.Taste(tmp_path / "taste.json")
    assert again.ready
    base = {"sharp": 0.8, "face": 0.5, "size": 0.5, "players": 0.6, "light": 0.8, "focus": 1.0, "eyes_open": 1.0}
    assert again({**base, "ball": 1.0}, {}) > 0.7 > 0.3 > again({**base, "ball": 0.0}, {})


def test_raw_and_jpeg_of_a_shot_are_one(tmp_path):
    Image.new("RGB", (40, 30)).save(tmp_path / "DSC001.JPG")
    (tmp_path / "DSC001.ARW").write_bytes(b"raw")
    Image.new("RGB", (40, 30)).save(tmp_path / "DSC002.JPG")
    shots = files.shots_in([tmp_path])
    assert len(shots) == 2
    one = next(s for s in shots if s["name"] == "DSC001.JPG")
    assert one["raw"] and len(one["files"]) == 2


def test_trash_undo_puts_files_back(tmp_path):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")
    moved_to = tmp_path / ".Trash-test" / "a.jpg"
    moved_to.parent.mkdir()
    a.rename(moved_to)  # (as the Trash would)
    assert files.from_trash([(str(a), str(moved_to))]) == 1 and a.exists() and not moved_to.exists()


def test_export_crops_on_the_action_and_edits(tmp_path):
    img = Image.new("RGB", (3000, 2000), (90, 140, 70))
    src = tmp_path / "shot.jpg"
    img.save(src)
    meas = {"group": (0.6, 0.3, 0.8, 0.9), "subject": (0.62, 0.3, 0.75, 0.9),
            "crops": {"4:5": (0.5, 0.0, 0.9, 1.0), "best": (0.5, 0.0, 0.9, 1.0), "wide": (0.05, 0.05, 0.95, 0.95)}}
    tight, wide = export.boxes(meas, "instagram", (3000, 2000))
    assert tight == (1500, 0, 2700, 2000)
    assert abs((wide[2] - wide[0]) / (wide[3] - wide[1]) - 0.8) < 0.01
    yours = export.boxes(meas, "instagram", (3000, 2000), override=(0.0, 0.0, 0.4, 1.0))[0]
    assert yours == (0, 0, 1200, 2000)
    out = export.edit_one(src, meas, "instagram", "OAC", tmp_path / "out")
    assert sorted(p.name for p in out) == ["shot_crop-only.jpg", "shot_natural.jpg", "shot_punchy.jpg"]
    assert all(Image.open(p).size == (1080, 1350) for p in out)
    again = export.edit_one(src, meas, "instagram", "A", tmp_path / "out")  # made again: replaced, not a copy
    assert again[0].name == "shot_natural.jpg" and len(list((tmp_path / "out").iterdir())) == 3


def test_white_balance_needs_no_opencv_extras():
    arr = np.full((60, 80, 3), (150.0, 120.0, 100.0), np.float32)
    out = enhance.auto_white_balance(arr)
    assert out[..., 2].mean() > arr[..., 2].mean() and out[..., 0].mean() < arr[..., 0].mean()  # warm cast eased


def test_ai_cost_wording():
    assert ai.cost(3) == "under 1¢" and ai.cost(100) == "about $0.10–$0.20"


def test_api_marks_win_and_trash_round_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import photo_presets.studio.cull as cu
    from photo_presets.studio import server
    monkeypatch.setattr(cu, "HOME", tmp_path)
    monkeypatch.setattr(cu, "STATE_FILE", tmp_path / "cull.json")
    monkeypatch.setattr(cu, "CACHE", tmp_path / "cache")
    shoot = tmp_path / "game"
    shoot.mkdir()
    for i in range(4):
        Image.new("RGB", (60, 40), (i * 40, 100, 50)).save(shoot / f"IMG{i}.jpg")
    sharp = [1200, 300, 1000, 1100]
    monkeypatch.setattr(cu.measure, "measure", lambda path, cache: m(sharp=sharp[int(Path(path).stem[-1])], t_hash=1 << int(Path(path).stem[-1]) * 9))
    monkeypatch.setattr(cu.files, "to_trash", lambda paths: [(p, p + ".trashed") for p in paths if Path(p).rename(p + ".trashed") or True])
    monkeypatch.setattr(cu, "C", cu.Cull())  # (made after the paths above: it saves only there)
    c = TestClient(server.app)
    sid = c.post("/api/cull/shoots", json={"folders": [str(shoot)]}).json()["id"]
    import time
    for _ in range(100):
        r = c.get(f"/api/cull/shoots/{sid}/photos").json()
        if r["shoot"]["pass1"]:
            break
        time.sleep(0.05)
    photos = {p["name"]: p for p in r["photos"]}
    assert photos["IMG1.jpg"]["auto"][0] == "reject" and photos["IMG0.jpg"]["auto"][0] == "keep"
    # your mark wins, and stays when pass 1 runs again
    c.post(f"/api/cull/shoots/{sid}/mark", json={"items": [{"id": photos["IMG1.jpg"]["id"], "flag": "keep", "stars": 4}]})
    c.post(f"/api/cull/shoots/{sid}/pass1", json={"keep": "1"})
    p1 = {p["name"]: p for p in c.get(f"/api/cull/shoots/{sid}/photos").json()["photos"]}["IMG1.jpg"]
    assert p1["flag"] == "keep" and p1["stars"] == 4 and p1["auto"][0] == "reject"
    # the Trash and back
    gone = c.post(f"/api/cull/shoots/{sid}/trash", json={"ids": [photos["IMG3.jpg"]["id"]]}).json()
    assert gone["moved"] == 1 and not (shoot / "IMG3.jpg").exists()
    c.post(f"/api/cull/shoots/{sid}/untrash", json={"token": gone["token"]})
    assert (shoot / "IMG3.jpg").exists()


def test_a_crop_too_small_for_its_size_is_widened_kept_native_or_enlarged_as_chosen(tmp_path):
    img = Image.new("RGB", (3000, 2000), (90, 140, 70))
    src = tmp_path / "shot.jpg"
    img.save(src)
    small = (0.5, 0.4, 0.6, 0.6)  # 300 x 400 px: Instagram needs 1080 x 1350
    meas = {"group": (0.5, 0.4, 0.6, 0.6), "crops": {"4:5": small, "best": small, "wide": (0, 0, 1, 1)}}
    box = export.boxes(meas, "instagram", (3000, 2000))[0]
    assert round(export.enlarged(box, "instagram", (3000, 2000)), 1) == 3.6
    grown = export.widen(box, "instagram", (3000, 2000))
    assert export.enlarged(grown, "instagram", (3000, 2000)) <= 1.0 + 1e-6
    assert abs((grown[0] + grown[2]) / 2 - 1650) < 2  # still around the action
    assert export.enlarged((0, 0, 3000, 2000), "original", (3000, 2000)) == 1.0
    assert export.enlarged(box, "youtube", (3000, 2000)) == 1.0  # saved at the crop's own size
    out = {f: export.edit_one(src, meas, "instagram", "O", tmp_path / f, fit=f)[0] for f in ("widen", "native", "enlarge")}
    assert Image.open(out["widen"]).size == (1080, 1350)
    assert Image.open(out["native"]).size == (300, 400)
    assert Image.open(out["enlarge"]).size == (1080, 1350)
    # your crop is kept per size
    assert export.your_crop({"story": (0, 0, 0.5, 1)}, "story") == (0, 0, 0.5, 1)
    assert export.your_crop({"story": (0, 0, 0.5, 1)}, "instagram") is None
