"""Pass 1's measurements of one photo, all on this Mac: who is in it and where (the players, the
ball, the camera's own focus point), how sharp the main player is, their faces (eyes, Apple's face
quality score), the exposure on them, the crop on the action in every shape, and a small picture
fingerprint for finding bursts. Measured once per file and kept on disk."""

from __future__ import annotations

import hashlib
import io
import pickle
import threading
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photo_crops import focus, framing, images

VERSION = 6  # raise when a measurement changes, so files are measured again
EDGE = 1600  # the photo is looked at this size (RAW: the camera's own preview)
THUMB_EDGE = 420
TIGHT_BELOW = 0.40  # the main player shorter than this share of a tall crop: it moves in close on them
TIGHT_ROOM = (1.5, 1.4)  # room around them then (width, height multipliers)
BORDER_ROOM = 1.14  # the main player's height with room above and below, for the soft border
BORDER_MOST = 1.35  # ...when that is at most this much taller than the shape allows (beyond it, mostly border)
SHAPES = ["4:5", "9:16", "16:9", "1:1", "3:2", "best"]
FACE_FOR_EYES = 60  # px (at EDGE): smaller faces are too small to judge the eyes
EYES_CLOSED = 0.17  # eye opening (height / width of the eye outline) below this on both eyes
_lock = threading.Lock()  # the detector and Vision are used one photo at a time


def cache_key(path: Path) -> str:
    st = path.stat()
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:24]


def thumb(path: Path, dest: Path) -> tuple[int, int]:
    """A small JPEG of the photo for the gallery (RAW: the camera's built-in preview, so it is quick).
    Returns the photo's own shape (width, height) at preview size."""
    img = images.preview_image(path, THUMB_EDGE)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    img.save(tmp, "JPEG", quality=82)
    tmp.replace(dest)
    return img.size


def _exif(path: Path) -> bytes | None:
    try:
        return images.raw_exif(path) if images.is_raw(path) else Image.open(path).info.get("exif")
    except Exception:
        return None


def settings(exif: bytes | None) -> dict:
    """When it was taken (seconds, to the hundredth when the camera writes it) and the camera settings."""
    out: dict = {}
    if not exif:
        return out
    data = Image.Exif()
    try:
        data.load(exif)
    except Exception:
        return out
    sub = data.get_ifd(0x8769)
    taken = images.taken_at(exif)
    if taken:
        frac = str(sub.get(0x9291) or "").strip("\x00 ")
        t = taken.timestamp()
        if frac.isdigit():
            t += int(frac) / (10 ** len(frac))
        out["time"] = t
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    iso = sub.get(0x8827)
    out["iso"] = int(iso[0] if isinstance(iso, tuple) else iso) if iso else None
    out["shutter"] = num(sub.get(0x829A))
    out["aperture"] = num(sub.get(0x829D))
    out["focal"] = num(sub.get(0x920A))
    out["camera"] = str(data.get(0x0110) or "").strip("\x00 ")
    return out


