"""Photos: the camera's settings from the file's EXIF data (including Sony's
own focus details), then measurements from the pixels (focus, grain and
exposure)."""

import math
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import logging

import cv2
import exifread
import numpy as np

logging.getLogger("exifread").setLevel(logging.ERROR)  # Sony maker notes trigger harmless warnings

from photo_presets.clipcheck.video import grain_of

RAW_EXTENSIONS = (".arw", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2")
HEIF_EXTENSIONS = (".heic", ".heif")
# Focus is judged on a grid of tiles; the sharpest tiles are where focus landed
TILES_X, TILES_Y = 8, 6
# Sony AF area codes (MakerNote 0x201C); unknown codes are shown as numbers
SONY_AF_AREA = {0: "Wide", 1: "Center", 3: "Flexible spot", 4: "Flexible spot", 11: "Zone",
                12: "Expanded flexible spot", 13: "Custom AF area"}


@dataclass
class StillInfo:
    path: str
    width: int = 0
    height: int = 0
    camera: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return Path(self.path).name


def _ratio(tag) -> float | None:
    try:
        value = tag.values[0]
        return float(Fraction(value.num, value.den)) if hasattr(value, "num") else float(value)
    except (AttributeError, IndexError, ValueError, ZeroDivisionError, TypeError):
        return None


def read_exif(path: str) -> dict:
    with open(path, "rb") as f:
        tags = exifread.process_file(f, details=True)
    get = lambda key: str(tags[key]).strip() if key in tags else None
    cam = {
        "make": get("Image Make"), "camera": get("Image Model"), "lens": get("EXIF LensModel"),
        "recorded": get("EXIF DateTimeOriginal"), "exposure_mode": get("EXIF ExposureProgram"),
        "metering": get("EXIF MeteringMode"), "white_balance": get("EXIF WhiteBalance"),
        "flash": get("EXIF Flash"), "focus_mode": get("MakerNote FocusMode"),
        "stabilization": get("MakerNote ImageStabilization"), "drive_mode": get("MakerNote ReleaseMode"),
        "picture_style": get("MakerNote CreativeStyle"), "noise_reduction": get("MakerNote HighISONoiseReduction"),
    }
    if "EXIF ExposureTime" in tags:
        cam["shutter"] = _ratio(tags["EXIF ExposureTime"])
    if "EXIF FNumber" in tags:
        cam["aperture"] = round(_ratio(tags["EXIF FNumber"]) or 0, 1) or None
    for key in ("EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity", "EXIF RecommendedExposureIndex"):
        if key in tags:
            cam["iso"] = int(_ratio(tags[key]) or 0) or None
            break
    if "EXIF FocalLength" in tags:
        cam["focal_length"] = round(_ratio(tags["EXIF FocalLength"]) or 0) or None
    if "EXIF FocalLengthIn35mmFilm" in tags:
        cam["focal_length_35mm"] = int(_ratio(tags["EXIF FocalLengthIn35mmFilm"]) or 0) or None
    if "EXIF ExposureBiasValue" in tags:
        cam["exposure_compensation"] = _ratio(tags["EXIF ExposureBiasValue"])
    if (cam.get("make") or "").upper() == "SONY" and "MakerNote Tag 0x201C" in tags:
        code = int(_ratio(tags["MakerNote Tag 0x201C"]) or 0)
        cam["focus_area"] = SONY_AF_AREA.get(code, f"code {code}")
    return {k: v for k, v in cam.items() if v not in (None, "")}


def load_gray(path: str) -> np.ndarray:
    ext = Path(path).suffix.lower()
    if ext in RAW_EXTENSIONS:
        import rawpy
        with rawpy.imread(path) as raw:
            # developed about as bright as the camera's own JPEG (1% allowed to clip)
            rgb = raw.postprocess(use_camera_wb=True, auto_bright_thr=0.01, output_bps=8)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if ext in HEIF_EXTENSIONS:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        return np.array(Image.open(path).convert("L"))
    gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("could not read the image")
    return gray


@dataclass
class StillStats:
    focus_sharpness: float  # sharpness where the photo is sharpest (the focused area)
    overall_sharpness: float
    focus_spot: tuple[float, float]  # where that is, as fractions of width and height
    grain: float
    brightness: float  # 0..255
    highlights_clipped: float  # share of pixels at pure white
    shadows_crushed: float  # share of pixels at pure black


def measure(path: str) -> tuple[StillInfo, StillStats]:
    gray = load_gray(path)
    h, w = gray.shape
    info = StillInfo(path=str(path), width=w, height=h, camera=read_exif(path))
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    tiles = []
    for ty in range(TILES_Y):
        for tx in range(TILES_X):
            y0, y1 = ty * h // TILES_Y, (ty + 1) * h // TILES_Y
            x0, x1 = tx * w // TILES_X, (tx + 1) * w // TILES_X
            tiles.append((lap[y0:y1, x0:x1].var(), (tx + 0.5) / TILES_X, (ty + 0.5) / TILES_Y))
    best = max(tiles)
    top = sorted(t[0] for t in tiles)[-3:]
    stats = StillStats(
        focus_sharpness=float(np.mean(top)), overall_sharpness=float(lap.var()), focus_spot=(best[1], best[2]),
        grain=grain_of(cv2.resize(gray, (min(w, 3000), round(h * min(w, 3000) / w)))
                       if w > 3000 else gray),
        brightness=float(gray.mean()), highlights_clipped=float((gray >= 254).mean()),
        shadows_crushed=float((gray <= 2).mean()))
    return info, stats


# Shutter speeds as cameras label them; recorded values within 3% are shown as
# these (Sony video records 1/125 as 1/128, for example)
NOMINAL_SHUTTERS = [8000, 6400, 5000, 4000, 3200, 2500, 2000, 1600, 1250, 1000, 800, 640, 500, 400, 320, 250, 200,
                    160, 125, 120, 100, 80, 60, 50, 48, 40, 30, 25, 24, 20, 15, 13, 10, 8, 6, 5, 4, 3, 2]


def shutter_text(seconds: float | None) -> str:
    if not seconds:
        return "-"
    if seconds >= 1:
        return f"{seconds:g} s"
    denominator = 1 / seconds
    nearest = min(NOMINAL_SHUTTERS, key=lambda d: abs(d - denominator))
    return f"1/{nearest if abs(nearest - denominator) / nearest <= 0.03 else round(denominator)}"


def safe_shutter(focal_35mm: float | None, stabilized: bool) -> float | None:
    """Slowest handheld shutter that usually avoids camera shake (1/focal
    length, two stops slower with stabilization)."""
    if not focal_35mm:
        return None
    return (1 / focal_35mm) * (4 if stabilized else 1)


def stops(a: float, b: float) -> float:
    return math.log2(a / b) if a and b else 0.0
