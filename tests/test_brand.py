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


SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
  <circle cx="50" cy="50" r="40" fill="#1f2a44"/><rect x="110" y="20" width="70" height="60" fill="#c8102e"/></svg>"""


def test_an_svg_logo_is_drawn_sharp_with_its_clear_background():
    from photo_presets import brand
    img = brand.open_any(SVG, "crest.svg")
    assert img.mode == "RGBA" and max(img.size) == brand.DRAW_EDGE
    assert img.size[0] == 2 * img.size[1]  # its own shape
    a = np.asarray(img)
    assert a[0, 0, 3] == 0  # the background stays clear
    assert a[img.height // 2, img.width // 4, 3] == 255  # the circle is solid


def test_a_pdf_logo_is_read_and_an_eps_says_what_to_do(tmp_path):
    import io
    import pytest
    from photo_presets import brand
    buf = io.BytesIO()
    Image.new("RGB", (300, 150), (31, 42, 68)).save(buf, "PDF")
    img = brand.open_any(buf.getvalue(), "sponsor.pdf")
    assert max(img.size) == brand.DRAW_EDGE
    logo = brand.add(tmp_path, brand.open_any(SVG, "crest.svg"), "crest")
    assert logo["name"] == "crest"
    with pytest.raises(brand.NotALogo, match="SVG, PDF or PNG"):
        brand.open_any(b"%!PS-Adobe-3.0 EPSF-3.0", "old.eps")


def test_a_two_tone_crest_in_white_keeps_its_letters_see_through():
    from photo_presets import brand
    a = np.zeros((100, 100, 4), np.uint8)
    a[..., 3] = 255
    a[20:80, 20:80, :3] = 255  # white letters on a black disc
    w = np.asarray(brand.colored(Image.fromarray(a, "RGBA"), "white"))
    assert w[5, 5, 3] == 255 and tuple(w[5, 5, :3]) == (255, 255, 255)  # the dark part: white
    assert w[50, 50, 3] == 0  # the letters: see-through, not a blank disc
