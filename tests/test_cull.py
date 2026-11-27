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


def test_card_import_never_writes_over_a_different_photo(tmp_path):
    import os
    def card(name, body, raw=None, t=1_700_000_000):
        d = tmp_path / name / "DCIM" / "100MSDCF"; d.mkdir(parents=True)
        (d / "DSC00001.JPG").write_bytes(body); os.utime(d / "DSC00001.JPG", (t, t))
        if raw:
            (d / "DSC00001.ARW").write_bytes(raw); os.utime(d / "DSC00001.ARW", (t, t))
        return tmp_path / name
    dest = tmp_path / "Import"
    a = card("a", b"first camera" * 10, b"raw one" * 10)
    assert files.import_card(a, dest) == (2, 0)
    assert files.import_card(a, dest) == (0, 2)  # (the same card again: nothing new)
    b = card("b", b"second camera" * 10, b"raw two" * 10, t=1_700_000_500)  # same names, other photos
    assert files.import_card(b, dest) == (2, 0)
    assert (dest / "DSC00001.JPG").read_bytes() == b"first camera" * 10  # never written over
    assert (dest / "DSC00001-2.JPG").read_bytes() == b"second camera" * 10 and (dest / "DSC00001-2.ARW").exists()  # JPEG and RAW renamed together
    c = card("c", b"x" * 120, t=1_700_000_900)  # same name AND same size as the first, another photo
    assert files.import_card(c, dest) == (1, 0) and (dest / "DSC00001-3.JPG").read_bytes() == b"x" * 120
    assert files.import_card(b, dest) == (0, 2)  # (the renamed ones are known again)


def test_trash_undo_puts_files_back(tmp_path):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")
    moved_to = tmp_path / ".Trash-test" / "a.jpg"
    moved_to.parent.mkdir()
    a.rename(moved_to)  # (as the Trash would)
    assert files.from_trash([(str(a), str(moved_to))]) == 1 and a.exists() and not moved_to.exists()


def test_originals_told_apart_from_copies(tmp_path):
    ev = tmp_path / "Event"; ev.mkdir()
    Image.new("RGB", (20, 20)).save(ev / "DSC1.JPG")
    (ev / "DSC1.ARW").write_bytes(b"raw")
    assert files.origin([str(ev / "DSC1.JPG"), str(ev / "DSC1.ARW")]) == (True, "camera file (with its RAW)")
    Image.new("RGB", (20, 20)).save(ev / "DSC2.JPG")
    assert files.origin([str(ev / "DSC2.JPG")])[0]
    crops = ev / "Best Crops"; crops.mkdir()
    Image.new("RGB", (20, 20)).save(crops / "DSC1.JPG")
    assert files.origin([str(crops / "DSC1.JPG")]) == (False, 'in "Best Crops", a folder of copies')
    Image.new("RGB", (20, 20)).save(ev / "DSC3_crop.jpg")
    assert not files.origin([str(ev / "DSC3_crop.jpg")])[0]
    Image.new("RGB", (20, 20)).save(ev / "DSC3-Edit (2).jpg")
    assert not files.origin([str(ev / "DSC3-Edit (2).jpg")])[0]
    ex = Image.Exif(); ex[0x0131] = "Adobe Photoshop Lightroom Classic 13.0"
    Image.new("RGB", (20, 20)).save(ev / "DSC4.jpg", exif=ex)
    assert files.origin([str(ev / "DSC4.jpg")]) == (False, "saved by Adobe Photoshop Lightroom Classic 13.0")
    mine = tmp_path / "My exports"; mine.mkdir()
    Image.new("RGB", (20, 20)).save(mine / "DSC5.jpg")
    assert not files.origin([str(mine / "DSC5.jpg")], (str(mine),))[0]  # (a folder the app saved keepers to)


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
    # before deleting, the app says exactly which folder and that these are the originals
    w = c.post(f"/api/cull/shoots/{sid}/trash-preview", json={"ids": [photos["IMG3.jpg"]["id"]]}).json()
    assert w["folders"][0]["path"] == str(shoot) and w["folders"][0]["jpeg"] == 1 and w["originals"] == 1 and not w["copies"]
    assert w["names"] == ["IMG3.jpg"] and (shoot / "IMG3.jpg").exists()  # (only a look: nothing moved)
    # only photos that are still rejects at the moment of deleting go: a keeper asked for is left alone
    c.post(f"/api/cull/shoots/{sid}/mark", json={"items": [{"id": photos["IMG3.jpg"]["id"], "flag": "reject"}]})
    gone = c.post(f"/api/cull/shoots/{sid}/trash", json={"ids": [photos["IMG3.jpg"]["id"], photos["IMG0.jpg"]["id"]]}).json()
    assert gone["moved"] == 1 and gone["ids"] == [photos["IMG3.jpg"]["id"]] and gone["not_rejects"] == [photos["IMG0.jpg"]["id"]]
    assert not (shoot / "IMG3.jpg").exists() and (shoot / "IMG0.jpg").exists() and gone["from"] == [files.shown(str(shoot))]
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


def test_crop_edges_cut_no_one():
    """A crop centered on the main player that would slice the player beside them moves (or widens)
    so that player is either fully in or fully out, and the main player stays inside."""
    from photo_presets.cull.measure import clean_edges
    size = (6000, 4000)
    main = (2600, 1500, 3000, 2700)          # the main player
    other = (3150, 1550, 3550, 2700)         # a player just to the right
    box = (2400, 1200, 3360, 2400)           # centered on the main player: cuts the other in half
    out = clean_edges(box, size, [main, other], main, main)
    assert out[0] <= main[0] and out[2] >= main[2]  # main fully in
    seen = max(0, min(other[2], out[2]) - max(other[0], out[0])) / (other[2] - other[0])
    assert seen < 0.02 or seen > 0.9, seen
    assert abs((out[2] - out[0]) / (out[3] - out[1]) - (box[2] - box[0]) / (box[3] - box[1])) < 0.01  # same shape


