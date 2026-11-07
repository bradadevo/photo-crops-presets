"""Finding the players, the ball, their jerseys, heads and sharpness.

Free models run on this Mac: YOLO instance segmentation finds every person
and ball; YOLO pose finds each head (eyes, nose, ears). Jersey colors are
the configured team, goalie and opponent colors, matched in Lab space with
lightness counting half, so a sunlit teal shirt is not mistaken for white.
"""

import os

os.environ.setdefault("YOLO_AUTOINSTALL", "false")  # never pip-install extras mid-run

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

CACHE_DIR = Path.home() / ".cache" / "photo-crops"
SEG_WEIGHTS = "yolo11x-seg.pt"
POSE_WEIGHTS = "yolo11x-pose.pt"
DETECT_EDGE = 2048
CONFIDENCE = 0.3
PERSON, BALL = 0, 32
# Torso band used for the jersey color, as fractions of the person's height
TORSO = (0.15, 0.5)
# Jersey colors are compared by hue direction, because sun and shade change
# lightness and color strength far more than hue (the teal goalie shirt
# measured from pale #afe2e5 in sun to #356679 in shade). A torso pixel
# matches a colorful jersey when its own color strength is at least
# PIXEL_CHROMA, its hue within HUE_TOLERANCE degrees and its lightness within
# LIGHTNESS_TOLERANCE; it matches a neutral jersey (white, gray, black) when
# it is near-neutral and within NEUTRAL_LIGHTNESS. Lab values on OpenCV's 0-255 scale.
COLORFUL = 8.0
PIXEL_CHROMA = 5.0
HUE_TOLERANCE = 35.0
LIGHTNESS_TOLERANCE = 110.0
NEUTRAL_LIGHTNESS = 50.0
# A person gets the color most of their torso matches, if at least JERSEY_SHARE does
JERSEY_SHARE = 0.25
# The focus point counts as on a person when within this share of the photo's
# width of their outline (their mask, not their box, so a player standing in
# front of another wins)
FOCUS_REACH = 0.01
# Pose keypoints 0-4 (nose, eyes, ears) are the head, used when this confident
HEAD_CONFIDENCE = 0.4

TEAM, GOALIE, OPPONENT, OTHER = "team", "goalie", "opponent", "other"


