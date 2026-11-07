"""Who the photo is about, and the crop and face boxes around them.

Subject priority (the photographer's rules):
1. The goalie, when sharp and not a small, distant figure.
2. A player from the photographer's team, preferring the one the camera
   focused on, then the sharpest and biggest.
3. Whoever the camera focused on, then the sharpest and biggest person.
The crop then takes in what belongs to the play: close opponents or
teammates of similar size (not blurry ones) and a nearby ball. Eight or more
same-size people, mostly the team, is a team photo and is framed as one.
"""

from dataclasses import dataclass

from photo_crops.people import GOALIE, TEAM, Person

Box = tuple[int, int, int, int]

# People shorter than this share of the tallest are background
MAIN_HEIGHT = 0.35
# The goalie leads when this sharp relative to the sharpest main person (or in
# focus) and at least this tall relative to the tallest
GOALIE_SHARP = 0.6
GOALIE_HEIGHT = 0.5
# ...and not mostly (this share of their box) behind a bigger, sharper person
HIDDEN_SHARE = 0.5
# Another person joins the crop when at least this tall relative to the
# subject, this sharp relative to the subject, and their box is within this
# gap (as a share of the subject's height)
GROUP_HEIGHT = 0.6
GROUP_SHARP = 0.3
GROUP_GAP = 0.6
# A ball this close to the subject's center (shares of their height) joins the crop
BALL_X, BALL_Y = 1.2, 1.0
# Team photo: at least this many people this tall relative to the tallest, mostly the team
TEAM_PHOTO_PEOPLE = 8
TEAM_PHOTO_HEIGHT = 0.55
TEAM_PHOTO_SHARE = 0.6
# Best crop: portrait 4:5 for a group narrower than this (width / height), else 3:2
PORTRAIT_BELOW = 0.9
# Room around the group: (width, height) multipliers
PORTRAIT_ROOM = (1.5, 1.3)
LANDSCAPE_ROOM = (1.3, 1.35)
TEAM_ROOM = (1.08, 1.15)
# A best crop wider than this share of the photo is redone as a 4:5 portrait,
# so it is a real crop and not the whole frame again
NEAR_FULL = 0.9
MIN_CROP_SHORT = 1200
# Face: head-and-shoulders width as a multiple of the head size, the head's
# height in the frame, and the smallest width that still looks sharp
FACE_WIDTH = 3.0
FACE_HEAD_AT = 0.34
FACE_MIN_WIDTH = {"sharp": 800, "tight": 300, "skip-small": 800}
# A face box covering more than this share of the crop is tightened to FACE_SHRINK
FACE_SAME_AS_CROP = 0.8
FACE_SHRINK = 0.6

ASPECTS = {"4:5": 4 / 5, "9:16": 9 / 16, "1:1": 1.0, "3:2": 3 / 2, "16:9": 16 / 9}


@dataclass
class Plan:
    subject: Person | None
    group: Box  # everything the crop should hold
    reason: str
    team_photo: bool = False
    face_person: Person | None = None


def union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _gap(a: Box, b: Box) -> float:
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return max(dx, dy)


