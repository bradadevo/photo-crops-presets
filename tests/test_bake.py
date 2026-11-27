"""Looks on top of an edit: the edited photo is saved at full size to make looks from."""

import numpy as np
from PIL import Image

from photo_crops import images
from photo_presets import pipeline
from photo_presets.engine import Engine, Job


def test_the_edited_photo_keeps_its_edits_at_full_size(tmp_path):
    src = tmp_path / "game.jpg"
    rng = np.random.default_rng(0)
    Image.fromarray(rng.integers(90, 170, (300, 400, 3), np.uint8)).save(src, quality=95)
    e = Engine()
    r = e.look(Job(src, {"name": "Original", "steps": []}, 0))
    darker = e.adjust(r, {"exposure": -1.0})
    baked = e.bake(darker, tmp_path / "edited")
    assert baked.name == "game.tif"  # named as the photo, so its exports are too
    photo = images.load(baked)
    assert photo.image.size == (400, 300)  # full size
    before = np.asarray(Image.open(src), np.float32).mean()
    assert np.asarray(photo.image, np.float32).mean() < before * 0.75  # the edit is in it
    assert e.bake(darker, tmp_path / "edited") == baked  # made once
    assert pipeline.adjusted(darker.recipe)
