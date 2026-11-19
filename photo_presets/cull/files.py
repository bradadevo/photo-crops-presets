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


def import_card(volume: Path, dest: Path, progress=None, on_file=None) -> tuple[int, int]:
    """Copies the card's photos (JPEG and RAW; not videos) into dest, oldest first, skipping any
    already there (same name and size), so importing the same card again only adds the new ones.
    progress(done, total); on_file(path) as each shot's files are in. Returns (copied, skipped)."""
    files = sorted(_card_photos(volume / "DCIM"), key=lambda p: (p.stat().st_mtime, p.name))
    dest.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for i, f in enumerate(files, 1):
        target = dest / f.name
        if target.exists() and target.stat().st_size == f.stat().st_size:
            skipped += 1
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