def choose(people: list[Person], balls: list[Box], size: tuple[int, int], goalie_first: bool = True) -> Plan:
    if not people:
        w, h = size
        return Plan(None, (w // 4, h // 4, 3 * w // 4, 3 * h // 4), "no people found: center crop")
    tallest = max(p.height for p in people)
    main = [p for p in people if p.height >= MAIN_HEIGHT * tallest]
    sharpest = max(p.sharp for p in main) or 1.0

    big = [p for p in people if p.height >= TEAM_PHOTO_HEIGHT * tallest]
    if len(big) >= TEAM_PHOTO_PEOPLE and sum(p.kind in (TEAM, GOALIE) for p in big) >= TEAM_PHOTO_SHARE * len(big):
        goalies = [p for p in big if p.kind == GOALIE]
        face = goalies[0] if goalies and goalie_first else max(big, key=lambda p: (p.focus_hit, p.sharp))
        return Plan(None, union([p.box for p in big]), "team photo", True, face)

    def rel(p: Person) -> float:
        return p.sharp / sharpest

    def hidden(p: Person) -> bool:
        """Mostly behind a bigger, sharper person."""
        area = max(p.width * p.height, 1)
        for q in main:
            if q is p or q.height <= p.height or q.sharp <= p.sharp:
                continue
            ox = max(0, min(p.box[2], q.box[2]) - max(p.box[0], q.box[0]))
            oy = max(0, min(p.box[3], q.box[3]) - max(p.box[1], q.box[1]))
            if ox * oy >= HIDDEN_SHARE * area:
                return True
        return False

    subject, reason = None, ""
    goalies = [p for p in main if p.kind == GOALIE and p.height >= GOALIE_HEIGHT * tallest
               and (p.focus_hit or rel(p) >= GOALIE_SHARP) and not hidden(p)]
    if goalie_first and goalies:
        subject, reason = max(goalies, key=lambda p: (p.focus_hit, rel(p))), "goalie"
    if subject is None:
        team = [p for p in main if p.kind in (TEAM, GOALIE) and (p.focus_hit or rel(p) >= GROUP_SHARP)
                and not hidden(p)]
        if team:
            subject = max(team, key=lambda p: (p.focus_hit, rel(p) + p.height / tallest))
            reason = "team player in focus" if subject.focus_hit else "sharpest team player"
    if subject is None:
        subject = max(main, key=lambda p: (p.focus_hit, rel(p) + p.height / tallest))
        reason = "in focus" if subject.focus_hit else "sharpest person"

    boxes = [subject.box]
    for p in main:
        if p is subject:
            continue
        if (p.height >= GROUP_HEIGHT * subject.height and p.sharp >= GROUP_SHARP * subject.sharp
                and _gap(p.box, subject.box) <= GROUP_GAP * subject.height):
            boxes.append(p.box)
    cx, cy = subject.center
    for b in balls:
        bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if abs(bx - cx) <= BALL_X * subject.height and abs(by - cy) <= BALL_Y * subject.height:
            boxes.append(b)
    return Plan(subject, union(boxes), reason, False, subject)


def fit(group: tuple[float, float, float, float], size: tuple[int, int], aspect: float,
        room: tuple[float, float] = (1.0, 1.0), min_short: float = 0) -> Box:
    """The smallest box of this aspect holding group with room around it,
    centered on it and kept inside the photo."""
    w, h = size
    x0, y0, x1, y1 = group
    gw, gh = x1 - x0, y1 - y0
    ch = max(gh * room[1], gw * room[0] / aspect, min_short if aspect >= 1 else min_short / aspect)
    cw = ch * aspect
    if cw > w:
        cw, ch = w, w / aspect
    if ch > h:
        ch, cw = h, h * aspect
    left = min(max((x0 + x1) / 2 - cw / 2, 0), w - cw)
    top = min(max((y0 + y1) / 2 - ch / 2, 0), h - ch)
    return round(left), round(top), round(left + cw), round(top + ch)


def crop_box(plan: Plan, size: tuple[int, int], shape: str) -> Box:
    if plan.team_photo:
        aspect = ASPECTS.get(shape, 3 / 2)
        return fit(plan.group, size, aspect, TEAM_ROOM, MIN_CROP_SHORT)
    gw, gh = plan.group[2] - plan.group[0], plan.group[3] - plan.group[1]
    if shape != "best":
        return fit(plan.group, size, ASPECTS[shape], PORTRAIT_ROOM if ASPECTS[shape] < 1 else LANDSCAPE_ROOM,
                   MIN_CROP_SHORT)
    if gw / max(gh, 1) <= PORTRAIT_BELOW:
        return fit(plan.group, size, 4 / 5, PORTRAIT_ROOM, MIN_CROP_SHORT)
    box = fit(plan.group, size, 3 / 2, LANDSCAPE_ROOM, MIN_CROP_SHORT)
    if box[2] - box[0] >= NEAR_FULL * size[0]:
        target = plan.subject.box if plan.subject else plan.group
        return fit(target, size, 4 / 5, (1.0, 1.0), MIN_CROP_SHORT)
    return box


def face_box(person: Person, size: tuple[int, int], mode: str, crop: Box | None = None) -> Box | None:
    """Head and shoulders of person, 4:5; None when mode is skip-small and the face is too small."""
    x0, y0, x1, y1 = person.box
    if person.head:
        hx, hy, spread = person.head
    else:
        hx, hy, spread = (x0 + x1) / 2, y0 + 0.08 * person.height, 0.0
    head = max(spread * 1.4, person.height * 0.12)
    want = head * FACE_WIDTH
    if mode == "skip-small" and want < FACE_MIN_WIDTH[mode]:
        return None
    fw = max(want, FACE_MIN_WIDTH[mode])
    if crop:
        crop_w = crop[2] - crop[0]
        if fw >= FACE_SAME_AS_CROP * crop_w:
            fw = max(FACE_SHRINK * crop_w, FACE_MIN_WIDTH[mode])
    fh = fw * 5 / 4
    top = hy - FACE_HEAD_AT * fh
    return fit((hx - fw / 2, top, hx + fw / 2, top + fh), size, 4 / 5)


def subject_box(plan: Plan) -> Box:
    return plan.subject.box if plan.subject else plan.group
