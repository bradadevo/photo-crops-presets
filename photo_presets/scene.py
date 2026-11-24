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

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import threading

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
HEAD_REACH = 1.8
MODEL_LOCK = threading.Lock()  # one full cut-out at a time in the whole app: each needs several GB at once
HEADS = 2  # heads traced again, the biggest first  # the head crop, in face radii around it
# Pieces of the traced outline count as the players when this much of them is
# inside YOLO's outlines of the players in the play
ATTACHED = 0.5
SAM_WEIGHTS = "sam2.1_b.pt"
SAM_EDGE = 1600  # a click is traced on the photo at this size, then again closer around what it found
SAM_PAD = 0.2  # the closer look reaches this share of the object's size around it


@dataclass(frozen=True)
class Fix:
    """One fix to the cut-out, in order:
    "click": the object at x, y (shares of the photo's width and height): add (True) or take it out;
    "brush": painted in (add) or out along points, a brush of radius r (a share of the photo's width);
    "edge":  the refine-edge brush along points: there, the edge follows the photo's own (hair, fingers);
    "tune":  the whole edge: x = softness (0-1), y = shift (-1 in ... +1 out)."""
    x: float
    y: float
    add: bool = True
    kind: str = "click"
    points: tuple = ()
    r: float = 0.0

    def to_json(self):
        if self.kind == "click":
            return [self.x, self.y, self.add]
        return {"kind": self.kind, "x": self.x, "y": self.y, "add": self.add, "r": self.r,
                "points": [[round(px, 4), round(py, 4)] for px, py in self.points]}

    @staticmethod
    def from_json(v) -> "Fix":
        if isinstance(v, (list, tuple)):
            return Fix(float(v[0]), float(v[1]), bool(v[2]))
        return Fix(float(v.get("x", 0)), float(v.get("y", 0)), bool(v.get("add", True)), str(v.get("kind", "click")),
                   tuple((float(px), float(py)) for px, py in v.get("points", [])), float(v.get("r", 0)))


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
    team: bool = False  # a team photo: the players are one group

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
                     keep(self.other_faces), keep(self.other_hands), self.team)


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
    box: tuple[float, float, float, float] | None = None  # cropped first ("crop", "wide", "face"): its box in the photo (shares)
    _auto: tuple | None = field(default=None, repr=False)  # the cut-out and players' outline before fixes
    matte_key: str | None = field(default=None, repr=False)  # its cut-out's name on disk, once made or found
    players_from: "Prepared | None" = field(default=None, repr=False)  # the same players, already found (see same_players)
    _pieces: dict = field(default_factory=dict, repr=False)  # each click's traced object
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def ensure_matte(self) -> np.ndarray | None:
        with self._lock:  # (asked for twice at once, the players are found once: the second waits)
            return self._ensure_matte()

    def _ensure_matte(self) -> np.ndarray | None:
        if self.scene.matte is None and self._auto is None and self.players_from is not None:
            src = self.players_from  # (the photo before its light and color were changed: the very same players)
            src.ensure_matte()
            _copy_scene(src.scene, self.scene)
            self._auto = (src.scene.matte, src.scene.subject_mask)
            self.matte_key = src.matte_key
        if self.scene.matte is None:
            if self._auto is None:
                matte = None
                if self.scene.subject_mask is not None:
                    key = _matte_key(self.image, self.scene.subject_mask, self.scene.team)
                    matte = _kept_matte(key)  # made before (this photo, these players): no minute's wait
                    if matte is None:
                        with MODEL_LOCK:  # (one at a time; made in the background meanwhile: found on disk)
                            matte = _kept_matte(key)
                            if matte is None:
                                matte = _made_matte(self.image, self.scene)
                                if matte is not None:
                                    _keep_matte(key, matte)
                    if matte is not None:
                        self.scene.take_in(matte)
                    self.matte_key = key
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
        soft = shift = 0.0
        for f in self.fixes:
            if f.kind == "tune":
                soft, shift = float(np.clip(f.x, 0, 1)), float(np.clip(f.y, -1, 1))
                continue
            if f.kind in ("brush", "edge"):
                stroke = brush_mask(f.points, f.r, (h, w))
                if f.kind == "edge":
                    matte = refine_edge(matte, self._guide(h, w), stroke, max(2.0, f.r * w * 0.35))
                elif f.add:
                    matte = np.maximum(matte, stroke)
                else:
                    matte = matte * (1 - stroke)
                part = cv2.resize(stroke, (iw, ih), interpolation=cv2.INTER_LINEAR) > 0.5
                if f.kind == "brush":
                    outline = (outline | part) if f.add else (outline & ~part)
                continue
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
        matte = tune_edge(matte, soft, shift)
        return matte.astype(np.float32), (outline.astype(np.uint8) * 255 if outline.any() else None)

    def _guide(self, h: int, w: int) -> np.ndarray:
        """The photo at the cut-out's size (floats), for the refine-edge brush."""
        key = ("guide", h, w)
        if key not in self._pieces:
            self._pieces[key] = cv2.resize(np.asarray(self.image.convert("RGB")), (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
        return self._pieces[key]


def refine_heads(img: Image.Image, matte: np.ndarray, faces: list[tuple[float, float, float]]) -> np.ndarray:
    """Each head traced again on its own, close up, so curly hair and afros keep
    their detail against the background (the gaps between curls open up). The
    new edge is used only around the head, and may not grow past the first
    cut-out, so no background object joins the player."""
    from rembg import remove
    W, H = img.size
    mh, mw = matte.shape
    out = matte.copy()
    # the two biggest faces (the main players): each tracing is a full run of the model
    for fx, fy, fr in sorted(faces, key=lambda f: -f[2])[:HEADS]:
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
        fine = np.asarray(remove(crop, session=_heads_session(), only_mask=True), np.float32) / 255
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
        # only around this head itself: another player's leg or arm in the same square is not this
        # head's piece, and keeps the first cut-out (it used to be wiped out, then blurred by the look)
        reach = max(5, int((X1 - X0) * 0.08)) | 1
        own = cv2.dilate((lab == here).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (reach, reach)))
        zone = zone * cv2.GaussianBlur(own.astype(np.float32), (0, 0), reach / 3)
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


def brush_mask(points, r: float, size: tuple[int, int]) -> np.ndarray:
    """A brush stroke (points: shares of the photo; r: its radius, a share of the photo's width) as a
    0-1 mask at size (h, w), with a slightly soft edge like a real brush."""
    h, w = size
    m = np.zeros((h, w), np.uint8)
    rad = max(1, int(round(r * w)))
    pts = [(int(round(x * w)), int(round(y * h))) for x, y in points] or []
    for a, b in zip(pts, pts[1:] or pts):
        cv2.line(m, a, b, 255, rad * 2, cv2.LINE_AA)
    for p in pts:
        cv2.circle(m, p, rad, 255, -1, cv2.LINE_AA)
    out = m.astype(np.float32) / 255
    return cv2.GaussianBlur(out, (0, 0), max(0.6, rad * 0.12))


def _box(a: np.ndarray, r: int) -> np.ndarray:
    return cv2.boxFilter(a, -1, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)


def guided(I: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """The color guided filter (He et al.): p's edges made to follow the edges in the color image I.
    It is what carries a cut-out's edge into single strands of hair."""
    mI = [_box(I[..., c], r) for c in range(3)]
    mp = _box(p, r)
    cov = [_box(I[..., c] * p, r) - mI[c] * mp for c in range(3)]
    var = np.empty(p.shape + (3, 3), np.float32)
    for i in range(3):
        for j in range(i, 3):
            v = _box(I[..., i] * I[..., j], r) - mI[i] * mI[j]
            var[..., i, j] = var[..., j, i] = v
    var += np.eye(3, dtype=np.float32) * eps
    a = np.linalg.solve(var, np.stack(cov, -1)[..., None])[..., 0]
    b = mp - sum(a[..., c] * mI[c] for c in range(3))
    ma = [_box(a[..., c], r) for c in range(3)]
    return sum(ma[c] * I[..., c] for c in range(3)) + _box(b, r)


def refine_edge(matte: np.ndarray, guide: np.ndarray, stroke: np.ndarray, rad: float = 6) -> np.ndarray:
    """The refine-edge brush: where it was painted, the cut-out's edge is worked out again from the photo
    itself (hair, fingers, a net). Each pixel there is weighed between the player's colors and the
    background's colors close to it (learned from what is surely one or the other), then smoothed along
    the photo's own edges, so single strands of hair come in and the grass between them stays out."""
    ys, xs = np.nonzero(stroke > 0.02)
    if not len(ys):
        return matte
    h, w = matte.shape
    near = max(6, int(rad * 4))  # how far to look for the player's and the background's colors
    pad = near + int(rad) + 8
    y0, y1, x0, x1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1), max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    m, I, s = matte[y0:y1, x0:x1].astype(np.float32), guide[y0:y1, x0:x1], stroke[y0:y1, x0:x1]
    unknown = s > 0.02
    fg = ((m > 0.95) & ~unknown).astype(np.float32)
    bg = ((m < 0.05) & ~unknown).astype(np.float32)
    if fg.sum() < 4 or bg.sum() < 4:  # (both kinds next to the brush, or nothing to learn from)
        fg, bg = (m > 0.95).astype(np.float32), (m < 0.05).astype(np.float32)
    if fg.sum() < 4 or bg.sum() < 4:
        return matte

    def local_mean(weights):
        k = near
        n = _box(weights, k)
        out = np.stack([_box(I[..., c] * weights, k) for c in range(3)], -1) / np.maximum(n, 1e-6)[..., None]
        far = n < 1e-3  # nothing of that kind close: its average over the whole brush area
        if far.any():
            out[far] = (I * weights[..., None]).sum((0, 1)) / max(weights.sum(), 1e-6)
        return out

    F, B = local_mean(fg), local_mean(bg)
    d = F - B
    alpha = ((I - B) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-3)
    alpha = np.clip(alpha, 0, 1)
    alpha = np.clip(guided(I, alpha.astype(np.float32), max(1, int(rad * 0.5)), 1e-3), 0, 1)
    alpha = np.clip((alpha - 0.1) / 0.8, 0, 1)  # (no grey haze left in the background)
    keep = cv2.erode((m > 0.97).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    alpha[keep] = 1.0
    out = matte.copy()
    out[y0:y1, x0:x1] = m * (1 - s) + alpha * s
    return out


def tune_edge(matte: np.ndarray, soft: float, shift: float) -> np.ndarray:
    """The whole edge softened (feathered) and moved in or out, like Select and Mask's sliders."""
    if not soft and not shift:
        return matte
    h, w = matte.shape
    unit = max(h, w) / 1000
    out = matte
    if shift:
        k = max(1, int(round(abs(shift) * 6 * unit)))
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
        out = cv2.dilate(out, ker) if shift > 0 else cv2.erode(out, ker)
    if soft:
        out = cv2.GaussianBlur(out, (0, 0), max(0.3, soft * 4 * unit))
    return np.clip(out, 0, 1).astype(np.float32)


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


_head_session = None


def _heads_session():
    """BiRefNet Lite for tracing heads again (hair): as fine on a head, three times quicker, and
    it needs far less memory (the full model can stall for minutes when the Mac is short of it)."""
    global _head_session
    if _head_session is None:
        import onnxruntime as ort
        from rembg import new_session
        opts = ort.SessionOptions()
        opts.enable_cpu_mem_arena = False
        _head_session = new_session("birefnet-general-lite", sess_opts=opts)
    return _head_session


def _session():
    global _matte_session
    if _matte_session is None:
        import onnxruntime as ort
        from rembg import new_session
        opts = ort.SessionOptions()
        # memory handed back after each run: the model needs several GB at once, and holding on
        # to it pushes the Mac into its swap, where one run can stall for minutes
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        _matte_session = new_session(MATTE_MODEL, sess_opts=opts)
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


_small_session = None
SMALL_MODEL = "u2net_human_seg"  # a people cut-out made for small pictures (320 px): 0.3 s and under 2 GB


def small_cutout(img: Image.Image, scene: "Scene") -> np.ndarray | None:
    """The players' cut-out for a small preview (the whole-event grid): the same steps as the full one
    (only pieces touching the players in the play, the ball, a team as one group) with a model made for
    small pictures, on 2 processor cores. Edges are only right at small sizes: never used for Make."""
    from rembg import remove
    global _small_session
    if scene.subject_mask is None:
        return None
    if _small_session is None:
        import onnxruntime as ort
        from rembg import new_session
        opts = ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = 2, 1  # (the other cores stay free for you)
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        _small_session = new_session(SMALL_MODEL, sess_opts=opts)
    w, h = img.size
    yolo = resized(scene.subject_mask, h, w) > 0.5
    if not yolo.any():
        return None
    alpha = np.asarray(remove(img, session=_small_session, only_mask=True), np.float32) / 255
    count, labels = cv2.connectedComponents((alpha > 0.05).astype(np.uint8))
    attached = np.unique(labels[yolo & (alpha > ATTACHED)])
    keep = np.zeros(count, bool)
    keep[attached[attached > 0]] = True
    alpha = np.where(keep[labels], alpha, 0).astype(np.float32)
    alpha = with_balls(alpha, scene.balls)
    if scene.team:
        alpha = fill_group(alpha, img, scene.subject_mask)
    return alpha


def release_small_cutout() -> None:
    """Hands the small cut-out model's memory back (the event's previews are all made)."""
    global _small_session
    _small_session = None


MATTE_VERSION = 6  # (raised when the cut-out is made differently: the kept ones are made again)
MATTES_KEPT = 400  # cut-outs kept on disk, the oldest let go


def _mattes_dir() -> Path:
    import os
    state = os.environ.get("ALLPROPHOTO_STATE")
    base = Path(state) if state else Path("~/.cache/photo-crops-presets").expanduser()
    return base / "mattes"


def _matte_key(image: Image.Image, subject: np.ndarray, team: bool) -> str:
    """The same picture with the same players: a small copy of it, its size and the players' outline."""
    import hashlib
    small = np.asarray(image.convert("RGB").resize((96, 96)), np.uint8)
    outline = np.packbits(cv2.resize(subject.astype(np.uint8), (128, 128), interpolation=cv2.INTER_NEAREST) > 0)
    h = hashlib.sha1()
    for part in (small.tobytes(), outline.tobytes(), repr((image.size, team, MATTE_VERSION)).encode()):
        h.update(part)
    return h.hexdigest()[:20]


def _kept_matte(key: str) -> np.ndarray | None:
    p = _mattes_dir() / f"{key}.png"
    try:
        if p.exists():
            p.touch()
            return np.asarray(Image.open(p).convert("L"), np.float32) / 255
    except OSError:
        pass
    return None


def _keep_matte(key: str, matte: np.ndarray) -> None:
    try:
        d = _mattes_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{key}.part.png"
        Image.fromarray((np.clip(matte, 0, 1) * 255 + 0.5).astype(np.uint8), "L").save(tmp, optimize=False)
        tmp.replace(d / f"{key}.png")
        kept = sorted(d.glob("*.png"), key=lambda q: q.stat().st_mtime)
        for old in kept[:-MATTES_KEPT]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _copy_scene(src: "Scene", dst: "Scene") -> None:
    import copy
    for f in dataclasses.fields(src):
        setattr(dst, f.name, copy.copy(getattr(src, f.name)))


def same_players(edited: Path, image: Image.Image, exif: bytes | None, fine: np.ndarray | None,
                 original: Prepared) -> Prepared:
    """A photo with only its light and color changed (nothing moved: no crop, turn or removal), ready
    for looks with the original's players: found once, cut out once (not 20 s again for each edit)."""
    p = Prepared(edited, image, Scene(), exif, fine, players_from=original)
    _copy_scene(original.scene, p.scene)
    p.scene.matte = None  # (taken from the original when a look needs it, fixes and all)
    return p


def _made_matte(image: Image.Image, scene: "Scene") -> np.ndarray | None:
    """The players' full cut-out made: the model, each head again for the hair, the ball, a team as
    one group."""
    matte = cutout(image, scene.subject_mask)
    if matte is None:
        return None
    scene.take_in(matte)  # (the faces found inside the players, for the hair pass)
    matte = refine_heads(image, matte, scene.faces)
    matte = with_balls(matte, scene.balls)
    if scene.team:
        matte = fill_group(matte, image, scene.subject_mask)
    return matte


def fill_group(alpha: np.ndarray, image: Image.Image | None = None, people: np.ndarray | None = None) -> np.ndarray:
    """A team photo's cut-out as one group: a child half hidden behind the others, or a dark kit
    the cut-out missed, inside the group is taken in, so no look puts smoke or blur over them.
    The grass between the players is not: what looks like the ground and background just around
    the team stays background (a look that greys or darkens the background reaches it too)."""
    h, w = alpha.shape
    solid = (alpha > 0.4).astype(np.uint8)
    k = max(5, int(0.05 * h)) | 1
    closed = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    # what is outside the group: reachable from the picture's edge
    outside = np.zeros((h + 2, w + 2), np.uint8)
    flood = closed.copy()
    for x in range(0, w, max(1, w // 64)):
        for y in (0, h - 1):
            if flood[y, x] == 0:
                cv2.floodFill(flood, outside, (x, y), 2)
    for y in range(0, h, max(1, h // 64)):
        for x in (0, w - 1):
            if flood[y, x] == 0:
                cv2.floodFill(flood, outside, (x, y), 2)
    group = (flood == 1) | (flood == 0)  # the group and everything it encloses
    # only what lies deep inside the group: its outline (between heads, between feet) stays the players' own
    depth = cv2.distanceTransform(group.astype(np.uint8), cv2.DIST_L2, 5)
    add = (group & (solid == 0) & (depth > k * 0.6)).astype(np.uint8)
    add = cv2.dilate(add, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k // 3 | 1, k // 3 | 1)))  # up to the players
    add = (add > 0) & group
    if image is not None and add.any():
        ground = _like_background(image, group, add, k)
        if people is not None:  # inside a player the detector found, it is the player, whatever the color
            person = cv2.resize(people.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
            ground &= ~cv2.erode(person.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        add &= ~ground
        add = cv2.morphologyEx(add.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
        count, labels, stats, _ = cv2.connectedComponentsWithStats(add.astype(np.uint8), connectivity=8)
        big = np.zeros(count, bool)
        big[1:] = stats[1:, cv2.CC_STAT_AREA] >= 0.002 * h * w  # a missed child, not a few blades of grass
        add = big[labels]
    soft = cv2.GaussianBlur(add.astype(np.float32), (0, 0), 1.5)
    return np.maximum(alpha, soft).astype(np.float32)


def _like_background(image: Image.Image, group: np.ndarray, add: np.ndarray, k: int) -> np.ndarray:
    """Which of the gaps' pixels look like what is just around the group (the grass, the field)."""
    h, w = group.shape
    lab = cv2.cvtColor(np.asarray(image.convert("RGB").resize((w, h))), cv2.COLOR_RGB2LAB).astype(np.float32)
    ring = cv2.dilate(group.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))) > 0
    ring &= ~group
    ys = np.nonzero(group.any(1))[0]
    if len(ys):  # the ground around the lower half of the group (not the trees or sky above the team)
        ring[: int((ys[0] + ys[-1]) / 2)] = False
    samples = lab[ring]
    if len(samples) < 200:
        return np.zeros_like(add)
    rng = np.random.default_rng(0)
    samples = samples[rng.choice(len(samples), min(6000, len(samples)), replace=False)]
    _, _, centers = cv2.kmeans(samples, 8, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 2,
                               cv2.KMEANS_PP_CENTERS)
    px = lab[add]
    weight = np.array([0.45, 1.0, 1.0], np.float32)  # the color counts most, the light less (shade on grass)
    d = np.sqrt((((px[:, None, :] - centers[None]) * weight) ** 2).sum(-1)).min(1)
    out = np.zeros_like(add)
    out[add] = d < 14
    return out


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
                 subject_box=sb, other_faces=other_faces, other_hands=other_hands, team=plan.team_photo)


def frame_boxes(path: Path, colors: dict[str, str] | None = None, goalie_first: bool = True,
                shape: str = "best") -> dict[str, tuple[float, float, float, float] | None]:
    """Where each crop-first choice would cut this photo (shares of it): "wide"
    (pro crop, no zoom), "crop" (zoomed in on the action) and "face"; None when
    it would keep the whole photo or finds no one. Shown on the photo before a
    look is made."""
    colors = colors or {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}
    img = images.preview_image(path, 2400)
    people, balls = detector().find(img, focus.focus_point(path, img.size), colors)
    plan = framing.choose(people, balls, img.size, goalie_first)
    W, H = img.size

    def shares(box):
        if not box or (box[2] - box[0]) * (box[3] - box[1]) >= 0.92 * W * H:  # (nearly) the whole photo
            return None
        return (max(0.0, box[0] / W), max(0.0, box[1] / H), min(1.0, box[2] / W), min(1.0, box[3] / H))
    face = None
    if plan.face_person:
        face = framing.face_box(plan.face_person, img.size, "sharp", framing.crop_box(plan, img.size, shape))
    return {"wide": shares(framing.wide_box(plan, img.size)), "crop": shares(framing.crop_box(plan, img.size, shape)),
            "face": shares(face)}


SMALL_EDGE = 1024  # px: a photo prepared for a small preview is looked at this size


def prepare_small(path: Path, edge: int = SMALL_EDGE) -> Prepared:
    """A photo prepared for a small preview (the whole-event grid): loaded, made small at once (the
    camera-size picture isn't kept), its players found and cut out at that size. Quick and light: about
    half a second and a few MB kept, so a whole event fits on any Mac."""
    photo = images.load(path)
    img = photo.image.copy()
    del photo
    img.thumbnail((edge, edge))
    colors = {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}  # (as prepare)
    people, balls = detector().find(img, focus.focus_point(path, img.size), colors)
    scene = find(img, people, balls, framing.choose(people, balls, img.size, True))
    p = Prepared(path, img, scene, None, None)
    matte = small_cutout(img, scene)
    if matte is not None:
        scene.take_in(matte)
    p._auto = (matte, scene.subject_mask)
    scene.matte = matte
    return p


def prepare(path: Path, crop: str = "none", colors: dict[str, str] | None = None,
            goalie_first: bool = True, shape: str = "best", retouch=None) -> Prepared:
    """Loads a photo (RAW in the camera's look), finds its scene and, if
    asked, crops it the photo-crops way: "crop" (pro crop, zoomed in on the
    action), "wide" (pro crop without zooming) or "face". retouch: a function
    cleaning the loaded photo first (distractions removed, see retouch.py)."""
    colors = colors or {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}
    photo = images.load(path)
    if retouch is not None:
        photo = retouch(photo)
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
        W, H = img.size
        return Prepared(path, cropped, scene.in_crop(box, img.size), photo.exif, fine,
                        box=(box[0] / W, box[1] / H, box[2] / W, box[3] / H))
    return Prepared(path, img, scene, photo.exif, photo.fine)
