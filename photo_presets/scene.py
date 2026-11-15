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

Fixes: you can click what the automatic cut-out missed (a teammate, the ball,
a flag) or should not have (a pole). Each click is traced with SAM 2.1 (Meta's
Segment Anything, free, run on this Mac) and added to or taken out of the
cut-out. A photo's fixes stay with it, for every look and the full-size export.
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
MATTE_EDGE = 3072  # high enough to keep the hair pass's detail (see refine_heads)
HEAD_EDGE = 1024  # each head is traced again on its own, at this size
HEAD_REACH = 1.8  # the head crop, in face radii around it
# Pieces of the traced outline count as the players when this much of them is
# inside YOLO's outlines of the players in the play
ATTACHED = 0.5
SAM_WEIGHTS = "sam2.1_b.pt"
SAM_EDGE = 1600  # a click is traced on the photo at this size, then again closer around what it found
SAM_PAD = 0.2  # the closer look reaches this share of the object's size around it


@dataclass(frozen=True)
class Fix:
    """A click on the photo: x, y (shares of its width and height); add (True)
    or take out (False) what is there."""
    x: float
    y: float
    add: bool = True


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
    hands: list[tuple[float, float, float]] = field(default_factory=list)  # the players in the play: x, y, radius
    subject_box: tuple[float, float, float, float] | None = None  # the main player (shares of the image)
    # everyone else's heads and hands: they join faces and hands when the cut-out takes them in
    # (a child holding the main player's hand is drawn with them, so needs their real face too)
    other_faces: list[tuple[float, float, float]] = field(default_factory=list)
    other_hands: list[tuple[float, float, float]] = field(default_factory=list)

    def take_in(self, matte: np.ndarray) -> None:
        """Everyone else whose head is inside the cut-out becomes a player in the
        play for faces and hands: their face is kept clean (and in drawn looks, the
        child's own), their hair traced, their hands drawn."""
        mh, mw = matte.shape[:2]
        for x, y, r in list(self.other_faces):
            cx, cy, rad = int(x * mw), int(y * mh), max(1, int(r * mw * 0.35))
            spot = matte[max(0, cy - rad):cy + rad + 1, max(0, cx - rad):cx + rad + 1]
            if spot.size and float(spot.mean()) > 0.5:
                self.faces.append((x, y, r))
                self.other_faces.remove((x, y, r))
                self.hands += [hd for hd in self.other_hands if abs(hd[0] - x) < r * 6 and abs(hd[1] - y) < r * 8]

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
        sb = None
        if self.subject_box:
            a0, b0 = move(self.subject_box[0], self.subject_box[1])
            a1, b1 = move(self.subject_box[2], self.subject_box[3])
            sb = (a0, b0, a1, b1)
        return Scene(keep(self.faces), keep(self.balls), feet, min(1.0, self.subject_height * h / ch),
                     cut(self.people_mask), cut(self.subject_mask), cut(self.matte), keep(self.hands), sb,
                     keep(self.other_faces), keep(self.other_hands))


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
    fine: np.ndarray | None = None  # the image in 16 bits (uint16), from RAW and 16-bit TIFF photos
    fixes: list[Fix] = field(default_factory=list)
    frame: tuple[float, float, float, float] | None = None  # framed for a look: its box in the photo (shares)
    _auto: tuple | None = field(default=None, repr=False)  # the cut-out and players' outline before fixes
    _pieces: dict = field(default_factory=dict, repr=False)  # each click's traced object

    def ensure_matte(self) -> np.ndarray | None:
        if self.scene.matte is None:
            if self._auto is None:
                matte = None
                if self.scene.subject_mask is not None:
                    matte = cutout(self.image, self.scene.subject_mask)
                    if matte is not None:
                        self.scene.take_in(matte)
                        matte = refine_heads(self.image, matte, self.scene.faces)
                    matte = with_balls(matte, self.scene.balls) if matte is not None else None
                self._auto = (matte, self.scene.subject_mask)
            self.scene.matte, self.scene.subject_mask = self._fixed()
        return self.scene.matte

    def set_fixes(self, fixes: list[Fix]) -> None:
        """Uses these clicks (all of them, in order) on the cut-out."""
        if list(fixes) == self.fixes:
            return
        self.fixes = list(fixes)
        if self._auto is not None:
            self.scene.matte, self.scene.subject_mask = self._fixed()
        elif self.fixes:
            self.ensure_matte()

    def _fixed(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        auto, subject = self._auto
        if not self.fixes:
            return auto, subject
        if auto is not None:
            h, w = auto.shape
        else:
            scale = min(1.0, MATTE_EDGE / max(self.image.size))
            w, h = max(1, round(self.image.width * scale)), max(1, round(self.image.height * scale))
        matte = auto.copy() if auto is not None else np.zeros((h, w), np.float32)
        ih, iw = (subject.shape if subject is not None else (self.image.height, self.image.width))
        outline = (subject > 127) if subject is not None else np.zeros((ih, iw), bool)
        for f in self.fixes:
            key = (f.x, f.y, h, w)
            if key not in self._pieces:
                self._pieces[key] = segment(self.image, f.x, f.y, (h, w))
            piece = self._pieces[key]
            part = cv2.resize(piece, (iw, ih), interpolation=cv2.INTER_LINEAR) > 0.5
            if f.add:
                matte = np.maximum(matte, piece)
                outline |= part
            else:
                matte = matte * (1 - piece)
                outline &= ~part
        return matte.astype(np.float32), (outline.astype(np.uint8) * 255 if outline.any() else None)


def refine_heads(img: Image.Image, matte: np.ndarray, faces: list[tuple[float, float, float]]) -> np.ndarray:
    """Each head traced again on its own, close up, so curly hair and afros keep
    their detail against the background (the gaps between curls open up). The
    new edge is used only around the head, and may not grow past the first
    cut-out, so no background object joins the player."""
    from rembg import remove
    W, H = img.size
    mh, mw = matte.shape
    out = matte.copy()
    for fx, fy, fr in faces:
        r = fr * W
        if r < 6:
            continue
        cx, cy = fx * W, fy * H - r * 0.25  # a little up: hair
        half = r * HEAD_REACH
        x0, y0, x1, y1 = int(max(0, cx - half)), int(max(0, cy - half)), int(min(W, cx + half)), int(min(H, cy + half))
        if x1 - x0 < 16 or y1 - y0 < 16:
            continue
        crop = img.crop((x0, y0, x1, y1))
        crop.thumbnail((HEAD_EDGE, HEAD_EDGE))
        fine = np.asarray(remove(crop, session=_session(), only_mask=True), np.float32) / 255
        X0, Y0 = int(x0 / W * mw), int(y0 / H * mh)
        X1, Y1 = max(X0 + 1, int(x1 / W * mw)), max(Y0 + 1, int(y1 / H * mh))
        fine = cv2.resize(fine, (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_LINEAR)
        old = out[Y0:Y1, X0:X1]
        # only the piece holding the face, and never past the first cut-out (grown a hair's width)
        n, lab = cv2.connectedComponents((fine > 0.3).astype(np.uint8))
        fcx, fcy = int((fx * W - x0) / (x1 - x0) * (X1 - X0)), int((fy * H - y0) / (y1 - y0) * (Y1 - Y0))
        here = lab[min(max(fcy, 0), Y1 - Y0 - 1), min(max(fcx, 0), X1 - X0 - 1)]
        if here == 0:
            continue
        piece = cv2.dilate((lab == here).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
        grow = max(3, int((X1 - X0) * 0.02)) | 1
        allowed = cv2.dilate((old > 0.05).astype(np.uint8), np.ones((grow, grow), np.uint8)).astype(np.float32)
        fine = fine * piece * allowed
        # used around the head, blending back to the first cut-out toward the crop's edges and below the chin
        yy, xx = np.mgrid[0:Y1 - Y0, 0:X1 - X0].astype(np.float32)
        d = np.sqrt(((xx - (X1 - X0) / 2) / ((X1 - X0) / 2)) ** 2 + ((yy - (Y1 - Y0) / 2) / ((Y1 - Y0) / 2)) ** 2)
        zone = np.clip((1.0 - d) / 0.3, 0, 1)
        chin = int((fy * H + r * 0.9 - y0) / (y1 - y0) * (Y1 - Y0))
        zone[max(0, chin):] *= np.clip(1 - (np.arange(max(0, chin), Y1 - Y0) - chin) / max(1, (Y1 - Y0) * 0.1), 0, 1)[:, None]
        out[Y0:Y1, X0:X1] = old * (1 - zone) + fine * zone
    return out


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
_sam = None


def _sam_model():
    global _sam
    if _sam is None:
        from ultralytics import SAM
        from photo_crops.people import _download
        _sam = SAM(_download(SAM_WEIGHTS))
    return _sam


def _sam_mask(img: Image.Image, x: float, y: float) -> np.ndarray | None:
    """SAM's outline (bool, at the image's size) of the object at x, y (pixels)."""
    import torch
    rgb = np.ascontiguousarray(np.asarray(img.convert("RGB"))[..., ::-1])
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        r = _sam_model()(rgb, points=[[x, y]], labels=[1], device=device, verbose=False)
    except RuntimeError:  # a GPU hiccup: the processor does it too
        r = _sam_model()(rgb, points=[[x, y]], labels=[1], device="cpu", verbose=False)
    if not r or r[0].masks is None or not len(r[0].masks.data):
        return None
    m = r[0].masks.data[0].cpu().numpy() > 0.5
    if m.shape != (img.height, img.width):
        m = cv2.resize(m.astype(np.uint8), img.size, interpolation=cv2.INTER_NEAREST).astype(bool)
    return m


def segment(img: Image.Image, x: float, y: float, size: tuple[int, int]) -> np.ndarray:
    """The object at x, y (shares of the image) as a soft mask (0-1) of size
    (h, w): found on the whole photo, then traced again closer around it, so
    small things (a ball, a hand) get sharp edges too."""
    h, w = size
    out = np.zeros((h, w), np.float32)
    small = img.copy()
    small.thumbnail((SAM_EDGE, SAM_EDGE))
    first = _sam_mask(small, x * small.width, y * small.height)
    if first is None or not first.any():
        return out
    ys, xs = np.nonzero(first)
    bx0, bx1 = xs.min() / small.width, (xs.max() + 1) / small.width
    by0, by1 = ys.min() / small.height, (ys.max() + 1) / small.height
    pad = SAM_PAD * max(bx1 - bx0, (by1 - by0) * img.height / img.width)
    x0, x1 = max(0.0, bx0 - pad), min(1.0, bx1 + pad)
    y0, y1 = max(0.0, by0 - pad * img.width / img.height), min(1.0, by1 + pad * img.width / img.height)
    box = (int(x0 * img.width), int(y0 * img.height), int(np.ceil(x1 * img.width)), int(np.ceil(y1 * img.height)))
    crop = img.crop(box)
    crop.thumbnail((SAM_EDGE, SAM_EDGE))
    second = _sam_mask(crop, (x * img.width - box[0]) / (box[2] - box[0]) * crop.width,
                       (y * img.height - box[1]) / (box[3] - box[1]) * crop.height)
    if second is None or not second.any():  # keep the first look
        piece = cv2.resize(first.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        X0, Y0 = int(round(x0 * w)), int(round(y0 * h))
        X1, Y1 = max(X0 + 1, int(round(x1 * w))), max(Y0 + 1, int(round(y1 * h)))
        piece = out.copy()
        piece[Y0:Y1, X0:X1] = cv2.resize(second.astype(np.float32), (X1 - X0, Y1 - Y0),
                                         interpolation=cv2.INTER_LINEAR)
    return np.clip(cv2.GaussianBlur(piece, (0, 0), 0.7), 0, 1).astype(np.float32)


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


BALL_IN_PLAY = 0.08  # a ball's size as a share of the nearest player's height, at least
BALL_REACH = 1.5  # how far a ball in the play can be from the nearest player, in their heights


def ball_in_play(ball: Box, in_play: list[Person]) -> bool:
    """Whether a ball belongs to the play: about as big as a ball at the players'
    own distance (a ball is about a seventh of a young player's height), and near
    them. A ball far behind them (another game, the warm-up) looks much smaller, and
    one far off to the side (or something round in a tree) is not in the play: both
    are left out of the cut-out, the framing and the effects placed at the ball."""
    if not in_play:
        return True
    bx, by = (ball[0] + ball[2]) / 2, (ball[1] + ball[3]) / 2
    def gap(p):
        return (max(p.box[0] - bx, 0, bx - p.box[2]) ** 2 + max(p.box[1] - by, 0, by - p.box[3]) ** 2) ** 0.5

    near = min(in_play, key=gap)
    size = max(ball[2] - ball[0], ball[3] - ball[1])
    return size >= BALL_IN_PLAY * near.height and gap(near) <= BALL_REACH * near.height


def find(img: Image.Image, people: list[Person], balls: list[Box], plan: framing.Plan) -> Scene:
    w, h = img.size
    # The players in the play: everyone whose box is inside the crop's group (team photos: everyone big)
    gx0, gy0, gx1, gy1 = plan.group
    in_play = [p for p in people if p.box[0] >= gx0 - 2 and p.box[2] <= gx1 + 2 and p.box[1] >= gy0 - 2
               and p.box[3] <= gy1 + 2]
    if not in_play and plan.subject:
        in_play = [plan.subject]
    def head(p):
        x, y, spread = p.head
        return x / w, y / h, max(spread * 1.4, p.height * 0.12) * FACE_REACH / 2 / w

    # Only the players in the play keep clean faces; people in the background
    # take the look like everything around them (else their faces stand out as patches).
    # Others are kept aside: the cut-out may take them in (Scene.take_in).
    others = [p for p in people if p not in in_play and p.head and p.height > 0.08 * h]
    faces = [head(p) for p in in_play if p.head and p.height > 0.08 * h]
    other_faces = [head(p) for p in others]
    other_hands = [(x / w, y / h, p.height * 0.065 / w) for p in others for x, y in p.hands]
    ball_list = [((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h, (b[2] - b[0]) / 2 / w)
                 for b in balls if ball_in_play(b, in_play)]
    hands = [(x / w, y / h, p.height * 0.065 / w) for p in in_play for x, y in p.hands if p.height > 0.08 * h]
    subject = plan.subject
    feet = ((subject.box[0] + subject.box[2]) / 2 / w, subject.box[3] / h) if subject else None
    height = (subject.height / h) if subject else 0.5
    sb = (subject.box[0] / w, subject.box[1] / h, subject.box[2] / w, subject.box[3] / h) if subject else None
    return Scene(faces, ball_list, feet, height, _union(people, img.size), _union(in_play, img.size), hands=hands,
                 subject_box=sb, other_faces=other_faces, other_hands=other_hands)


def prepare(path: Path, crop: str = "none", colors: dict[str, str] | None = None,
            goalie_first: bool = True, shape: str = "best") -> Prepared:
    """Loads a photo (RAW in the camera's look), finds its scene and, if
    asked, crops it the photo-crops way: "crop" (pro crop, zoomed in on the
    action), "wide" (pro crop without zooming) or "face"."""
    colors = colors or {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}
    photo = images.load(path)
    img = photo.image
    people, balls = detector().find(img, focus.focus_point(path, img.size), colors)
    plan = framing.choose(people, balls, img.size, goalie_first)
    scene = find(img, people, balls, plan)
    box = None
    if crop == "crop":
        box = framing.crop_box(plan, img.size, shape)
    elif crop == "wide":
        box = framing.wide_box(plan, img.size)
        box = None if box == (0, 0, img.width, img.height) else box
    elif crop == "face" and plan.face_person:
        box = framing.face_box(plan.face_person, img.size, "sharp", framing.crop_box(plan, img.size, shape))
    if box:
        cropped = img.crop(box)
        fine = None
        if photo.fine is not None:
            # the same pixels as Pillow's crop (which pads past the edges with black)
            l, t = int(round(box[0])), int(round(box[1]))
            fine = np.zeros((cropped.height, cropped.width, 3), np.uint16)
            part = photo.fine[max(t, 0):t + cropped.height, max(l, 0):l + cropped.width]
            fine[max(-t, 0):max(-t, 0) + part.shape[0], max(-l, 0):max(-l, 0) + part.shape[1]] = part
        return Prepared(path, cropped, scene.in_crop(box, img.size), photo.exif, fine)
    return Prepared(path, img, scene, photo.exif, photo.fine)