def dhash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def detail(gray: np.ndarray, box, height: int = 256) -> float:
    """How sharp a part of the photo is, judged at a fixed size (so a small far player and a big close
    one compare fairly): the spread of the fine detail."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    H, W = gray.shape
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    part = gray[y0:y1, x0:x1]
    scale = height / part.shape[0]
    if scale < 1:  # (never enlarged: that would invent softness)
        part = cv2.resize(part, (max(8, int(part.shape[1] * scale)), height), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(part.astype(np.float32), cv2.CV_32F).var())


def _vision_faces(img: Image.Image) -> list[dict]:
    """Faces Apple's Vision finds in a (head-area) picture: their size, eye opening and face quality
    (Apple's score for picking the best frame: eyes, blur, light and pose; 0-1)."""
    try:
        import Vision
        from Foundation import NSData
    except ImportError:
        return []
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    marks = Vision.VNDetectFaceLandmarksRequest.alloc().init()
    quality = Vision.VNDetectFaceCaptureQualityRequest.alloc().init()
    ok, _ = handler.performRequests_error_([marks, quality], None)
    if not ok:
        return []
    W, H = img.size
    quals = [(q.boundingBox(), float(q.faceCaptureQuality() or 0)) for q in (quality.results() or [])]
    out = []
    for f in marks.results() or []:
        bb = f.boundingBox()
        fw, fh = bb.size.width, bb.size.height
        lm = f.landmarks()

        def opening(region):
            if region is None or region.pointCount() < 4:
                return None
            pts = region.normalizedPoints()
            p = np.array([(pts[i].x * fw * W, pts[i].y * fh * H) for i in range(region.pointCount())])
            return float(np.ptp(p[:, 1]) / max(np.ptp(p[:, 0]), 1e-6))
        eyes = [e for e in (opening(lm.leftEye()), opening(lm.rightEye())) if e is not None] if lm else []
        q = max((v for b, v in quals if abs(b.origin.x - bb.origin.x) < 0.2 and abs(b.origin.y - bb.origin.y) < 0.2),
                default=None)
        out.append({"px": fw * W, "eyes": max(eyes) if eyes else None, "quality": q,
                    "box": (bb.origin.x, 1 - bb.origin.y - fh, fw, fh)})
    return out


def faces_of(img: Image.Image, people: list) -> list[dict]:
    """The faces of the players in the play (the biggest four): each one's head area is enlarged and
    looked at closely (Vision misses small faces in a whole sports photo)."""
    out = []
    for p in sorted(people, key=lambda p: -p.height)[:4]:
        x0, y0, x1, y1 = p.box
        bw, bh = x1 - x0, y1 - y0
        box = (int(max(0, x0 - 0.1 * bw)), int(max(0, y0 - 0.05 * bh)), int(min(img.width, x1 + 0.1 * bw)),
               int(min(img.height, y0 + 0.4 * bh)))
        if box[2] - box[0] < 12 or box[3] - box[1] < 12:
            continue
        head = img.crop(box)
        s = 480 / max(head.size)
        if s > 1:
            head = head.resize((max(1, int(head.width * s)), max(1, int(head.height * s))), Image.Resampling.BICUBIC)
        found = _vision_faces(head)
        if not found:
            out.append({"person": p.box, "px": 0, "eyes": None, "quality": None, "box": None})
            continue
        f = max(found, key=lambda f: f["px"])
        scale = (box[2] - box[0]) / head.width
        fx, fy, fw, fh = f["box"]
        f["px"] *= scale
        f["box"] = (box[0] + fx * head.width * scale, box[1] + fy * head.height * scale,
                    box[0] + (fx + fw) * head.width * scale, box[1] + (fy + fh) * head.height * scale)
        f["person"] = p.box
        out.append(f)
    return out


def measure(path: Path, cache: Path) -> dict:
    """Everything pass 1 needs about one photo (kept in cache: measured once)."""
    keep = cache / f"{cache_key(path)}.pkl"
    if keep.exists():
        try:
            return pickle.loads(keep.read_bytes())
        except Exception:
            pass
    from photo_presets.scene import GOALIE, OPPONENT, TEAM, detector
    img = images.preview_image(path, EDGE)
    W, H = img.size
    arr = np.asarray(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    exif = _exif(path)
    out: dict = {"size": (W, H), **settings(exif)}
    point = focus.focus_point(path, img.size)
    with _lock:
        people, balls = detector().find(img, point, {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"})
        plan = framing.choose(people, balls, img.size, True)
        tallest = max((p.height for p in people), default=0)
        in_play = [p for p in people if p.height >= framing.MAIN_HEIGHT * tallest]
        faces = faces_of(img, in_play) if people else []
    # the main player: the framing's own, or in a crowd (many players, which the framing treats as
    # one group) the sharpest of the biggest few
    main_p = plan.subject
    if main_p is None and in_play:
        big = sorted(in_play, key=lambda p: -p.height)[:4]
        main_p = max(big, key=lambda p: detail(gray, (p.box[0], p.box[1], p.box[2], p.box[1] + 0.55 * p.height)))
    sub = main_p.box if main_p else plan.group
    out["people"] = len(in_play)
    out["subject"] = tuple(v / d for v, d in zip(sub, (W, H, W, H))) if main_p else None
    out["subject_height"] = (main_p.height / H) if main_p else 0.0
    out["group"] = tuple(v / d for v, d in zip(plan.group, (W, H, W, H))) if people else None
    out["team_photo"] = plan.team_photo
    gx0, gy0, gx1, gy1 = plan.group
    gh = gy1 - gy0
    # the ball in the play: among the players, or in the air just above them (a header, a shot)
    out["ball"] = any(gx0 - 0.2 * gh <= (b[0] + b[2]) / 2 <= gx1 + 0.2 * gh and gy0 - 0.8 * gh <= (b[1] + b[3]) / 2 <= gy1
                      for b in balls)
    out["focus_point"] = (point[0] / W, point[1] / H) if point else None
    out["focus_on_subject"] = (None if not point or not main_p else
                               any(p.box[0] <= point[0] <= p.box[2] and p.box[1] <= point[1] <= p.box[3] for p in in_play))
    # sharpness: the main player's head and upper body, and the sharpest part of the whole frame
    if main_p:
        x0, y0, x1, y1 = main_p.box
        out["sharp"] = detail(gray, (x0, y0, x1, y0 + 0.55 * (y1 - y0)))
    else:
        out["sharp"] = 0.0
    tiles = [detail(gray, (x, y, x + W / 4, y + H / 4), 200) for x in np.linspace(0, W * 0.75, 4)
             for y in np.linspace(0, H * 0.75, 4)]
    out["frame_sharp"] = float(max(tiles))
    # exposure: on the main player, and how much of the frame is pure white or black
    lum = gray.astype(np.float32) / 255
    if main_p:
        x0, y0, x1, y1 = (int(v) for v in main_p.box)
        out["subject_light"] = float(lum[max(0, y0):y1, max(0, x0):x1].mean())
    else:
        out["subject_light"] = float(lum.mean())
    out["white"] = float((lum > 0.985).mean())
    out["black"] = float((lum < 0.015).mean())
    out["light"] = float(lum.mean())
    # faces
    main = main_p.box if main_p else None
    out["faces"] = [{"px": f["px"], "eyes": f["eyes"], "quality": f["quality"],
                     "box": tuple(v / d for v, d in zip(f["box"], (W, H, W, H))) if f["box"] else None,
                     "main": f["person"] == main} for f in faces]
    # the photo's real size: how many pixels each crop really has (when an export would enlarge it)
    out["full"] = full_size(path, (W, H))
    # the crop on the action in every shape, and the no-zoom pro crop (shares of the photo)
    if people:
        # the action itself: the main player and a ball near them (in the air above them too)
        action = [main_p.box] if main_p else [plan.group]
        if main_p:
            mh = main_p.height
            mx = (main_p.box[0] + main_p.box[2]) / 2
            action += [b for b in balls if abs((b[0] + b[2]) / 2 - mx) <= 1.5 * mh
                       and main_p.box[1] - 1.2 * mh <= (b[1] + b[3]) / 2 <= main_p.box[3]]
        # the crop maths at the photo's real size (its smallest crop is in real pixels)
        k = out["full"][0] / W
        sc = lambda b: tuple(v * k for v in b)
        big = (round(W * k), round(H * k))
        fplan = framing.Plan(_scaled(plan.subject, k), sc(plan.group), plan.reason, plan.team_photo)
        act = sc(framing.union(action))

        # the player on the ball, when it isn't the main player: the crop holds them both
        core = main_p.box if main_p else plan.group
        if main_p and balls:
            near = lambda bx, p: (p.box[0] - 0.3 * p.height <= (bx[0] + bx[2]) / 2 <= p.box[2] + 0.3 * p.height
                                  and p.box[1] <= (bx[1] + bx[3]) / 2 <= p.box[3] + 0.15 * p.height)
            if not any(near(bx, main_p) for bx in balls):
                on_ball = [p for p in in_play if p is not main_p and p.height >= 0.75 * main_p.height
                           and any(near(bx, p) for bx in balls)]
                if on_ball:
                    q = min(on_ball, key=lambda p: abs(p.center[0] - main_p.center[0]))
                    core = framing.union([main_p.box, q.box] + [bx for bx in balls if near(bx, q)])
        core = sc(core)

        def shaped(s):
            box = framing.crop_box(fplan, big, s)
            gw, gh = fplan.group[2] - fplan.group[0], fplan.group[3] - fplan.group[1]
            # a shape too narrow (or short) for the whole group: centered on the action, not the
            # middle of the group (which can be empty grass between two clusters of players)
            if s in framing.ASPECTS and ((box[2] - box[0]) < 0.97 * gw or (box[3] - box[1]) < 0.97 * gh):
                a = framing.ASPECTS[s]
                box = framing.fit(act, big, a, framing.PORTRAIT_ROOM if a < 1 else framing.LANDSCAPE_ROOM,
                                  framing.MIN_CROP_SHORT)
            # the main player small in a tall or square shape (the framing held players nearby who
            # aren't in the moment with them): in close on the main player and whoever they're in it with
            a = framing.ASPECTS.get(s)
            if a and a <= 1 and main_p and not plan.team_photo and (core[3] - core[1]) < TIGHT_BELOW * (box[3] - box[1]):
                mb, mh = sc(main_p.box), main_p.height * k
                with_them = [sc(p.box) for p in in_play if p is not main_p and p.height >= 0.75 * main_p.height
                             and framing._gap(p.box, main_p.box) < 0.25 * main_p.height]
                box = framing.fit(framing.union([act, core, mb] + with_them), big, a, TIGHT_ROOM, framing.MIN_CROP_SHORT)
            if s in framing.ASPECTS:
                box = clean_edges(box, big, [sc(p.box) for p in people if p.height >= 0.45 * tallest],
                                  act, core, plan.team_photo)
            return tuple(v / d for v, d in zip(box, (*big, *big)))
        out["crops"] = {s: shaped(s) for s in SHAPES}
        # a team photo too wide for a tall shape: the whole team is kept (on a soft border) when made
        gw, gh = (plan.group[2] - plan.group[0]) * k, (plan.group[3] - plan.group[1]) * k
        out["team_fit"] = {s: bool(plan.team_photo and gw / max(gh, 1) > framing.ASPECTS[s] * 1.02)
                           for s in SHAPES if s in framing.ASPECTS}
        # a photo too narrow for a shape to hold the main player with room above and below (a tall
        # screenshot, a narrow crop): the player whole, with room, on a soft border, never trimmed
        out["border"] = {}
        need = (core[3] - core[1]) * BORDER_ROOM
        for s, a in framing.ASPECTS.items():
            if main_p and not plan.team_photo and big[0] / a < need <= min(big[1], BORDER_MOST * big[0] / a):
                top = min(max(core[1] - 0.09 * need, 0.0), big[1] - need)
                out["border"][s] = (0.0, top / big[1], 1.0, (top + need) / big[1])
        out["crops"]["wide"] = tuple(v / d for v, d in zip(framing.wide_box(fplan, big), (*big, *big)))
    else:
        out["crops"] = {}
    out["hash"] = dhash(gray)
    cache.mkdir(parents=True, exist_ok=True)
    tmp = keep.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(out))
    tmp.replace(keep)
    return out


def clean_edges(box, size, people, action, main, team=False):
    """The crop moved (or widened a little) so its edges cut through no one, with the main player as
    near the middle as that allows and the action (the main player and the ball) always inside.
    A person half in the frame at the edge is what makes a crop look accidental."""
    W, H = size
    x0, y0, x1, y1 = box
    cw0, ch0 = x1 - x0, y1 - y0
    tall = max((p[3] - p[1] for p in people), default=1) or 1
    mcx, mcy = (main[0] + main[2]) / 2, (main[1] + main[3]) / 2
    best, best_score = box, None
    for grow in (1.0, 1.08, 1.16, 1.25, 1.35):
        cw, ch = cw0 * grow, ch0 * grow
        if cw > W + 0.5 or ch > H + 0.5:
            break
        m = 0.04 * cw  # room around the main player, who is always fully in
        lo_x, hi_x = max(0.0, main[2] + m - cw), min(W - cw, main[0] - m)
        lo_y, hi_y = max(0.0, main[3] + 0.02 * ch - ch), min(H - ch, main[1] - 0.06 * ch)
        if lo_x > hi_x:
            lo_x = hi_x = min(max(mcx - cw / 2, 0), W - cw)
        if lo_y > hi_y:
            lo_y = hi_y = min(max(mcy - ch / 2, 0), H - ch)
        for left in np.linspace(lo_x, hi_x, 17):
            for top in np.linspace(lo_y, hi_y, 9):
                r = left + cw, top + ch
                cut = 0.0
                for p in people:
                    pw, ph = p[2] - p[0], p[3] - p[1]
                    vx = max(0.0, min(p[2], r[0]) - max(p[0], left)) / max(pw, 1)
                    vy = max(0.0, min(p[3], r[1]) - max(p[1], top)) / max(ph, 1)
                    seen = vx * min(1.0, vy / 0.6)  # (feet cut off at the bottom is fine; a body sliced is not)
                    if 0.012 < seen < 0.92:
                        cut += (ph / tall) ** 1.5 * (1.0 - 0.6 * abs(seen - 0.5))
                # the action (the ball near them) in the frame is a plus, not a must
                ball_out = 0.0 if (action[0] >= left and action[2] <= r[0] and action[1] >= top and action[3] <= r[1]) else 0.25
                off = abs(mcx - (left + cw / 2)) / cw + 0.4 * abs(mcy - (top + ch * 0.48)) / ch
                score = 2.0 * cut + (0.3 if team else 1.2) * off + 0.5 * (grow - 1.0) + ball_out
                if best_score is None or score < best_score - 1e-9:
                    best, best_score = (round(left), round(top), round(left + cw), round(top + ch)), score
    return best


def full_size(path: Path, shown: tuple[int, int]) -> tuple[int, int]:
    """The photo's real pixel size, the right way up (the same shape as the preview shown)."""
    try:
        if images.is_raw(path):
            import rawpy
            with rawpy.imread(str(path)) as raw:
                w, h = raw.sizes.width, raw.sizes.height
        else:
            with Image.open(path) as im:
                w, h = im.size
    except Exception:
        return shown
    return (w, h) if (w >= h) == (shown[0] >= shown[1]) else (h, w)


def _scaled(person, k: float):
    """A copy of a detected person with their box at k times the size (for the crop maths)."""
    if person is None:
        return None
    import copy
    p = copy.copy(person)
    p.box = tuple(v * k for v in person.box)
    if person.head:
        p.head = (person.head[0] * k, person.head[1] * k, person.head[2] * k)
    return p


def taken_from_name(path: Path) -> float | None:
    """The file's own date when the camera wrote none (a copy, a screenshot)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def when(m: dict, path: Path) -> float:
    return m.get("time") or taken_from_name(path) or datetime.now().timestamp()
