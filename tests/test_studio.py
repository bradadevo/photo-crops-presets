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
    monkeypatch.setattr(server.E, "_sharp", __import__("collections").OrderedDict())
    server.PICTURES.items.clear()  # (pictures made by another test for the same slot number)
    monkeypatch.setattr(server, "AHEAD_DIR", tmp_path / "ahead")
    monkeypatch.setattr(server, "A", server.Ahead())
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
    assert len(list(server.AHEAD_DIR.glob("*.jpg"))) == 2  # kept on disk
    server.A = server.Ahead()  # (as after a restart)
    assert client.get(f"/img/ahead/{pid}/Clean Pro.jpg?e={r['token']}").status_code == 200  # from disk, not made again
