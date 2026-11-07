"""What is in a photo: faces, the ball, the main player's feet, everyone's
outline and, when a look needs it, a precise cut-out of the players (the
subject layer) against everything else (the background layer).

Positions are shares of the image's width and height, and masks cover the
whole image at any size, so one scene serves the preview and the full-size
export. People, ball and heads come from photo-crops' free YOLO models and
subject rules (goalie first, then your team, then whoever is in focus).

The cut-out comes from BiRefNet (an open-source subject segmentation model,
run with rembg on this Mac): it traces hair and limbs far more precisely than
YOLO's outlines. YOLO only decides which traced pieces are the players in the
play, so background people, poles and signs stay in the background layer.
"""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photo_crops import focus, framing, images
from photo_crops.people import GOALIE, OPPONENT, TEAM, Detector, Person

Box = tuple[int, int, int, int]

# A face is drawn this many head-sizes wide when keeping it clean
FACE_REACH = 1.6
MATTE_MODEL = "birefnet-general"
# The cut-out is traced on the whole picture when this small; on bigger ones
# around the players, padded, at this many pixels on the long edge
WHOLE_FRAME_PIXELS = 4_000_000
MATTE_EDGE = 2048
# Pieces of the traced outline count as the players when this much of them is
# inside YOLO's outlines of the players in the play
ATTACHED = 0.5


@dataclass
class Scene:
    faces: list[tuple[float, float, float]] = field(default_factory=list)  # x, y, radius (shares of width)
    balls: list[tuple[float, float, float]] = field(default_factory=list)
    feet: tuple[float, float] | None = None
    subject_height: float = 0.5  # share of the image's height
    # Outlines covering the whole image (any resolution): everyone, and the players in the play
    people_mask: np.ndarray | None = field(default=None, repr=False)
    subject_mask: np.ndarray | None = field(default=None, repr=False)
    # The players' precise cut-out (alpha 0-1), set when a look needs layers
    matte: np.ndarray | None = field(default=None, repr=False)

    def in_crop(self, box: Box, size: tuple[int, int]) -> "Scene":
        """The same scene inside a crop of the image it was found in."""
        w, h = size
        x0, y0, x1, y1 = box
        cw, ch = x1 - x0, y1 - y0

        def move(x, y):
            return (x * w - x0) / cw, (y * h - y0) / ch

        def keep(items):
            out = []
            for x, y, r in items:
                nx, ny = move(x, y)
                if -0.1 <= nx <= 1.1 and -0.1 <= ny <= 1.1:
                    out.append((nx, ny, r * w / cw))
            return out

        def cut(mask):
            if mask is None:
                return None
            mh, mw = mask.shape[:2]
            return mask[int(y0 / h * mh):max(int(y0 / h * mh) + 1, int(y1 / h * mh)),
                        int(x0 / w * mw):max(int(x0 / w * mw) + 1, int(x1 / w * mw))]

        feet = move(*self.feet) if self.feet else None
        return Scene(keep(self.faces), keep(self.balls), feet, min(1.0, self.subject_height * h / ch),
                     cut(self.people_mask), cut(self.subject_mask), cut(self.matte))


def resized(mask: np.ndarray | None, h: int, w: int) -> np.ndarray | None:
    """A mask (any resolution) at h x w, as floats 0-1."""
    if mask is None:
        return None
    m = mask.astype(np.float32)
    if m.max() > 1:
        m /= 255.0
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR) if m.shape[:2] != (h, w) else m


@dataclass
class Prepared:
    """A photo ready for looks: the image (cropped if asked) and its scene."""
    path: Path
    image: Image.Image
    scene: Scene
    exif: bytes | None

    def ensure_matte(self) -> np.ndarray | None:
        if self.scene.matte is None and self.scene.subject_mask is not None:
            matte = cutout(self.image, self.scene.subject_mask)
            self.scene.matte = with_balls(matte, self.scene.balls) if matte is not None else None
        return self.scene.matte


def with_balls(matte: np.ndarray, balls: list[tuple[float, float, float]]) -> np.ndarray:
    """The ball belongs with the players in the subject layer (it is often in
    the air, apart from them, where the cut-out does not reach)."""
    h, w = matte.shape
    discs = np.zeros_like(matte)
    for x, y, r in balls:
        cv2.circle(discs, (int(x * w), int(y * h)), max(1, int(r * w)), 1.0, -1, cv2.LINE_AA)
    return np.maximum(matte, cv2.GaussianBlur(discs, (0, 0), 0.8))


