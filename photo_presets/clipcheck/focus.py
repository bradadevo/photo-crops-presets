"""Was the subject sharp? For a video: who you were following, how sharp they are next to the sharpest
part of the picture, moment by moment, and, when they aren't sharp, why: the focus sat behind or in
front of them, the whole picture went soft, they moved too fast, or they came too close.

Sharpness is measured as edge width: at every strong edge, how many pixels the change from dark to
light takes. An edge in focus takes 2-4 pixels; out of focus it spreads wider. Unlike a "how much
detail" measure, it doesn't mistake a plain dark shirt for a blurry one. The subject is compared with
the rest of the same frame, so the camera, the resolution and the light don't matter.

Measured once per file (`sample`, the slow part: people found with the app's own YOLO model, edges
measured at full resolution); who the subject is can then be changed without measuring again
(`analyze`)."""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field

import cv2
import numpy as np

PER_SECOND = 4  # samples a second (fewer on long clips)
MOST_SAMPLES = 240
DETECT_EDGE = 1280  # people and objects are found on a copy this wide
MAXW = 24  # widest edge measured (px either side)
MIN_CONTRAST = 24  # (0-255) fainter edges are left out: grain would count
MIN_EDGES = 30  # edge points needed to judge a person or a patch of the picture
ROWS = 6  # the picture is judged in tiles, 6 rows of them
SOFT = 1.6  # the subject's edges this many times wider than the sharpest part: out of focus
SHARP = 1.35  # under this: as sharp as anything in the picture
FRAME_SOFT = 1.6  # the sharpest part this many times wider than usual: the whole picture is soft
FAST_SUBJECT = 20.0  # % of the frame width a second: the subject moves fast across the frame
TOO_CLOSE = 0.9  # the subject taller than this share of the frame
MIN_RUN = 0.5  # seconds
SHARP_THING = 1.6  # a car, a truck or another person this close to the sharpest part: it was in focus
JOIN = 0.8  # seconds: soft stretches closer than this are one

PERSON = 0
COCO_NAMES = {2: "car", 3: "motorbike", 5: "bus", 7: "truck", 9: "traffic light", 11: "stop sign", 12: "parking meter",
              13: "bench", 32: "ball", 56: "chair", 58: "potted plant", 60: "table"}


@dataclass
class Thing:
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 as shares of the frame
    width: float | None  # edge width (px); None: too few edges to say
    edges: int
    name: str = "person"


@dataclass
class Sample:
    t: float
    people: list[Thing]
    objects: list[Thing]
    tiles: list[list[float | None]]  # edge width of each tile (people left out); None: nothing to measure
    best: float | None  # the sharpest part of the picture (people left out)


@dataclass
class Sampled:
    samples: list[Sample]
    width: int
    height: int
    duration: float


def _trimmed(w: np.ndarray) -> float:
    """How wide the crisper edges are (the 10th to 40th percentile): anything in focus has some crisp
    edges, even a truck with smooth shiny panels; anything out of focus has none."""
    lo, hi = np.percentile(w, [10, 40])
    mid = w[(w >= lo) & (w <= hi)]
    return float(mid.mean()) if len(mid) else float(np.median(w))


