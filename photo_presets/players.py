"""Finding one player in every photo of a game, and their best shots.

You click your player once. Everyone in every photo is looked at (once, then
remembered) for three things:

- their face: a free face-recognition model on this Mac (OpenCV's YuNet to find
  faces, SFace to compare them), when the face is big enough to tell;
- their jersey number: read with the Mac's own text reading (Apple Vision);
- their kit: the colors of their shirt, so a player of the other team is never
  taken for them.

A matching number or face makes it sure; a different number, or a clearly
different face, rules it out; the same kit with nothing against it makes it
likely. Of the photos with them, the best are those where they are sharp,
big, facing the camera and near the ball; of a burst (photos a moment apart),
only the best one is kept.
"""

from __future__ import annotations

import hashlib
import pickle
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photo_crops import images

CACHE = Path.home() / ".cache" / "photo-crops"
MODELS = {
    "face_detection_yunet_2023mar.onnx": "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"
EDGE = 2048  # px: each photo is looked at this size
SURE_FACE = 0.58  # SFace likeness at or above this: sure (measured on a youth game; kids' faces are hard)
MAYBE_FACE = 0.40  # between the two: asked ("Is this your player?")
FACE_MIN = 36  # px: a face smaller than this is not compared
SAME_KIT = 0.55  # shirt color likeness (0-1) needed at all
BURST = 1.5  # s: photos this close together are one moment
VERSION = 2  # what is remembered about a photo changes with this


@dataclass
class Sighting:
    """One person in one photo."""
    box: tuple[float, float, float, float]  # shares of the photo
    face: np.ndarray | None = None  # SFace features
    face_px: int = 0
    number: str | None = None
    kit: np.ndarray | None = None  # shirt color (hue-saturation histogram)
    sharp: float = 0.0
    facing: bool = False
    ball: bool = False
    kind: str = ""


@dataclass
class Scan:
    path: str
    taken: datetime | None
    size: tuple[int, int]
    people: list[Sighting] = field(default_factory=list)
    digest: bytes = b""  # a tiny picture of the whole photo, for telling near-duplicates


def _model(name: str) -> str:
    p = CACHE / name
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(ZOO + MODELS[name], p)
    return str(p)


_det = _rec = None


def _faces(arr: np.ndarray) -> np.ndarray:
    """Faces in an RGB image: rows of x, y, w, h, 5 landmarks (10), score."""
    global _det
    h, w = arr.shape[:2]
    if _det is None:
        _det = cv2.FaceDetectorYN.create(_model("face_detection_yunet_2023mar.onnx"), "", (w, h), 0.7, 0.3, 5000)
    _det.setInputSize((w, h))
    _, faces = _det.detect(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return faces if faces is not None else np.zeros((0, 15), np.float32)


def _features(arr: np.ndarray, face: np.ndarray) -> np.ndarray:
    global _rec
    if _rec is None:
        _rec = cv2.FaceRecognizerSF.create(_model("face_recognition_sface_2021dec.onnx"), "")
    aligned = _rec.alignCrop(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), face)
    return _rec.feature(aligned).flatten()


def _numbers(crop: np.ndarray) -> list[str]:
    """Jersey numbers (1 or 2 digits) read in a person's picture."""
    try:
        import Vision
        from Foundation import NSData
    except ImportError:
        return []
    import io
    h, w = crop.shape[:2]
    if h < 40:
        return []
    scale = 600 / h
    img = Image.fromarray(crop).resize((max(1, int(w * scale)), 600))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    ok, _ = handler.performRequests_error_([req], None)
    if not ok:
        return []
    out = []
    for ob in req.results() or []:
        for cand in ob.topCandidates_(2):
            t = str(cand.string()).strip()
            if re.fullmatch(r"\d{1,2}", t) and float(cand.confidence()) > 0.4:
                out.append(t.lstrip("0") or "0")
    return out


def _kit(arr: np.ndarray, mask: np.ndarray | None, box: tuple[int, int, int, int]) -> np.ndarray | None:
    x0, y0, x1, y1 = box
    h = y1 - y0
    t0, t1 = y0 + int(0.2 * h), y0 + int(0.5 * h)  # the shirt
    part = arr[t0:t1, x0:x1]
    if part.size < 300:
        return None
    hsv = cv2.cvtColor(part, cv2.COLOR_RGB2HSV)
    m = None
    if mask is not None:
        m = mask[t0:t1, x0:x1].astype(np.uint8)
        if m.sum() < 50:
            m = None
    hist = cv2.calcHist([hsv], [0, 1, 2], m, [12, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, None).flatten()


def scan(path: Path) -> Scan:
    """Everyone in the photo, remembered (in ~/.cache/photo-crops/players) so a game is looked at once."""
    st = path.stat()
    key = hashlib.sha1(f"{VERSION}:{path}:{st.st_size}:{st.st_mtime}".encode()).hexdigest()
    store = CACHE / "players" / f"{key}.pkl"
    if store.exists():
        try:
            return pickle.loads(store.read_bytes())
        except Exception:
            pass
    from photo_presets.scene import GOALIE, OPPONENT, TEAM, detector
    img = images.preview_image(path, EDGE)
    arr = np.asarray(img.convert("RGB"))
    H, W = arr.shape[:2]
    found, balls = detector().find(img, None, {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"})
    faces = _faces(arr)
    exif = None
    try:
        exif = images.raw_exif(path) if images.is_raw(path) else Image.open(path).info.get("exif")
    except Exception:
        pass
    out = Scan(str(path), images.taken_at(exif), (W, H))
    small = cv2.resize(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY), (16, 12), interpolation=cv2.INTER_AREA)
    out.digest = small.tobytes()
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    for p in found:
        x0, y0, x1, y1 = (int(v) for v in p.box)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 - x0 < 8 or y1 - y0 < 16:
            continue
        mask = None
        if p.mask is not None:
            mask = cv2.resize(p.mask.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
        s = Sighting((x0 / W, y0 / H, x1 / W, y1 / H), kind=p.kind)
        upper = gray[y0:y0 + (y1 - y0) // 2, x0:x1]
        s.sharp = float(cv2.Laplacian(upper, cv2.CV_32F).var()) if upper.size else 0.0
        # the face inside their head area
        for f in faces:
            fx, fy, fw, fh = f[:4]
            cx, cy = fx + fw / 2, fy + fh / 2
            if x0 <= cx <= x1 and y0 <= cy <= y0 + (y1 - y0) * 0.4:
                if fw > s.face_px:
                    s.face_px = int(fw)
                    s.facing = True
                    if fw >= FACE_MIN:
                        s.face = _features(arr, f)
        nums = _numbers(arr[y0:y1, x0:x1])
        s.number = max(set(nums), key=nums.count) if nums else None
        s.kit = _kit(arr, mask, (x0, y0, x1, y1))
        reach = (y1 - y0) * 0.8
        s.ball = any(abs((b[0] + b[2]) / 2 - (x0 + x1) / 2) < reach and abs((b[1] + b[3]) / 2 - (y0 + y1) / 2) < reach * 1.2
                     for b in balls)
        out.people.append(s)
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_bytes(pickle.dumps(out))
    except OSError:
        pass
    return out


def at(sc: Scan, x: float, y: float) -> Sighting | None:
    """The person at x, y (shares of the photo): whose box holds the point (the smallest if several)."""
    inside = [s for s in sc.people if s.box[0] <= x <= s.box[2] and s.box[1] <= y <= s.box[3]]
    if not inside:
        return None
    return min(inside, key=lambda s: (s.box[2] - s.box[0]) * (s.box[3] - s.box[1]))


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def likeness(target: Sighting, s: Sighting, yes: list[np.ndarray] = (), no: list[np.ndarray] = ()) -> tuple[str, float, str]:
    """Is s the player? ("sure" | "maybe" | "no", how close, why). yes: faces you said are them,
    no: faces you said are not (kids' faces at a distance look alike, so close calls are asked)."""
    kit = float(cv2.compareHist(target.kit, s.kit, cv2.HISTCMP_CORREL)) if target.kit is not None and s.kit is not None else 0.5
    if kit < SAME_KIT:
        return "no", 0.0, "another kit"
    if target.number and s.number:
        if target.number == s.number:
            return "sure", 0.97, f"number {s.number}"
        return "no", 0.0, f"number {s.number}, not {target.number}"
    if target.face is None or s.face is None:
        return "no", 0.0, "face not seen"
    pos = max([_cos(target.face, s.face)] + [_cos(f, s.face) for f in yes])
    neg = max([_cos(f, s.face) for f in no], default=-1.0)
    if pos >= SURE_FACE and pos >= neg + 0.05:
        return "sure", pos, "face"
    if pos >= MAYBE_FACE and pos > neg:
        return "maybe", pos, "face, a little like them"
    return "no", pos, "another face"


def quality(sc: Scan, s: Sighting, sharp_ref: float) -> float:
    """How good a shot of them it is (0-1): sharp, big in the frame, face to the camera, the ball near."""
    big = min(1.0, (s.box[3] - s.box[1]) / 0.6)
    sharp = min(1.0, s.sharp / max(sharp_ref, 1e-3))
    return 0.45 * sharp + 0.25 * big + 0.18 * float(s.facing) + 0.12 * float(s.ball)


def same_moment(a: Scan, b: Scan) -> bool:
    if a.taken and b.taken:
        return abs((a.taken - b.taken).total_seconds()) <= BURST
    da, db = np.frombuffer(a.digest, np.uint8).astype(np.float32), np.frombuffer(b.digest, np.uint8).astype(np.float32)
    return len(da) == len(db) and float(np.abs(da - db).mean()) < 6


def find(scans: list[Scan], target: Sighting, yes: list[np.ndarray] = (), no: list[np.ndarray] = ()) -> list[dict]:
    """Every photo with the player, sure or to ask about:
    [{"path", "person", "box", "status", "score", "why", "quality", "best"}], best first;
    "best" is False for the lesser photos of a burst (of the sure ones)."""
    hits = []
    for sc in scans:
        rated = [(likeness(target, s, yes, no), i, s) for i, s in enumerate(sc.people)]
        rated = [r for r in rated if r[0][0] != "no"]
        if not rated:
            continue
        (status, score, why), i, s = max(rated, key=lambda r: (r[0][0] == "sure", r[0][1]))
        hits.append({"scan": sc, "person": i, "sighting": s, "status": status, "score": score, "why": why, "best": False})
    if not hits:
        return []
    ref = float(np.percentile([h["sighting"].sharp for h in hits], 90))
    for h in hits:
        h["quality"] = quality(h["scan"], h["sighting"], ref)
    sure = sorted((h for h in hits if h["status"] == "sure"), key=lambda h: (h["scan"].taken or datetime.min, h["scan"].path))
    group = []
    for h in sure:  # bursts: photos a moment apart are one moment; only its best is "best"
        if group and not same_moment(group[-1]["scan"], h["scan"]):
            _mark(group)
            group = []
        group.append(h)
    _mark(group)
    hits.sort(key=lambda h: (h["status"] != "sure", not h["best"], -h["quality"]))
    return [{"path": h["scan"].path, "person": h["person"], "box": h["sighting"].box, "status": h["status"],
             "score": round(h["score"], 2), "why": h["why"], "quality": round(h["quality"], 2), "best": h["best"]}
            for h in hits]


def _mark(group: list[dict]) -> None:
    if not group:
        return
    top = max(group, key=lambda h: h["quality"])
    for h in group:
        h["best"] = h is top
