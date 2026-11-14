"""Lightroom presets to LUTs, through the color chart."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photo_crops import images
from photo_presets import lightroom, luts


def preset(a):  # a stand-in for a Lightroom preset: warmer, a contrast curve, muted blues
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    out = np.stack([r ** 0.85 * 1.04, g ** 0.97, b ** 1.15 * 0.93], -1)
    return np.clip(out, 0, 1).astype(np.float32)


def test_a_preset_round_trips_through_the_chart(tmp_path):
    chart = tmp_path / "chart.tif"
    lightroom.save_chart(chart)
    exported = tmp_path / "Moody Film.tif"
    images.save_tiff16(preset(lightroom.read_chart(chart)), exported, None)  # "Lightroom"
    name, cube, notes = lightroom.convert(exported, folder=tmp_path / "luts")
    assert name == "Moody Film" and cube.exists() and not notes
    lut = luts.parse_cube(str(cube))
    assert lut.size == 64
    colors = np.random.default_rng(0).random((200, 300, 3)).astype(np.float32)
    assert np.abs(luts.apply_float(colors, lut) - preset(colors)).max() < 0.012  # within about 3 levels


def test_problems_are_explained(tmp_path):
    chart = lightroom.chart()
    with pytest.raises(ValueError, match="full size"):
        lightroom.to_table(chart[:500, :500])  # resized or cropped
    assert any("applied" in n for n in lightroom.check(lightroom.to_table(chart)))  # nothing changed
    grainy = np.clip(preset(chart) + np.random.default_rng(1).normal(0, 0.02, chart.shape), 0, 1)
    assert any("grain" in n for n in lightroom.check(lightroom.to_table(grainy.astype(np.float32))))


def test_names_come_from_the_file():
    assert lightroom.lut_name(Path("Golden_Hour chart.tif")) == "Golden Hour"
    assert lightroom.lut_name(Path("Moody Film-AllProPhoto color chart.tif")) == "Moody Film"


def test_float_luts_match_pillow_and_keep_precision():
    n = 17
    g = np.linspace(0, 1, n, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    lut = luts.Lut("t", np.stack([r ** 0.8, gg * 0.9 + 0.05, np.sqrt(b)], -1).astype(np.float32),
                   np.zeros(3, np.float32), np.ones(3, np.float32))
    a8 = np.random.default_rng(2).integers(0, 256, (50, 60, 3), np.uint8)
    ref = np.asarray(luts.apply_lut(Image.fromarray(a8), lut), np.float32) / 255
    assert np.abs(luts.apply_float(a8.astype(np.float32) / 255, lut) - ref).max() <= 1 / 255
    ramp = np.tile(np.linspace(0.2, 0.21, 400, dtype=np.float32)[None, :, None], (2, 1, 3))
    assert len(np.unique(luts.apply_float(ramp, lut)[0, :, 0])) > 100  # smooth, not 3 flat 8-bit steps
