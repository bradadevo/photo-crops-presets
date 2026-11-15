import json

from photo_presets import pipeline, timing


def _use(tmp_path, monkeypatch):
    monkeypatch.setattr(timing, "CONFIG", tmp_path)
    monkeypatch.setattr(timing, "LEARNED", tmp_path / "timings.json")
    monkeypatch.setattr(timing, "MEASURED", {"Oil": 20.0})


def test_measured_then_guessed(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    assert timing.seconds("Oil", {}) == 20.0
    assert timing.seconds("Mine", {"steps": [{"op": "comic_redraw"}]}) == timing.DRAWN
    assert timing.seconds("Mine", {"steps": [{"op": "vignette"}]}) == timing.QUICK


def test_learning_averages_real_runs(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    timing.learn("Oil", 40.0)
    assert timing.seconds("Oil", {}) == 28.0  # 0.6 x 20 + 0.4 x 40
    assert json.loads((tmp_path / "timings.json").read_text()) == {"Oil": 28.0}
    timing.learn("New", 5.0)
    assert timing.seconds("New", {}) == 5.0


def test_run_adds_photos_and_model_loading(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    monkeypatch.setattr(timing, "models_loaded", lambda: False)
    ai = {"steps": [{"op": "comic_redraw"}]}
    assert timing.run_seconds([("Oil", ai)] * 2, photos=2) == 40 + 2 * timing.PHOTO_READY + timing.MODEL_LOAD + (2 * timing.CUT_OUT if pipeline.needs_cutout(ai) else 0)
    monkeypatch.setattr(timing, "models_loaded", lambda: True)
    assert timing.run_seconds([("Oil", ai)], photos=1, ready=1) == 20


def test_say():
    assert timing.say(0.3) == "about 1 s"
    assert timing.say(23) == "about 25 s"
    assert timing.say(400) == "about 7 min"
