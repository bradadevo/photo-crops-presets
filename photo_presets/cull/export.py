"""What happens to the keepers: copied to a folder as they are (RAW and JPEG together), or cropped
and edited like match-cull (O, A, B, C and the optional AI ones, D and the best crop)."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from photo_crops import images
from photo_presets import enlarge
from photo_presets.cull import crops, enhance

SIZES = crops.SIZES  # instagram 4:5, story 9:16, youtube 16:9, original, ai (best crop)
SHAPE_OF = {"instagram": "4:5", "story": "9:16", "youtube": "16:9"}
VERSIONS = {"A": "Natural", "C": "Punchy", "B": "Softer, a little wider", "O": "No edits (just the crop)",
            "D": "AI touch-up"}
# each version's file name ends in its plain name: DSC01234_natural.jpg
WORDS = {"O": "crop-only", "A": "natural", "B": "softer", "C": "punchy", "D": "ai-touch-up"}
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


def safe_name(name: str) -> str:
    """A label as a folder name (no slashes or colons)."""
    import re
    return re.sub(r'[/:\\]+', "-", name).strip(" .") or "Label"


def files_same(a: Path, b: Path) -> bool:
    from photo_presets.cull.files import same_file
    return same_file(a, b)


def copy_files(files: list[Path], folder: Path) -> list[Path]:
    """Straight copies (dates kept); one already there with the same size is skipped."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        dest = folder / f.name
        if dest.exists() and files_same(f, dest):  # (the same photo, copied before: a different one gets a new name)
            out.append(dest)
            continue
        dest = unique(dest)
        shutil.copy2(f, dest)
        out.append(dest)
    return out


FITS = {"widen": "Widen those crops just enough to stay sharp",
        "native": "Keep the crop's own pixels (a smaller file, never enlarged)",
        "enlarge": "Enlarge them with the AI detail enlarger (sharp, about 7 s each)"}


def target(size_key: str, full: tuple[int, int]) -> tuple[int, int] | None:
    """The pixels an export of this size needs (None: the crop's own size, never enlarged)."""
    size = SIZES[size_key]
    if size.pixels:
        return size.pixels
    if size.match_source:
        return tuple(full)
    return None


def enlarged(box: crops.Box, size_key: str, full: tuple[int, int]) -> float:
    """How many times this crop would be enlarged for this size (1.0 or less: no loss)."""
    t = target(size_key, full)
    if not t:
        return 1.0
    return max(t[0] / max(1, box[2] - box[0]), t[1] / max(1, box[3] - box[1]))


def widen(box: crops.Box, size_key: str, full: tuple[int, int]) -> crops.Box:
    """The crop grown around its middle (same shape) until it has the pixels the size needs, kept
    inside the photo; as large as the photo allows when it can't get there."""
    f = enlarged(box, size_key, full)
    if f <= 1.0:
        return box
    W, H = full
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    w, h = (box[2] - box[0]) * f, (box[3] - box[1]) * f
    if w > W or h > H:
        s = min(W / w, H / h)
        w, h = w * s, h * s
    x0 = min(max(cx - w / 2, 0), W - w)
    y0 = min(max(cy - h / 2, 0), H - h)
    return round(x0), round(y0), round(x0 + w), round(y0 + h)


def your_crop(override, size_key: str):
    """Your own crop for this size (the crop is kept per size; an older single crop counts for all)."""
    if isinstance(override, dict):
        return override.get(size_key)
    return override


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
    else:  # no players found: the biggest crop of this shape, centered (nothing to zoom in on)
        tight = crops.crop_box(W, H, (0.0, 0.0, 1.0, 1.0), size.aspect, tight=False)
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
        out = enlarge.fit_pil(out, size.pixels)
    elif size.match_source and out.size != src.size:
        out = enlarge.fit_pil(out, src.size)
    return enhance.output_sharpen(out) if sharpen else out


