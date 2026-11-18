"""What happens to the keepers: copied to a folder as they are (RAW and JPEG together), or cropped
and edited like match-cull (O, A, B, C and the optional AI ones, D and the best crop)."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from photo_crops import images
from photo_presets.cull import crops, enhance

SIZES = crops.SIZES  # instagram 4:5, story 9:16, youtube 16:9, original, ai (best crop)
SHAPE_OF = {"instagram": "4:5", "story": "9:16", "youtube": "16:9"}
VERSIONS = {"O": "Crop only (no edits)", "A": "Crop + natural edit", "B": "Wider crop, softer edit",
            "C": "Crop + punchy edit", "D": "Crop + AI's suggested adjustments"}
FOLDER_NAMES = {"instagram": "Instagram 4x5", "story": "Story 9x16", "youtube": "YouTube 16x9",
                "original": "Original size", "ai": "Best crop"}


def unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    i = 2
    while True:
        cand = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not cand.exists():
            return cand
        i += 1


def copy_files(files: list[Path], folder: Path) -> list[Path]:
    """Straight copies (dates kept); one already there with the same size is skipped."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        dest = folder / f.name
        if dest.exists() and dest.stat().st_size == f.stat().st_size:
            out.append(dest)
            continue
        dest = unique(dest)
        shutil.copy2(f, dest)
        out.append(dest)
    return out


def boxes(m: dict, size_key: str, img_size: tuple[int, int], override: tuple | None = None,
          ai_crop: tuple | None = None) -> tuple[crops.Box, crops.Box]:
    """The tight crop (A, C, D, O) and the wider one (B), in pixels. The crop on the action from pass 1
    (or yours, when you moved it); the AI's own when the size is the best crop."""
    W, H = img_size
    px = lambda b: (round(b[0] * W), round(b[1] * H), round(b[2] * W), round(b[3] * H))
    size = SIZES[size_key]
    subject = m.get("group") or m.get("subject") or (0.25, 0.25, 0.75, 0.75)
    if size.ai_framing and ai_crop:
        box, shape = ai_crop
        return crops.ai_crop_box(W, H, box, shape), (0, 0, W, H)
    if override:
        tight = px(override)
    elif size_key in SHAPE_OF and m.get("crops"):
        tight = px(m["crops"][SHAPE_OF[size_key]])
    elif m.get("crops"):  # original size and best crop without the AI: the no-zoom pro crop
        tight = px(m["crops"]["wide"]) if size_key == "original" else px(m["crops"]["best"])
    else:
        tight = crops.crop_box(W, H, subject, size.aspect, tight=True)
    wide = crops.crop_box(W, H, subject, size.aspect, tight=False) if size.aspect else (0, 0, W, H)
    return tight, wide


def _subject_in(box, subject, img_size):
    if not subject:
        return None
    W, H = img_size
    return (round(subject[0] * W) - box[0], round(subject[1] * H) - box[1],
            round(subject[2] * W) - box[0], round(subject[3] * H) - box[1])


def _final(out: Image.Image, src: Image.Image, size: crops.OutputSize, sharpen: bool = True) -> Image.Image:
    if size.pixels:
        out = out.resize(size.pixels, Image.Resampling.LANCZOS)
    elif size.match_source and out.size != src.size:
        out = out.resize(src.size, Image.Resampling.LANCZOS)
    return enhance.output_sharpen(out) if sharpen else out


def edit_one(path: Path, m: dict, size_key: str, versions: str, folder: Path, override: tuple | None = None,
             ai_crop: tuple | None = None, adjust_fn=None) -> list[Path]:
    """One keeper's versions, saved in folder as <name>_<version>.jpg with its camera data.
    adjust_fn: Gemini's adjustments for D (given the natural edit), only when D is asked for."""
    photo = images.load(path)
    img, exif = photo.image, images.upright_exif(photo.exif) if photo.from_raw else photo.exif
    size = SIZES[size_key]
    tight, wide = boxes(m, size_key, img.size, override, ai_crop)
    subject = m.get("group") or m.get("subject")
    folder.mkdir(parents=True, exist_ok=True)
    out = []

    def save(im, v):
        dest = folder / f"{path.stem}_{v}.jpg"  # (made again: replaces the last export's own file)
        images.save_jpeg(im, dest, exif)
        out.append(dest)

    def at_size(box):
        """The crop at its final size first, so the edit's detail and clarity suit what is seen
        (edited at 33 MP and then shrunk, the texture packs together and looks crunchy)."""
        crop = img.crop(box)
        if size.pixels:
            return crop.resize(size.pixels, Image.Resampling.LANCZOS)
        if size.match_source and crop.size != img.size:
            return crop.resize(img.size, Image.Resampling.LANCZOS)
        return crop

    def sub(box, shown):
        s = _subject_in(box, subject, img.size)
        if not s:
            return None
        kx, ky = shown.width / (box[2] - box[0]), shown.height / (box[3] - box[1])
        return (round(s[0] * kx), round(s[1] * ky), round(s[2] * kx), round(s[3] * ky))
    natural = None
    if "O" in versions:
        save(at_size(tight), "O")
    if "A" in versions or "D" in versions or "C" in versions:
        shown = at_size(tight)
        natural = enhance.enhance(shown, sub(tight, shown))
    if "A" in versions:
        save(enhance.output_sharpen(natural), "A")
    if "B" in versions:
        shown = at_size(wide)
        b = enhance.enhance(shown, sub(wide, shown))
        save(enhance.output_sharpen(enhance.soften_contrast(b)), "B")
    if "C" in versions:
        save(enhance.output_sharpen(enhance.punch(natural)), "C")
    if "D" in versions and adjust_fn is not None:
        from photo_presets.cull import adjust
        shown = at_size(tight)
        save(enhance.output_sharpen(adjust.apply(natural, adjust_fn(natural), sub(tight, shown))), "D")
    return out
