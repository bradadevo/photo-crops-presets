"""AllProPhoto Studio: the app's own web page (studio/web) and the small local
server behind it. The looks engine does the work; this file keeps the session
(photos, the looks made, the ones you keep) and answers the page.

Everything that makes pictures runs on one worker thread, in order of
importance: fixing a cut-out, then the looks you asked for, then exports and
reels, then the little look previews on your photo (so they never slow a run).

    uv run allprophoto            (the classic Gradio app: uv run allprophoto-classic)
"""

from __future__ import annotations

import asyncio
import io
import itertools
import os
import json
import uuid
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import dataclasses
from collections import OrderedDict
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from pathlib import Path
from queue import PriorityQueue

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image

from photo_crops import images
from photo_crops.ui import choose_folder
from photo_presets import brand, deliver, edits, engine, pipeline, players, presets, reel, timing, poster
from photo_presets.engine import Engine, Job, Result
from photo_presets.scene import Fix, frame_boxes

WEB = Path(__file__).parent / "web"
CONFIG = Path("~/.config/photo-crops-presets").expanduser()
# ALLPROPHOTO_STATE: a folder of its own for the session, settings and added photos (a test copy of the app)
STATE = Path(os.environ["ALLPROPHOTO_STATE"]) if os.environ.get("ALLPROPHOTO_STATE") else None
PREFS = (STATE or CONFIG) / "studio.json"
EXAMPLES = Path("~/.cache/photo-crops-presets/examples").expanduser()  # each look's last picture, for the picker
WORK = Path(tempfile.mkdtemp(prefix="allprophoto-"))  # songs for reels
ADDED = (STATE / "added") if STATE else Path("~/.cache/photo-crops-presets/added").expanduser()  # photos dropped or pasted
EDITED = ADDED.parent / "edited"
if STATE:  # a test copy: its own presets too (never your real ones)
    presets.PRESETS_FILE = STATE / "presets.json"  # photos as edited, to make more looks on top of the edits
SESSION = (STATE or CONFIG) / "studio-session.json"  # the photos you are working on, kept for next time
# the looks made, with their edits, picks and stars, kept for next time (pictures at preview size)
LOOKS = (STATE / "looks") if STATE else Path("~/.cache/photo-crops-presets/session-looks").expanduser()
DEFAULT_EXPORT = str(Path.home() / "Pictures" / "Photo Presets")
THUMB, VIEW, SWATCH, TRY = 560, 1800, 420, 1400  # px: the strip and grid, a photo, a look's card, trying a look on
ZOOM = 3600  # px: a look made again, sharper, when you zoom in
CROPS = ["none", "wide", "crop", "face"]
FIX, RUN, OUTPUT, PREVIEW = 0, 1, 2, 5  # the worker's order of importance

# the look groups, short, for the picker's filters
SHORT_GROUPS = {
    presets.BOLD: "Bold", presets.EDITORIAL: "Editorial", presets.STUDIO: "Studio", presets.MINE: "Mine",
}


# The worker --------------------------------------------------------------------------

class Worker:
    """One thread for everything that makes pictures, most important first."""

    def __init__(self):
        self.q: PriorityQueue = PriorityQueue()
        self.order = itertools.count()
        threading.Thread(target=self._loop, daemon=True, name="allprophoto-worker").start()

    def submit(self, priority: int, fn, *args) -> Future:
        fut: Future = Future()
        self.q.put((priority, next(self.order), fut, fn, args))
        return fut

    def _loop(self):
        while True:
            _, _, fut, fn, args = self.q.get()
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(*args))
            except BaseException as e:  # shown to the page by whoever waits on it
                fut.set_exception(e)


# The session ---------------------------------------------------------------------------

@dataclass
class Photo:
    id: int
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class Slot:
    """A look in the results: waiting, being made, done (with its result) or failed."""
    id: int
    run: int
    photo: int
    look: str
    title: str
    expect: float
    state: str = "wait"
    result: Result | None = None
    ver: int = 0
    kept: bool = False
    rating: int = 0
    crop: str = "none"
    cut: bool = False  # the look cuts out the players (once per photo)
    source: str = ""  # the picture it is made from, when not the photo itself (the photo as edited)
    ai: bool = False  # drawn by the AI models (loaded once per session)
    started: float = 0.0
    extra: float = 0.0  # one-off work in this look's time (getting the photo ready, loading models)
    loading: bool = False
    secs: float = 0.0
    error: str = ""
    future: Future | None = None
    edit_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def public(self) -> dict:
        pct = 0
        if self.state == "now":
            pct = min(95, int(100 * (time.time() - self.started) / max(1.0, self.expect + self.extra)))
        out = {"id": self.id, "run": self.run, "photo": self.photo, "look": self.look, "title": self.title,
               "state": self.state, "ver": self.ver, "kept": self.kept, "rating": self.rating, "pct": pct,
               "crop": self.crop,
               "secs": round(self.secs, 1),
               "error": self.error, "note": "Loading the AI models (once a session)"
               if self.state == "now" and self.loading and not timing.models_loaded() else ""}
        if self.result is not None:
            r = self.result
            w, h = edits.final_size(r.after.width, r.after.height, r.edits)
            out.update(adjust=pipeline.adjustments(r.recipe), about=presets.describe(r.name, r.recipe)
                       if r.name else "", notes=r.notes, matched="match" in r.recipe,
                       width=w, height=h, base_width=r.after.width, base_height=r.after.height,
                       edits=r.edits, ai=timing.uses_ai(r.recipe), cutout=pipeline.needs_cutout(r.recipe),
                       fixes=len(E.fixes_for(r)), removed=len(E.removals.get(str(r.source), [])))
        return out


@dataclass
class Task:
    """An export or a reel: how far it is, and what came of it."""
    id: int
    kind: str
    total: int
    done: int = 0
    now: str = ""
    state: str = "running"
    message: str = ""
    path: str = ""
    video: str = ""
    started: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "kind", "total", "done", "now", "state", "message", "path",
                                              "video")} | {"elapsed": round(time.time() - self.started)}


class Session:
    def __init__(self):
        self.lock = threading.RLock()
        self.photos: OrderedDict[int, Photo] = OrderedDict()
        self.slots: OrderedDict[int, Slot] = OrderedDict()
        self.tasks: dict[int, Task] = {}
        self.ids = itertools.count(1)
        self.runs = itertools.count(1)
        self.pace: list[tuple[float, float]] = []  # (took, expected) of clean looks: how this Mac runs today
        self.future: dict[int, list[dict]] = {}  # removed from every look of a photo: also from looks made later
        self.trash: dict[int, tuple[float, Slot]] = {}  # looks just removed, for undo
        self.cutting: dict[tuple[str, str], float] = {}  # when each photo's cut-out began (for the countdown)

    def photo(self, pid: int) -> Photo:
        p = self.photos.get(pid)
        if p is None:
            raise HTTPException(404, "That photo is no longer here")
        return p

    def slot(self, sid: int) -> Slot:
        s = self.slots.get(sid)
        if s is None or s.result is None:
            raise HTTPException(404, "That look is no longer here")
        return s

    def add_photos(self, paths: list[Path]) -> list[int]:
        with self.lock:
            known = {str(p.path) for p in self.photos.values()}
            added = []
            for path in paths:
                if str(path) in known:
                    continue
                pid = next(self.ids)
                self.photos[pid] = Photo(pid, path)
                known.add(str(path))
                added.append(pid)
            if added:
                self.save()
            return added

    def remove_photo(self, pid: int) -> None:
        with self.lock:
            self.photos.pop(pid, None)
            self.save()

    def saved(self) -> dict:
        return {"photos": [str(p.path) for p in self.photos.values()],
                "future": {str(self.photos[pid].path): rms for pid, rms in self.future.items() if pid in self.photos and rms},
                "fixes": [[k[0], k[1], [[f.x, f.y, f.add] for f in v]] for k, v in E.fixes.items() if v],
                "removals": E.removals}

    def save(self) -> None:
        try:
            SESSION.parent.mkdir(parents=True, exist_ok=True)
            SESSION.write_text(json.dumps(self.saved(), indent=1))
        except OSError:
            pass

    def restore(self) -> None:
        """The photos from last time (those still there), their cut-out fixes and removals,
        and the looks made of them (with their edits, picks and stars)."""
        try:
            data = json.loads(SESSION.read_text())
        except (OSError, ValueError):
            return
        for path, crop, fixes in data.get("fixes", []):
            E.fixes[(path, crop)] = [Fix(float(x), float(y), bool(add)) for x, y, add in fixes]
        for path, removals in (data.get("removals") or {}).items():
            E.removals[path] = removals
        looks = restore_looks()
        if looks:
            self.ids = itertools.count(max(m["id"] for m, _ in looks) + 1)
        self.add_photos([Path(p) for p in data.get("photos", []) if Path(p).is_file()])
        by_path = {str(p.path): p.id for p in self.photos.values()}
        for path, rms in (data.get("future") or {}).items():
            if path in by_path:
                self.future[by_path[path]] = rms
        for meta, r in looks:
            pid = by_path.get(meta["photo"])
            if pid is None:
                continue
            self.slots[meta["id"]] = Slot(meta["id"], 0, pid, meta["look"], r.title, 0.0, state="done", result=r,
                                          kept=bool(meta.get("kept")), rating=int(meta.get("rating", 0)),
                                          crop=r.crop)

    def busy(self) -> bool:
        return any(s.state in ("wait", "now") for s in self.slots.values()) or any(
            t.state == "running" for t in self.tasks.values())

    def left(self) -> float:
        """About how many seconds the looks still waiting take, the one-off work included from the
        start (getting each photo ready, cutting out its players, loading the AI models), so the
        estimate does not jump up as it meets them."""
        return self.progress()[0]

    def progress(self) -> tuple[float, str]:
        """(seconds left, what is being done now)."""
        pace = 1.0
        if self.pace:
            pace = min(2.5, max(0.5, sum(t for t, _ in self.pace) / max(1e-6, sum(x for _, x in self.pace))))
        total, phase = 0.0, ""
        ready, cut, models = set(), set(), timing.models_loaded()
        for s in self.slots.values():
            if s.state == "now":
                whole = (s.expect + s.extra) * pace
                spent = time.time() - s.started
                # running over: a little more, not "nearly done" (which would then jump back up)
                total += max(whole - spent, 0.15 * whole, 2.0)
                key = (s.photo, s.source, s.crop)
                ready.add(key)
                cut.add(key)
                if s.ai:
                    models = True
                if s.loading and not timing.models_loaded():
                    phase = "Loading the AI models (once a session)"
                elif s.extra >= timing.cut_out() * 0.9 and spent < s.extra * pace:
                    p = self.photos.get(s.photo)
                    phase = "Separating the players from the background" + (f" · {p.name}" if p is not None else "")
                else:
                    phase = f"Making {s.look}"
        for s in self.slots.values():
            if s.state != "wait":
                continue
            total += s.expect * pace
            key = (s.photo, s.source, s.crop)
            p = self.photos.get(s.photo)
            src = Path(s.source) if s.source else (p.path if p is not None else None)
            if p is not None and key not in ready and not E.is_prepared(src, s.crop):
                total += timing.PHOTO_READY * pace
                ready.add(key)
            if s.cut and p is not None and key not in cut and not E.is_cut_out(src, s.crop):
                began = self.cutting.get((str(src), s.crop))
                whole = timing.cut_out()
                total += max(whole - (time.time() - began), 0.15 * whole, 2.0) if began else whole
                cut.add(key)
            if s.ai and not models:
                total += timing.MODEL_LOAD
                models = True
        if not phase and any(s.state == "wait" for s in self.slots.values()):
            phase = "Getting the photo ready"
        return total, phase


