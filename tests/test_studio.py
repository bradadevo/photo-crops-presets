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