def test_team_photo_on_border():
    from PIL import Image
    from photo_presets.cull.export import team_on_border
    img = Image.new("RGB", (6000, 4000), (40, 120, 40))
    out = team_on_border(img, (0.1, 0.3, 0.9, 0.8), 4 / 5, (1080, 1350))
    assert out.size == (1080, 1350)


def test_edited_copies_dont_raise_the_sharpness_bar():
    """Shrunk, sharpened copies (other sizes) in a folder must not make the camera's photos look soft,
    and a lone crop the camera focused on is not marked down for sharpness."""
    from photo_presets.cull import rank
    cam = [{"subject": (0, 0, 1, 1), "sharp": v, "full": (7008, 4672), "focus_on_subject": True} for v in (700, 800, 850, 900)]
    edits = [{"subject": (0, 0, 1, 1), "sharp": v, "full": (1080, 1350)} for v in (2000, 3000, 3600)]
    crop = {"subject": (0, 0, 1, 1), "sharp": 806, "full": (3178, 4048), "focus_on_subject": True}
    items = [(str(i), float(i), m) for i, m in enumerate(cam + edits + [crop])]
    r = rank.rank(items)
    assert r["1"].parts["sharp"] > 0.6  # a camera photo judged against its own kind
    assert r[str(len(items) - 1)].parts["sharp"] > 0.8  # the lone crop


def test_narrow_photo_keeps_the_player_whole_on_a_border(tmp_path):
    """A photo too narrow for 4:5 to hold the player with room (a tall screenshot): the player whole,
    head and feet with room, on a soft border, never trimmed."""
    from PIL import Image
    import numpy as np
    from photo_presets.cull import export
    img = Image.new("RGB", (1320, 2868), (40, 120, 40))
    px = img.load()
    for x in range(400, 900):  # the player: red head at the top, blue feet at the bottom of them
        for y in range(953, 990):
            px[x, y] = (255, 0, 0)
        for y in range(2600, 2637):
            px[x, y] = (0, 0, 255)
    src = tmp_path / "keeper.png"
    img.save(src)
    m = {"crops": {"4:5": (0.0, 0.338, 1.0, 0.913)}, "subject": (0.26, 0.3325, 0.85, 0.919),
         "border": {"4:5": (0.0, 0.272, 1.0, 0.941)}, "full": (1320, 2868)}
    out = np.asarray(Image.open(export.edit_one(src, m, "instagram", "O", tmp_path / "out")[0]).convert("RGB")).astype(int)
    h = out.shape[0]
    red = np.where((out[:, :, 0] > 200) & (out[:, :, 1] < 60))[0]
    blue = np.where((out[:, :, 2] > 200) & (out[:, :, 0] < 60))[0]
    assert len(red) and len(blue)
    assert red.min() > 0.05 * h and blue.max() < 0.97 * h  # room above the head and below the feet


def test_export_never_writes_one_keeper_over_another_with_the_same_name(tmp_path, monkeypatch):
    """Two folders (two cameras) in one event, both with DSC00001.jpg: each keeper gets its own file."""
    from fastapi.testclient import TestClient
    import time
    import photo_presets.studio.cull as cu
    from photo_presets.studio import server
    monkeypatch.setattr(cu, "HOME", tmp_path)
    monkeypatch.setattr(cu, "STATE_FILE", tmp_path / "cull.json")
    monkeypatch.setattr(cu, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cu, "TEST_OUT", None)
    cams = [tmp_path / "Event" / "cam A", tmp_path / "Event" / "cam B"]
    for i, d in enumerate(cams):
        d.mkdir(parents=True)
        Image.new("RGB", (600, 400), (200 * i, 60, 60)).save(d / "DSC00001.jpg")
    monkeypatch.setattr(cu.measure, "measure", lambda path, cache: m())
    monkeypatch.setattr(cu, "C", cu.Cull())
    c = TestClient(server.app)
    sid = c.post("/api/cull/shoots", json={"folders": [str(d) for d in cams]}).json()["id"]
    for _ in range(100):
        r = c.get(f"/api/cull/shoots/{sid}/photos").json()
        if r["shoot"]["pass1"]:
            break
        time.sleep(0.05)
    ids = [p["id"] for p in r["photos"]]
    assert len(ids) == 2
    for what, body in (("edit", {"versions": "O", "size": "youtube"}), ("copy", {})):
        out = c.post(f"/api/cull/shoots/{sid}/export", json={"what": what, "ids": ids, "folder": f"Out {what}", **body}).json()
        for _ in range(200):
            j = c.get("/api/cull/state").json()["shoots"][0]["job"]
            if j["state"] != "now":
                break
            time.sleep(0.05)
        assert j["state"] == "done", j
        made = sorted(p.name for p in Path(out["folder"]).iterdir())
        assert len(made) == 2, made  # (one each: neither written over)
    # a folder name is only a name: never a path somewhere else
    out = c.post(f"/api/cull/shoots/{sid}/export", json={"what": "copy", "ids": ids[:1], "folder": "../../elsewhere"}).json()
    assert Path(out["folder"]).parent == cams[0]
