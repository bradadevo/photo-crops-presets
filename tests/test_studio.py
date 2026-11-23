"""The studio server: looks listed for the picker, photos added once, pictures served."""

import io

import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from photo_presets import presets  # noqa: E402
from photo_presets.studio import server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ADDED", tmp_path / "added")
    monkeypatch.setattr(server, "SESSION", tmp_path / "session.json")
    monkeypatch.setattr(server, "PREFS", tmp_path / "prefs.json")
    monkeypatch.setattr(server, "LOOKS", tmp_path / "looks")
    monkeypatch.setattr(server, "S", server.Session())
    monkeypatch.setattr(server.E, "sharp_dir", tmp_path / "sharp")
    monkeypatch.setattr(server.E, "cutout_dir", tmp_path / "cutouts")
    monkeypatch.setattr(server.E, "_cutouts", {})
    monkeypatch.setattr(server.E, "_sharp", __import__("collections").OrderedDict())
    server.PICTURES.items.clear()  # (pictures made by another test for the same slot number)
    monkeypatch.setattr(server, "AHEAD_DIR", tmp_path / "ahead")
    monkeypatch.setattr(server, "A", server.Ahead())
    monkeypatch.setattr(server, "EV", server.EventAhead())
    return TestClient(server.app)


def _jpeg(color=(40, 90, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(buf, "JPEG")
    return buf.getvalue()


def test_every_preset_is_in_the_picker(client):
    data = client.get("/api/looks").json()
    names = {look["name"] for look in data["looks"]}
    assert names == set(presets.load_all())
    assert data["groups"][:2] == ["Pro grades", "Bold"] and "Mine" in data["groups"]
    assert any(look["ai"] for look in data["looks"]) and any(not look["ai"] for look in data["looks"])
    assert data["sizes"][0]["key"] == "full"


def test_the_same_photo_is_added_once(client):
    first = client.post("/api/photos/upload", files=[("files", ("game.jpg", _jpeg(), "image/jpeg"))]).json()
    again = client.post("/api/photos/upload", files=[("files", ("game.jpg", _jpeg(), "image/jpeg"))]).json()
    assert len(first["added"]) == 1 and again["added"] == []
    state = client.get("/api/state").json()
    assert [p["name"] for p in state["photos"]] == ["game.jpg"]
    assert server.SESSION.exists()  # kept for next time


def test_photo_pictures_are_jpegs(client):
    pid = client.post("/api/photos/upload", files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    r = client.get(f"/img/photo/{pid}/thumb.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/img/photo/999/thumb.jpg").status_code == 404


def test_photos_come_back_after_a_restart(client, monkeypatch):
    client.post("/api/photos/upload", files=[("files", ("b.jpg", _jpeg((200, 50, 50)), "image/jpeg"))])
    monkeypatch.setattr(server, "S", server.Session())
    server.S.restore()
    assert [p.name for p in server.S.photos.values()] == ["b.jpg"]


def test_a_run_needs_photos_and_looks(client):
    assert client.post("/api/run", json={"photos": [], "looks": ["Clean Pro"]}).status_code == 400
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    r = client.post("/api/run", json={"photos": [pid], "looks": []})
    assert r.status_code == 400 and "look" in r.json()["error"]


def _made(client, monkeypatch):
    """A photo with one finished look in the session (made without the models)."""
    import dataclasses
    from pathlib import Path
    from photo_presets.engine import Result
    pid = client.post("/api/photos/upload", files=[("files", ("d.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    img = Image.new("RGB", (320, 240), (40, 90, 160))
    r = Result(Path(server.S.photo(pid).path), "none", {"name": "Clean Pro", "steps": []}, 0, img, img.copy())
    slot = server.Slot(999, 1, pid, "Clean Pro", r.title, 1.0, state="done", result=r)
    server.S.slots[999] = slot
    return slot


def test_editing_a_picture(client, monkeypatch):
    slot = _made(client, monkeypatch)
    s = client.post("/api/slots/999/edit", json={"adjust": {"exposure": 0.5},
                                                 "edits": {"crop": [0, 0, 0.5, 1], "texts": [{"text": "GO"}]}}).json()
    assert s["adjust"]["exposure"] == 0.5 and s["width"] == 160 and s["base_width"] == 320
    for kind in ("after", "thumb", "full", "before", "base"):
        r = client.get(f"/img/slot/999/{s['ver']}/{kind}.jpg")
        assert r.status_code == 200, kind
    shown = Image.open(io.BytesIO(client.get(f"/img/slot/999/{s['ver']}/after.jpg").content)).size
    assert shown[0] * 240 == shown[1] * 160 and shown[0] >= 160  # a tight crop: made sharp (bigger), its shape kept
    assert client.get("/api/slots/999/sharp").json() == {"on": True, "needed": True, "ready": True}
    assert client.post("/api/slots/rate", json={"ids": [999], "rating": 4}).status_code == 200
    assert slot.rating == 4


def test_sharing_exports_then_hands_over(client, monkeypatch, tmp_path):
    slot = _made(client, monkeypatch)
    calls = []
    out = tmp_path / "pic.jpg"
    out.write_bytes(_jpeg())
    monkeypatch.setattr(server.E, "export", lambda *a, **k: ([out], []))
    monkeypatch.setattr(server.subprocess, "Popen", lambda args, **k: calls.append(args))
    monkeypatch.setattr(server.W, "submit", lambda prio, fn, *a: fn(*a))  # at once, in the test
    task = client.post("/api/slots/999/share", json={"service": "airdrop"}).json()
    assert server.S.tasks[task["id"]].state == "done"
    assert calls and calls[0][-2:] == ["airdrop", str(out)]
    assert client.post("/api/slots/999/share", json={"service": "fax"}).status_code == 400


def test_looks_come_back_after_a_restart(client, monkeypatch):
    slot = _made(client, monkeypatch)
    client.post("/api/slots/999/edit", json={"edits": {"crop": [0, 0, 0.5, 1]}})
    client.post("/api/slots/keep", json={"ids": [999], "on": True})
    server.Keeper().flush()
    monkeypatch.setattr(server, "S", server.Session())
    server.S.restore()
    back = server.S.slots[999]
    assert back.state == "done" and back.kept and back.result.edits["crop"] == [0, 0, 0.5, 1]
    assert back.result.after.size == (320, 240)
    assert next(server.S.ids) > 999  # new looks never take its number


def test_the_page_is_the_one_the_app_started_with(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200 and r.content == server.PAGE["app.js"]
    assert client.get("/static/nope.js").status_code == 404


def test_page_scripts_do_not_declare_the_same_name_twice():
    """The page's scripts share one scope: a name declared in two of them stops the page loading."""
    import re
    from collections import Counter
    from pathlib import Path
    web = Path(__file__).parents[1] / "photo_presets/studio/web"
    names = Counter()
    for f in web.glob("*.js"):
        for n in set(re.findall(r"^(?:const|let|var|function|async function|class) ([A-Za-z_$][\w$]*)", f.read_text(), re.M)):
            names[n] += 1
    assert [n for n, c in names.items() if c > 1] == []


def test_a_sharp_crop_stays_sharp_when_a_poster_is_added_and_can_be_switched_off(client, monkeypatch):
    """The enhanced crop sticks: adding a poster (or any later click) lays the poster out on the same
    sharp picture, never back on the soft preview. AI sharpen off: the plain preview again."""
    _made(client, monkeypatch)
    monkeypatch.setattr(server.E, "sharp_on", True)
    s = client.post("/api/slots/999/edit", json={"edits": {"crop": [0, 0, 0.5, 1]}}).json()
    size = lambda ver: Image.open(io.BytesIO(client.get(f"/img/slot/999/{ver}/after.jpg").content)).size
    sharp = size(s["ver"])
    s = client.post("/api/slots/999/edit", json={"edits": {"crop": [0, 0, 0.5, 1],
                                                           "poster": {"template": "card", "title": "LINCOLN"}}}).json()
    with_poster = size(s["ver"])
    assert with_poster[0] >= sharp[0] * 0.95 and with_poster[0] > 160  # the poster on the sharp picture
    assert client.post("/api/prefs/sharp", json={"on": False}).json()["on"] is False
    off = size(server.S.slot(999).ver)
    assert off[0] < with_poster[0]  # switched off: the plain preview
    assert client.get("/api/slots/999/sharp").json()["needed"] is False
    client.post("/api/prefs/sharp", json={"on": True})


def test_sliders_colors_and_moving_words_never_run_the_crop_enhancement_again(client, monkeypatch):
    """The AI makes a tight crop sharp once; after that, sliders, poster colors and moving a word only
    redraw on top of it (the hang: every slider used to redo the whole enhancement)."""
    _made(client, monkeypatch)
    monkeypatch.setattr(server.E, "sharp_on", True)
    from photo_presets import enlarge
    runs = []
    real = enlarge.fit
    monkeypatch.setattr(enlarge, "fit", lambda *a, **k: (runs.append(1), real(*a, **k))[1])
    crop = {"crop": [0, 0, 0.5, 1]}
    poster = {"template": "card", "title": "LINCOLN"}
    get = lambda: client.get(f"/img/slot/999/{server.S.slot(999).ver}/after.jpg").status_code
    client.post("/api/slots/999/edit", json={"edits": crop | {"poster": poster}})
    assert get() == 200 and len(runs) == 1
    adj = server.S.slot(999).public()["adjust"]
    for v in (-0.3, -0.6):
        client.post("/api/slots/999/edit", json={"adjust": adj | {"background": v}})
        assert get() == 200
    for color in ("#b3121a", "#0b3d91"):
        client.post("/api/slots/999/edit", json={"edits": crop | {"poster": poster | {"color": color}}})
        assert get() == 200
    client.post("/api/slots/999/edit", json={"edits": crop | {"poster": poster | {"moves": {"title": {"x": 0.01, "y": 0, "s": 1}}}}})
    assert get() == 200
    assert len(runs) == 1  # enhanced once, kept for everything after


def test_a_sharp_crop_is_kept_on_disk_so_a_restart_never_runs_the_ai_again(client, monkeypatch):
    """Quit and reopen: the enhanced crop is loaded from disk (no AI), and thumbnails never start the AI."""
    _made(client, monkeypatch)
    monkeypatch.setattr(server.E, "sharp_on", True)
    from photo_presets import enlarge
    runs = []
    real = enlarge.fit
    monkeypatch.setattr(enlarge, "fit", lambda *a, **k: (runs.append(1), real(*a, **k))[1])
    client.post("/api/slots/999/edit", json={"edits": {"crop": [0, 0, 0.5, 1]}})
    ver = server.S.slot(999).ver
    assert client.get(f"/img/slot/999/{ver}/thumb.jpg").status_code == 200 and runs == []  # (a thumbnail: no AI)
    first = Image.open(io.BytesIO(client.get(f"/img/slot/999/{ver}/after.jpg").content)).size
    assert len(runs) == 1 and any((server.E.sharp_dir).iterdir())
    server.E._sharp.clear()  # (as after a restart: nothing in memory)
    server.PICTURES.items.clear()
    assert client.get("/api/slots/999/sharp").json()["ready"] is True
    again = Image.open(io.BytesIO(client.get(f"/img/slot/999/{ver}/after.jpg").content)).size
    assert again == first and len(runs) == 1  # loaded from disk, the AI not run again


def test_every_look_is_made_ahead_so_hovering_shows_it_at_once(client, monkeypatch):
    """Instant looks: the look under the pointer first, then the rest; each made once (kept on disk)."""
    import time
    pid = client.post("/api/photos/upload", files=[("files", ("h.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    looks = {"Clean Pro": presets.load_all()["Clean Pro"], "Mono Editorial": presets.load_all()["Mono Editorial"]}
    monkeypatch.setattr(server.Ahead, "looks", lambda self: looks)
    r = client.post(f"/api/ahead/{pid}", json={"order": ["Mono Editorial"]}).json()
    assert r["total"] == 2
    for _ in range(100):
        r = client.post(f"/api/ahead/{pid}", json={"order": ["Mono Editorial"]}).json()
        if len(r["ready"]) == 2:
            break
        time.sleep(0.1)
    assert sorted(r["ready"]) == ["Clean Pro", "Mono Editorial"]
    got = client.get(f"/img/ahead/{pid}/Mono Editorial.jpg?e={r['token']}")
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).size[0] > 100
    assert len([f for f in server.AHEAD_DIR.glob("*.jpg") if ".chip" not in f.name]) == 2  # kept on disk (with small pictures)
    assert client.get(f"/img/ahead/{pid}/Clean Pro.jpg?e={r['token']}&chip=1").status_code == 200
    server.A = server.Ahead()  # (as after a restart)
    assert client.get(f"/img/ahead/{pid}/Clean Pro.jpg?e={r['token']}").status_code == 200  # from disk, not made again


def _wait(fn, tries=200):
    import time
    for _ in range(tries):
        got = fn()
        if got:
            return got
        time.sleep(0.05)
    return fn()


def test_every_look_is_made_ahead_for_the_whole_event(client, monkeypatch):
    """Whole-event preview: each look once (even if the page names it twice), on every photo, kept on disk,
    and the small photos and cut-out model let go once all are made."""
    pids = [client.post("/api/photos/upload", files=[("files", (f"e{i}.jpg", _jpeg((40 + 60 * i, 90, 160)), "image/jpeg"))]).json()["added"][0]
            for i in range(2)]
    looks = {"Clean Pro": presets.load_all()["Clean Pro"], "Mono Editorial": presets.load_all()["Mono Editorial"]}
    monkeypatch.setattr(server.Ahead, "looks", lambda self: looks)
    ask = lambda: client.post("/api/event-ahead", json={"order": ["Mono Editorial", "Mono Editorial", "Clean Pro"], "focus": "Mono Editorial"}).json()
    assert ask()["total"] == 2 and ask()["photos"] == 2  # (each look once)
    r = _wait(lambda: (lambda r: r if len(r["complete"]) == 2 else None)(ask()))
    assert r and sorted(r["complete"]) == ["Clean Pro", "Mono Editorial"] and sorted(r["focus"]) == sorted(pids)
    got = client.get(f"/img/event/{pids[0]}/Mono Editorial.jpg")
    assert got.status_code == 200 and max(Image.open(io.BytesIO(got.content)).size) <= server.EVENT_EDGE
    assert _wait(lambda: not server.EV.minis)  # (all made: the small photos let go)
    assert all(v is None for v in server.EV.made.values())  # (kept on disk, not held in memory)
    server.EV = server.EventAhead()  # (as after a restart)
    monkeypatch.setattr(server.EventAhead, "_make", lambda *a: (_ for _ in ()).throw(AssertionError("made again")))
    r = _wait(lambda: (lambda r: r if len(r["complete"]) == 2 else None)(ask()))
    assert r and client.get(f"/img/event/{pids[1]}/Clean Pro.jpg").status_code == 200  # from disk, not made again


def test_a_look_that_fails_never_stops_all_ready(client, monkeypatch):
    """One look failing on one photo: the rest are still made and "all ready" is still reached
    (the page would otherwise say "116 of 117" and keep asking for ever)."""
    pids = [client.post("/api/photos/upload", files=[("files", (f"f{i}.jpg", _jpeg((90, 40 + 50 * i, 60)), "image/jpeg"))]).json()["added"][0]
            for i in range(2)]
    looks = {"Clean Pro": presets.load_all()["Clean Pro"], "Mono Editorial": presets.load_all()["Mono Editorial"]}
    monkeypatch.setattr(server.Ahead, "looks", lambda self: looks)
    make_event, make_one = server.EventAhead._make, server.Ahead._make

    def broken_event(self, pid, name):
        if name == "Clean Pro" and pid == pids[0]:
            raise RuntimeError("broken look")
        return make_event(self, pid, name)

    def broken_one(self, key, name):
        if name == "Clean Pro":
            raise RuntimeError("broken look")
        return make_one(self, key, name)
    monkeypatch.setattr(server.EventAhead, "_make", broken_event)
    monkeypatch.setattr(server.Ahead, "_make", broken_one)
    ask = lambda: client.post("/api/event-ahead", json={"order": [], "focus": None}).json()
    r = _wait(lambda: (lambda r: r if len(r["complete"]) == r["total"] else None)(ask()))
    assert r and r["total"] == 2
    one = lambda: client.post(f"/api/ahead/{pids[0]}", json={"order": []}).json()
    r = _wait(lambda: (lambda r: r if len(r["ready"]) >= r["total"] else None)(one()))
    assert r and r["ready"] == ["Mono Editorial"] and r["failed"] == ["Clean Pro"] and r["total"] == 1


def test_thousands_of_kept_previews_come_back_without_a_crash(client, monkeypatch):
    """After a restart every preview comes straight from disk: the queue steps through them in a loop
    (a call per look would overflow Python's limit of about 1000)."""
    pid = client.post("/api/photos/upload", files=[("files", ("k.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    looks = {f"Look {i}": {"steps": []} for i in range(3000)}
    monkeypatch.setattr(server.Ahead, "looks", lambda self: looks)
    monkeypatch.setattr(server.EventAhead, "has", lambda self, p, n: self.made.setdefault((p, n), None) is None)
    monkeypatch.setattr(server.Ahead, "get", lambda self, p, t, n, chip=False: self.made.setdefault((p, t), {}).setdefault(n, (b"k", b"k"))[0])
    server.EV.want([pid], [])
    assert server.EV.status(None)["complete"].__len__() == 3000 and not server.EV.busy
    server.A.want(pid, "", [])
    assert len(server.A.ready(pid, "")) == 3000 and not server.A.busy


def test_kept_previews_are_bounded_and_go_with_their_small_copy(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(server.random, "random", lambda: 0.0)  # (check now)
    for i in range(10):
        (tmp_path / f"{i}.jpg").write_bytes(b"x")
        (tmp_path / f"{i}.chip.jpg").write_bytes(b"x")
        os.utime(tmp_path / f"{i}.jpg", (i, i))
    server._trim(tmp_path, 4)
    left = sorted(f.name for f in tmp_path.iterdir())
    assert left == sorted([f"{i}.jpg" for i in range(6, 10)] + [f"{i}.chip.jpg" for i in range(6, 10)])


def test_photo_thumbnails_are_kept_across_restarts(client, monkeypatch):
    pid = client.post("/api/photos/upload", files=[("files", ("t.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    first = client.get(f"/img/photo/{pid}/thumb.jpg").content
    server.PICTURES.items.clear()  # (as after a restart)
    monkeypatch.setattr(server.images, "preview_image", lambda *a: (_ for _ in ()).throw(AssertionError("read the camera file again")))
    monkeypatch.setattr(server.images, "load", lambda *a: (_ for _ in ()).throw(AssertionError("read the camera file again")))
    assert client.get(f"/img/photo/{pid}/thumb.jpg").content == first


def test_kept_previews_from_older_drawing_code_are_not_shown(client, monkeypatch):
    """A new version that draws looks differently never shows a preview the old one made (nor an old sharp crop)."""
    pid = client.post("/api/photos/upload", files=[("files", ("v.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    recipe = presets.load_all()["Clean Pro"]
    before = (server.A.file(pid, "", "Clean Pro", recipe), server.EV.file(pid, "Clean Pro", recipe))
    monkeypatch.setattr(server, "RENDER_CODE", "a-newer-version")
    after = (server.A.file(pid, "", "Clean Pro", recipe), server.EV.file(pid, "Clean Pro", recipe))
    assert before[0] != after[0] and before[1] != after[1]


def test_added_photos_get_their_small_picture_ahead(client, monkeypatch):
    """Added photos: their small pictures made in the background and kept on disk (not in memory)."""
    monkeypatch.setattr(server.W, "submit", lambda prio, fn, *a: fn(*a))  # (at once, in the test)
    pid = client.post("/api/photos/upload", files=[("files", ("n.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    kept = server._kept_thumb(server.S.photo(pid).path, server.THUMB)
    assert kept.exists() and ("photo", pid, "thumb") not in server.PICTURES.items


def test_a_looks_cut_out_comes_back_from_disk_after_a_restart(client, monkeypatch):
    """Sliders after a restart: the look's cut-out is loaded from disk (milliseconds), the photo isn't
    loaded and its players found again (seconds)."""
    import numpy as np
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    path = server.S.photo(pid).path
    r = server.E._one(path, "none", {"steps": []}, 0)
    fake = np.zeros((r.before.height, r.before.width), np.float32)
    fake[10:40, 20:60] = 1.0

    class P:  # (a prepared photo with a known cut-out: no AI in the test)
        scene = type("Sc", (), {"matte": fake})()
    monkeypatch.setattr(server.E, "ready", lambda *a, **k: P())
    first = server.E.cutout(r)
    assert first is not None and first[20, 30] > 0.9
    monkeypatch.setattr(server.E, "_cutouts", {})  # (as after a restart)
    monkeypatch.setattr(server.E, "ready", lambda *a, **k: (_ for _ in ()).throw(AssertionError("traced again")))
    again = server.E.cutout(r)
    assert np.array_equal(again, first)
