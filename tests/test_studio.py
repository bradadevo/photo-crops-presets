"""The studio server: looks listed for the picker, photos added once, pictures served."""

import io
import os
import threading
import time
from pathlib import Path

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
    monkeypatch.setattr(server, "CUT", server.CutAhead(tmp_path / "cut-ahead.json", run=False))
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
    assert len([f for f in server.AHEAD_DIR.glob("*.jpg") if ".chip" not in f.name and ".card" not in f.name]) == 2  # kept on disk (with small pictures)
    assert client.get(f"/img/ahead/{pid}/Clean Pro.jpg?e={r['token']}&chip=1").status_code == 200
    # the grid's card of a look made ahead: that very picture, not drawn a second time
    monkeypatch.setattr(server, "_swatch", lambda *a: (_ for _ in ()).throw(AssertionError("drawn twice")))
    s = client.post(f"/api/swatches/{pid}", json={"names": ["Clean Pro", "Mono Editorial"]}).json()
    assert sorted(s["ready"]) == ["Clean Pro", "Mono Editorial"]
    card = client.get(f"/img/swatch/{pid}/Clean Pro.jpg?e={s['token']}")
    assert card.status_code == 200 and max(Image.open(io.BytesIO(card.content)).size) <= server.SWATCH
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


def _players_photo(monkeypatch, tmp_path):
    """Each photo with a player in it, and the cut-out model faked (counted, no AI in the test)."""
    import numpy as np
    from photo_presets import scene
    monkeypatch.setenv("ALLPROPHOTO_STATE", str(tmp_path))  # (the kept cut-outs: in the test's folder)
    runs = []

    def unkept(path, crop):
        img = Image.open(path).convert("RGB")
        subject = np.zeros((img.height, img.width), bool)
        subject[40:200, 100:220] = True
        return scene.Prepared(path, img, scene.Scene(subject_mask=subject), None)

    def made(image, sc):
        runs.append(image.size)
        time.sleep(0.2)  # (the model takes a while: long enough for two to meet)
        return sc.subject_mask.astype(np.float32)
    monkeypatch.setattr(server.E, "unkept", unkept)
    monkeypatch.setattr(scene, "_made_matte", made)
    return runs


def test_each_added_photo_is_cut_out_ahead_and_remembered_after_a_restart(client, monkeypatch, tmp_path):
    """Adding photos starts their players' cut-out at once (in the background); each is kept on disk and
    remembered, so a restart cuts out none of them again, and the app knows they're ready."""
    runs = _players_photo(monkeypatch, tmp_path)
    files = [("files", (f"p{i}.jpg", _jpeg((40 + i, 90, 160)), "image/jpeg")) for i in range(3)]
    pids = client.post("/api/photos/upload", files=files).json()["added"]
    assert server.CUT.queue == pids  # (all of them waiting, in the event's order)
    path = server.S.photo(pids[0]).path
    assert not server.E.is_cut_out(path, "none")
    for pid in list(server.CUT.queue):
        server.CUT.queue.remove(pid)
        server.CUT.one(pid)
    assert len(runs) == 3
    assert server.E.is_cut_out(path, "none")  # (ready: the page's wait estimate says so too)
    again = server.CutAhead(server.CUT.file, run=False)  # (as after a restart)
    monkeypatch.setattr(server, "CUT", again)
    again.want(pids)
    assert again.queue == [] and server.E.is_cut_out(path, "none")
    p = server.E.prepared(path, "none")  # (a look needing the players: from disk, the model isn't run again)
    assert p.ensure_matte() is not None and len(runs) == 3


def test_a_changed_photo_is_cut_out_again(client, monkeypatch, tmp_path):
    runs = _players_photo(monkeypatch, tmp_path)
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    server.CUT.queue.clear()
    server.CUT.one(pid)
    path = server.S.photo(pid).path
    assert server.CUT.is_done(path)
    path.write_bytes(_jpeg((200, 30, 30)))  # (the file changed: an edited copy saved over it)
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert not server.CUT.is_done(path)
    server.CUT.want([pid])
    assert server.CUT.queue == [pid]