_detector: Detector | None = None
_matte_session = None


def detector() -> Detector:
    global _detector
    if _detector is None:
        _detector = Detector()
    return _detector


def _session():
    global _matte_session
    if _matte_session is None:
        from rembg import new_session
        _matte_session = new_session(MATTE_MODEL)
    return _matte_session


def cutout(img: Image.Image, subject_mask: np.ndarray) -> np.ndarray | None:
    """The players' precise cut-out (alpha 0-1), at up to MATTE_EDGE px on the long edge."""
    from rembg import remove
    small = img.copy()
    small.thumbnail((MATTE_EDGE, MATTE_EDGE))
    w, h = small.size
    yolo = resized(subject_mask, h, w) > 0.5
    if not yolo.any():
        return None
    if img.width * img.height <= WHOLE_FRAME_PIXELS:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        ys, xs = np.nonzero(yolo)
        bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        pad = int(max(0.5 * max(bx1 - bx0, by1 - by0), 0.25 * min(w, h)))
        x0, y0, x1, y1 = max(0, bx0 - pad), max(0, by0 - pad), min(w, bx1 + pad), min(h, by1 + pad)
    alpha = np.asarray(remove(small.crop((x0, y0, x1, y1)), session=_session(), only_mask=True), np.float32) / 255
    # Keep only traced pieces that touch the players in the play
    count, labels = cv2.connectedComponents((alpha > 0.05).astype(np.uint8))
    attached = np.unique(labels[yolo[y0:y1, x0:x1] & (alpha > ATTACHED)])
    keep = np.zeros(count, bool)
    keep[attached[attached > 0]] = True
    alpha = np.where(keep[labels], alpha, 0).astype(np.float32)
    full = np.zeros((h, w), np.float32)
    full[y0:y1, x0:x1] = alpha
    return full


def _union(people: list[Person], shape: tuple[int, int]) -> np.ndarray | None:
    masks = [p.mask for p in people if p.mask is not None]
    if not masks:
        return None
    out = np.zeros(masks[0].shape, np.uint8)
    for m in masks:
        out |= m.astype(np.uint8)
    return out * 255


def find(img: Image.Image, people: list[Person], balls: list[Box], plan: framing.Plan) -> Scene:
    w, h = img.size
    # The players in the play: everyone whose box is inside the crop's group (team photos: everyone big)
    gx0, gy0, gx1, gy1 = plan.group
    in_play = [p for p in people if p.box[0] >= gx0 - 2 and p.box[2] <= gx1 + 2 and p.box[1] >= gy0 - 2
               and p.box[3] <= gy1 + 2]
    if not in_play and plan.subject:
        in_play = [plan.subject]
    faces = []
    # Only the players in the play keep clean faces; people in the background
    # take the look like everything around them (else their faces stand out as patches)
    for p in in_play:
        if p.head and p.height > 0.08 * h:
            x, y, spread = p.head
            radius = max(spread * 1.4, p.height * 0.12) * FACE_REACH / 2
            faces.append((x / w, y / h, radius / w))
    ball_list = [((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h, (b[2] - b[0]) / 2 / w) for b in balls]
    subject = plan.subject
    feet = ((subject.box[0] + subject.box[2]) / 2 / w, subject.box[3] / h) if subject else None
    height = (subject.height / h) if subject else 0.5
    return Scene(faces, ball_list, feet, height, _union(people, img.size), _union(in_play, img.size))


def prepare(path: Path, crop: str = "none", colors: dict[str, str] | None = None,
            goalie_first: bool = True, shape: str = "best") -> Prepared:
    """Loads a photo (RAW in the camera's look), finds its scene and, if
    asked, crops it the photo-crops way: "crop" (pro crop) or "face"."""
    colors = colors or {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}
    photo = images.load(path)
    img = photo.image
    people, balls = detector().find(img, focus.focus_point(path, img.size), colors)
    plan = framing.choose(people, balls, img.size, goalie_first)
    scene = find(img, people, balls, plan)
    box = None
    if crop == "crop":
        box = framing.crop_box(plan, img.size, shape)
    elif crop == "face" and plan.face_person:
        box = framing.face_box(plan.face_person, img.size, "sharp", framing.crop_box(plan, img.size, shape))
    if box:
        return Prepared(path, img.crop(box), scene.in_crop(box, img.size), photo.exif)
    return Prepared(path, img, scene, photo.exif)
