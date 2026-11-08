import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from photo_presets import reel


def test_photos_get_their_time_and_shorten_to_fit_under_a_minute():
    assert reel.fit(10) == (2.0, 10)                       # 20 s: every photo gets 2 s
    sec, keep = reel.fit(30)                               # 60 s at 2 s: shortened to fit 59 s
    assert keep == 30 and sec * keep <= 59 and sec >= reel.PHOTO_MIN_SEC
    sec, keep = reel.fit(60)                               # too many even at the shortest time
    assert sec == reel.PHOTO_MIN_SEC and keep == 39 and keep * sec <= 59


def test_with_a_song_every_cut_lands_on_a_beat():
    beat = 0.5                                             # 120 BPM
    sec, keep = reel.fit(10, beat=beat)
    assert sec / beat == pytest.approx(round(sec / beat)) and sec == 2.0
    assert reel.fit(10, beat=0.65)[0] == pytest.approx(1.95)   # 3 beats: the nearest to 2 s
    sec, keep = reel.fit(40, beat=0.47)
    assert sec / 0.47 == pytest.approx(round(sec / 0.47)) and sec >= reel.PHOTO_MIN_SEC and keep * sec <= 59


def test_song_starts_on_a_beat():
    assert reel.song_start([0.2, 0.7, 1.2, 1.7], 1.0) == 1.2
    assert reel.song_start([], 3.0) == 3.0


def test_landscape_photo_shows_half_its_width_centered_on_the_player():
    img = np.zeros((1000, 1500, 3), np.uint8)
    img[:, 1100:1200] = 255                                # the "player": a white band right of center
    shot = reel.Shot(Image.fromarray(img), focus=(1150 / 1500, 0.5))
    frame = reel._frame(reel._layers(shot), shot.focus, 0.0)
    assert frame.shape == (reel.H, reel.W, 3)
    assert frame[reel.H // 2, reel.W // 2].mean() > 200    # the player is in the middle of the screen
    assert frame[10, reel.W // 2].mean() < 200             # blurred copy above the photo


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_reel_is_a_vertical_mp4_of_the_planned_length(tmp_path):
    shots = [reel.Shot(Image.new("RGB", (600, 400), c), name=str(i))
             for i, c in enumerate([(200, 30, 30), (30, 200, 30), (30, 30, 200)])]
    p = reel.plan(shots, photo_sec=1.5)
    out = reel.render(p, tmp_path / "r.mp4", title="PSG 11U vs West Park", closing="@me")
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_name:format=duration", "-of", "json",
         str(out)], capture_output=True, text=True).stdout)
    v = info["streams"][0]
    assert (v["codec_name"], v["width"], v["height"]) == ("h264", 1080, 1920)
    assert float(info["format"]["duration"]) == pytest.approx(4.5, abs=0.1)
