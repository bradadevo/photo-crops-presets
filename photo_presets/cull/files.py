"""Finding the photos of a shoot (RAW and JPEG of one shot kept together), camera cards, and the
Trash: deleting moves files to the Mac's Trash (recoverable), and undo moves them back."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from photo_crops import images

VIDEO = {".mp4", ".mov", ".m4v", ".mts", ".avi"}


def shots_in(folders: list[Path]) -> list[dict]:
    """Every shot in these folders (not their subfolders' "Picks"/"Culled" outputs): the file shown
    (the camera's JPEG when there is one) and every file of that shot (JPEG + RAW)."""
    out = []
    for folder in folders:
        if not folder.is_dir():
            continue
        groups: dict[str, list[Path]] = {}
        for p in sorted(folder.iterdir()):
            if p.is_file() and images.is_image(p) and not images.is_screenshot(p):
                groups.setdefault(p.stem, []).append(p)
        for stem, files in groups.items():
            shown = next((f for f in files if not images.is_raw(f)), files[0])
            out.append({"path": str(shown), "files": [str(f) for f in files], "name": shown.name,
                        "raw": any(images.is_raw(f) for f in files)})
    return out


# folders this app (or Photo Crops) makes copies in, and the name endings its copies get
COPY_FOLDERS = ("Picks", "Culled - ", "Best Crops", "Best crop", "Instagram 4x5", "Story 9x16", "YouTube 16x9",
                "Original size", "VS Digital Pro")
COPY_ENDINGS = ("_O", "_crop", "_face", "_crop-only", "_natural", "_softer", "_punchy", "_ai-touch-up", "_look",
                "-Edit", "_edit", "-edit", " copy", "-copy")
EDITORS = ("lightroom", "photoshop", "capture one", "snapseed", "gimp", "luminar", "darktable", "affinity",
           "pixelmator", "vsco", "photo crops", "vs digital pro")


def origin(files: list[str], copy_folders: tuple[str, ...] = ()) -> tuple[bool, str]:
    """Whether a shot's files are the camera's own (the originals), and if not, why it looks like a copy:
    it sits in a folder copies are made in, its name ends like a copy, or an editing app saved it."""
    first = Path(files[0])
    for d in [first.parent, *first.parent.parents]:
        if str(d) in copy_folders or any(d.name == n or (n.endswith(" ") and d.name.startswith(n)) for n in COPY_FOLDERS):
            return False, f'in "{d.name}", a folder of copies'
    stem = first.stem
    stem = stem[:stem.rfind(" (")] if stem.endswith(")") and " (" in stem else stem
    end = next((e for e in COPY_ENDINGS if stem.endswith(e)), None)
    if end:
        return False, f'the name ends in "{end}", like a copy'
    if any(images.is_raw(Path(f)) for f in files):
        return True, "camera file (with its RAW)"
    try:
        from PIL import Image
        with Image.open(first) as im:
            soft = str(im.getexif().get(0x0131) or "")
    except Exception:
        soft = ""
    if any(e in soft.lower() for e in EDITORS):
        return False, f"saved by {soft.strip()}"
    return True, "camera file"


def shown(path: str) -> str:
    """A path the way you'd say it: your home folder as ~."""
    home = str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def to_trash(paths: list[str]) -> list[tuple[str, str]]:
    """Moves files to the Trash; returns (where it was, where it is in the Trash) for undo."""
    from Foundation import NSURL, NSFileManager
    fm = NSFileManager.defaultManager()
    moved = []
    for p in paths:
        if not os.path.exists(p):
            continue
        ok, where, err = fm.trashItemAtURL_resultingItemURL_error_(NSURL.fileURLWithPath_(p), None, None)
        if ok and where is not None:
            moved.append((p, str(where.path())))
    return moved


def from_trash(moved: list[tuple[str, str]]) -> int:
    """Puts files back from the Trash where they were (undo)."""
    n = 0
    for was, now in moved:
        if os.path.lexists(now) and not os.path.lexists(was):
            Path(was).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(now, was)
            n += 1
    return n


def cards() -> list[dict]:
    """Camera cards plugged in (a volume with a DCIM folder), with how many photos each holds."""
    out = []
    vols = Path("/Volumes")
    if not vols.is_dir():
        return out
    for v in sorted(vols.iterdir()):
        dcim = v / "DCIM"
        if not dcim.is_dir():
            continue
        n = sum(1 for _ in _card_photos(dcim))
        out.append({"name": v.name, "path": str(v), "photos": n})
    return out


def _card_photos(dcim: Path):
    for root, dirs, files in os.walk(dcim):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if images.is_image(p) and not f.startswith("."):
                yield p


def same_file(a: Path, b: Path) -> bool:
    """The same photo already copied: the same size and the same bytes at its start and end. Two different
    photos can share a name (two cameras, or a camera's numbers starting again) and even a size
    (uncompressed RAW are all one size), so the name, or name and size, never is."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        n = 1 << 16  # the same size: the same bytes at the start (the camera data, the time to 1/100 s) and the end
        with open(a, "rb") as fa, open(b, "rb") as fb:
            if fa.read(n) != fb.read(n):
                return False
            size = a.stat().st_size
            if size > 2 * n:
                fa.seek(size - n); fb.seek(size - n)
                return fa.read(n) == fb.read(n)
            return fa.read() == fb.read()
    except OSError:
        return False


def import_card(volume: Path, dest: Path, progress=None, on_file=None) -> tuple[int, int]:
    """Copies the card's photos (JPEG and RAW; not videos) into dest, oldest first, skipping any
    already there (the same photo: same name and the same bytes), so importing the same card again only adds
    the new ones. A different photo with a name already used (a second camera, or a camera's numbers
    starting again) is never written over: its JPEG and RAW get a new name together (DSC00001-2.JPG).
    Nothing on the card is changed. progress(done, total); on_file(path) as each file is in.
    Returns (copied, skipped)."""
    files = sorted(_card_photos(volume / "DCIM"), key=lambda p: (p.stat().st_mtime, p.name))
    dest.mkdir(parents=True, exist_ok=True)
    shots: dict[tuple[str, str], list[Path]] = {}
    for f in files:
        shots.setdefault((str(f.parent), f.stem), []).append(f)
    stem_for: dict[tuple[str, str], str] = {}
    taken: set[str] = set()  # (stems given to another shot of this card)

    def fits(stem: str, group: list[Path]) -> bool:
        return stem not in taken and all(not (dest / (stem + g.suffix)).exists() or same_file(g, dest / (stem + g.suffix)) for g in group)

    for key, group in shots.items():
        stem, n = key[1], 2
        while not fits(stem, group):
            stem, n = f"{key[1]}-{n}", n + 1
        stem_for[key] = stem
        taken.add(stem)
    copied = skipped = 0
    for i, f in enumerate(files, 1):
        target = dest / (stem_for[(str(f.parent), f.stem)] + f.suffix)
        if target.exists() and same_file(f, target):
            skipped += 1
        elif target.exists():  # (never: fits() chose a free name; kept as a last guard)
            raise RuntimeError(f"{target.name} is already there and is a different photo")
        else:
            tmp = target.with_name("." + target.name + ".part")
            shutil.copy2(f, tmp)
            tmp.replace(target)
            copied += 1
            if on_file:
                on_file(target)
        if progress:
            progress(i, len(files))
    return copied, skipped


def import_folder_name(volume: Path) -> str:
    """'2026-11-18 Import' from the newest photo's day on the card."""
    newest = max((p.stat().st_mtime for p in _card_photos(volume / "DCIM")), default=time.time())
    return time.strftime("%Y-%m-%d", time.localtime(newest)) + " Import"