def test_the_photo_you_open_is_cut_out_first(client, monkeypatch, tmp_path):
    _players_photo(monkeypatch, tmp_path)
    files = [("files", (f"p{i}.jpg", _jpeg((40 + i, 90, 160)), "image/jpeg")) for i in range(4)]
    pids = client.post("/api/photos/upload", files=files).json()["added"]
    client.post(f"/api/ahead/{pids[2]}", json={"order": []})
    assert server.CUT.queue == [pids[2], pids[0], pids[1], pids[3]]


def test_two_asking_for_one_photos_cut_out_run_the_model_once(client, monkeypatch, tmp_path):
    """The background and a look you make ask for the same photo's players at once: the model runs once
    (one cut-out at a time in the whole app, never two of several GB each), the other reads it from disk."""
    runs = _players_photo(monkeypatch, tmp_path)
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    path = server.S.photo(pid).path
    a, b = server.E.unkept(path, "none"), server.E.unkept(path, "none")  # (two separate copies of the photo)
    t = threading.Thread(target=a.ensure_matte)
    t.start()
    time.sleep(0.05)
    assert b.ensure_matte() is not None
    t.join()
    assert len(runs) == 1 and a.matte_key == b.matte_key


def test_looks_on_the_players_wait_for_the_cut_out_made_ahead_the_rest_are_made_now(client, monkeypatch):
    """While a photo's players are being cut out in the background, its looks that don't need them are
    made ahead at once, and the ones that do wait for it (they'd hold up the app's worker for 20 s)."""
    from photo_presets import pipeline
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    looks = server.A.looks()
    on_players = [n for n, r in looks.items() if pipeline.needs_cutout(r)]
    plain = [n for n, r in looks.items() if not pipeline.needs_cutout(r)]
    assert on_players and plain
    made = []
    monkeypatch.setattr(server.Ahead, "_make", lambda self, key, name: made.append(name) or (b"x", b"x"))
    monkeypatch.setattr(server.Ahead, "get", lambda self, *a, **k: None)
    client.post(f"/api/ahead/{pid}", json={"order": [on_players[0], plain[0]]})
    for _ in range(200):
        if len(made) >= len(plain):
            break
        time.sleep(0.02)
    assert set(made) == set(plain)  # (the players' looks held back)
    server.CUT.queue.clear()  # (its cut-out done)
    server.A.kick()
    for _ in range(200):
        if len(made) == len(looks):
            break
        time.sleep(0.02)
    assert set(made) == set(looks) and made[len(plain)] == on_players[0]  # (the one under the pointer first)


def test_the_background_cut_out_steps_aside_for_the_photo_you_open(client, monkeypatch, tmp_path):
    """Opening another photo while the background waits to cut one out: the one you opened goes first,
    the other right after it (not to the back of the event)."""
    _players_photo(monkeypatch, tmp_path)
    files = [("files", (f"p{i}.jpg", _jpeg((40 + i, 90, 160)), "image/jpeg")) for i in range(3)]
    pids = client.post("/api/photos/upload", files=files).json()["added"]
    cut = server.CUT
    cut.queue = [pids[2], pids[1]]  # (pids[0] taken off the queue: about to be cut out)
    monkeypatch.setattr(server.A, "key", (pids[2], ""))
    monkeypatch.setattr(server.A, "busy", True)  # (the opened photo's looks being made)
    cut.one(pids[0])
    assert cut.queue == [pids[2], pids[0], pids[1]] and not cut.is_done(server.S.photo(pids[0]).path)


