"""People in the Culling tab: the players you name (from a click on them, or just their jersey number)
and which photos of an event they are in, best first, one per burst. Uses VS Digital Pro's player finder
(photo_presets.players: faces with a free model on this Mac, numbers read by the Mac's own text
reading, kit colors), with one addition: a player can be just a number."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from photo_presets import players


def person_from(s: players.Sighting, name: str, pid: str) -> dict:
    """A saved player from one sighting of them (their face, kit and number, as features)."""
    return {"id": pid, "name": name, "number": s.number,
            "face": s.face.tolist() if s.face is not None else None,
            "kit": s.kit.tolist() if s.kit is not None else None, "yes": [], "no": []}


def _arr(v):
    return np.asarray(v, np.float32) if v is not None else None


def likeness(person: dict, s: players.Sighting) -> tuple[str, float, str]:
    """Is this sighting the person? ("sure" | "maybe" | "no", how close, why)."""
    number = person.get("number")
    if person.get("face") is None and person.get("kit") is None:  # just a number
        if number and s.number == number:
            return "sure", 0.95, f"number {number}"
        return "no", 0.0, ""
    target = players.Sighting((0, 0, 0, 0), face=_arr(person.get("face")), number=number, kit=_arr(person.get("kit")))
    if target.kit is None:
        target.kit = s.kit
    return players.likeness(target, s, [_arr(f) for f in person.get("yes", [])], [_arr(f) for f in person.get("no", [])])


def matches(person: dict, scans: list[players.Scan]) -> dict[str, dict]:
    """{photo path: {status, score, why, quality, best, box}} for the photos with them."""
    hits = []
    for sc in scans:
        rated = [(likeness(person, s), s) for s in sc.people]
        rated = [r for r in rated if r[0][0] != "no"]
        if not rated:
            continue
        (status, score, why), s = max(rated, key=lambda r: (r[0][0] == "sure", r[0][1]))
        hits.append({"scan": sc, "s": s, "status": status, "score": score, "why": why})
    if not hits:
        return {}
    ref = float(np.percentile([h["s"].sharp for h in hits], 90)) or 1.0
    for h in hits:
        h["quality"] = players.quality(h["scan"], h["s"], ref)
        h["best"] = False
    sure = sorted((h for h in hits if h["status"] == "sure"), key=lambda h: (h["scan"].taken or datetime.min, h["scan"].path))
    group: list[dict] = []
    for h in sure + [None]:
        if h is None or (group and not players.same_moment(group[-1]["scan"], h["scan"])):
            if group:
                max(group, key=lambda g: g["quality"])["best"] = True
            group = []
        if h is not None:
            group.append(h)
    return {h["scan"].path: {"status": h["status"], "score": round(h["score"], 2), "why": h["why"],
                             "quality": round(h["quality"], 2), "best": h["best"], "box": h["s"].box,
                             "face": h["s"].face.tolist() if h["s"].face is not None else None} for h in hits}