E = Engine()
E.brand_dir = STATE or CONFIG
S = Session()
W = Worker()


# Keeping the session for next time ------------------------------------------------------------

def _look_dir(sid: int) -> Path:
    return LOOKS / str(sid)


def save_look(s: Slot) -> None:
    """The look's pictures (when they changed) and what it is."""
    r = s.result
    d = _look_dir(s.id)
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "before.jpg").exists():
        r.before.convert("RGB").save(d / "before.jpg", quality=94)
    r.after.convert("RGB").save(d / "after.jpg", quality=94)
    if r.look is not None and r.look is not r.after:
        r.look.convert("RGB").save(d / "look.jpg", quality=94)
    else:
        (d / "look.jpg").unlink(missing_ok=True)
    (d / "meta.json").write_text(json.dumps({
        "id": s.id, "photo": str(r.source), "look": s.look, "crop": r.crop, "recipe": r.recipe, "seed": r.seed,
        "frame": r.frame, "edits": r.edits, "notes": r.notes, "kept": s.kept, "rating": s.rating}, indent=1))


def restore_looks() -> list[tuple[dict, Result]]:
    out = []
    for d in sorted(LOOKS.glob("*/meta.json"), key=lambda p: int(p.parent.name) if p.parent.name.isdigit() else 0):
        try:
            meta = json.loads(d.read_text())
            before = Image.open(d.parent / "before.jpg").convert("RGB")
            after = Image.open(d.parent / "after.jpg").convert("RGB")
            look = Image.open(d.parent / "look.jpg").convert("RGB") if (d.parent / "look.jpg").exists() else None
        except (OSError, ValueError):
            continue
        frame = tuple(meta["frame"]) if meta.get("frame") else None
        out.append((meta, Result(Path(meta["photo"]), meta.get("crop", "none"), meta["recipe"], int(meta.get("seed", 0)),
                                 before, after, meta.get("notes", []), None, look, frame, meta.get("edits") or {})))
    return out


class Keeper:
    """Every couple of seconds, writes the looks that changed (and drops removed ones)."""

    def __init__(self):
        self.stamps: dict[int, tuple] = {}
        self.session = ""
        self.lock = threading.Lock()
        self.started = False

    def start(self):
        if not self.started:
            self.started = True
            threading.Thread(target=self._loop, daemon=True, name="allprophoto-keeper").start()

    def _loop(self):
        while True:
            time.sleep(2.0)
            self.flush()

    def flush(self) -> None:
        with self.lock:
            with S.lock:
                done = [s for s in S.slots.values() if s.state == "done" and s.result is not None]
                live = {str(s.id) for s in S.slots.values()}
            for s in done:
                stamp = (s.ver, id(s.result), s.kept, s.rating)
                if self.stamps.get(s.id) != stamp:
                    try:
                        save_look(s)
                        self.stamps[s.id] = stamp
                    except OSError:
                        pass
            if LOOKS.exists():
                for d in LOOKS.iterdir():
                    if d.is_dir() and d.name not in live:
                        shutil.rmtree(d, ignore_errors=True)
            now = json.dumps(S.saved(), sort_keys=True)
            if now != self.session:
                S.save()
                self.session = now


K = Keeper()


# Updates: the app serves the page it started with; a newer version on disk is offered as a restart

def _snapshot() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in WEB.iterdir() if p.is_file()}


PAGE = _snapshot()


def _code_time() -> float:
    root = Path(__file__).resolve().parents[1]
    return max(p.stat().st_mtime for p in [*root.rglob("*.py"), *WEB.iterdir()] if p.is_file())


STARTED_CODE = _code_time()
_update = {"checked": 0.0, "ready": False}


def update_ready() -> bool:
    if time.time() - _update["checked"] > 10:
        _update["checked"] = time.time()
        try:
            _update["ready"] = _code_time() > STARTED_CODE + 1
        except OSError:
            pass
    return _update["ready"]


# Pictures --------------------------------------------------------------------------------

def jpeg(img: Image.Image, edge: int | None = None, quality: int = 88) -> bytes:
    if edge and max(img.size) > edge:
        img = img.copy()
        img.thumbnail((edge, edge))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


class Cache:
    """Recently served pictures, as JPEG bytes."""

    def __init__(self, size: int):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key, make):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        data = make()
        with self.lock:
            self.items[key] = data
            while len(self.items) > self.size:
                self.items.popitem(last=False)
        return data


PICTURES = Cache(600)
JPEG_HEADERS = {"Cache-Control": "private, max-age=31536000, immutable"}


def picture(data: bytes) -> Response:
    return Response(data, media_type="image/jpeg", headers=JPEG_HEADERS)


# Look previews on your photo ------------------------------------------------------------

def example_file(name: str) -> Path:
    return EXAMPLES / f"{engine.slug(name)}.jpg"


def keep_example(name: str, img: Image.Image) -> None:
    """The look's latest picture, shown in the picker until a photo previews it."""
    try:
        EXAMPLES.mkdir(parents=True, exist_ok=True)
        example_file(name).write_bytes(jpeg(img, SWATCH, 84))
    except OSError:
        pass


def edit_token(pid: int, wanted: bool) -> str:
    """Which edit of the photo the look previews start from ("" = the photo as shot)."""
    slot = _edited_original(pid) if wanted else None
    return f"{slot.id}-{slot.ver}" if slot is not None else ""


def _start_from(pid: int, token: str) -> Path:
    """The picture looks start from: the photo, or the photo as edited (saved once at full size)."""
    slot = _edited_original(pid) if token else None
    if slot is None:
        return S.photo(pid).path
    return E.bake(slot.result, EDITED)


def _swatch(pid: int, name: str, token: str = "") -> bytes | None:
    recipe = presets.load_all().get(name)
    if recipe is None or timing.uses_ai(recipe) or recipe.get("design"):  # (a design shows as saved)
        return None  # the AI looks take 20 s each: shown by their example instead
    recipe = dict(recipe, name=name)
    path = _start_from(pid, token)
    if pipeline.needs_cutout(recipe) and not E.is_cut_out(path, "none"):
        S.cutting.setdefault((str(path), "none"), time.time())
    p = E.ready(path, "none", recipe)
    small = p.image.copy()
    small.thumbnail((SWATCH, SWATCH))
    img, _ = pipeline.render(small, recipe, E.library, p.scene, 0)
    if not token:
        keep_example(name, img)
    return jpeg(img, quality=84)


SWATCHES: dict[tuple[int, str, str], Future] = {}


def swatch_future(pid: int, name: str, token: str = "") -> Future:
    key = (pid, name, token)
    with S.lock:
        fut = SWATCHES.get(key)
        if fut is None or fut.cancelled():
            for k, f in list(SWATCHES.items()):  # another photo's previews: not needed now
                if (k[0] != pid or k[2] != token) and not f.done():
                    f.cancel()
            recipe = presets.load_all().get(name, {})
            slow = pipeline.needs_cutout(recipe) or bool(recipe.get("frame"))  # wait for the cut-out: after the quick ones
            fut = SWATCHES[key] = W.submit(PREVIEW + slow, _swatch, pid, name, token)
        return fut


