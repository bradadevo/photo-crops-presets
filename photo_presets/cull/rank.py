"""Pass 1 over a whole shoot: each photo's score (0-100), what holds it back, its burst, and the
keep / reject suggestion with how sure it is and why, in plain words.

Sharpness is judged against the rest of the shoot (the same camera, lens and light), not a fixed
number, so a dull day or a long lens does not mark everything soft."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Bursts (from match-cull): frames this close in time are one burst whatever they look like; up to
# BURST_SIMILAR apart they are when they also look alike
BURST_SECONDS = 0.7
BURST_SIMILAR_SECONDS = 3.0
BURST_HASH_DISTANCE = 12
SOFT = 0.4  # main player's sharpness under this share of the shoot's typical sharp photo: soft
SOFT_HARD = 0.25  # ...under this: clearly missed
EYES_CLOSED = 0.17
FACE_FOR_EYES = 60
KEEP_AT = 55  # "the best ones": best of their burst, no serious problem, and at least this score
HARD = {"blur", "eyes", "empty", "focus"}  # problems that reject a photo by themselves

ISSUE_TEXT = {
    "blur": "The main player is soft (missed focus or motion blur)",
    "eyes": "Eyes look closed",
    "focus": "The camera focused on the background, not the players",
    "empty": "No players in it",
    "small": "The players are small in the frame",
    "dark": "Too dark on the players",
    "bright": "Too bright: parts are blown out",
    "back": "The main player's face can't be seen",
    "dupe": "A near copy of a better frame in the same burst",
}


@dataclass
class Ranked:
    score: float = 0.0
    parts: dict = field(default_factory=dict)  # the score's pieces (0-1)
    issues: list = field(default_factory=list)
    good: list = field(default_factory=list)  # what is good about it, in words
    burst: int = 0
    burst_size: int = 1
    burst_best: bool = True
    suggest: str = ""  # "keep" or "reject"
    sure: float = 0.5  # how sure pass 1 is (0-1): pass 2 starts with the unsure ones
    why: str = ""


def _smooth(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def same_burst(a: tuple[float, int], b: tuple[float, int]) -> bool:
    (ta, ha), (tb, hb) = a, b
    gap = abs(tb - ta)
    if gap <= BURST_SECONDS:
        return True
    if gap > BURST_SIMILAR_SECONDS:
        return False
    return (ha ^ hb).bit_count() <= BURST_HASH_DISTANCE


def reference_sharpness(ms: list[dict]) -> float:
    """The shoot's typical sharp photo: three quarters of the way up its players' sharpness."""
    vals = [m["sharp"] for m in ms if m.get("subject") and m.get("sharp", 0) > 0]
    return float(np.percentile(vals, 75)) if len(vals) >= 3 else (max(vals) if vals else 1.0)


def features(m: dict, ref: float) -> dict:
    """The score's pieces, each 0-1 (also what the taste model learns from)."""
    rel = m.get("sharp", 0) / max(ref, 1e-6) if m.get("subject") else 0.0
    main = next((f for f in m.get("faces", []) if f.get("main")), None)
    has_face = bool(main and main.get("px"))
    q = (main or {}).get("quality") or 0.0
    h = m.get("subject_height", 0)
    light = m.get("subject_light", 0.5)
    return {
        "sharp": _smooth(0.25, 0.9, rel),
        "face": (0.35 + 0.65 * _smooth(0.03, 0.35, q)) if has_face else (0.25 if m.get("subject") else 0.0),
        "size": _smooth(0.08, 0.35, h) * (1 - 0.3 * _smooth(0.85, 1.0, h)),
        "ball": 1.0 if m.get("ball") else 0.0,
        "players": min(1.0, m.get("people", 0) / 3),
        "light": 1 - min(1.0, abs(light - 0.48) / 0.32) - min(0.5, m.get("white", 0) * 3),
        "focus": {True: 1.0, False: 0.0, None: 0.6}[m.get("focus_on_subject")],
        "eyes_open": 0.0 if (has_face and main["px"] >= FACE_FOR_EYES and (main.get("eyes") or 1) < EYES_CLOSED) else 1.0,
        "rel": rel,
    }


WEIGHTS = {"sharp": 0.34, "face": 0.18, "size": 0.12, "ball": 0.08, "players": 0.04, "light": 0.10,
           "focus": 0.08, "eyes_open": 0.06}


def issues_of(m: dict, f: dict) -> list[str]:
    out = []
    if not m.get("people"):
        return ["empty"]
    if f["rel"] < SOFT:
        out.append("blur")
    if f["eyes_open"] == 0:
        out.append("eyes")
    if m.get("focus_on_subject") is False and f["rel"] < 0.8:
        out.append("focus")
    if m.get("subject_height", 1) < 0.1:
        out.append("small")
    light = m.get("subject_light", 0.5)
    if light < 0.2:
        out.append("dark")
    if light > 0.8 or m.get("white", 0) > 0.15:
        out.append("bright")
    main = next((x for x in m.get("faces", []) if x.get("main")), None)
    if m.get("subject_height", 0) > 0.2 and not (main and main.get("px")):
        out.append("back")
    return out


