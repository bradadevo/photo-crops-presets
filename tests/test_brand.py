"""The brand kit: logos made transparent, recolored and placed."""

import numpy as np
from PIL import Image, ImageDraw

from photo_presets import brand


def _crest_on_white() -> Image.Image:
    img = Image.new("RGB", (300, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((80, 30, 220, 170), fill=(20, 40, 120))
    d.ellipse((120, 70, 180, 130), fill=(220, 30, 40))
    return img


def test_a_logo_on_white_becomes_transparent_and_trimmed():
    logo = brand.transparent(_crest_on_white())
    a = np.asarray(logo)[..., 3]
    assert logo.size[0] < 200 and logo.size[1] < 180  # trimmed to the crest
    assert a[0, 0] == 0 and a[a.shape[0] // 2, a.shape[1] // 2] == 255
    rgb = np.asarray(logo)[..., :3][a > 250]
    assert rgb.mean() < 200  # no white fringe left in the crest


def test_a_logo_with_a_clear_background_is_kept():
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((20, 20, 80, 80), fill=(255, 200, 0, 255))
    logo = brand.transparent(img)
    assert logo.size == (65, 65) and np.asarray(logo)[32, 32, 0] == 255


def test_placed_and_auto_colored(tmp_path):
    meta = brand.add(tmp_path, _crest_on_white(), "Crest")
    assert brand.listing(tmp_path)[0]["name"] == "Crest"
    light = np.ones((400, 600, 3), np.float32)
    out = brand.draw(light, [{"id": meta["id"], "x": 0.8, "y": 0.8, "size": 0.2, "color": "auto"}], tmp_path)
    assert out[:200].min() > 0.99  # nothing at the top
    assert out[300:360, 450:510].min() < 0.05  # black on a light picture
    dark = np.zeros((400, 600, 3), np.float32)
    out = brand.draw(dark, [{"id": meta["id"], "x": 0.8, "y": 0.8, "size": 0.2, "color": "auto"}], tmp_path)
    assert out[300:360, 450:510].max() > 0.95  # white on a dark one
    x, y = brand.corner_place("br", 0.2, 1.0, 600, 400)
    assert x > 0.8 and y > 0.75
    brand.remove_logo(tmp_path, meta["id"])
    assert brand.listing(tmp_path) == []


def test_auto_keeps_a_crest_as_it_is(tmp_path):
    crest = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(crest)
    d.ellipse((0, 0, 199, 199), fill=(0, 0, 0, 255))
    d.ellipse((50, 50, 150, 150), fill=(255, 255, 255, 255))
    assert not brand.flat(crest)
    meta = brand.add(tmp_path, crest, "Crest")
    dark = np.zeros((400, 400, 3), np.float32)
    out = brand.draw(dark, [{"id": meta["id"], "x": 0.5, "y": 0.5, "size": 0.5, "color": "auto"}], tmp_path)
    assert out[200, 200].min() > 0.9 and out[200, 120].max() < 0.1  # white middle, black ring: as it is


def test_a_two_color_logo_is_not_one_color():
    assert not brand.flat(brand.transparent(_crest_on_white()))
    mark = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    ImageDraw.Draw(mark).rectangle((10, 10, 110, 50), fill=(30, 30, 30, 255))
    assert brand.flat(mark)