def _try(pid: int, name: str, token: str = "") -> bytes | None:
    recipe = presets.load_all().get(name)
    if recipe is None or timing.uses_ai(recipe) or recipe.get("design"):
        return None
    recipe = dict(recipe, name=name)
    p = E.ready(_start_from(pid, token), "none", recipe)
    small = p.image.copy()
    small.thumbnail((TRY, TRY))
    img, _ = pipeline.render(small, recipe, E.library, p.scene, 0)
    return jpeg(img, quality=86)


TRIES: dict[tuple[int, str, str], Future] = {}


def try_future(pid: int, name: str, token: str = "") -> Future:
    """One look tried on at a time: moving to another card drops the one not started."""
    key = (pid, name, token)
    with S.lock:
        for k, f in list(TRIES.items()):
            if k != key and not f.done():
                f.cancel()
        fut = TRIES.get(key)
        if fut is None or fut.cancelled():
            fut = TRIES[key] = W.submit(RUN, _try, pid, name, token)
        return fut


# Making looks ------------------------------------------------------------------------------

def _make(slot: Slot, job: Job, crop: str) -> None:
    """One look, on the worker."""
    fresh = not E.is_prepared(job.path, crop)
    extra = timing.PHOTO_READY if fresh else 0.0
    cutting = pipeline.needs_cutout(job.recipe) and not E.is_cut_out(job.path, crop)
    if cutting:
        began = S.cutting.setdefault((str(job.path), crop), time.time())
        extra += max(timing.cut_out() - (time.time() - began), 2.0)  # (it may have begun for the look previews)
        fresh = True
    loading = timing.uses_ai(job.recipe) and not timing.models_loaded()
    if loading:
        extra += timing.MODEL_LOAD
    slot.extra, slot.loading, slot.started, slot.state = extra, loading, time.time(), "now"
    try:
        r = E.look(job, crop)
    except Exception as e:  # one look failing leaves the others
        slot.state, slot.error = "failed", str(e) or type(e).__name__
        return
    took = time.time() - slot.started
    name = job.recipe.get("name", "")
    if not fresh and not loading:
        timing.learn(name, took)
        S.pace.append((took, slot.expect))
    elif cutting and not loading:  # how long the cut-out itself took, for the next estimates
        timing.learn("__cut_out__", max(5.0, took - slot.expect - (timing.PHOTO_READY if extra > timing.cut_out() else 0)))
    design = design_of(job.recipe.get("design"))
    if name in presets.load_all() and not design:
        keep_example(name, r.after)
    future = S.future.get(slot.photo)
    if future:  # removed from every look of this photo, so from this one too
        whole = Result(r.source, "none", {}, 0, r.before, r.after)
        placed = [rm for rm in (_to_look(whole, r, rm) for rm in future) if rm]
        if placed:
            r = dataclasses.replace(r, edits=edits.clean({"removals": placed}))
    if design:  # the preset's poster, text and logos, on this photo
        if job.recipe.get("team_number") and design.get("poster"):  # one of a team's: this player's number, read off their shirt
            design = {**design, "poster": poster.with_player(design["poster"], number=_jersey_number(job.path, crop))}
        r = dataclasses.replace(r, edits=edits.clean({**(r.edits or {}), **design}))
    slot.result, slot.secs, slot.state = r, took, "done"



def start_run(jobs: list[tuple[int, Job]], crop: str, by_photo: list[int] | None = None, priority: int = RUN) -> list[int]:
    """The jobs (photo id, job) as slots, listed in the order given. by_photo: made
    photo by photo in this order instead (so each photo is prepared once)."""
    run = next(S.runs)
    slots = []
    with S.lock:
        for pid, job in jobs:
            name = job.recipe.get("name", "")
            sid = next(S.ids)
            S.slots[sid] = Slot(sid, run, pid, name or "Random look", job.title, timing.seconds(name, job.recipe),
                                crop=crop, cut=pipeline.needs_cutout(job.recipe), ai=timing.uses_ai(job.recipe),
                                source=str(job.path) if job.path != S.photo(pid).path else "")
            slots.append(S.slots[sid])
        order = range(len(jobs))
        if by_photo:
            order = sorted(order, key=lambda i: by_photo.index(jobs[i][0]))
        for i in order:
            slots[i].future = W.submit(priority, _make, slots[i], jobs[i][1], crop)
    return [s.id for s in slots]


# The app -------------------------------------------------------------------------------------

app = FastAPI(title="AllProPhoto")


def prefs() -> dict:
    try:
        return json.loads(PREFS.read_text())
    except (OSError, ValueError):
        return {}


def save_prefs(update: dict) -> None:
    data = prefs() | update
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps(data, indent=1))
    except OSError:
        pass


def looks_list() -> list[dict]:
    all_presets = presets.load_all()
    out = []
    for group, names in presets.grouped(all_presets).items():
        for name in names:
            r = all_presets[name]
            out.append({"name": name, "group": SHORT_GROUPS.get(group, group), "about": presets.describe(name, r),
                        "secs": round(timing.seconds(name, r), 1), "ai": timing.uses_ai(r),
                        "cutout": pipeline.needs_cutout(r) or bool((r.get("design") or {}).get("poster")),
                        "example": example_file(name).exists(), "mine": group == presets.MINE,
                        "design": bool(design_of(r.get("design")))})
    return out


TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png"}