def edge_widths(g: np.ndarray, most: int = 150_000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(y, x, width) of strong edges in a grey picture: the distance between the darkest and the
    brightest point either side of each edge, across the edge."""
    g = cv2.GaussianBlur(g.astype(np.float32), (0, 0), 0.6)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    h, w = g.shape
    out_y, out_x, out_w = [], [], []
    off = np.arange(-MAXW, MAXW + 1)
    c = MAXW
    for axis, ga, gb in ((1, gx, gy), (0, gy, gx)):
        a = np.abs(ga)
        peak = (a >= np.roll(a, 1, axis)) & (a >= np.roll(a, -1, axis))
        cand = (a > 1.5 * np.abs(gb)) & peak & (mag > 4 * MIN_CONTRAST / 3)
        cand[:MAXW] = cand[-MAXW:] = False
        cand[:, :MAXW] = cand[:, -MAXW:] = False
        ys, xs = np.nonzero(cand)
        if len(ys) > most // 2:
            k = np.random.default_rng(len(ys)).choice(len(ys), most // 2, replace=False)
            ys, xs = ys[k], xs[k]
        if not len(ys):
            continue
        prof = g[ys[:, None], xs[:, None] + off] if axis == 1 else g[ys[:, None] + off, xs[:, None]]
        prof = prof * np.sign(ga[ys, xs])[:, None]  # (every edge rising)
        d = np.diff(prof, axis=1)
        up = d[:, c:] > 0.5
        right = np.where(up.all(1), MAXW, np.argmin(up, axis=1))
        down = d[:, :c][:, ::-1] > 0.5
        left = np.where(down.all(1), MAXW, np.argmin(down, axis=1))
        n = np.arange(len(ys))
        ok = (prof[n, c + right] - prof[n, c - left] > MIN_CONTRAST) & (left < MAXW) & (right < MAXW)
        out_y.append(ys[ok]); out_x.append(xs[ok]); out_w.append((left + right)[ok].astype(np.float32))
    if not out_y:
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0, np.float32)
    return np.concatenate(out_y), np.concatenate(out_x), np.concatenate(out_w)


def _frames(path: str, width: int, height: int, duration: float):
    """(seconds, grey frame) at PER_SECOND (fewer on long clips), at full resolution."""
    rate = min(PER_SECOND, MOST_SAMPLES / max(duration, 0.1))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={rate:.4f}", "-pix_fmt", "gray",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    i = 0
    try:
        while True:
            buf = proc.stdout.read(width * height)
            if len(buf) < width * height:
                break
            yield (i + 0.5) / rate, np.frombuffer(buf, np.uint8).reshape(height, width)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def _model():
    from photo_presets.scene import detector  # (the model the Looks tab already loads: never two in memory)
    d = detector()
    seg, _ = d._models()
    return seg, d._device


def sample(path: str, width: int, height: int, duration: float, progress=None) -> Sampled:
    """The slow part, done once per file: people and objects in each sampled frame, and how sharp
    each of them and each patch of the picture is."""
    seg, device = _model()
    cols = max(1, round(ROWS * width / height))
    th, tw = height / ROWS, width / cols
    erode = np.ones((max(3, width // 640) * 2 + 1,) * 2, np.uint8)
    out = []
    total = max(1, int(min(PER_SECOND * duration, MOST_SAMPLES)))
    for t, g in _frames(path, width, height, duration):
        scale = DETECT_EDGE / width
        small = cv2.cvtColor(cv2.resize(g, (DETECT_EDGE, max(1, round(height * scale))), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_GRAY2RGB)
        r = seg.predict(small, conf=0.3, classes=[PERSON, *COCO_NAMES], retina_masks=True, verbose=False,
                        device=device)[0]
        ys, xs, ws = edge_widths(g)
        anyone = np.zeros(small.shape[:2], np.uint8)
        found = []
        if r.boxes is not None and r.masks is not None:
            masks = r.masks.data.cpu().numpy() > 0.5
            for box, cls, m in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int), masks):
                if int(cls) == PERSON:
                    anyone |= m.astype(np.uint8)
                found.append((box / scale, int(cls), cv2.erode(m.astype(np.uint8), erode)))
        sy, sx = (ys * scale).astype(int).clip(0, small.shape[0] - 1), (xs * scale).astype(int).clip(0, small.shape[1] - 1)
        people, objects = [], []
        for box, cls, m in found:
            inside = m[sy, sx] > 0
            n = int(inside.sum())
            thing = Thing(tuple(float(v) for v in (box[0] / width, box[1] / height, box[2] / width, box[3] / height)),
                          _trimmed(ws[inside]) if n >= MIN_EDGES else None, n,
                          "person" if cls == PERSON else COCO_NAMES.get(cls, "object"))
            (people if cls == PERSON else objects).append(thing)
        near_people = cv2.dilate(anyone, np.ones((15, 15), np.uint8))[sy, sx] > 0
        tiles = [[None] * cols for _ in range(ROWS)]
        free = ~near_people
        ty, tx = (ys[free] / th).astype(int).clip(0, ROWS - 1), (xs[free] / tw).astype(int).clip(0, cols - 1)
        fw = ws[free]
        for row in range(ROWS):
            for col in range(cols):
                sel = fw[(ty == row) & (tx == col)]
                if len(sel) >= MIN_EDGES:
                    tiles[row][col] = _trimmed(sel)
        vals = sorted(v for row in tiles for v in row if v is not None)
        out.append(Sample(round(t, 3), people, objects, tiles, float(np.mean(vals[:3])) if vals else None))
        if progress:
            progress(min(1.0, len(out) / total))
    return Sampled(out, width, height, duration)


# Who the subject is ---------------------------------------------------------------------------------

def _iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def tracks(s: Sampled) -> list[list[tuple[int, int]]]:
    """Each person followed from sample to sample: lists of (sample index, person index)."""
    done: list[list[tuple[int, int]]] = []
    live: list[list[tuple[int, int]]] = []
    for i, smp in enumerate(s.samples):
        pairs = []
        for k, tr in enumerate(live):
            j0, p0 = tr[-1]
            if smp.t - s.samples[j0].t > 1.0:
                continue
            a = s.samples[j0].people[p0].box
            for p, person in enumerate(smp.people):
                b = person.box
                ha, hb = a[3] - a[1], b[3] - b[1]
                if not 0.6 < hb / max(ha, 1e-6) < 1.7:
                    continue
                dist = math.hypot((a[0] + a[2] - b[0] - b[2]) / 2 * s.width / s.height, (a[1] + a[3] - b[1] - b[3]) / 2)
                score = _iou(a, b) + max(0.0, 1 - dist / (0.6 * max(ha, hb)))
                if score > 0.3:
                    pairs.append((score, k, p))
        took_track, took_person = set(), set()
        for score, k, p in sorted(pairs, reverse=True):  # (the best matches first; each used once)
            if k in took_track or p in took_person:
                continue
            live[k].append((i, p))
            took_track.add(k)
            took_person.add(p)
        for p in range(len(smp.people)):
            if p not in took_person:
                live.append([(i, p)])
        still = []
        for tr in live:
            (still if smp.t - s.samples[tr[-1][0]].t <= 1.0 else done).append(tr)
        live = still
    return done + live


def _weight(s: Sampled, tr) -> float:
    total = 0.0
    for i, p in tr:
        b = s.samples[i].people[p].box
        centre = 1 - min(1.0, abs((b[0] + b[2]) / 2 - 0.5) * 1.4)
        total += (b[3] - b[1]) * (0.3 + centre)
    return total


def pick_track(s: Sampled, pick: dict | None = None):
    """The subject: the person you picked (a time and a point on the picture), else the one the camera
    followed (in the frame longest, biggest and nearest the middle)."""
    trs = [tr for tr in tracks(s) if len(tr) >= 2]
    if not trs:
        return None
    if pick:
        i = min(range(len(s.samples)), key=lambda j: abs(s.samples[j].t - float(pick.get("t", 0))))
        x, y = float(pick.get("x", 0.5)), float(pick.get("y", 0.5))
        hits = [(p, b) for p, b in enumerate(q.box for q in s.samples[i].people) if b[0] <= x <= b[2] and b[1] <= y <= b[3]]
        if hits:
            p = min(hits, key=lambda h: (h[1][2] - h[1][0]) * (h[1][3] - h[1][1]))[0]
            for tr in tracks(s):
                if (i, p) in tr:
                    return tr
    return max(trs, key=lambda tr: _weight(s, tr))


# Why it isn't sharp ---------------------------------------------------------------------------------

@dataclass
class Point:
    t: float
    ratio: float | None  # the subject's edge width over the sharpest part's: 1 is as sharp as anything
    state: str  # sharp, slightly_soft, soft, frame_soft, unknown
    where: str = ""  # behind, front, same (the sharp part, compared with the subject)
    box: tuple | None = None
    sharp_boxes: list = field(default_factory=list)
    named: str = ""  # a thing in the picture that was sharp instead ("truck")
    speed: float = 0.0  # the subject across the frame (% width a second)


def _where(s: Sampled, smp: Sample, box) -> tuple[str, list]:
    cols = len(smp.tiles[0])
    best = smp.best
    sharp = [(r, c) for r in range(ROWS) for c in range(cols)
             if smp.tiles[r][c] is not None and smp.tiles[r][c] <= best * 1.2]
    boxes = [(c / cols, r / ROWS, (c + 1) / cols, (r + 1) / ROWS) for r, c in sharp]
    if not sharp:
        return "", boxes
    row = float(np.mean([(r + 0.5) / ROWS for r, _ in sharp]))
    tall = box[3] - box[1]
    if box[3] >= 0.97:  # (their feet are out of the frame: they're near; the ground at the bottom is their distance)
        return ("behind" if row < box[1] + 0.6 * tall else "same"), boxes
    feet = box[3]
    return ("behind" if row < feet - 0.25 * tall else "front" if row > feet + 0.05 else "same"), boxes


def analyze(s: Sampled, pick: dict | None = None, camera_speed=None) -> dict:
    """The subject's sharpness over time, the stretches where it was missed and why, and what to change."""
    tr = pick_track(s, pick)
    if tr is None:
        return {"subject": None, "points": [], "runs": [], "finding": "", "advice": [], "habits": []}
    bests = [x.best for x in s.samples if x.best]
    usual = float(np.median(bests)) if bests else None
    points = []
    prev = None
    for i, p in tr:
        smp = s.samples[i]
        who = smp.people[p]
        ratio = who.width / smp.best if who.width and smp.best else None
        speed = 0.0
        if prev is not None:
            pb, pt = prev
            dt = max(1e-3, smp.t - pt)
            speed = abs((who.box[0] + who.box[2] - pb[0] - pb[2]) / 2) / dt * 100
        prev = (who.box, smp.t)
        if ratio is None:
            state = "unknown"
        elif usual and smp.best > FRAME_SOFT * usual:
            state = "frame_soft"
        elif ratio >= SOFT:
            state = "soft"
        elif ratio >= SHARP:
            state = "slightly_soft"
        else:
            state = "sharp"
        where, boxes = _where(s, smp, who.box) if smp.best else ("", [])
        named = ""
        if state == "soft":
            sharp_enough = lambda o: o.width and o.edges >= 60 and o.width <= smp.best * SHARP_THING and o.width * 1.4 <= who.width
            cand = [o for o in smp.objects if sharp_enough(o)]
            others = [q for k, q in enumerate(smp.people) if k != p and sharp_enough(q)]
            if cand:
                named = max(cand, key=lambda o: (o.box[2] - o.box[0]) * (o.box[3] - o.box[1])).name
            elif others:
                named = "another person"
        points.append(Point(smp.t, round(ratio, 2) if ratio else None, state, where, who.box, boxes, named, round(speed, 1)))
    step = (s.samples[1].t - s.samples[0].t) if len(s.samples) > 1 else 0.25
    runs = _runs(points, step, s, camera_speed)
    first, last = points[0].t, points[-1].t
    return {"subject": {"from": first, "to": last, "box": points[len(points) // 2].box},
            "points": [p.__dict__ for p in points], "runs": runs, "step": step,
            **_explain(points, runs, s, step)}


def _runs(points: list[Point], step: float, s: Sampled, camera_speed) -> list[dict]:
    out = []
    cur = None
    for p in points:  # (a moment of near-sharp inside a soft stretch doesn't split it)
        kind = "focus" if p.state == "soft" else "frame" if p.state == "frame_soft" else None
        if not kind:
            continue
        if cur and cur["kind"] == kind and p.t - cur["pts"][-1].t <= max(step * 2.5, JOIN):
            cur["pts"].append(p)
            continue
        if cur:
            out.append(cur)
        cur = {"kind": kind, "pts": [p]}
    if cur:
        out.append(cur)
    runs = []
    for r in out:
        pts = r["pts"]
        start, end = pts[0].t - step / 2, min(s.duration, pts[-1].t + step / 2)
        if end - start < MIN_RUN:
            continue
        ratios = [p.ratio for p in pts if p.ratio]
        ratio = float(np.median(ratios)) if ratios else None
        tall = [p.box[3] - p.box[1] for p in pts]
        if r["kind"] == "focus":
            wheres = [p.where for p in pts if p.where]
            where = max(set(wheres), key=wheres.count) if wheres else ""
            named = [p.named for p in pts if p.named]
            named = max(set(named), key=named.count) if named else ""
            speed = float(np.median([p.speed for p in pts]))
            coming = tall[-1] > tall[0] * 1.25
            going = tall[-1] < tall[0] / 1.25
            worse = len(ratios) >= 3 and ratios[-1] > ratios[0] * 1.3
            if max(tall) >= TOO_CLOSE and where != "behind":
                cause = "close"
            elif where == "same" and speed >= FAST_SUBJECT:
                cause = "motion"
            elif where == "front":
                cause = "front"
            elif where == "behind":
                cause = "behind"
            else:
                cause = "motion" if speed >= FAST_SUBJECT else "elsewhere"
            runs.append({"kind": "focus", "start": round(start, 2), "end": round(end, 2), "ratio": ratio, "cause": cause,
                         "named": named, "coming": coming and worse, "going": going and worse, "speed": speed})
        else:
            fast = camera_speed is not None and np.median([camera_speed(p.t) for p in pts]) >= 12
            runs.append({"kind": "frame", "start": round(start, 2), "end": round(end, 2), "ratio": ratio,
                         "cause": "swing" if fast else "hunting", "named": "", "coming": False, "going": False, "speed": 0})
    return runs


def clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _times(x: float) -> str:
    return f"{x:.1f}x" if x < 10 else f"{x:.0f}x"


def run_text(r: dict) -> tuple[str, str]:
    """(label, detail) for one stretch where the subject wasn't sharp."""
    if r["kind"] == "frame":
        return ("Whole picture soft",
                "Everything goes soft here, your subject too: the camera swung fast." if r["cause"] == "swing" else
                "Everything goes soft here, your subject too: the lens lost focus and searched for it (hunting).")
    x = _times(r["ratio"]) if r["ratio"] else "much"
    named = f" (the {r['named']} was sharp)" if r["named"] and r["named"] != "another person" else \
        " (someone else was sharp)" if r["named"] else ""
    move = " and didn't follow them as they came closer" if r["coming"] else \
        " and didn't follow them as they moved away" if r["going"] else ""
    detail = {
        "behind": f"Your subject's edges are {x} wider than the sharpest part of the picture: the focus sat behind them{named}{move}.",
        "front": f"Your subject's edges are {x} wider than the sharpest part of the picture: the focus sat in front of them{named}{move}.",
        "elsewhere": f"Your subject's edges are {x} wider than the sharpest part of the picture: the focus was on something else{named}{move}.",
        "motion": f"Your subject is {x} softer than things at the same distance, while moving fast across the frame: motion blur from a slow shutter.",
        "close": f"Your subject fills the frame and is {x} softer than the sharpest part: they're likely closer than the lens can focus, or the lens couldn't keep up.",
    }[r["cause"]]
    return "Subject out of focus", detail


def _explain(points: list[Point], runs: list[dict], s: Sampled, step: float) -> dict:
    there = sum(step for p in points)
    focus_runs = [r for r in runs if r["kind"] == "focus"]
    missed = sum(r["end"] - r["start"] for r in focus_runs)
    ratios = [p.ratio for p in points if p.ratio and p.state != "frame_soft"]
    if not ratios:
        return {"finding": "", "advice": [], "habits": [], "missed": 0.0, "sharpest": None, "never_sharp": False}
    # the stretch where they were sharpest (about a second around the best moment)
    best_i = int(np.argmin([p.ratio if p.ratio and p.state != "frame_soft" else 99 for p in points]))
    near = [p for p in points if p.ratio and p.ratio <= points[best_i].ratio * 1.15 and abs(p.t - points[best_i].t) <= 3]
    sharpest = (near[0].t - step / 2, near[-1].t + step / 2, points[best_i].ratio) if near else None
    never = min(ratios) >= SHARP
    advice_rows, habits = [], []
    causes = {r["cause"] for r in focus_runs}
    if not focus_runs:
        if never:
            finding = (f"Focus: your subject was never quite as sharp as the sharpest part of the picture "
                       f"(at best {_times(min(ratios))} wider edges, {clock(sharpest[0])}–{clock(sharpest[1])}), but close enough not to stand out.")
        else:
            finding = f"Focus: your subject stayed sharp while in the picture ({clock(points[0].t)}–{clock(points[-1].t)})."
        return {"finding": finding, "advice": [], "habits": [], "missed": 0.0, "sharpest": sharpest, "never_sharp": never}
    worst = max(focus_runs, key=lambda r: (r["end"] - r["start"]) * (r["ratio"] or 1))
    where = {"behind": "the focus sat behind them", "front": "the focus sat in front of them",
             "elsewhere": "the focus was on something else", "motion": "they moved too fast for the shutter",
             "close": "they came closer than the lens could focus"}[worst["cause"]]
    if worst["named"] and worst["cause"] in ("behind", "front", "elsewhere") and worst["named"] != "another person":
        where += f" (the {worst['named']} was sharp)"
    follow = ", and it didn't follow them as they came closer" if worst["coming"] else \
        ", and it didn't follow them as they moved away" if worst["going"] else ""
    when = ", ".join(f"{clock(r['start'])}–{clock(r['end'])}" for r in focus_runs[:4])
    finding = (f"Your subject was out of focus for {missed:.1f} of the {there:.1f} s they're in the clip ({when}): "
               f"{where}{follow}.")
    locked = worst["cause"] in ("behind", "front") and (worst["coming"] or worst["going"])
    if sharpest and locked and sharpest[1] <= (worst["start"] + worst["end"]) / 2:
        finding += (f" The focus matched them only at {clock(sharpest[0])}–{clock(sharpest[1])}, while they were still "
                    f"{'far away' if worst['coming'] else 'close'}, and stayed at that distance as they "
                    f"{'came in' if worst['coming'] else 'moved off'}: it was set once (focus locked early, AF-S or manual) "
                    "instead of following them.")
    elif sharpest:
        finding += (f" They were sharpest at {clock(sharpest[0])}–{clock(sharpest[1])}"
                    + (", but even then the background was sharper: the focus was never quite on them." if never else "."))
        if locked:
            finding += " The focus stayed at one distance while they moved: it was set once (locked, AF-S or manual) instead of following them."
    if causes & {"behind", "front", "elsewhere", "close"}:
        if locked:
            advice_rows.append(("Focus mode", "Continuous AF (AF-C), not AF-S or manual",
                                "Focus set once stays at that distance; someone running toward or away from you leaves it in a second or two."))
        advice_rows += [
            ("Focus area", "Tracking (Flexible Spot or Zone), started on them",
             "A wide area lets the camera choose, and it often picks the background or the nearest bright edge."),
            ("Subject recognition", "Face/Eye AF on, set to Human",
             "The camera finds their face and holds it as they move, even when they run at you."),
            ("AF subject shift sensitivity", "4–5 (Responsive)",
             "Lets focus move onto them quickly as the distance changes instead of staying on the background."),
            ("AF transition speed", "5–7 (Fast)",
             "Someone coming toward you changes distance fast; a slow transition always lags behind them."),
        ]
        habits += ["Lock on early and keep it: put the tracking box on them (half-press, the AF-ON button or tap the screen) before they start moving, and keep it on them.",
                   "Watch the focus box on the screen: if it jumps to the background, tap your subject again."]
    if "close" in causes:
        habits.append("When they come right up to you, step back or zoom out: closer than the lens's minimum distance, nothing can focus.")
    if "motion" in causes:
        advice_rows.append(("Shutter", "1/250 or faster for running players",
                            "At twice the frame rate fast movement smears; a faster shutter freezes it (raise ISO or open the aperture to make up the light)."))
    if any(r["kind"] == "frame" and r["cause"] == "hunting" for r in runs):
        habits.append("Avoid quick swings past things nearer or farther than your subject: the lens jumps to them and has to search its way back.")
    return {"finding": finding, "advice": advice_rows, "habits": habits, "missed": round(missed, 2),
            "sharpest": sharpest, "never_sharp": never}
