"""Rebuilding screenshots from the original camera photos.

A screenshot of a zoomed-in photo keeps only the screen's pixels, blurred and
compressed. Each screenshot is matched to its source photo (SIFT features
plus a RANSAC homography), and the same framing is cut from the original at
full camera quality. Sources are the photos in the folder plus, optionally,
another folder such as the camera's SD card, limited there to photos taken
on the same days as the folder's photos.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photo_crops import images

INDEX_EDGE = 1752
FEATURES = 4000
RATIO = 0.75
# A match needs at least this many geometrically consistent points
MIN_INLIERS = 40


@dataclass
class Match:
    source: Path
    corners: np.ndarray  # the screenshot's corners, as shares of the source's width
    inliers: int

    def box(self, size: tuple[int, int]) -> tuple[int, int, int, int]:
        c = self.corners * size[0]
        return (max(0, round(c[:, 0].min())), max(0, round(c[:, 1].min())),
                min(size[0], round(c[:, 0].max())), min(size[1], round(c[:, 1].max())))


def _day(path: Path) -> date:
    return date.fromtimestamp(path.stat().st_mtime)


def candidate_sources(photos: list[Path], extra: Path | None) -> list[Path]:
    """The folder's photos plus extra-folder photos from the same days (JPEG preferred over RAW)."""
    out = list(photos)
    if extra and extra.is_dir():
        days = {_day(p) for p in photos}
        known = {p.stem for p in photos}
        extra_photos, _ = images.collect(extra)
        out += [p for p in extra_photos if p.stem not in known and (not days or _day(p) in days)]
    return out


class Index:
    def __init__(self, sources: list[Path], progress=None, stop=None):
        self.sift = cv2.SIFT_create(FEATURES)
        self.entries = []
        for i, path in enumerate(sources):
            if stop is not None and stop.is_set():
                break
            try:
                gray = cv2.cvtColor(np.asarray(images.preview_image(path, INDEX_EDGE)), cv2.COLOR_RGB2GRAY)
            except Exception:
                continue
            kp, desc = self.sift.detectAndCompute(gray, None)
            if desc is not None and len(desc) >= 10:
                self.entries.append((path, np.float32([k.pt for k in kp]), desc, gray.shape[1]))
            if progress:
                progress(i + 1, len(sources))
        self.matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=50))

    def match(self, shot: Image.Image) -> Match | None:
        gray = cv2.cvtColor(np.asarray(shot.convert("RGB")), cv2.COLOR_RGB2GRAY)
        kp, desc = self.sift.detectAndCompute(gray, None)
        if desc is None or len(desc) < 10:
            return None
        points = np.float32([k.pt for k in kp])
        best = None
        for path, src_pts, src_desc, width in self.entries:
            pairs = self.matcher.knnMatch(desc, src_desc, k=2)
            good = [a for a, b in (p for p in pairs if len(p) == 2) if a.distance < RATIO * b.distance]
            if len(good) < MIN_INLIERS or (best and len(good) <= best.inliers):
                continue
            H, mask = cv2.findHomography(points[[g.queryIdx for g in good]], src_pts[[g.trainIdx for g in good]],
                                         cv2.RANSAC, 4.0)
            inliers = int(mask.sum()) if mask is not None else 0
            if H is None or inliers < MIN_INLIERS or (best and inliers <= best.inliers):
                continue
            h, w = gray.shape
            corners = cv2.perspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]])[None], H)[0]
            best = Match(path, corners / width, inliers)
        return best