@app.get("/")
def index():
    return Response(PAGE["index.html"], media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/static/{name}")
def static(name: str):
    if name not in PAGE:
        raise HTTPException(404)
    return Response(PAGE[name], media_type=TYPES.get(Path(name).suffix, "application/octet-stream"),
                    headers={"Cache-Control": "no-store"})


@app.post("/api/restart")
def restart():
    """Restarts the app with the newer version (the looks are saved first, and come back)."""
    K.flush()

    def go():
        time.sleep(0.4)
        exe = Path(sys.executable)
        bundle = next((p for p in exe.parents if p.suffix == ".app"), None)
        if bundle is not None:  # the Mac app: open it again once this one has quit
            subprocess.Popen(["/bin/sh", "-c", f"sleep 1.2; open -n '{bundle}'"], start_new_session=True)
            os._exit(0)
        args = [a for a in sys.argv[1:] if a != "--no-browser"] + ["--no-browser"]
        os.execv(sys.executable, [sys.executable, "-m", "photo_presets.studio.server", *args])
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


@app.get("/api/version")
def version():
    """Which version of the code this app is running (for a newer copy opening)."""
    return {"code": STARTED_CODE}


@app.post("/api/quit")
def quit_app():
    """Ends this app (its looks and photos saved first): a newer version is taking over."""
    def go():
        time.sleep(0.3)
        _shut_down()
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


def _shut_down() -> None:
    """Saves everything and ends the app for good, engine and all (nothing left running unseen)."""
    try:
        K.flush()
        S.save()
    finally:
        os._exit(0)


@app.get("/api/state")
def state():
    with S.lock:
        photos = [{"id": p.id, "name": p.name, "edited": _edited_original(p.id) is not None,
                   "edit": edit_token(p.id, True)} for p in S.photos.values()]
        slots = [s.public() for s in S.slots.values()]
        tasks = [t.public() for t in S.tasks.values() if t.state == "running" or time.time() - t.started < 600]
    credit = deliver.Credit.load()
    left, phase = S.progress()
    return {"photos": photos, "slots": slots, "tasks": tasks, "busy": S.busy(), "left": round(left), "phase": phase,
            "update": update_ready(), "player": FIND.public(),
            "models_loaded": timing.models_loaded(), "credit": credit.__dict__,
            "prefs": {"folder": DEFAULT_EXPORT} | prefs()}


@app.get("/api/looks")
def looks():
    groups = []
    for g in presets.GROUPS:
        short = SHORT_GROUPS.get(g, g)
        if short not in groups:
            groups.append(short)
    return {"looks": looks_list(), "groups": groups,
            "sizes": [{"key": deliver.FULL, "label": "Full size", "short": "Full size"}]
            + [{"key": k, "label": s.label, "short": s.label.split(" (")[0]} for k, s in deliver.SIZES.items()]}


# Photos

def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


@app.post("/api/photos/choose")
def choose_photos():
    """The Mac's own file dialog (keeps your photos where they are: RAW, names and dates)."""
    out = _osascript(
        'set fs to choose file with prompt "Add photos" of type {"public.image", "public.camera-raw-image"} '
        'with multiple selections allowed\nset out to ""\nrepeat with f in fs\n'
        'set out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    paths = engine.collect([line for line in out.splitlines() if line.strip()])
    return {"added": S.add_photos(paths)}


@app.post("/api/photos/folder")
def choose_photo_folder():
    folder = choose_folder("Choose a folder of photos", prefs().get("photo_folder", ""))
    if not folder:
        return {"added": []}
    save_prefs({"photo_folder": folder})
    return {"added": S.add_photos(engine.collect([folder]))}


@app.post("/api/photos/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Photos dropped or pasted onto the page."""
    folder = ADDED / time.strftime("%Y-%m-%d %H.%M.%S")
    paths = []
    have = {(p.name, p.path.stat().st_size) for p in S.photos.values() if p.path.exists()}
    for f in files:
        name = re.sub(r'[/:\\]+', "-", Path(f.filename or "photo.jpg").name)
        data = await f.read()
        if (name, len(data)) in have:  # already here (pasted or dropped again)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        dest = engine._unique(folder / name)
        dest.write_bytes(data)
        if images.is_image(dest):
            paths.append(dest)
    return {"added": S.add_photos(paths)}


@app.delete("/api/photos/{pid}")
def remove_photo(pid: int):
    S.remove_photo(pid)
    return {"ok": True}


@app.post("/api/photos/clear")
def clear_photos():
    for pid in list(S.photos):
        S.remove_photo(pid)
    return {"ok": True}


@app.get("/img/photo/{pid}/{size}.jpg")
def photo_image(pid: int, size: str):
    path = S.photo(pid).path
    edge = THUMB if size == "thumb" else VIEW

    def make():
        try:
            return jpeg(images.preview_image(path, edge), quality=86)
        except Exception:
            return jpeg(images.load(path).image, edge, 86)
    return picture(PICTURES.get(("photo", pid, size), make))


@app.post("/api/swatches/{pid}")
async def swatches(pid: int, req: Request):
    """{names: [...], edits: bool}: starts making these looks' cards on the photo (or on the photo
    as edited), and says which are ready (the page asks again until all are)."""
    S.photo(pid)
    body = await req.json()
    token = edit_token(pid, bool(body.get("edits")))
    ready, failed = [], []
    for name in body.get("names", [])[:80]:
        fut = swatch_future(pid, name, token)
        if fut.done():
            (failed if fut.cancelled() or fut.exception() or fut.result() is None else ready).append(name)
    return {"ready": ready, "failed": failed, "token": token}


@app.get("/img/swatch/{pid}/{name}.jpg")
def swatch(pid: int, name: str, e: str = ""):
    fut = SWATCHES.get((pid, name, e))
    if fut is None or not fut.done() or fut.cancelled() or fut.exception() or fut.result() is None:
        raise HTTPException(404, "Not made yet")
    return picture(fut.result())


@app.get("/img/try/{pid}/{name}.jpg")
async def try_on(pid: int, name: str, edits: int = 0):
    S.photo(pid)
    try:
        data = await asyncio.wrap_future(try_future(pid, name, edit_token(pid, bool(edits))))
    except (CancelledError, asyncio.CancelledError):
        raise HTTPException(409, "Another look is being tried on")
    if data is None:
        raise HTTPException(404, "The AI looks are made with Make")
    return picture(data)


@app.get("/img/example/{name}.jpg")
def example(name: str):
    f = example_file(name)
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


# Making looks

@app.post("/api/run")
async def run(req: Request):
    """{photos: [ids], looks: [names] | random: n, crop}: the looks, as slots that fill in."""
    body = await req.json()
    pids = [int(p) for p in body.get("photos", []) if int(p) in S.photos]
    if not pids:
        raise HTTPException(400, "Add a photo first")
    crop = body.get("crop", "none") if body.get("crop") in CROPS else "none"
    run_tag = uuid.uuid4().hex[:6]
    source = {p: S.photo(p).path for p in pids}
    if body.get("from_edits"):  # on top of the photo as edited (where it has been)
        for p in pids:
            slot = _edited_original(p)
            if slot is not None:
                source[p] = await asyncio.wrap_future(W.submit(RUN, E.bake, slot.result, EDITED))
    paths = [source[p] for p in pids]
    if body.get("random"):
        made = E.explore_jobs(paths, int(body["random"]))
        by_path = {str(source[p]): p for p in pids}
        jobs = [(by_path[str(j.path)], j) for j in made]
    else:
        saved = presets.load_all()
        names = [n for n in body.get("looks", []) if n in saved]
        if not names:
            raise HTTPException(400, "Choose at least one look")
        jobs = [(p, Job(source[p], _for_team(dict(saved[n], name=n), n, run_tag), 0)) for n in names for p in pids]
        save_prefs({"crop": crop})
        return {"slots": start_run(jobs, crop, by_photo=pids)}
    save_prefs({"crop": crop})
    return {"slots": start_run(jobs, crop)}


FRAMES: dict[int, Future] = {}


@app.get("/api/photos/{pid}/frames")
async def frames(pid: int):
    """Where Pro, Tight and Face would crop this photo (shares), for showing on it."""
    path = S.photo(pid).path
    with S.lock:
        fut = FRAMES.get(pid)
        if fut is None or fut.cancelled():
            fut = FRAMES[pid] = W.submit(RUN, frame_boxes, path)
    try:
        return await asyncio.wrap_future(fut)
    except Exception:
        FRAMES.pop(pid, None)
        return {"wide": None, "crop": None, "face": None}


ORIGINAL = {"name": "Original", "description": "The photo as shot, to edit as it is", "steps": []}


def _edited_original(pid: int) -> "Slot | None":
    """The photo's own picture, edited (light, color, crop, removals...): to make looks on top of."""
    with S.lock:
        for s in S.slots.values():
            if s.photo == pid and s.look == "Original" and s.state == "done" and s.result is not None:
                r = s.result
                e = {k: v for k, v in (r.edits or {}).items() if k not in ("texts", "logos", "poster")}
                if edits.edited(e) or pipeline.adjusted(r.recipe):
                    return s
    return None


@app.post("/api/photos/{pid}/original")
def original(pid: int):
    """The photo itself as a picture to edit (no look): made once, then reused."""
    S.photo(pid)
    with S.lock:
        for s in S.slots.values():
            if s.photo == pid and s.look == "Original" and s.crop == "none" and s.state != "failed":
                return {"slot": s.id}
    with S.lock:  # you are waiting on this: the look previews of other photos are dropped, and it goes first
        for k, f in list(SWATCHES.items()):
            if k[0] != pid and not f.done():
                f.cancel()
    return {"slot": start_run([(pid, Job(S.photo(pid).path, dict(ORIGINAL), 0))], "none", priority=FIX)[0]}


@app.post("/api/run/stop")
def stop():
    with S.lock:
        for sid, s in list(S.slots.items()):
            if s.state == "wait" and s.future is not None and s.future.cancel():
                del S.slots[sid]
    return {"ok": True}


@app.post("/api/slots/{sid}/use_on_all")
def use_on_all(sid: int):
    """This look, with its fine-tuning, on every other photo."""
    s = S.slot(sid)
    r = s.result
    others = [p for p in S.photos.values() if p.id != s.photo]
    if not others:
        raise HTTPException(400, "Add more photos to use this look on them")
    jobs = [(p.id, Job(p.path, dict(r.recipe, name=r.name), i)) for i, p in enumerate(others)]
    return {"slots": start_run(jobs, r.crop)}


@app.post("/api/slots/remove")
async def remove_slots(req: Request):
    """Takes looks out (finished ones can be put back for a while: /api/slots/restore)."""
    ids = set((await req.json()).get("ids", []))
    gone = []
    with S.lock:
        order = list(S.slots)
        for sid in ids:
            s = S.slots.get(sid)
            if s and s.state not in ("now",) and (s.future is None or s.future.done() or s.future.cancel()):
                del S.slots[sid]
                if s.state == "done":
                    S.trash[sid] = (order.index(sid), s)
                    gone.append(sid)
        for sid in [k for k, (_, s) in S.trash.items() if k not in gone and len(S.trash) > 300]:
            S.trash.pop(sid, None)
    return {"removed": gone}


@app.post("/api/slots/restore")
async def restore_slots(req: Request):
    """Puts removed looks back where they were (undo)."""
    ids = (await req.json()).get("ids", [])
    with S.lock:
        items = list(S.slots.items())
        for sid in sorted(ids, key=lambda i: S.trash.get(i, (0,))[0]):
            if sid in S.trash:
                at, s = S.trash.pop(sid)
                items.insert(min(at, len(items)), (sid, s))
                K.stamps.pop(sid, None)  # saved again
        S.slots = OrderedDict(items)
    return {"ok": True}


@app.post("/api/slots/keep")
async def keep(req: Request):
    body = await req.json()
    with S.lock:
        for sid in body.get("ids", []):
            if sid in S.slots:
                S.slots[sid].kept = bool(body.get("on", True))
    return {"ok": True}


async def traced(r: Result) -> None:
    """The parts the result's edits adjust, traced (on the worker: it uses the AI model)."""
    for a in (r.edits or {}).get("areas", []):
        await asyncio.wrap_future(W.submit(FIX, E.part, r, a["x"], a["y"], 8, 8))


def _variant(r: Result, kind: str) -> bytes:
    """after: the picture as edited, without its text (the page draws the text, to move it);
    thumb, full: with its text; before: the original, straightened and cropped the same;
    base: parts adjusted, not yet straightened or cropped (for cropping and brushing);
    area-N: base with part N shown in blue."""
    arr = E.base_after(r)
    if kind == "before":
        return jpeg(pipeline.to_image(edits.geometry(pipeline.to_array(r.before), r.edits)), quality=90)
    if kind == "base":
        return jpeg(pipeline.to_image(E.finalize(r, arr, geometry=False, texts=False, removals=False)), quality=90)
    if kind.startswith("area-"):
        base = E.finalize(r, arr, geometry=False, texts=False, removals=False)
        areas = (r.edits or {}).get("areas", [])
        i = int(kind[5:])
        if 0 <= i < len(areas):
            m = E.part(r, areas[i]["x"], areas[i]["y"], *base.shape[:2])[..., None] * 0.5
            base = base * (1 - m) + engine.CUTOUT_TINT * m
        return jpeg(pipeline.to_image(base), quality=88)
    if kind == "thumb":
        return jpeg(pipeline.to_image(E.finalize(r, arr, removals=False)), THUMB, 84)
    if kind == "full":
        return jpeg(pipeline.to_image(E.finalize(r, arr, removals=False)), quality=92)
    return jpeg(pipeline.to_image(E.finalize(r, arr, texts=False, removals=False)), quality=90)


@app.get("/img/slot/{sid}/{ver}/{kind}.jpg")
async def slot_image(sid: int, ver: int, kind: str):
    s = S.slot(sid)
    r = s.result
    if kind == "fix":
        return picture(jpeg(await asyncio.to_thread(E.fix_view, r), quality=88))
    if kind not in ("after", "thumb", "full", "before", "base") and not re.fullmatch(r"area-\d+", kind):
        raise HTTPException(404)
    if not edits.edited(r.edits):  # nothing to work out
        if kind == "before":
            return picture(PICTURES.get(("before", sid), lambda: jpeg(r.before, quality=90)))
        if kind == "thumb":
            return picture(PICTURES.get(("thumb", sid, s.ver), lambda: jpeg(r.after, THUMB, 84)))
        if kind in ("after", "full", "base"):
            return picture(PICTURES.get(("after", sid, s.ver), lambda: jpeg(r.after, quality=90)))
    await traced(r)
    data = await asyncio.to_thread(PICTURES.get, (kind, sid, s.ver), lambda: _variant(r, kind))
    return picture(data)


def _zoomed(r: Result) -> tuple[bytes, bytes]:
    """The look and the photo at ZOOM px, for checking faces and focus (the AI
    drawing is reused, so this is quick)."""
    p = E.ready(r.source, r.crop, r.recipe)
    img = p.image.copy()
    img.thumbnail((ZOOM, ZOOM))
    after, _ = pipeline.render(img, r.recipe, E.library, p.scene, r.seed, E.drawings,
                               E.memo_key(r.source, r.crop, r.recipe, p.frame))
    if edits.edited(r.edits):
        after = pipeline.to_image(E.finalize(r, pipeline.to_array(after), texts=False))
        img = pipeline.to_image(edits.geometry(pipeline.to_array(img), r.edits))
    return jpeg(after, quality=90), jpeg(img, quality=90)


@app.get("/img/zoom/{sid}/{ver}/{kind}.jpg")
async def zoom_image(sid: int, ver: int, kind: str):
    s = S.slot(sid)
    key = ("zoom", sid, s.ver)
    with PICTURES.lock:
        pair = PICTURES.items.get(key)
    if pair is None:
        pair = await asyncio.wrap_future(W.submit(FIX, _zoomed, s.result))
        with PICTURES.lock:
            PICTURES.items[key] = pair
    return picture(pair[1] if kind == "before" else pair[0])


def _adj(body: dict) -> dict:
    """The sliders from the page (any left out stay at their default)."""
    return {k: type(v)(body.get(k, v)) for k, v in pipeline.ADJUST.items()}


@app.post("/api/slots/{sid}/adjust")
async def adjust(sid: int, req: Request):
    """The fine-tune sliders: instant, the look is not made again."""
    s = S.slot(sid)
    adj = _adj(await req.json())
    r = await asyncio.to_thread(E.adjust, s.result, adj)
    with S.lock:
        s.result, s.ver = r, s.ver + 1
    return s.public()


@app.post("/api/slots/{sid}/edit")
async def edit(sid: int, req: Request):
    """{adjust: {...}, edits: {...}}: the picture's sliders and its edits (each one given is replaced whole)."""
    s = S.slot(sid)
    body = await req.json()
    new = edits.clean(body["edits"]) if "edits" in body else None
    if new is not None:  # the slow part first (tracing parts, filling removals) ...
        await traced(dataclasses.replace(s.result, edits=new))
    async with s.edit_lock:  # ... then applied to the latest picture, one change at a time
        r = s.result
        if "adjust" in body:
            r = await asyncio.to_thread(E.adjust, r, _adj(body["adjust"]))
        if new is not None:
            r = dataclasses.replace(r, edits=new)
        with S.lock:
            s.result, s.ver = r, s.ver + 1
    return s.public()


@app.post("/api/slots/{sid}/whitebalance")
async def white_balance(sid: int, req: Request):
    """{x, y}: a click on something that should be white or gray (shares of the picture shown)."""
    s = S.slot(sid)
    body = await req.json()
    async with s.edit_lock:
        r = s.result
        await traced(r)
        shown = await asyncio.to_thread(lambda: E.finalize(r, E.base_after(r), texts=False, removals=False))
        if not edits.neutral_enough(shown, float(body["x"]), float(body["y"])):
            raise HTTPException(400, "That spot has a color of its own. Click something that should be white or "
                                     "gray: a white kit, a line, a cloud.")
        adj = pipeline.adjustments(r.recipe)
        adj["warmth"], adj["tint"] = edits.white_balance(shown, float(body["x"]), float(body["y"]), adj["warmth"],
                                                         adj["tint"])
        r = await asyncio.to_thread(E.adjust, r, adj)
        with S.lock:
            s.result, s.ver = r, s.ver + 1
    return s.public()


@app.get("/api/slots/{sid}/level")
async def level(sid: int):
    """The turn that levels the picture (from its field lines, horizon and posts)."""
    r = S.slot(sid).result
    return {"angle": await asyncio.to_thread(edits.level_angle, pipeline.to_array(r.before))}


@app.post("/api/slots/rate")
async def rate(req: Request):
    body = await req.json()
    with S.lock:
        for sid in body.get("ids", []):
            if sid in S.slots:
                S.slots[sid].rating = int(max(0, min(5, int(body.get("rating", 0)))))
    return {"ok": True}


def _to_look(src: Result, dst: Result, removal: dict) -> dict | None:
    """A removal made on one look of a photo, placed on another look of it (their crops can
    differ); None when it falls outside that look's picture."""
    scale = E.photo_scale(src) / max(E.photo_scale(dst), 1e-6)
    move = lambda x, y: list(E.from_photo(dst, *E.to_photo(src, x, y)))
    points = [move(x, y) for x, y in removal.get("points", [])]
    points = [p for p in points if 0 <= p[0] <= 1 and 0 <= p[1] <= 1]
    strokes = [{"pts": [move(x, y) for x, y in st["pts"]], "r": st["r"] * scale} for st in removal.get("strokes", [])]
    strokes = [st for st in strokes if any(-0.05 <= x <= 1.05 and -0.05 <= y <= 1.05 for x, y in st["pts"])]
    return {"points": points, "strokes": strokes} if points or strokes else None


def _removal(body: dict) -> dict:
    return {"points": [[float(x), float(y)] for x, y in body.get("points", [])],
            "strokes": [{"pts": [[float(x), float(y)] for x, y in st.get("pts", [])], "r": float(st.get("r", 0.02))}
                        for st in body.get("strokes", [])]}


@app.post("/api/slots/{sid}/remove/preview")
async def remove_preview(sid: int, req: Request):
    """{points, strokes}: what would be removed, as a picture to lay over this look (red where it goes)."""
    s = S.slot(sid)
    removal = _removal(await req.json())
    w, h = s.result.after.size

    def make() -> bytes:
        m = E.removal_mask(s.result, removal, h, w)
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[m] = (255, 60, 90, 150)
        edge = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
        rgba[edge] = (255, 255, 255, 230)
        buf = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, "PNG")
        return buf.getvalue()
    data = await asyncio.wrap_future(W.submit(FIX, make))
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/slots/{sid}/people")
async def background_people(sid: int):
    """The people in this look who are not the players kept (a click on each removes them)."""
    s = S.slot(sid)

    def find():
        found = E.people_in(s.result)
        matte = E.cutout(s.result)
        out = []
        for m in found:
            ys, xs = np.nonzero(m)
            if not len(ys):
                continue
            if matte is not None:
                mm = cv2.resize(matte, (m.shape[1], m.shape[0])) > 0.5
                if (mm & m).sum() > 0.3 * m.sum():
                    continue  # a player kept in the look
            # a point well inside them: the middle of their body
            cy = int(np.median(ys)); row = np.nonzero(m[cy])[0]
            cx = int(np.median(row)) if len(row) else int(np.median(xs))
            out.append({"x": cx / m.shape[1], "y": cy / m.shape[0],
                        "box": [xs.min() / m.shape[1], ys.min() / m.shape[0], xs.max() / m.shape[1], ys.max() / m.shape[0]]})
        return out
    return {"people": await asyncio.wrap_future(W.submit(FIX, find))}


@app.post("/api/slots/{sid}/remove")
async def remove_from_looks(sid: int, req: Request):
    """{points, strokes, scope: "look" | "photo"}: removes what was clicked or brushed from this
    look, or from every look of this photo (and the looks made of it later). Quick: the looks are
    not made again, each just has it filled in."""
    s = S.slot(sid)
    body = await req.json()
    removal = _removal(body)
    if not removal["points"] and not removal["strokes"]:
        raise HTTPException(400, "Click or brush over what should go")
    targets = [s]
    if body.get("scope") == "photo":
        targets += [o for o in S.slots.values() if o is not s and o.photo == s.photo and o.result is not None]
        X = [list(E.to_photo(s.result, x, y)) for x, y in removal["points"]]
        strokes = [{"pts": [list(E.to_photo(s.result, x, y)) for x, y in st["pts"]], "r": st["r"] * E.photo_scale(s.result)}
                   for st in removal["strokes"]]
        S.future.setdefault(s.photo, []).append({"points": X, "strokes": strokes})

    placed = [(o, removal if o is s else _to_look(s.result, o.result, removal)) for o in targets]
    placed = [(o, rm) for o, rm in placed if rm is not None]

    def with_it(o, rm):
        e = dict(o.result.edits or {})
        e["removals"] = list(e.get("removals", [])) + [rm]
        return dataclasses.replace(o.result, edits=edits.clean(e))

    def apply():  # worked out now (the slow part), so the pictures show at once
        for o, rm in placed:
            E.finished(with_it(o, rm), texts=False)
    await asyncio.wrap_future(W.submit(FIX, apply))
    for o, rm in placed:  # added to each look as it is now (a slider may have moved meanwhile)
        async with o.edit_lock:
            with S.lock:
                o.result, o.ver = with_it(o, rm), o.ver + 1
    return {"slots": [o.public() for o in targets], "future": S.future.get(s.photo, [])}


@app.post("/api/photos/{pid}/future_removals")
async def future_removals(pid: int, req: Request):
    """{removals}: what new looks of this photo have removed (undo and redo)."""
    S.photo(pid)
    S.future[pid] = (await req.json()).get("removals", [])
    return {"ok": True}


@app.post("/api/slots/{sid}/adjust_look")
async def adjust_look(sid: int, req: Request):
    """These settings on every picture with the same look."""
    s = S.slot(sid)
    adj = _adj(await req.json())
    same = [o for o in S.slots.values() if o.result is not None and o.result.name == s.result.name]

    def go():
        for o in same:
            o.result, o.ver = E.adjust(o.result, adj), o.ver + 1
    await asyncio.to_thread(go)
    return {"count": len(same)}


@app.post("/api/slots/{sid}/save_preset")
async def save_preset(sid: int, req: Request):
    body = await req.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Give the preset a name")
    s = S.slot(sid)
    recipe = dict(s.result.recipe)
    recipe.pop("match", None)  # a game match belongs to its photo, not to the look
    recipe.pop("name", None)
    recipe.pop("design", None)
    design = design_of(s.result.edits) if body.get("design", True) else {}
    if design:  # the poster, text and logos go with it: made on any photo, the same design
        recipe["design"] = design
        recipe["description"] = "Your design: " + ", ".join(design_words(design))
    presets.save(name, recipe)
    shown = await asyncio.wrap_future(W.submit(FIX, E.finished, s.result)) if design else s.result.after
    keep_example(name, shown)
    return {"name": name}


POSTERS_FILE = (STATE or CONFIG) / "posters.json"  # your saved posters (their layout, words, text and logos)


def saved_posters() -> list[dict]:
    try:
        return json.loads(POSTERS_FILE.read_text())
    except (OSError, ValueError):
        return []


@app.post("/api/poster/words")
async def poster_words(req: Request):
    """{poster, logo}: where each of its words sits (shares), for clicking one on the picture."""
    body = await req.json()
    p = body.get("poster") or {}
    art = brand.load(E.brand_dir, p.get("logo") or "") if p.get("logo") else None
    return {"words": await asyncio.to_thread(poster.words, p, bool(body.get("logo")), art)}


@app.post("/api/poster/customize")
async def poster_customize(req: Request):
    """{poster}: the same poster as a custom one (its words and panels as pieces to move and restyle)."""
    body = await req.json()
    p = body.get("poster") or {}
    return {"poster": await asyncio.to_thread(poster.customized, p, bool(p.get("logo")))}


@app.get("/api/posters")
def list_posters():
    return {"posters": [{"name": p["name"], "about": ", ".join(design_words(p["design"]))} for p in saved_posters()]}


@app.post("/api/posters")
async def save_poster(req: Request):
    """{name, slot}: the picture's poster (with its text and logos) saved, to put any picture into."""
    body = await req.json()
    name = (body.get("name") or "").strip()[:40]
    if not name:
        raise HTTPException(400, "Give the poster a name")
    design = design_of(S.slot(int(body["slot"])).result.edits)
    if not design.get("poster"):
        raise HTTPException(400, "This picture has no poster yet: pick a layout above first")
    kept = [p for p in saved_posters() if p["name"] != name] + [{"name": name, "design": design}]
    POSTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSTERS_FILE.write_text(json.dumps(kept, indent=1))
    return {"name": name}


@app.get("/api/posters/{name}")
def get_poster(name: str):
    for p in saved_posters():
        if p["name"] == name:
            return p
    raise HTTPException(404, "That poster is no longer saved")


@app.delete("/api/posters/{name}")
def delete_poster(name: str):
    POSTERS_FILE.write_text(json.dumps([p for p in saved_posters() if p["name"] != name], indent=1))
    return {"ok": True}


DESIGN = ("poster", "texts", "logos")  # the parts of a picture's edits that fit any photo


def _for_team(recipe: dict, name: str, tag: str) -> dict:
    """A saved preset with a poster, made on photos: one team family per look and run (so the team list
    shows them together), each player's name left to type and number read off their shirt."""
    d = recipe.get("design") or {}
    if not d.get("poster"):
        return recipe
    first = {k: v for k, v in d["poster"].items() if k != "pic"}
    family = (tag + uuid.uuid5(uuid.NAMESPACE_DNS, name).hex)[:12]
    return {**recipe, "design": {**d, "poster": poster.with_player({**first, "family": family}, name="NAME", number="")},
            "team_number": True}


def _jersey_number(path: Path, crop: str) -> str:
    """The number on the main player's shirt in this photo (read by the Mac), or "" when it can't be read."""
    try:
        sc = players.scan(path)
        p = E.prepared(path, crop)
        fx, fy = engine.focus(p.scene)
        if p.box is not None:  # (a cropped photo: back to the whole photo's shares)
            x0, y0, x1, y1 = p.box
            fx, fy = x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)
        who = players.at(sc, fx, fy)
        if who is None and sc.people:
            who = min(sc.people, key=lambda s: ((s.box[0] + s.box[2]) / 2 - fx) ** 2 + ((s.box[1] + s.box[3]) / 2 - fy) ** 2)
        return (who.number or "") if who else ""
    except Exception:
        return ""


@app.post("/api/slots/{sid}/team")
async def team_posters(sid: int, req: Request):
    """{photos: [ids]}: this picture's poster (and look) made for each of these photos: one family, each
    with the player's number read off their shirt and the name left for you to type."""
    s = S.slot(sid)
    design = design_of(s.result.edits)
    if not design.get("poster"):
        raise HTTPException(400, "Make a poster on this picture first")
    pids = [int(p) for p in (await req.json()).get("photos", []) if int(p) in S.photos and int(p) != s.photo]
    if not pids:
        raise HTTPException(400, "Choose the other players' photos")
    family = design["poster"].get("family") or uuid.uuid4().hex[:8]
    if not design["poster"].get("family"):  # this picture is the first of the family
        async with s.edit_lock:
            e = dict(s.result.edits or {})
            e["poster"] = {**e["poster"], "family": family}
            with S.lock:
                s.result, s.ver = dataclasses.replace(s.result, edits=edits.clean(e)), s.ver + 1
    first = {k: v for k, v in design["poster"].items() if k != "pic"}  # (each photo starts framed on its own player)
    d = {**design, "poster": poster.with_player({**first, "family": family}, name="NAME", number="")}
    recipe = {k: v for k, v in s.result.recipe.items() if k not in ("match", "design", "team_number")}
    recipe.update(name=s.look if s.look != "Original" else "Poster", design=d, team_number=True)
    jobs = [(p, Job(S.photo(p).path, dict(recipe), 0)) for p in pids]
    return {"slots": start_run(jobs, s.crop, by_photo=pids), "family": family}


def design_of(e: dict | None) -> dict:
    return {k: v for k, v in (e or {}).items() if k in DESIGN and v}


def design_words(d: dict) -> list[str]:
    out = []
    if d.get("poster"):
        out.append(f"{poster.TEMPLATES.get(d['poster'].get('template'), 'a')} poster")
    if d.get("texts"):
        out.append("your text" if len(d["texts"]) == 1 else f"{len(d['texts'])} texts")
    if d.get("logos"):
        out.append("your logo")
    return out


@app.post("/api/slots/{sid}/match")
async def match(sid: int):
    """Every photo's exposure and white balance evened out to this one's, its looks made again."""
    ref = S.slot(sid)
    done = [s for s in S.slots.values() if s.result is not None]
    out, changed = await asyncio.wrap_future(W.submit(RUN, E.match_game, [s.result for s in done], ref.result))
    for s, r in zip(done, out):
        if r is not s.result:
            s.result, s.ver = r, s.ver + 1
    return {"changed": changed}


@app.post("/api/match/clear")
async def clear_match():
    done = [s for s in S.slots.values() if s.result is not None]
    out = await asyncio.wrap_future(W.submit(RUN, E.clear_match, [s.result for s in done]))
    for s, r in zip(done, out):
        if r is not s.result:
            s.result, s.ver = r, s.ver + 1
    return {"ok": True}


# Fixing the cut-out

@app.post("/api/slots/{sid}/fix")
async def fix(sid: int, req: Request):
    """{x, y (shares of the picture), add} a click; {undo: true}; {reset: true}."""
    s = S.slot(sid)
    body = await req.json()
    r = s.result
    fixes = E.fixes_for(r)
    if body.get("reset"):
        fixes = []
    elif body.get("undo"):
        fixes = fixes[:-1]
    else:
        x, y = engine.from_frame(r.frame, float(body["x"]), float(body["y"]))
        fixes.append(Fix(round(x, 4), round(y, 4), bool(body.get("add", True))))
    await asyncio.wrap_future(W.submit(FIX, E.set_fixes, r, fixes))
    return {"fixes": len(fixes)}


@app.post("/api/slots/{sid}/remake")
async def remake(sid: int):
    """Every look of this photo made again with its fixed cut-out."""
    s = S.slot(sid)
    same = [o for o in S.slots.values() if o.result is not None and o.result.source == s.result.source
            and o.result.crop == s.result.crop]
    for o in same:
        o.state, o.started, o.extra, o.loading = "now", time.time(), 0.0, False
        r = await asyncio.wrap_future(W.submit(RUN, E.remake, o.result))
        o.result, o.ver, o.state = r, o.ver + 1, "done"
    return {"count": len(same)}


# Export

FILES, ZIP = "files", "zip"


@app.post("/api/export")
async def export(req: Request):
    """{ids, how, kind, sizes, folder, credit: {...}, watermark: {on, text, style, opacity}}"""
    body = await req.json()
    chosen = [S.slots[i].result for i in body.get("ids", []) if i in S.slots and S.slots[i].result is not None]
    if not chosen:
        raise HTTPException(400, "Choose at least one picture")
    sizes = [k for k in body.get("sizes", [deliver.FULL]) if k == deliver.FULL or k in deliver.SIZES]
    if not sizes:
        raise HTTPException(400, "Choose at least one size")
    kind = body.get("kind", engine.JPEG)
    how = body.get("how", FILES)
    dest = Path(body.get("folder") or DEFAULT_EXPORT).expanduser()
    c = body.get("credit") or {}
    credit = deliver.Credit(c.get("creator", ""), c.get("copyright", ""), c.get("contact", ""))
    if credit != deliver.Credit.load():
        credit.save()  # remembered for next time
    w = body.get("watermark") or {}
    mark = None
    if w.get("on"):
        text = (w.get("text") or "").strip() or credit.notice() or "PROOF"
        mark = deliver.Watermark(text, w.get("style", deliver.CORNER), float(w.get("opacity", 0.5)))
    logo = body.get("logo") if (body.get("logo") or {}).get("on") else None
    save_prefs({"folder": str(dest), "how": how, "kind": kind, "sizes": sizes,
                "watermark": {k: w.get(k) for k in ("on", "text", "style", "opacity")},
                "logo": {k: (body.get("logo") or {}).get(k) for k in ("on", "id", "corner", "size", "color")}})
    recipes = bool(body.get("recipes"))
    save_prefs({"recipes": recipes})
    task = Task(next(S.ids), "export", len(chosen), now=chosen[0].title)
    S.tasks[task.id] = task
    W.submit(OUTPUT, _export, task, chosen, dest, how, kind, sizes, credit, mark, logo, recipes)
    return task.public()


def _export(task: Task, chosen, dest: Path, how, kind, sizes, credit, mark, logo=None, recipes=False) -> None:
    def tick(done, total, name):
        task.done, task.now = done, name
    try:
        n = len(chosen)
        photos = f"{n} picture{'s' if n != 1 else ''}"
        stamp = f"AllProPhoto {time.strftime('%Y-%m-%d %H.%M.%S')} ({photos})"
        # separate files go in a folder of their own (never scattered over the Desktop)
        into = Path(tempfile.mkdtemp(prefix="allprophoto-zip-")) if how == ZIP else engine._unique(dest / stamp)
        saved, notes = E.export(chosen, into, tick, kind, sizes, credit, mark, logo, recipes)
        if how == ZIP:
            dest.mkdir(parents=True, exist_ok=True)
            zipped = engine._unique(dest / f"{stamp}.zip")
            with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(into.rglob("*")):
                    if f.is_file():
                        z.write(f, f.relative_to(into))
            shutil.rmtree(into, ignore_errors=True)
            task.path, task.message = str(zipped), f"Saved {photos} in {zipped.name}"
        else:
            task.path = str(saved[0]) if saved else str(into)
            task.message = f"Saved {photos} in {dest.name} › {into.name}" + (f" ({len(saved)} files)" if len(saved) != n else "")
        if notes:
            task.message += ". " + "; ".join(notes)
        task.state = "done"
    except Exception as e:
        task.state, task.message = "failed", f"Export failed: {e}"


# Finding a player in every photo --------------------------------------------------------------

class Finder:
    """The player you clicked, the photos with them, and your answers to "Is this your player?"."""

    def __init__(self):
        self.target: tuple[str, int] | None = None  # (photo path, person)
        self.yes: list[tuple[str, int]] = []
        self.no: list[tuple[str, int]] = []
        self.scans: dict[str, "players.Scan"] = {}
        self.results: list[dict] = []

    def sighting(self, key):
        sc = self.scans.get(key[0])
        return sc.people[key[1]] if sc and key[1] < len(sc.people) else None

    def run(self) -> list[dict]:
        if not self.target:
            return []
        t = self.sighting(self.target)
        faces = lambda keys: [f for f in (getattr(self.sighting(k), "face", None) for k in keys) if f is not None]
        found = players.find(list(self.scans.values()), t, faces(self.yes), faces(self.no))
        by_path = {str(p.path): p.id for p in S.photos.values()}
        answered = {tuple(k): "yes" for k in self.yes} | {tuple(k): "no" for k in self.no}
        out = []
        for h in found:
            key = (h["path"], h["person"])
            if answered.get(key) == "no":
                continue
            if answered.get(key) == "yes" or key == self.target:
                h["status"] = "sure"
            if h["path"] in by_path:
                out.append(h | {"photo": by_path[h["path"]]})
        self.results = out
        return out

    def public(self) -> dict | None:
        if not self.target:
            return None
        pid = next((p.id for p in S.photos.values() if str(p.path) == self.target[0]), None)
        return {"photo": pid, "person": self.target[1], "results": self.results,
                "sure": sum(h["status"] == "sure" for h in self.results),
                "ask": sum(h["status"] == "maybe" for h in self.results),
                "best": [h["photo"] for h in self.results if h["status"] == "sure" and h["best"]]}


FIND = Finder()


@app.get("/api/players/people/{pid}")
async def people_in_photo(pid: int):
    """Everyone the app sees in this photo (boxes, shares), to click your player."""
    path = S.photo(pid).path
    sc = await asyncio.wrap_future(W.submit(FIX, players.scan, path))
    FIND.scans[str(path)] = sc
    return {"people": [{"person": i, "box": s.box, "face": s.face is not None, "number": s.number}
                       for i, s in enumerate(sc.people)]}


@app.post("/api/players/find")
async def find_player(req: Request):
    """{photo, person}: looks at every photo for this player (each photo once), then lists them."""
    body = await req.json()
    path = str(S.photo(int(body["photo"])).path)
    FIND.target, FIND.yes, FIND.no, FIND.results = (path, int(body["person"])), [], [], []
    todo = [p for p in S.photos.values() if str(p.path) not in FIND.scans]
    task = Task(next(S.ids), "find", len(todo), now="Looking at the photos")
    S.tasks[task.id] = task

    def go():
        try:
            for i, p in enumerate(todo):
                task.now = p.name
                try:
                    FIND.scans[str(p.path)] = players.scan(p.path)
                except Exception:
                    pass
                task.done = i + 1
            FIND.run()
            sure = sum(h["status"] == "sure" for h in FIND.results)
            task.message = f"Found them in {plural_s(sure, 'photo')}" + (
                f"; {plural_s(sum(h['status'] == 'maybe' for h in FIND.results), 'more')} to check" if any(
                    h["status"] == "maybe" for h in FIND.results) else "")
            task.state = "done"
        except Exception as e:
            task.state, task.message = "failed", f"Could not look through the photos: {e}"
    W.submit(RUN, go)
    return task.public()


def plural_s(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 or word.endswith("more") else "s")


@app.post("/api/players/answer")
async def answer(req: Request):
    """{photo, person, yes}: is this your player? The list is worked out again with it."""
    body = await req.json()
    key = (str(S.photo(int(body["photo"])).path), int(body["person"]))
    for lst in (FIND.yes, FIND.no):
        if key in lst:
            lst.remove(key)
    (FIND.yes if body.get("yes") else FIND.no).append(key)
    await asyncio.to_thread(FIND.run)
    return FIND.public()


@app.get("/api/players")
def player_state():
    return FIND.public() or {}


@app.post("/api/players/clear")
def clear_player():
    FIND.target, FIND.results = None, []
    return {"ok": True}


@app.get("/img/person/{pid}/{person}.jpg")
async def person_face(pid: int, person: int):
    """A close-up of one person's head and shoulders, for asking about them."""
    path = S.photo(pid).path
    sc = FIND.scans.get(str(path)) or await asyncio.wrap_future(W.submit(FIX, players.scan, path))
    if person >= len(sc.people):
        raise HTTPException(404)
    x0, y0, x1, y1 = sc.people[person].box

    def crop():
        img = images.preview_image(path, 2048)
        W, H = img.size
        bh = (y1 - y0) * H
        box = (int(x0 * W), int(y0 * H), int(x1 * W), int(y0 * H + max(bh * 0.5, (x1 - x0) * W)))
        return jpeg(img.crop(box), 320, 86)
    return picture(PICTURES.get(("person", pid, person), crop))


# The brand kit: logos kept ready to put on pictures

@app.get("/api/logos")
def logos():
    return {"logos": brand.listing(E.brand_dir)}


@app.post("/api/logos")
async def add_logo(file: UploadFile = File(...)):
    """A logo for the kit, any way it comes (PNG, JPG on white, SVG, PDF, Illustrator, a screenshot): made transparent."""
    data = await file.read()
    try:
        img = await asyncio.to_thread(brand.open_any, data, file.filename or "")
    except brand.NotALogo as e:
        raise HTTPException(400, str(e))
    name = Path(file.filename or "Logo").stem[:40]
    return await asyncio.wrap_future(W.submit(FIX, brand.add, E.brand_dir, img, name))


@app.delete("/api/logos/{lid}")
def delete_logo(lid: str):
    brand.remove_logo(E.brand_dir, lid)
    return {"ok": True}


@app.get("/img/logo/{lid}/{color}.png")
def logo_image(lid: str, color: str):
    art = brand.load(E.brand_dir, lid)
    if art is None:
        raise HTTPException(404)
    buf = io.BytesIO()
    brand.colored(art, color).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-cache"})


SHARES = ("airdrop", "messages", "mail", "photos")


@app.post("/api/slots/{sid}/share")
async def share(sid: int, req: Request):
    """{service: airdrop | messages | mail | photos}: the picture full size (a JPEG with your
    name and copyright, its edits and text), sent the Mac way, or added to Photos (and so to
    your iPhone through iCloud)."""
    s = S.slot(sid)
    service = (await req.json()).get("service")
    if service not in SHARES:
        raise HTTPException(400, "Unknown way to share")
    task = Task(next(S.ids), "share", 1, now=s.result.title)
    S.tasks[task.id] = task
    W.submit(OUTPUT, _share, task, s.result, service)
    return task.public()


def _share(task: Task, r: Result, service: str) -> None:
    try:
        folder = WORK / "share" / str(task.id)
        saved, _ = E.export([r], folder, None, engine.JPEG, [deliver.FULL], deliver.Credit.load(), None)
        path = saved[0]
        task.done, task.path = 1, str(path)
        if service == "photos":
            script = f'tell application "Photos" to import POSIX file "{path}" skip check duplicates true'
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if out.returncode != 0:
                raise RuntimeError(out.stderr.strip() or "Photos did not take it")
            task.message = "Added to Photos (it reaches your iPhone through iCloud Photos)"
        else:
            import os
            env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
            subprocess.Popen([sys.executable, "-m", "photo_presets.studio.share", service, str(path)], env=env)
            task.message = {"airdrop": "AirDrop is open: pick your iPhone",
                            "messages": "Messages is open with the picture",
                            "mail": "Mail is open with the picture"}[service]
        task.state = "done"
    except Exception as e:
        task.state, task.message = "failed", f"Could not share: {e}"


@app.post("/api/folder/choose")
async def choose_export_folder(req: Request):
    start = (await req.json()).get("folder") or DEFAULT_EXPORT
    folder = await asyncio.to_thread(choose_folder, "Choose where to export", start)
    if folder:
        save_prefs({"folder": folder})
    return {"folder": folder}


@app.post("/api/open")
async def open_url(req: Request):
    """A page of this app in your web browser (the classic tools)."""
    path = str((await req.json()).get("path") or "/")
    if path.startswith("/"):
        subprocess.run(["open", str(req.base_url).rstrip("/") + path])
    return {"ok": True}


@app.post("/api/reveal")
async def reveal(req: Request):
    """Shows a file (or a folder) in Finder."""
    path = Path((await req.json()).get("path") or DEFAULT_EXPORT).expanduser()
    if path.is_file():
        subprocess.run(["open", "-R", str(path)])
    elif path.is_dir():
        subprocess.run(["open", str(path)])
    return {"ok": True}


@app.post("/api/notify")
async def notify(req: Request):
    """A Mac notification (when a run or an export finishes while you are in another app)."""
    body = await req.json()

    def q(text) -> str:
        return '"' + str(text or "").replace("\\", "\\\\").replace('"', '\\"')[:200] + '"'
    subprocess.Popen(["osascript", "-e", f"display notification {q(body.get('body'))} with title {q(body.get('title'))}"
                      ' sound name "Glass"'])
    return {"ok": True}


# Reel

@app.post("/api/reel")
async def make_reel(ids: str = Form(...), title: str = Form(""), closing: str = Form(""),
                    photo_sec: float = Form(reel.PHOTO_SEC), max_sec: float = Form(reel.MAX_SEC),
                    start: float = Form(0.0), song: UploadFile | None = File(None)):
    chosen = [S.slots[int(i)].result for i in json.loads(ids) if int(i) in S.slots and S.slots[int(i)].result]
    if not chosen:
        raise HTTPException(400, "Make some looks first")
    song_path = None
    if song is not None and song.filename:
        song_path = WORK / "songs" / re.sub(r'[/:\\]+', "-", song.filename)
        song_path.parent.mkdir(parents=True, exist_ok=True)
        song_path.write_bytes(await song.read())
    task = Task(next(S.ids), "reel", len(chosen), now="Getting ready")
    S.tasks[task.id] = task
    folder = Path(prefs().get("folder") or DEFAULT_EXPORT).expanduser()
    W.submit(OUTPUT, _reel, task, chosen, song_path, start, title, closing, photo_sec, max_sec, folder)
    return task.public()


def _reel(task: Task, chosen, song, start, title, closing, photo_sec, max_sec, folder: Path) -> None:
    try:
        beat, beats = None, []
        if song:
            task.now = "Finding the song's beat"
            beat, beats = reel.song_beat(song)
        sec, keep = reel.fit(len(chosen), float(photo_sec), float(max_sec), beat)
        task.total = keep

        def shots_tick(done, total, name=""):
            task.done, task.now = done, f"Preparing {name}"
        shots = E.reel_shots(chosen[:keep], shots_tick)
        plan = reel.Plan(shots, sec, [])
        name = re.sub(r"[/:\\]+", "-", " ".join((title or "").split())) or "Reel"
        dest = engine._unique(folder / "Reels" / f"{name}.mp4")

        def frames_tick(done, total, name=""):
            task.total, task.done, task.now = total, done, "Making frames"
        reel.render(plan, dest, song, reel.song_start(beats, float(start or 0)) if song else 0.0, title, closing,
                    frames_tick)
        left = f"; {len(chosen) - keep} did not fit" if keep < len(chosen) else ""
        beat_note = f", on the beat ({60 / beat:.0f} BPM)" if beat else ""
        task.path, task.video = str(dest), f"/media/reel/{task.id}"
        task.message = f"A {plan.length:.0f} s reel of {keep} pictures{beat_note}{left}"
        task.state = "done"
    except Exception as e:
        task.state, task.message = "failed", f"Reel failed: {e}"


@app.get("/media/reel/{tid}")
def reel_video(tid: int):
    t = S.tasks.get(tid)
    if t is None or not t.path:
        raise HTTPException(404)
    return FileResponse(t.path, media_type="video/mp4")


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)




