"""Turning Lightroom presets (or any photo app's look) into LUTs the app can use.

The HALD trick: the app makes a color chart holding every color (a "HALD
CLUT": a 64 x 64 x 64 color cube laid out in a 512 x 512 picture). You apply
your preset to the chart in Lightroom and export it; how each square changed
is the preset's color, saved as a .cube LUT.

It captures everything a preset does to color and tone: white balance,
exposure, contrast, curves, HSL and color mixer, color grading, profiles,
B&W. It cannot capture what depends on where a pixel is or its neighbours:
masks, vignettes, grain, texture, clarity, dehaze, sharpening and noise
reduction. If those were on, the LUT comes out noisy; the check here warns.
"""

import re
from pathlib import Path

import numpy as np
from PIL import Image

from photo_crops import images

LEVEL = 8  # a 64-color cube, a 512 x 512 chart
LUT_FOLDER = Path.home() / ".config" / "photo-crops-presets" / "luts"
UNCHANGED = 0.002  # mean change below this: the preset was not applied
ROUGH = 0.012  # unevenness above this: grain, sharpening or a vignette were on


def chart(level: int = LEVEL) -> np.ndarray:
    """The identity color chart as floats 0-1 (level**3 pixels square):
    red changes fastest, then green, then blue."""
    n = level * level
    side = level ** 3
    i = np.arange(side * side)
    r, g, b = i % n, (i // n) % n, i // (n * n)
    return (np.stack([r, g, b], -1).reshape(side, side, 3) / (n - 1)).astype(np.float32)


def save_chart(dest: Path, level: int = LEVEL) -> Path:
    """The chart as a 16-bit TIFF in sRGB, ready to import into Lightroom."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    images.save_tiff16(chart(level), dest, None)
    return dest


def read_chart(path: Path) -> np.ndarray:
    """An exported chart as floats 0-1 (16-bit TIFF or PNG kept at 16 bits)."""
    if path.suffix.lower() in {".tif", ".tiff"}:
        import tifffile
        a = tifffile.imread(str(path))
        if a.ndim == 3 and a.shape[2] >= 3:
            a = a[..., :3]
            return a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0)
    img = Image.open(path)
    img = images.to_srgb(img.convert("RGB"), img.info.get("icc_profile"))
    return np.asarray(img, np.float32) / 255.0


def to_table(a: np.ndarray) -> np.ndarray:
    """The LUT table (N x N x N x 3, indexed [blue][green][red]) from a chart."""
    h, w = a.shape[:2]
    level = round(h ** (1 / 3))
    if h != w or level ** 3 != h or level < 4:
        raise ValueError(f"this is not the color chart: it is {w} x {h} pixels, the chart is "
                         f"{LEVEL ** 3} x {LEVEL ** 3}. Export it at full size (no resizing or cropping).")
    n = level * level
    return np.ascontiguousarray(a.reshape(n, n, n, 3), dtype=np.float32)


def check(table: np.ndarray) -> list[str]:
    """Warnings about a converted chart."""
    n = table.shape[0]
    ident = chart(round(n ** 0.5)).reshape(n, n, n, 3)
    notes = []
    if float(np.abs(table - ident).mean()) < UNCHANGED:
        notes.append("it is almost unchanged: was the preset applied before exporting?")
    rough = float(np.abs(table[:, :, 2:] - 2 * table[:, :, 1:-1] + table[:, :, :-2]).mean())
    if rough > ROUGH:
        notes.append("it is uneven, so grain, sharpening, texture, clarity, a vignette or a mask was probably on "
                     "in the preset; turn those off on the chart and export it again for a clean LUT")
    return notes


def write_cube(table: np.ndarray, dest: Path, title: str) -> Path:
    """Saves a .cube (red changes fastest, as the table's rows are laid out)."""
    n = table.shape[0]
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in table.reshape(-1, 3))
    dest.write_text(f'TITLE "{title}"\n# Made by AllProPhoto from a Lightroom color chart\n'
                    f"LUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n{rows}\n")
    return dest


def lut_name(path: Path) -> str:
    """A LUT name from the exported file's name ("Moody Film-chart.tif" -> "Moody Film")."""
    stem = re.sub(r"(?i)[ _-]*(allprophoto[ _-]*)?(color[ _-]*)?chart([ _-]*\d+)?$", "", path.stem)
    stem = re.sub(r"[_]+", " ", stem).strip(" -")
    return stem or path.stem


def convert(path: Path, name: str | None = None, folder: Path = LUT_FOLDER) -> tuple[str, Path, list[str]]:
    """An exported chart as a .cube in your LUT folder: its name, path and any warnings."""
    name = (name or lut_name(path)).strip()
    table = np.clip(to_table(read_chart(path)), 0, 1)
    safe = re.sub(r"[/:\\]+", "-", name)
    dest = write_cube(table, folder / f"{safe}.cube", name)
    return name, dest, check(table)