@dataclass
class Person:
    box: tuple[int, int, int, int]
    kind: str = OTHER
    sharp: float = 0.0  # fine detail in the upper body (higher = sharper)
    head: tuple[float, float, float] | None = None  # x, y, keypoint spread
    focus_hit: bool = False

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def center(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


def hex_to_lab(color: str) -> np.ndarray:
    c = color.lstrip("#")
    rgb = np.array([[[int(c[i:i + 2], 16) for i in (0, 2, 4)]]], np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]


def _hue_chroma(lab: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b = lab[..., 1] - 128, lab[..., 2] - 128
    return np.degrees(np.arctan2(b, a)), np.hypot(a, b)


def jersey_kind(lab_pixels: np.ndarray, colors: dict[str, str]) -> str:
    """The configured jersey color most of these torso pixels match, or OTHER."""
    if len(lab_pixels) < 20:
        return OTHER
    hue, chroma = _hue_chroma(lab_pixels)
    light = lab_pixels[:, 0]
    shares = {}
    for name, color in colors.items():
        ref = hex_to_lab(color)
        ref_hue, ref_chroma = _hue_chroma(ref)
        if ref_chroma >= COLORFUL:
            diff = np.abs((hue - ref_hue + 180) % 360 - 180)
            match = (chroma >= PIXEL_CHROMA) & (diff <= HUE_TOLERANCE) & (np.abs(light - ref[0]) <= LIGHTNESS_TOLERANCE)
        else:
            match = (chroma < COLORFUL) & (np.abs(light - ref[0]) <= NEUTRAL_LIGHTNESS)
        shares[name] = float(match.mean())
    best = max(shares, key=shares.get)
    return best if shares[best] >= JERSEY_SHARE else OTHER


def _download(name: str) -> str:
    path = CACHE_DIR / name
    if not path.exists():
        from ultralytics.utils.downloads import attempt_download_asset
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        attempt_download_asset(path)
    return str(path)


class Detector:
    def __init__(self):
        self._seg = self._pose = None

    def _models(self):
        if self._seg is None:
            import torch
            from ultralytics import YOLO
            self._device = "mps" if torch.backends.mps.is_available() else "cpu"
            self._seg, self._pose = YOLO(_download(SEG_WEIGHTS)), YOLO(_download(POSE_WEIGHTS))
        return self._seg, self._pose

    def find(self, img: Image.Image, focus: tuple[float, float] | None,
             colors: dict[str, str]) -> tuple[list[Person], list[tuple[int, int, int, int]]]:
        seg, pose = self._models()
        small = img.copy()
        small.thumbnail((DETECT_EDGE, DETECT_EDGE))
        s = img.width / small.width
        arr = np.asarray(small)
        lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        r = seg.predict(arr, conf=CONFIDENCE, classes=[PERSON, BALL], retina_masks=True, verbose=False,
                        device=self._device)[0]
        p = pose.predict(arr, conf=0.25, verbose=False, device=self._device)[0]
        pose_boxes = p.boxes.xyxy.cpu().numpy() if p.boxes is not None else np.zeros((0, 4))
        keypoints = p.keypoints.data.cpu().numpy() if p.keypoints is not None else np.zeros((0, 17, 3))
        people, balls = [], []
        if r.boxes is None or r.masks is None:
            return people, balls
        masks = r.masks.data.cpu().numpy() > 0.5
        person_masks = []
        for box, cls, mask in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), masks):
            full = tuple(int(round(v * s)) for v in box)
            if int(cls) == BALL:
                balls.append(full)
                continue
            x0, y0, x1, y1 = box
            h = y1 - y0
            torso = np.zeros_like(mask)
            torso[int(y0 + TORSO[0] * h):int(y0 + TORSO[1] * h), int(x0):int(x1)] = True
            person = Person(full, jersey_kind(lab[mask & torso], colors))
            upper = gray[int(y0):int(y0 + h / 2), int(x0):int(x1)]
            person.sharp = float(cv2.Laplacian(upper, cv2.CV_32F).var()) if upper.size else 0.0
            person.head = _head(box, pose_boxes, keypoints, s)
            people.append(person)
            person_masks.append(mask)
        if focus and people:
            focused = focused_person((focus[0] / s, focus[1] / s), person_masks,
                                     max(2, int(FOCUS_REACH * arr.shape[1])))
            if focused is not None:
                people[focused].focus_hit = True
        return people, balls


def focused_person(point: tuple[float, float], masks: list[np.ndarray], reach: int) -> int | None:
    """The one person the camera focused on: whose outline holds the focus
    point (the biggest, so the one in front, if several overlap there), else
    whose outline is nearest within reach."""
    x, y = int(point[0]), int(point[1])
    h, w = masks[0].shape
    if not (0 <= x < w and 0 <= y < h):
        return None
    inside = [i for i, m in enumerate(masks) if m[y, x]]
    if inside:
        return max(inside, key=lambda i: int(masks[i].sum()))
    best, best_d = None, None
    y0, x0 = max(0, y - reach), max(0, x - reach)
    for i, m in enumerate(masks):
        ys, xs = np.nonzero(m[y0:y + reach + 1, x0:x + reach + 1])
        if len(ys):
            d = float(np.min(np.hypot(ys + y0 - y, xs + x0 - x)))
            if d <= reach and (best_d is None or d < best_d):
                best, best_d = i, d
    return best


def _head(box, pose_boxes, keypoints, s) -> tuple[float, float, float] | None:
    """The head (x, y, spread) from the pose model's person that best overlaps box."""
    if not len(pose_boxes):
        return None
    x0, y0, x1, y1 = box
    area = max((x1 - x0) * (y1 - y0), 1)
    overlap = [max(0, min(x1, q[2]) - max(x0, q[0])) * max(0, min(y1, q[3]) - max(y0, q[1])) / area
               for q in pose_boxes]
    j = int(np.argmax(overlap))
    if overlap[j] < 0.5:
        return None
    pts = keypoints[j][:5]
    seen = pts[pts[:, 2] > HEAD_CONFIDENCE]
    if not len(seen):
        return None
    spread = float(np.ptp(seen[:, 0])) if len(seen) > 1 else 0.0
    return float(seen[:, 0].mean() * s), float(seen[:, 1].mean() * s), spread * s