def test_an_edited_photo_light_and_color_only_keeps_the_originals_players(client, monkeypatch, tmp_path):
    """Looks made on top of your edit (a slider moved): the players are found and cut out once, on the
    photo; the edited copy (nothing moved) reuses them, never 20 s more on the worker. A crop moves
    them: that copy finds its own."""
    import numpy as np
    from photo_presets import engine, scene
    monkeypatch.setenv("ALLPROPHOTO_STATE", str(tmp_path))
    runs, found = [], []

    def fake_prepare(path, crop="none", retouch=None, **k):
        found.append(Path(path).name)
        img = Image.open(path).convert("RGB")
        subject = np.zeros((img.height, img.width), bool)
        subject[40:200, 100:220] = True
        return scene.Prepared(Path(path), img, scene.Scene(subject_mask=subject, faces=[(0.5, 0.3, 0.05)]), None)

    def made(image, sc):
        runs.append(image.size)
        return sc.subject_mask.astype(np.float32)
    monkeypatch.setattr(engine, "prepare", fake_prepare)
    monkeypatch.setattr(scene, "_made_matte", made)
    monkeypatch.setattr(server.E, "_prepared", __import__("collections").OrderedDict())
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    path = server.S.photo(pid).path
    r = server.E._one(path, "none", {"steps": []}, 0)
    lit = server.E.adjust(r, dict(server.pipeline.ADJUST, background=-0.5))  # (a slider: light only)
    baked = server.E.bake(lit, tmp_path / "edited")
    p = server.E.prepared(baked, "none")
    assert p.players_from is not None and p.ensure_matte() is not None
    assert len(runs) == 1 and found.count(baked.name) == 0  # (cut out once; the copy's players never looked for)
    assert server.E.is_cut_out(baked, "none")
    import dataclasses as dc
    cropped = dc.replace(lit, edits={"crop": [0.1, 0.1, 0.9, 0.9]})  # (a crop: the players moved)
    again = server.E.bake(cropped, tmp_path / "edited")
    assert str(again) not in server.E.same_as


def test_an_older_ask_arriving_late_never_reorders_the_looks(client, monkeypatch):
    """The page asks every moment; one sent just before you pointed at a look can arrive just after: the
    look under the pointer stays first."""
    pid = client.post("/api/photos/upload", files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))]).json()["added"][0]
    names = list(server.A.looks())
    monkeypatch.setattr(server.Ahead, "kick", lambda self: None)  # (only the order, here)
    client.post(f"/api/ahead/{pid}", json={"order": [names[5]], "page": "p1", "seq": 7})
    client.post(f"/api/ahead/{pid}", json={"order": [names[0]], "page": "p1", "seq": 6})  # (sent before, came after)
    assert server.A.order[0] == names[5]
    client.post(f"/api/ahead/{pid}", json={"order": [names[2]], "page": "p1", "seq": 8})
    assert server.A.order[0] == names[2]
    client.post(f"/api/ahead/{pid}", json={"order": [names[3]], "page": "p2", "seq": 1})  # (another window)
    assert server.A.order[0] == names[3]


def test_the_photos_panel_says_which_photos_are_getting_ready(client):
    """Each photo's state, for the banner and the photo tiles: the one being got ready, the ones waiting
    in order, and the rest ready; with about how long is left."""
    from photo_presets.studio import server
    ids = [client.post("/api/photos/upload", files=[("files", (f"p{i}.jpg", _jpeg((40 + i * 30, 90, 160)), "image/jpeg"))]).json()["added"][0]
           for i in range(3)]
    b = client.get("/api/prep").json()
    assert b["now"] is None and b["waiting"] == ids and b["done"] == 0 and b["total"] == 3
    assert b["left_s"] == 3 * b["each"]
    with server.CUT.cv:  # (as when the first is being got ready)
        server.CUT.now = server.CUT.queue.pop(0)
        server.CUT.since = time.time()
    b = client.get("/api/prep").json()
    assert b["now"] == ids[0] and b["waiting"] == ids[1:] and b["done"] == 0
    with server.CUT.cv:
        server.CUT.now = None
        server.CUT.queue.clear()
    b = client.get("/api/prep").json()
    assert b == b | {"now": None, "waiting": [], "done": 3, "total": 3, "left_s": 0}


def test_only_a_photo_with_a_player_becomes_a_looks_example(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(server, "_PLAYER", {})
    monkeypatch.setattr(server, "camera_photo", lambda p: True)  # (both from a camera)
    player = SimpleNamespace(subject_box=(0.4, 0.2, 0.6, 0.9), subject_height=0.7)
    bird = SimpleNamespace(subject_box=None, subject_height=0.5)  # (no person found: a heron on grass)
    speck = SimpleNamespace(subject_box=(0.5, 0.5, 0.52, 0.55), subject_height=0.05)
    assert server.example_photo(tmp_path / "player.jpg", player)
    assert not server.example_photo(tmp_path / "heron.jpg", bird)
    assert not server.example_photo(tmp_path / "far.jpg", speck)
