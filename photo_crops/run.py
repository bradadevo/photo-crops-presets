"""Running a whole folder: every photo's versions, then the screenshots."""

import csv
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from photo_crops import edit, focus, framing, images, screenshots
from photo_crops.people import GOALIE, OPPONENT, TEAM, Detector
from photo_crops.settings import Settings

SCREENSHOT_FOLDER = "Screenshots rebuilt"
REPORT = "report.csv"
# Rough seconds of work, measured on a MacBook Pro M5 with 33 MP Sony files
SECONDS_PER_PHOTO = 9.0
SECONDS_PER_SOURCE = 0.9
SECONDS_PER_MATCH_PAIR = 0.02

# progress(done, total, message)
Progress = Callable[[int, int, str], None]


@dataclass
class Job:
    photos: list[Path]
    screenshots: list[Path]
    sources: list[Path]

    @property
    def seconds(self) -> float:
        t = len(self.photos) * SECONDS_PER_PHOTO
        if self.screenshots and self.sources:
            t += len(self.sources) * SECONDS_PER_SOURCE + len(self.screenshots) * len(self.sources) * SECONDS_PER_MATCH_PAIR
        return t

    def summary(self) -> str:
        minutes = max(1, round(self.seconds / 60))
        lines = [f"Photos: {len(self.photos)}", f"Screenshots: {len(self.screenshots)}"]
        if self.screenshots:
            lines.append(f"Possible screenshot sources: {len(self.sources)}")
        lines.append(f"Time: about {minutes} min, all on this Mac (no AI service, no cost)")
        return "\n".join(lines)


def prepare(s: Settings) -> Job:
    photos, shots = images.collect(s.folder_path)
    if s.screenshots == "skip":
        shots = []
    sources = screenshots.candidate_sources(photos, s.sources_path) if shots and s.screenshots == "rebuild" else []
    return Job(photos, shots, sources)


def _name(path: Path) -> str:
    return path.stem


def run(s: Settings, progress: Progress, stop: threading.Event | None = None) -> Path:
    stop = stop or threading.Event()
    job = prepare(s)
    out = s.out_path
    out.mkdir(parents=True, exist_ok=True)
    colors = {TEAM: s.team_color, GOALIE: s.goalie_color, OPPONENT: s.opponent_color}
    detector = Detector()
    rows = []
    total = len(job.photos) + len(job.screenshots)
    for i, path in enumerate(job.photos):
        if stop.is_set():
            break
        progress(i, total, f"{path.name}: loading")
        try:
            rows.append(_photo(path, s, out, detector, colors))
            progress(i + 1, total, f"{path.name}: {rows[-1]['subject']}")
        except Exception as e:  # one bad file must not stop the rest
            rows.append({"file": path.name, "subject": "", "notes": f"FAILED: {e}"})
            progress(i + 1, total, f"{path.name}: FAILED ({e})")

    if job.screenshots and not stop.is_set():
        rows += _screenshots(job, s, out, progress, stop, len(job.photos), total)

    with open(out / REPORT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "subject", "files", "notes"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    progress(total, total, "Stopped" if stop.is_set() else f"Done: {out}")
    return out


def _photo(path: Path, s: Settings, out: Path, detector: Detector, colors: dict[str, str]) -> dict:
    photo = images.load(path)
    img = photo.image
    stem = out / _name(path)
    files = []
    if "O" in s.versions:
        files.append(images.save_original(photo, Path(f"{stem}_O")).name)
    if not ({"crop", "face"} & set(s.versions)):
        return {"file": path.name, "subject": "-", "files": " ".join(files)}
    people, balls = detector.find(img, focus.focus_point(path, img.size), colors)
    plan = framing.choose(people, balls, img.size, s.goalie_first)
    crop = framing.crop_box(plan, img.size, s.shape)
    notes = []
    if "crop" in s.versions:
        dest = Path(f"{stem}_crop.jpg")
        images.save_jpeg(edit.crop_and_edit(img, crop, framing.subject_box(plan), s.edit), dest, photo.exif)
        files.append(dest.name)
    if "face" in s.versions:
        face = framing.face_box(plan.face_person, img.size, s.faces, crop) if plan.face_person else None
        if face:
            fp = plan.face_person
            head = fp.head or (fp.center[0], fp.box[1] + 0.08 * fp.height, 0)
            r = max(fp.height * 0.06, 1)
            dest = Path(f"{stem}_face.jpg")
            images.save_jpeg(edit.crop_and_edit(img, face, (head[0] - r, head[1] - r, head[0] + r, head[1] + r), s.edit),
                             dest, photo.exif)
            files.append(dest.name)
        else:
            notes.append("no face version (face too small or no person)")
    return {"file": path.name, "subject": plan.reason, "files": " ".join(files), "notes": "; ".join(notes)}


def _screenshots(job: Job, s: Settings, out: Path, progress: Progress, stop: threading.Event,
                 done: int, total: int) -> list[dict]:
    folder = out / SCREENSHOT_FOLDER
    folder.mkdir(exist_ok=True)
    rows = []
    index = None
    if s.screenshots == "rebuild":
        index = screenshots.Index(job.sources, lambda i, n: progress(done, total, f"Indexing screenshot sources {i}/{n}"),
                                  stop)
    for k, shot_path in enumerate(job.screenshots):
        if stop.is_set():
            break
        shot = Image.open(shot_path)
        match = index.match(shot) if index else None
        if match:
            photo = images.load(match.source)
            box = match.box(photo.image.size)
            w, h = box[2] - box[0], box[3] - box[1]
            dest = folder / f"{shot_path.stem} - from {match.source.stem}.jpg"
            subject = (box[0] + w // 5, box[1] + h // 8, box[0] + 4 * w // 5, box[1] + 7 * h // 8)
            images.save_jpeg(edit.crop_and_edit(photo.image, box, subject, s.edit), dest, photo.exif)
            gain = (w * h) / (shot.width * shot.height)
            note = f"{gain:.1f}x the screenshot's pixels" + (" (screenshot was zoomed past the camera's detail)"
                                                             if gain < 1 else "")
            rows.append({"file": shot_path.name, "subject": f"rebuilt from {match.source.name}",
                         "files": f"{SCREENSHOT_FOLDER}/{dest.name}", "notes": note})
        elif s.screenshots == "copy" or s.no_match == "copy":
            suffix = "" if s.screenshots == "copy" else "_NO_SOURCE"
            dest = folder / f"{shot_path.stem}{suffix}{shot_path.suffix}"
            dest.write_bytes(shot_path.read_bytes())
            rows.append({"file": shot_path.name, "subject": "copied", "files": f"{SCREENSHOT_FOLDER}/{dest.name}",
                         "notes": "" if s.screenshots == "copy" else "no matching photo found"})
        else:
            rows.append({"file": shot_path.name, "subject": "left out", "notes": "no matching photo found"})
        progress(done + k + 1, total, f"{shot_path.name}: {rows[-1]['subject']}")
    return rows