def _classic() -> None:
    """The classic app's tools (preset editor, Lightroom presets, assets) at /classic."""
    import gradio as gr
    from photo_presets import app as classic
    classic.ENGINE = E  # one engine: the same caches, cut-out fixes and drawings
    gr.mount_gradio_app(app, classic.build(), path="/classic", theme=classic.THEME, css=classic.CSS,
                        head=classic.PASTE_JS, footer_links=[])


def _ours(port: int) -> bool:
    """Is AllProPhoto already running on this port?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/looks", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def _older(port: int) -> bool:
    """Is the AllProPhoto running on this port an older version than the code here?"""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1.5) as r:
            return float(json.loads(r.read())["code"]) < _code_time() - 1
    except (OSError, ValueError, KeyError):
        return True  # from before versions were asked: older


def _retire(port: int) -> None:
    """Asks the older AllProPhoto to save and quit (or ends it, if it is too old to be asked)."""
    import signal
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quit", data=b"{}",
                                                      headers={"Content-Type": "application/json"}), timeout=3)
    except OSError:
        try:
            out = subprocess.run(["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"], capture_output=True, text=True).stdout
            for pid in out.split():
                cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
                if "AllProPhoto" in cmd or "photo_presets" in cmd or "allprophoto" in cmd:
                    os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    for _ in range(100):  # until it has gone
        if _free(port):
            return
        time.sleep(0.1)


def _free(port: int) -> bool:
    import socket
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _window(url: str) -> None:
    """AllProPhoto in its own Mac window, named and with its icon in the Dock."""
    import webview
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = info["CFBundleDisplayName"] = "AllProPhoto"
        icon = WEB / "icon.png"
        if icon.exists():
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initWithContentsOfFile_(str(icon)))
    except Exception:
        pass
    win = webview.create_window("AllProPhoto", url, width=1480, height=920, min_size=(980, 620),
                                background_color="#0b0c0e", text_select=False)
    win.events.closed += _shut_down  # closing the window quits the whole app, engine included
    webview.start()


def main() -> int:
    """uv run allprophoto [--window] [--port N] [--no-browser]"""
    import uvicorn
    import webbrowser
    port = 7860
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    window = "--window" in sys.argv
    url = f"http://127.0.0.1:{port}"
    if _ours(port) and _older(port):  # an older version still running: it makes way for this one
        _retire(port)
    if _ours(port):  # already running: just open it
        if window:
            _window(url)
        elif "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return 0
    while not _free(port):
        port += 1
    url = f"http://127.0.0.1:{port}"
    _classic()
    S.restore()
    K.start()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: _shut_down())  # stopped by the Mac (log out, restart): saved first
    if not window:
        if "--no-browser" not in sys.argv:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
        return 0
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    _window(url)  # until the window is closed
    _shut_down()
    return 0


if __name__ == "__main__":
    sys.exit(main())