def team_on_border(img: Image.Image, group, aspect: float, t, room: bool = True) -> Image.Image:
    """The whole team (with a little room) across the frame, on a blurred, darkened copy of the photo
    filling the rest of the tall shape, the way a wide photo is posted to a tall feed."""
    from PIL import ImageFilter, ImageEnhance
    W, H = img.size
    gx0, gy0, gx1, gy1 = group[0] * W, group[1] * H, group[2] * W, group[3] * H
    rx, ry = (0.05 * (gx1 - gx0), 0.12 * (gy1 - gy0)) if room else (0.0, 0.0)
    box = (max(0, round(gx0 - rx)), max(0, round(gy0 - ry)), min(W, round(gx1 + rx)), min(H, round(gy1 + ry)))
    team = img.crop(box)
    cw, ch = (t if t else (team.width, round(team.width / aspect)))
    small = img.resize((max(1, W // 8), max(1, H // 8)), Image.Resampling.BILINEAR)
    k = max(cw / small.width, ch / small.height)
    bg = small.resize((round(small.width * k), round(small.height * k)), Image.Resampling.BILINEAR)
    bg = bg.crop(((bg.width - cw) // 2, (bg.height - ch) // 2, (bg.width - cw) // 2 + cw, (bg.height - ch) // 2 + ch))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(max(8, cw // 40)))).enhance(0.55)
    s = min(cw / team.width, ch / team.height)
    if t is None or s > 1:  # never enlarged: it sits a little smaller on the border instead
        s = min(s, 1.0)
    fg = team.resize((max(1, round(team.width * s)), max(1, round(team.height * s))), Image.Resampling.LANCZOS)
    bg.paste(fg, ((cw - fg.width) // 2, (ch - fg.height) // 2))
    return bg


def edit_one(path: Path, m: dict, size_key: str, versions: str, folder: Path, override: tuple | None = None,
             ai_crop: tuple | None = None, adjust_fn=None, fit: str = "widen", report: list | None = None,
             stem: str | None = None) -> list[Path]:
    """One keeper's versions, saved in folder as <name>_<version>.jpg with its camera data (stem: the
    name to use, when two keepers of one export share a file name).
    adjust_fn: Gemini's adjustments for D (given the natural edit), only when D is asked for."""
    photo = images.load(path)
    img, exif = photo.image, images.upright_exif(photo.exif) if photo.from_raw else photo.exif
    size = SIZES[size_key]
    tight, wide = boxes(m, size_key, img.size, your_crop(override, size_key), ai_crop)
    if fit == "widen":  # never enlarged: a crop too small for the size grows just enough
        tight, wide = widen(tight, size_key, img.size), widen(wide, size_key, img.size)
    subject = m.get("group") or m.get("subject")
    shape = SHAPE_OF.get(size_key)
    # a team photo too wide for this shape: the whole team on a soft border, never kids cut in half
    team = bool(shape and not override and not ai_crop and (m.get("team_fit") or {}).get(shape) and m.get("group"))
    # or a photo too narrow for this shape to hold the main player with room: them whole, on the border
    border = (m.get("border") or {}).get(shape) if shape and not override and not ai_crop else None
    if team or border:
        subject = None
    folder.mkdir(parents=True, exist_ok=True)
    out = []

    def save(im, v):
        dest = folder / f"{stem or path.stem}_{WORDS[v]}.jpg"  # (made again: replaces the last export's own file)
        images.save_jpeg(im, dest, exif)
        out.append(dest)

    made = {}

    def at_size(box):
        """The crop at its final size (made once per box: the AI enlarger takes seconds)."""
        if tuple(box) not in made:
            made[tuple(box)] = _at_size(box)
        return made[tuple(box)].copy()

    def _at_size(box):
        """The crop at its final size first, so the edit's detail and clarity suit what is seen
        (edited at 33 MP and then shrunk, the texture packs together and looks crunchy)."""
        if team:
            return team_on_border(img, m["group"], SIZES[size_key].aspect, target(size_key, img.size))
        if border:
            return team_on_border(img, border, SIZES[size_key].aspect, target(size_key, img.size), room=False)
        crop = img.crop(box)
        t = target(size_key, img.size)
        if not t or crop.size == tuple(t):
            return crop
        if fit == "native" and (crop.width < t[0] or crop.height < t[1]):
            return crop  # its own pixels: never enlarged (it may be made smaller, never bigger)
        how = []
        out = enlarge.fit_pil(crop, tuple(t), how)  # (a real enlargement: the AI detail enlarger)
        if report is not None:
            report.extend({**h, "photo": path.name, "size": SIZES[size_key].label.split(" (")[0]} for h in how)
        return out

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
