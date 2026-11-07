"""Finding and loading photos the way the camera made them.

Camera RAW files are developed at full quality and then matched, color
channel by color channel, to the camera's own JPEG preview stored inside the
RAW. A plain RAW development comes out much darker and harsher than the
camera's JPEG (median brightness about 70-100 against 125-165 on a sunny
field); the match gives the camera's look with the RAW's full detail.
"""

import io
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import rawpy
from PIL import Image, ImageOps

import pillow_heif

pillow_heif.register_heif_opener()

JPEG_EXTS = {".jpg", ".jpeg"}
OTHER_EXTS = {".png", ".heic", ".heif", ".tif", ".tiff"}
RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".orf", ".rw2"}
SCREENSHOT_PREFIXES = ("screenshot", "screen shot")
# The tone match uses this many points along each channel's tonal range
MATCH_POINTS = 1025
# The matched curve is smoothed over this many 16-bit levels, so it has no steps
MATCH_SMOOTH = 200


@dataclass
class Photo:
    path: Path
    image: Image.Image
    exif: bytes | None
    from_raw: bool


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXTS


def is_image(path: Path) -> bool:
    return path.suffix.lower() in JPEG_EXTS | OTHER_EXTS | RAW_EXTS and not path.name.startswith(".")


def is_screenshot(path: Path) -> bool:
    return path.name.lower().startswith(SCREENSHOT_PREFIXES)


def collect(folder: Path) -> tuple[list[Path], list[Path]]:
    """The photos and screenshots directly inside folder. When a shot was
    saved as both JPEG and RAW, the camera's JPEG is used."""
    photos: dict[str, Path] = {}
    shots = []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or not is_image(p):
            continue
        if is_screenshot(p):
            shots.append(p)
            continue
        current = photos.get(p.stem)
        if current is None or (is_raw(current) and not is_raw(p)):
            photos[p.stem] = p
    return sorted(photos.values()), shots


def match_tones(raw16: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Maps each channel of a 16-bit image so its tones follow the reference
    8-bit image of the same scene (any size): a smooth curve per channel from
    their histograms, so it needs no exact alignment."""
    h, w = reference.shape[:2]
    scale = min(1.0, 1500 / max(h, w))
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    small_raw = cv2.resize(raw16, size, interpolation=cv2.INTER_AREA)
    small_ref = cv2.resize(reference, size, interpolation=cv2.INTER_AREA)
    q = np.linspace(0, 100, MATCH_POINTS)
    out = np.empty(raw16.shape, np.uint8)
    for c in range(3):
        src = np.percentile(small_raw[..., c], q)
        src = np.maximum.accumulate(src + np.arange(len(q)) * 1e-6)  # strictly increasing
        dst = np.percentile(small_ref[..., c], q)
        lut = np.interp(np.arange(65536), src, dst).astype(np.float32)
        lut = cv2.GaussianBlur(lut.reshape(1, -1), (0, 0), MATCH_SMOOTH, borderType=cv2.BORDER_REPLICATE).ravel()
        out[..., c] = np.clip(lut[raw16[..., c]] + 0.5, 0, 255).astype(np.uint8)
    return out


def camera_preview(raw: rawpy.RawPy) -> np.ndarray | None:
    try:
        thumb = raw.extract_thumb()
    except (rawpy.LibRawError, ValueError):
        return None
    if thumb.format == rawpy.ThumbFormat.JPEG:
        return np.asarray(Image.open(io.BytesIO(thumb.data)).convert("RGB"))
    if thumb.format == rawpy.ThumbFormat.BITMAP:
        return np.asarray(thumb.data)
    return None


def develop_raw(path: Path) -> Image.Image:
    with rawpy.imread(str(path)) as raw:
        preview = camera_preview(raw)
        if preview is None:
            return Image.fromarray(raw.postprocess(use_camera_wb=True, output_bps=8))
        raw16 = raw.postprocess(use_camera_wb=True, output_bps=16, no_auto_bright=True)
    return Image.fromarray(match_tones(raw16, preview))


def preview_image(path: Path, long_edge: int) -> Image.Image:
    """A fast, smaller copy for matching: JPEG draft decoding, or the RAW's
    built-in preview."""
    if is_raw(path):
        with rawpy.imread(str(path)) as raw:
            preview = camera_preview(raw)
        img = Image.fromarray(preview) if preview is not None else develop_raw(path)
    else:
        img = Image.open(path)
        img.draft("RGB", (long_edge, long_edge))
        img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((long_edge, long_edge))
    return img


def load(path: Path) -> Photo:
    if is_raw(path):
        return Photo(path, develop_raw(path), None, True)
    raw = Image.open(path)
    exif = raw.info.get("exif")
    return Photo(path, ImageOps.exif_transpose(raw).convert("RGB"), exif, False)


def save_original(photo: Photo, dest_stem: Path) -> Path:
    """The untouched original: a straight file copy, or for RAW the
    developed full-size JPEG (camera look, no edits)."""
    if photo.from_raw:
        dest = dest_stem.with_suffix(".jpg")
        photo.image.save(dest, quality=95)
    else:
        dest = dest_stem.with_suffix(photo.path.suffix)
        shutil.copy2(photo.path, dest)
    return dest


def save_jpeg(img: Image.Image, dest: Path, exif: bytes | None) -> None:
    img.save(dest, quality=95, **({"exif": exif} if exif else {}))