def good_of(m: dict, f: dict) -> list[str]:
    out = []
    if f["rel"] >= 0.8:
        out.append("sharp on the main player")
    if f["face"] >= 0.6:
        out.append("face clearly visible")
    if m.get("ball"):
        out.append("the ball is in the play")
    if f["size"] >= 0.7:
        out.append("players fill the frame well")
    if m.get("people", 0) >= 2 and not m.get("team_photo"):
        out.append("more than one player in the moment")
    if m.get("team_photo"):
        out.append("the whole group in the frame")
    return out


def rank(items: list[tuple[str, float, dict]], taste=None) -> dict[str, Ranked]:
    """items: (id, time taken, measurements) for the whole shoot. taste: a function from features to
    how likely you are to keep it (0-1), once it has learned enough; blended into the score."""
    ms = [m for _, _, m in items if m]
    ref = reference_sharpness(ms)
    out: dict[str, Ranked] = {}
    order = sorted((it for it in items if it[2]), key=lambda it: (it[1], it[0]))
    burst, prev = -1, None
    for pid, t, m in order:
        f = features(m, ref)
        r = Ranked(parts=f)
        r.score = 100 * sum(WEIGHTS[k] * f[k] for k in WEIGHTS)
        if taste is not None:
            like = taste(f, m)
            if like is not None:
                r.score = 0.55 * r.score + 0.45 * 100 * like
                r.parts["taste"] = like
        r.issues = issues_of(m, f)
        if "blur" in r.issues and f["rel"] < SOFT_HARD:
            r.score *= 0.6
        r.good = good_of(m, f)
        key = (t, m.get("hash", 0))
        if prev is None or not same_burst(prev, key):
            burst += 1
        prev = key
        r.burst = burst
        out[pid] = r
    # the best frame of each burst
    groups: dict[int, list[str]] = {}
    for pid, r in out.items():
        groups.setdefault(r.burst, []).append(pid)
    for b, ids in groups.items():
        best = max(ids, key=lambda i: (round(out[i].score, 1), out[i].parts.get("rel", 0)))  # ties: the sharper
        for i in ids:
            out[i].burst_size = len(ids)
            out[i].burst_best = i == best
            if i != best:
                out[i].issues.append("dupe")
    return out


def parse_keep(text: str | None, total: int) -> int | None:
    """'30' -> 30, '25%' -> a quarter, '' / 'best' -> None (every photo good enough)."""
    text = (text or "").strip().lower()
    if not text or text in ("best", "auto"):
        return None
    if text.endswith("%"):
        pct = float(text[:-1])
        return max(1, math.ceil(total * min(100.0, max(0.0, pct)) / 100))
    return max(1, int(float(text)))


def suggest(ranked: dict[str, Ranked], keep: int | None = None, one_per_burst: bool = True,
            strict: float = 0.5) -> None:
    """Pass 1's marks: keep the best moments, reject the rest, each with how sure and why.
    keep: how many (None: every photo good enough). strict (0-1): how picky about soft and
    closed-eye frames. Within a burst only its best frame is kept unless one_per_burst is off."""
    cut = KEEP_AT + (strict - 0.5) * 20
    pool = [i for i, r in ranked.items() if (r.burst_best or not one_per_burst)]
    good = [i for i in pool if not (set(ranked[i].issues) & HARD) and ranked[i].score >= cut]
    good.sort(key=lambda i: -ranked[i].score)
    if keep is not None:
        if len(good) < keep:  # asked for more: the best of what is left, problems and all
            rest = sorted((i for i in pool if i not in good), key=lambda i: -ranked[i].score)
            good += rest[:keep - len(good)]
        good = good[:keep]
    chosen = set(good)
    last = min((ranked[i].score for i in good), default=cut)
    for i, r in ranked.items():
        hard = [x for x in r.issues if x in HARD]
        if i in chosen:
            r.suggest = "keep"
            margin = (r.score - last) / 15
            r.sure = float(min(0.98, 0.55 + 0.4 * min(1.0, margin))) if not hard else 0.35
            r.why = "Kept: " + (", ".join(r.good) if r.good else "the best of its moment")
            if hard:
                r.why += f". But: {ISSUE_TEXT[hard[0]].lower()}"
        else:
            r.suggest = "reject"
            if hard:
                r.sure = 0.9 if (ranked[i].parts.get("rel", 1) < SOFT_HARD or "empty" in hard) else 0.75
                r.why = "Rejected: " + "; ".join(ISSUE_TEXT[x].lower() for x in hard)
            elif "dupe" in r.issues:
                best = next(j for j, q in ranked.items() if q.burst == r.burst and q.burst_best)
                gap = ranked[best].score - r.score
                r.sure = float(min(0.95, 0.45 + gap / 25))
                r.why = f"Rejected: a near copy; a better frame of this moment is kept"
            else:
                r.sure = float(min(0.9, 0.4 + (last - r.score) / 30))
                r.why = "Rejected: weaker than the photos kept" + (
                    f" ({ISSUE_TEXT[r.issues[0]].lower()})" if r.issues else "")
