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
    return TestClient(server.app)


def _jpeg(color=(40, 90, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(buf, "JPEG")
    return buf.getvalue()


def test_every_preset_is_in_the_picker(client):
    data = client.get("/api/looks").json()
    names = {look["name"] for look in data["looks"]}
    assert names == set(presets.load_all())
    assert data["groups"][0] == "Bold" and "Mine" in data["groups"]
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
    assert Image.open(io.BytesIO(client.get(f"/img/slot/999/{s['ver']}/after.jpg").content)).size == (160, 240)
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
