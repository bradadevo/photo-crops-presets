"""Finding and loading photos the way the camera made them.

Camera RAW files are developed at full quality and then matched, color
channel by color channel, to the camera's own JPEG preview stored inside the
RAW. A plain RAW development comes out much darker and harsher than the
camera's JPEG (median brightness about 70-100 against 125-165 on a sunny
field); the match gives the camera's look with the RAW's full detail.

Color: every photo is turned into sRGB, the color space the edits work in and
that the web, phones and print labs expect. A photo saved in another space
(an iPhone's Display P3, a camera set to Adobe RGB) is converted with its
profile, so its colors stay true. Saved pictures carry the sRGB profile.

Precision: RAW and 16-bit TIFF photos also keep a 16-bit copy (Photo.fine),
so full-size edits and 16-bit exports have no banding in smooth gradients.
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
    image: Image.Image  # 8-bit sRGB, for finding players and quick previews
    exif: bytes | None
    from_raw: bool
    fine: np.ndarray | None = None  # the same picture in 16 bits (uint16), when the file has more than 8


def srgb_profile() -> bytes:
    """The sRGB color profile, embedded in saved pictures."""
    global _SRGB
    if _SRGB is None:
        mac = Path("/System/Library/ColorSync/Profiles/sRGB Profile.icc")  # the standard sRGB IEC61966-2.1
        if mac.exists():
            _SRGB = mac.read_bytes()
        else:
            from PIL import ImageCms
            _SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _SRGB


_SRGB = None


def to_srgb(img: Image.Image, icc: bytes | None) -> Image.Image:
    """The picture in sRGB, converted from its own color profile if it has
    another one (Display P3, Adobe RGB...)."""
    if not icc:
        return img
    from PIL import ImageCms
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if "srgb" in ImageCms.getProfileDescription(src).lower().replace(" ", ""):
            return img
        dst = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        return ImageCms.profileToProfile(img, src, dst, renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                         outputMode="RGB")
    except (ImageCms.PyCMSError, OSError, ValueError):
        return img


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


def match_tones(raw16: np.ndarray, reference: np.ndarray, fine: bool = False) -> np.ndarray:
    """Maps each channel of a 16-bit image so its tones follow the reference
    8-bit image of the same scene (any size): a smooth curve per channel from
    their histograms, so it needs no exact alignment. fine: a 16-bit result
    (uint16) instead of 8-bit, keeping the RAW's smooth gradients."""
    h, w = reference.shape[:2]
    scale = min(1.0, 1500 / max(h, w))
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    small_raw = cv2.resize(raw16, size, interpolation=cv2.INTER_AREA)
    small_ref = cv2.resize(reference, size, interpolation=cv2.INTER_AREA)
    q = np.linspace(0, 100, MATCH_POINTS)
    out = np.empty(raw16.shape, np.uint16 if fine else np.uint8)
    top = 65535 / 255 if fine else 1.0
    for c in range(3):
        src = np.percentile(small_raw[..., c], q)
        src = np.maximum.accumulate(src + np.arange(len(q)) * 1e-6)  # strictly increasing
        dst = np.percentile(small_ref[..., c], q)
        lut = np.interp(np.arange(65536), src, dst).astype(np.float32)
        lut = cv2.GaussianBlur(lut.reshape(1, -1), (0, 0), MATCH_SMOOTH, borderType=cv2.BORDER_REPLICATE).ravel()
        out[..., c] = np.clip(lut[raw16[..., c]] * top + 0.5, 0, 255 * top).astype(out.dtype)
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
    return develop_raw_fine(path)[0]


def develop_raw_fine(path: Path) -> tuple[Image.Image, np.ndarray]:
    """The RAW in the camera's look: 8-bit, and the same in 16 bits."""
    with rawpy.imread(str(path)) as raw:
        preview = camera_preview(raw)
        if preview is None:
            fine = raw.postprocess(use_camera_wb=True, output_bps=16)
        else:
            raw16 = raw.postprocess(use_camera_wb=True, output_bps=16, no_auto_bright=True)
            fine = match_tones(raw16, preview, fine=True)
    return Image.fromarray(to_8bit(fine)), fine


