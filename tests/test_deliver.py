"""Delivery: sizes, credit, watermark, and matching a game."""

from pathlib import Path

import numpy as np
from PIL import Image

from photo_crops import images
from photo_presets import deliver, match, pipeline


def test_crops_keep_the_players_and_the_shape():
    w, h = 6000, 4000
    # a 4:5 crop of a landscape photo, players near the left edge
    x0, y0, x1, y1 = deliver.crop_box(w, h, 4 / 5, (0.12, 0.5), keep=(0.05, 0.3, 0.2, 0.8))
    assert abs((x1 - x0) / (y1 - y0) - 0.8) < 0.01 and x0 == 0  # pushed to the edge, not past it
    assert x1 >= 0.2 * w  # the players are whole
    # players wider than the crop: centered on the focus
    x0, _, x1, _ = deliver.crop_box(w, h, 9 / 16, (0.5, 0.5), keep=(0.1, 0.2, 0.9, 0.8))
    assert abs((x0 + x1) / 2 - w / 2) <= 1


def test_sizes_have_exact_pixels_and_follow_print_orientation():
    land = np.random.default_rng(0).random((400, 600, 3)).astype(np.float32)
    out, grow = deliver.sized(land, deliver.SIZES["ig_portrait"], (0.5, 0.5))
    assert out.shape == (1350, 1080, 3) and grow > 1
    out, _ = deliver.sized(land, deliver.SIZES["print_8x10"], (0.5, 0.5))
    assert out.shape == (2400, 3000, 3)  # landscape photo: landscape print
    port = land.transpose(1, 0, 2)
    out, _ = deliver.sized(port, deliver.SIZES["print_8x10"], (0.5, 0.5))
    assert out.shape == (3000, 2400, 3)


def test_credit_goes_into_exif_and_xmp(tmp_path):
    credit = deliver.Credit("Brad DeVore", "", "brad@example.com")
    assert credit.notice(2026) == "© 2026 Brad DeVore"
    exif = deliver.credited_exif(None, credit, 2026)
    packet = deliver.xmp(credit, 2026)
    dest = tmp_path / "a.jpg"
    images.save_jpeg(Image.new("RGB", (16, 16)), dest, exif, packet)
    img = Image.open(dest)
    data = img.getexif()
    assert data[0x013B] == "Brad DeVore" and data[0x8298] == "(c) 2026 Brad DeVore"
    xmp = img.info.get("xmp")
    assert b"Brad DeVore" in xmp and b"CiEmailWork>brad@example.com" in xmp
    assert "© 2026 Brad DeVore".encode() in xmp
    tif = tmp_path / "a.tif"
    images.save_tiff16(np.zeros((8, 8, 3), np.float32), tif, exif, packet)
    import tifffile
    with tifffile.TiffFile(tif) as t:
        tags = t.pages[0].tags
        assert tags["Artist"].value == "Brad DeVore" and "2026" in tags["Copyright"].value
        assert b"Brad DeVore" in bytes(tags["XMP"].value)
    assert deliver.xmp(deliver.Credit(), 2026) is None
    assert deliver.credited_exif(b"x", deliver.Credit()) == b"x"  # nothing given: untouched


def test_credit_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver, "CONFIG", tmp_path / "delivery.json")
    deliver.Credit("A", "B", "C").save()
    assert deliver.Credit.load() == deliver.Credit("A", "B", "C")


def test_watermarks_mark_the_right_place():
    arr = np.zeros((600, 900, 3), np.float32)
    corner = deliver.watermark(arr, deliver.Watermark("© 2026 Brad DeVore", deliver.CORNER, 0.6))
    assert corner[450:, 600:].max() > 0.3 and corner[:300, :300].max() == 0  # bottom right only
    across = deliver.watermark(arr, deliver.Watermark("PROOF", deliver.ACROSS, 0.6))
    for part in (across[:300, :450], across[300:, 450:]):
        assert part.max() > 0.1  # all over the photo
    assert np.array_equal(deliver.watermark(arr, deliver.Watermark("  ")), arr)


def test_matching_evens_out_light_and_color():
    rng = np.random.default_rng(1)
    scene = rng.random((120, 160, 3)).astype(np.float32) * 0.6 + 0.2
    scene[:40] = 0.75  # a white kit / haze: near-neutral
    reference = Image.fromarray((scene * 255).astype(np.uint8))
    darker_warm = np.clip(scene * 0.6 * np.array([1.06, 1.0, 0.92], np.float32), 0, 1)
    photo = Image.fromarray((darker_warm * 255).astype(np.uint8))
    m = match.correction(match.measure(reference), match.measure(photo))
    assert 0.4 < m["stops"] <= match.MAX_STOPS  # brightened toward the reference
    assert m["gains"][2] > 1 > m["gains"][0]  # the warm cast cooled
    fixed = match.apply(pipeline.to_array(photo), m)
    before = abs(np.median(pipeline.to_array(photo)) - np.median(scene))
    assert abs(np.median(fixed) - np.median(scene)) < before / 2
    assert match.correction(match.measure(reference), match.measure(reference)) is None


def test_a_match_comes_before_the_look(tmp_path):
    from photo_presets.assets import Library, Sources
    from photo_presets.scene import Scene
    img = Image.fromarray(np.full((20, 20, 3), 60, np.uint8))
    lib = Library(Sources([], [], [], [], [], []))
    out, _ = pipeline.render(img, {"steps": [], "match": {"stops": 1.0, "gains": [1, 1, 1]}}, lib, Scene())
    assert abs(np.asarray(out)[0, 0, 0] - 120) <= 1