def to_8bit(fine: np.ndarray) -> np.ndarray:
    return ((fine.astype(np.uint32) * 255 + 32767) // 65535).astype(np.uint8)


def _tiff16(path: Path) -> np.ndarray | None:
    """A 16-bit RGB TIFF as uint16 (which Pillow cannot read), else None."""
    try:
        import tifffile
        a = tifffile.imread(str(path))
    except Exception:
        return None
    if a.dtype != np.uint16 or a.ndim != 3 or a.shape[2] < 3:
        return None
    return np.ascontiguousarray(a[..., :3])


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


def raw_exif(path: Path) -> bytes | None:
    """The camera data of a RAW file (when it was taken, camera, lens,
    exposure) as JPEG EXIF, so pictures made from it keep its real date."""
    try:
        import exifread
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception:  # an unreadable file just has no camera data
        return None
    if not tags:
        return None

    def text(key):
        v = tags.get(key)
        return str(v).strip() if v is not None else None

    def ratio(key):
        v = tags.get(key)
        if v is None or not v.values:
            return None
        r = v.values[0]
        try:
            from fractions import Fraction
            return Fraction(r.num, r.den) if hasattr(r, "num") else Fraction(r)
        except (ZeroDivisionError, ValueError, TypeError):
            return None

    exif = Image.Exif()
    taken = text("EXIF DateTimeOriginal") or text("Image DateTime")
    for tag, value in ((0x010F, text("Image Make")), (0x0110, text("Image Model")), (0x0132, taken)):
        if value:
            exif[tag] = value
    exif[0x0112] = 1  # the picture is saved upright
    sub = exif.get_ifd(0x8769)
    for tag, value in ((0x9003, taken), (0x9004, text("EXIF DateTimeDigitized") or taken),
                       (0x9011, text("EXIF OffsetTimeOriginal")), (0xA434, text("EXIF LensModel"))):
        if value:
            sub[tag] = value
    for tag, key in ((0x829A, "EXIF ExposureTime"), (0x829D, "EXIF FNumber"), (0x920A, "EXIF FocalLength")):
        r = ratio(key)
        if r is not None:
            from PIL.TiffImagePlugin import IFDRational
            sub[tag] = IFDRational(r.numerator, r.denominator)
    iso = tags.get("EXIF ISOSpeedRatings")
    if iso is not None and iso.values:
        sub[0x8827] = int(iso.values[0])
    return exif.tobytes()


def upright_exif(exif: bytes | None) -> bytes | None:
    """The photo's EXIF with its orientation reset to upright (the picture
    itself is already turned upright, so viewers must not turn it again)."""
    if not exif:
        return exif
    data = Image.Exif()
    try:
        data.load(exif)
    except Exception:
        return exif
    data[0x0112] = 1
    return data.tobytes()


def taken_at(exif: bytes | None):
    """When the photo was taken (a datetime), from its EXIF, else None."""
    if not exif:
        return None
    from datetime import datetime
    data = Image.Exif()
    try:
        data.load(exif)
    except Exception:
        return None
    value = data.get_ifd(0x8769).get(0x9003) or data.get(0x0132)
    try:
        return datetime.strptime(str(value).strip("\x00 "), "%Y:%m:%d %H:%M:%S") if value else None
    except ValueError:
        return None


def load(path: Path) -> Photo:
    if is_raw(path):
        img, fine = develop_raw_fine(path)
        return Photo(path, img, raw_exif(path), True, fine)
    if path.suffix.lower() in {".tif", ".tiff"} and (fine := _tiff16(path)) is not None:
        return Photo(path, Image.fromarray(to_8bit(fine)), None, False, fine)
    raw = Image.open(path)
    exif = upright_exif(raw.info.get("exif"))
    img = ImageOps.exif_transpose(raw).convert("RGB")
    return Photo(path, to_srgb(img, raw.info.get("icc_profile")), exif, False)


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
    """Saves with the photo's camera data and the sRGB profile, and dates the
    file when the photo was taken."""
    img.save(dest, quality=95, subsampling=0, icc_profile=srgb_profile(), **({"exif": exif} if exif else {}))
    date_file(dest, exif)


def date_file(dest: Path, exif: bytes | None) -> None:
    when = taken_at(exif)
    if when:
        import os
        os.utime(dest, (when.timestamp(), when.timestamp()))


def save_tiff16(arr: np.ndarray, dest: Path, exif: bytes | None) -> None:
    """A 16-bit TIFF (for print and further editing) from floats 0-1, with
    the sRGB profile, the camera, the date taken, and the file dated then too."""
    import tifffile
    data = Image.Exif()
    if exif:
        try:
            data.load(exif)
        except Exception:
            pass
    when = taken_at(exif)
    icc = srgb_profile()
    extra = [(34675, "B", len(icc), icc, True)]
    for tag, value in ((271, data.get(0x010F)), (272, data.get(0x0110)),
                       (306, when.strftime("%Y:%m:%d %H:%M:%S") if when else None)):
        if value:
            text = str(value).strip("\x00 ")
            extra.append((tag, "s", 0, text, True))
    pixels = np.round(np.clip(arr, 0, 1) * 65535).astype(np.uint16)
    tifffile.imwrite(str(dest), pixels, photometric="rgb", compression="zlib", predictor=True,
                     resolution=(300, 300), resolutionunit="INCH", extratags=extra, metadata=None)
    date_file(dest, exif)
