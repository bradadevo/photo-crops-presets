"""VS Digital Pro Studio: the app's own web page (studio/web) and the small local
server behind it. The looks engine does the work; this file keeps the session
(photos, the looks made, the ones you keep) and answers the page.

Everything that makes pictures runs on one worker thread, in order of
importance: fixing a cut-out, then the looks you asked for, then exports and
reels, then the little look previews on your photo (so they never slow a run).

    uv run vsdigitalpro            (the classic Gradio app: uv run vsdigitalpro-classic)
"""

from __future__ import annotations

import asyncio
import io
import itertools
import os
import hashlib
import random
import json
import logging
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
from photo_presets import brand, deliver, edits, engine, enlarge, pipeline, players, presets, reel, retouch, scene, timing, poster
from photo_presets.engine import Engine, Job, Result
from photo_presets.scene import Fix, frame_boxes

log = logging.getLogger("vsdigitalpro")

WEB = Path(__file__).parent / "web"
CONFIG = Path("~/.config/photo-crops-presets").expanduser()
# ALLPROPHOTO_STATE: a folder of its own for the session, settings and added photos (a test copy of the app)
STATE = Path(os.environ["ALLPROPHOTO_STATE"]) if os.environ.get("ALLPROPHOTO_STATE") else None
PREFS = (STATE or CONFIG) / "studio.json"
EXAMPLES = (STATE / "examples") if STATE else Path("~/.cache/photo-crops-presets/examples").expanduser()  # each look's last picture, for the picker
WORK = Path(tempfile.mkdtemp(prefix="vsdigitalpro-"))  # songs for reels
ADDED = (STATE / "added") if STATE else Path("~/.cache/photo-crops-presets/added").expanduser()  # photos dropped or pasted
EDITED = ADDED.parent / "edited"
if STATE:  # a test copy: its own presets and their pictures too (never your real ones)
    presets.PRESETS_FILE = STATE / "presets.json"  # photos as edited, to make more looks on top of the edits
SESSION = (STATE or CONFIG) / "studio-session.json"  # the photos you are working on, kept for next time
# the looks made, with their edits, picks and stars, kept for next time (pictures at preview size)
LOOKS = (STATE / "looks") if STATE else Path("~/.cache/photo-crops-presets/session-looks").expanduser()
# (a test copy exports into its own folder: never into your real Pictures)
DEFAULT_EXPORT = str(STATE / "Exports") if STATE else str(Path.home() / "Pictures" / "Photo Presets")
THUMB, VIEW, SWATCH, TRY = 560, 1800, 420, 1400  # px: the strip and grid, a photo, a look's card, trying a look on
CHIP = 160  # px: a look's small picture in the looks list (made with the look ahead)
ZOOM = 3600  # px: a look made again, sharper, when you zoom in
CROPS = ["none", "wide", "crop", "face"]
FIX, RUN, OUTPUT, PREVIEW = 0, 1, 2, 5  # the worker's order of importance
AHEAD = 9  # looks made ahead for hovering: after everything else

# the look groups, short, for the picker's filters
SHORT_GROUPS = {
    presets.GRADES: "Pro grades", presets.BOLD: "Bold", presets.EDITORIAL: "Editorial", presets.STUDIO: "Studio", presets.FIELD: "Field", presets.OTHER: "Other", presets.MINE: "Mine",
}


# The worker --------------------------------------------------------------------------

class Worker:
    """One thread for everything that makes pictures, most important first."""

    def __init__(self):
        self.q: PriorityQueue = PriorityQueue()
        self.order = itertools.count()
        threading.Thread(target=self._loop, daemon=True, name="vsdigitalpro-worker").start()

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
    full: tuple | None = None  # the photo's own pixels (as framed), for the crop's real size

    def full_size(self) -> tuple[int, int] | None:
        if self.full is None and self.result is not None:
            try:
                self.full = E.prepared(self.result.source, self.result.crop).image.size
            except Exception:
                return None
        return self.full

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
                       fixes=len(E.fixes_for(r)), removed=len(E.removals.get(str(r.source), [])),
                       tune=next(([f.x, f.y] for f in E.fixes_for(r) if f.kind == "tune"), [0, 0]))
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
    detail: str = ""  # a second line (an export: what the AI detail enlarger sharpened)
    path: str = ""
    video: str = ""
    started: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "kind", "total", "done", "now", "state", "message", "detail", "path",
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
        if added:
            _thumbs_ahead(added)
            CUT.want(added)  # (each photo's players cut out now, in the background)
        return added

    def remove_photo(self, pid: int) -> None:
        with self.lock:
            self.photos.pop(pid, None)
            self.save()

    def saved(self) -> dict:
        return {"photos": [str(p.path) for p in self.photos.values()],
                "future": {str(self.photos[pid].path): rms for pid, rms in self.future.items() if pid in self.photos and rms},
                "fixes": [[k[0], k[1], [f.to_json() for f in v]] for k, v in E.fixes.items() if v],
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
            E.fixes[(path, crop)] = [Fix.from_json(v) for v in fixes]
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
E.bg_dir = ADDED.parent / "backgrounds"  # your own background pictures (a test copy: its own)
E.sharp_dir = ADDED.parent / "sharp"  # tight crops made sharp by the AI, kept across restarts
E.cutout_dir = ADDED.parent / "cutouts"  # each look's players' cut-out, kept across restarts
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
            threading.Thread(target=self._loop, daemon=True, name="vsdigitalpro-keeper").start()

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


_CAMERA: dict[str, bool] = {}


def camera_photo(path: Path) -> bool:
    """Taken with a camera (its EXIF names one): only these become a look's picture in the picker, never
    a screenshot or a downloaded image (which may show something private)."""
    key = str(path)
    if key not in _CAMERA:
        try:
            _CAMERA[key] = images.is_raw(path) or bool(Image.open(path).getexif().get(0x010F))
        except Exception:
            _CAMERA[key] = False
    return _CAMERA[key]


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
    if not token and camera_photo(path):
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


# Instant looks: every look made ahead for the photo, so hovering one shows it at once ----------

class Ahead:
    """The looks made ahead of time for the photo you're on (the same engine and size as Make, so a
    hovered look is the real one), one at a time at the lowest priority: the look under the mouse
    first, then its neighbors, then the rest. Kept in memory (the last few photos) and on disk."""

    KEEP = 4  # photos kept in memory (about 50 looks x 300 KB each)

    def __init__(self):
        self.lock = threading.Lock()
        self.key: tuple[int, str] | None = None  # (photo, edits token) being made
        self.order: list[str] = []
        self.made: OrderedDict = OrderedDict()  # (photo, token) -> {name: jpeg bytes}
        self.failed: set = set()
        self.recipes: dict[str, dict] = {}
        self.busy = False
        self.waiting = False
        self.last_edit = 0.0
        self.asked: tuple[str, int] = ("", 0)  # (the page, its latest ask): an older ask arriving late never reorders

    def looks(self) -> dict[str, dict]:
        return {n: r for n, r in presets.load_all().items() if not timing.uses_ai(r) and not r.get("design")}

    def file(self, pid: int, token: str, name: str, recipe: dict) -> Path:
        src = _start_from(pid, token) if token else S.photo(pid).path
        try:
            stamp = src.stat().st_mtime
        except OSError:
            stamp = 0
        digest = hashlib.sha1(json.dumps([str(src), stamp, name, recipe, engine.PREVIEW_EDGE, RENDER_CODE], sort_keys=True,
                                         default=str).encode()).hexdigest()
        return AHEAD_DIR / f"{digest}.jpg"

    def want(self, pid: int, token: str, order: list[str], page: str = "", seq: int = 0) -> None:
        """Make these looks for this photo, in this order (the page sends it again as the mouse moves;
        seq: its ask's number, so one overtaken by a later ask is not followed)."""
        allowed = self.looks()
        with self.lock:
            if page and page == self.asked[0] and seq < self.asked[1] and self.key == (pid, token):
                return  # (an older ask: the look under the pointer now stays first)
            if page:
                self.asked = (page, seq)
            self.recipes = allowed  # (read once per ask, not once per look)
            self.key = (pid, token)
            self.made.setdefault(self.key, {})
            self.made.move_to_end(self.key)
            while len(self.made) > self.KEEP:
                self.made.popitem(last=False)
            rest = [n for n in allowed if n not in order]
            self.order = list(dict.fromkeys([n for n in order if n in allowed] + rest))  # (each look once)
        self.kick()

    def ready(self, pid: int, token: str) -> list[str]:
        with self.lock:
            return list(self.made.get((pid, token), {}))

    def get(self, pid: int, token: str, name: str, chip: bool = False, card: bool = False) -> bytes | None:
        """The look made ahead (or its small picture for the looks list), from memory or disk."""
        with self.lock:
            got = self.made.get((pid, token), {}).get(name)
        if got is None:
            recipe = (self.recipes or self.looks()).get(name)  # (made before: from disk)
            f = self.file(pid, token, name, recipe) if recipe is not None else None
            if f is not None and all(q.exists() for q in (f, f.with_suffix(".chip.jpg"), f.with_suffix(".card.jpg"))):
                got = (f.read_bytes(), f.with_suffix(".chip.jpg").read_bytes(), f.with_suffix(".card.jpg").read_bytes())
                with self.lock:
                    self.made.setdefault((pid, token), {})[name] = got
        return None if got is None else got[2 if card else 1 if chip else 0]

    def kick(self) -> None:
        while True:  # (a loop, not a call per look: after a restart they all come straight from disk)
            with self.lock:
                if self.busy or self.key is None:
                    return
                if time.time() - self.last_edit < 1.0:  # (you're editing: wait, so nothing slows you)
                    if not self.waiting:
                        self.waiting = True
                        threading.Timer(1.0, self._resume).start()
                    return
                key, todo = self.key, [n for n in self.order if n not in self.made.get(self.key, {}) and (self.key, n) not in self.failed]
                if not key[1] and not CUT.settled(key[0]):  # (its players are being cut out ahead: those looks after, the rest now)
                    todo = [n for n in todo if not pipeline.needs_cutout(self.recipes.get(n) or {})]
                if not todo:
                    return
                self.busy = True
            name = todo[0]
            if self.get(*key, name) is None:
                break
            with self.lock:  # (on disk already)
                self.busy = False
        fut = W.submit(AHEAD, self._make, key, name)
        fut.add_done_callback(lambda f: self._done(key, name, f))

    def _make(self, key: tuple[int, str], name: str) -> tuple[bytes, bytes]:
        pid, token = key
        recipe = dict(self.looks()[name], name=name)
        path = _start_from(pid, token)
        p = E.ready(path, "none", recipe)
        small = p.image.copy()
        small.thumbnail((engine.PREVIEW_EDGE, engine.PREVIEW_EDGE))
        img, _ = pipeline.render(small, recipe, E.library, p.scene, 0)
        # (the look; its small picture for the list; its card for the grid: the look is drawn once for all three)
        data = (jpeg(img, quality=90), jpeg(img, CHIP, 82), jpeg(img, SWATCH, 84))
        if not token and camera_photo(path):
            keep_example(name, img)
        try:
            AHEAD_DIR.mkdir(parents=True, exist_ok=True)
            f = self.file(pid, token, name, self.looks()[name])
            f.with_suffix(".chip.jpg").write_bytes(data[1])
            f.with_suffix(".card.jpg").write_bytes(data[2])
            f.write_bytes(data[0])
            _trim(AHEAD_DIR, AHEAD_KEPT)
        except OSError:
            pass
        return data

    def _resume(self) -> None:
        with self.lock:
            self.waiting = False
        self.kick()

    def _done(self, key, name, fut) -> None:
        with self.lock:
            self.busy = False
            try:
                self.made.setdefault(key, {})[name] = fut.result()
            except Exception:
                log.exception("Making %s ahead failed", name)
                self.failed.add((key, name))
        self.kick()


AHEAD_DIR = (STATE or Path("~/.cache/photo-crops-presets").expanduser()) / "ahead"
A = Ahead()


EVENT_EDGE = 320  # px: a photo in the whole-event preview grid
RENDER_CODE = engine.RENDER_CODE
AHEAD_KEPT = 3000  # previews of single photos kept on disk (about 300 KB each: 900 MB), the oldest let go
EVENT_KEPT = 15000  # event previews kept on disk (about 20 KB each: 300 MB), the oldest let go


class EventAhead:
    """Every look made ahead for every photo of the event, small, for the whole-event preview: point at a
    look and every photo shows it. Each photo is prepared once as a small picture with its players'
    cut-out (the full-size photo isn't kept), then each look takes about 0.02 s. The look under the
    pointer first (on every photo), then its neighbors; kept in memory and on disk."""

    def __init__(self):
        self.lock = threading.Lock()
        self.minis: dict[int, tuple] = {}  # photo -> (small picture, its scene at that size)
        self.made: dict[tuple[int, str], bytes] = {}
        self.failed: set = set()
        self.pids: list[int] = []
        self.order: list[str] = []
        self.recipes: dict[str, dict] = {}
        self.busy = False
        self.waiting = False

    def file(self, pid: int, name: str, recipe: dict) -> Path:
        src = S.photo(pid).path
        try:
            stamp = src.stat().st_mtime
        except OSError:
            stamp = 0
        digest = hashlib.sha1(json.dumps([str(src), stamp, name, recipe, EVENT_EDGE, RENDER_CODE], sort_keys=True,
                                         default=str).encode()).hexdigest()
        return AHEAD_DIR / "event" / f"{digest}.jpg"

    def want(self, pids: list[int], order: list[str]) -> None:
        allowed = A.looks()
        with self.lock:
            self.recipes = allowed  # (read once per ask, not once per picture)
            self.pids = [i for i in pids if i in S.photos]
            self.order = list(dict.fromkeys([n for n in order if n in allowed] + list(allowed)))  # (each look once)
        self.kick()

    def _kept(self, pid: int, name: str) -> Path | None:
        recipe = self.recipes.get(name)
        if recipe is None or pid not in S.photos:
            return None
        f = self.file(pid, name, recipe)
        return f if f.exists() else None

    def has(self, pid: int, name: str) -> bool:
        """Made (in memory or kept on disk), without reading the picture."""
        with self.lock:
            if (pid, name) in self.made:
                return True
        if self._kept(pid, name) is None:
            return False
        with self.lock:
            self.made.setdefault((pid, name), None)  # (None: kept on disk, read when asked for)
        return True

    def get(self, pid: int, name: str) -> bytes | None:
        with self.lock:
            got = self.made.get((pid, name))
        if got is not None:
            return got
        f = self._kept(pid, name)
        if f is None:
            with self.lock:  # (let go from disk since: made again)
                self.made.pop((pid, name), None)
            return None
        try:
            data = f.read_bytes()
        except OSError:
            return None
        with self.lock:
            self.made.setdefault((pid, name), None)
        return data

    def status(self, focus: str | None) -> dict:
        """Which looks are ready on every photo, and which photos have the look under the pointer."""
        with self.lock:
            pids, order = list(self.pids), list(self.order)
            made, failed = set(self.made), set(self.failed)
        # (a look that couldn't be made on a photo counts as done: that photo shows as it is, and the rest go on)
        complete = [n for n in order if all((i, n) in made or (i, n) in failed for i in pids)]
        return {"complete": complete, "total": len(order), "photos": len(pids),
                "focus": [i for i in pids if (i, focus) in made] if focus else []}

    def kick(self) -> None:
        while True:  # (a loop, not a call per look: after a restart thousands come straight from disk)
            with self.lock:
                if self.busy:
                    return
                if time.time() - A.last_edit < 1.0:  # (you're editing: wait)
                    if not self.waiting:
                        self.waiting = True
                        threading.Timer(1.0, self._resume).start()
                    return
                job = next(((i, n) for n in self.order for i in self.pids
                            if (i, n) not in self.made and (i, n) not in self.failed), None)
                if job is None:
                    self.minis.clear()  # (all made: the small photos and the cut-out model's memory go)
                    from photo_presets.scene import release_small_cutout
                    release_small_cutout()
                    return
                self.busy = True
            if not self.has(*job):
                break
            with self.lock:  # (on disk already)
                self.busy = False
        fut = W.submit(AHEAD, self._make, *job)
        fut.add_done_callback(lambda f: self._done(job, f))

    def _resume(self) -> None:
        with self.lock:
            self.waiting = False
        self.kick()

    def _mini(self, pid: int) -> tuple:
        if pid not in self.minis:
            from photo_presets.scene import prepare_small, resized
            p = prepare_small(S.photo(pid).path)
            small = p.image.copy()
            small.thumbnail((EVENT_EDGE, EVENT_EDGE))
            sc = p.scene
            h, w = small.height, small.width
            for k in ("people_mask", "subject_mask", "matte"):
                if getattr(sc, k) is not None:
                    setattr(sc, k, resized(getattr(sc, k), h, w))
            self.minis[pid] = (small, sc)
        return self.minis[pid]

    def _make(self, pid: int, name: str) -> bytes | None:
        """The look on this photo, small; kept on disk (None then: read when asked for), else in memory."""
        small, sc = self._mini(pid)
        recipe = dict(self.recipes[name], name=name)
        img, _ = pipeline.render(small.copy(), recipe, E.library, sc, 0)
        data = jpeg(img, quality=86)
        try:
            f = self.file(pid, name, self.recipes[name])
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(f)
            _trim(f.parent, EVENT_KEPT)
            return None
        except OSError:
            return data

    def _done(self, job, fut) -> None:
        with self.lock:
            self.busy = False
            try:
                self.made[job] = fut.result()
            except Exception:
                log.exception("Making %s ahead for photo %s failed", job[1], job[0])
                self.failed.add(job)
        self.kick()


EV = EventAhead()


CUT_SECONDS = 20  # about how long one photo's players take to cut out (said on the page, so a wait is never a mystery)


class CutAhead:
    """Every photo's players cut out in the background as soon as it's added: the full cut-out, the
    very one Make uses (about 20 s a photo), so opening a photo, pointing at a look built on its
    players, or making it never waits for it. The photo you have open goes first, then the rest of
    the event in order. One at a time (each needs several GB, the same as when you edit); it waits
    while you move a slider; each is kept on disk and remembered, so a restart does none again."""

    def __init__(self, file: Path, run: bool = True):
        self.file = file
        self.run = run  # (off in tests: each step is run by hand)
        self.cv = threading.Condition()
        self.queue: list[int] = []
        self.now: int | None = None
        self.since = 0.0  # (when the photo being got ready now was started)
        self.failed: set[str] = set()
        self.thread: threading.Thread | None = None
        try:
            kept = json.loads(file.read_text())
        except (OSError, ValueError):
            kept = {}
        self.done: dict[str, list] = {k: v for k, v in kept.items() if isinstance(v, list) and len(v) == 3
                                      and v[2] == scene.MATTE_VERSION}  # (made another way before: made again)

    def is_done(self, path: Path) -> bool:
        """This photo's players are cut out, on disk (the same file, unchanged since)."""
        with self.cv:
            v = self.done.get(str(path))
        if v is None:
            return False
        try:  # ("": nobody in it to cut out)
            return v[0] == path.stat().st_mtime and (not v[1] or (scene._mattes_dir() / f"{v[1]}.png").exists())
        except OSError:
            return False

    def settled(self, pid: int) -> bool:
        """Nothing to wait for on this photo: not waiting to be cut out, nor being cut out now."""
        with self.cv:
            return pid != self.now and pid not in self.queue

    def want(self, pids: list[int], first: bool = False) -> None:
        """These photos cut out ahead (first: before the rest, the one you have open)."""
        todo = []
        for pid in pids:
            try:
                path = S.photo(pid).path
            except HTTPException:
                continue
            if not self.is_done(path) and str(path) not in self.failed:
                todo.append(pid)
        with self.cv:
            if first:
                self.queue = [q for q in todo if q != self.now] + [q for q in self.queue if q not in todo]
            else:
                self.queue += [q for q in todo if q != self.now and q not in self.queue]
            self.cv.notify()
            if self.run and self.thread is None and self.queue:
                self.thread = threading.Thread(target=self._loop, daemon=True, name="vsdigitalpro-cut-ahead")
                self.thread.start()

    def status(self) -> dict:
        with self.cv:
            left = len(self.queue) + (self.now is not None)
        return {"left": left}

    def about(self, pid: int) -> dict:
        """For the page: this photo's players ("ready", "now": being cut out, "next": waiting for
        `ahead` others first), and how many of the event's photos are ready."""
        with self.cv:
            left = len(self.queue) + (self.now is not None)
            this = "now" if pid == self.now else "next" if pid in self.queue else "ready"
            ahead = self.queue.index(pid) + (self.now is not None) if this == "next" else 0
        total = len(S.photos)
        return {"this": this, "ahead": ahead, "done": max(0, total - left), "total": total, "each": CUT_SECONDS}

    def board(self) -> dict:
        """For the Photos panel: each photo getting ready, in plain view. `now`: the photo being got
        ready, `waiting`: the ones after it, in order (every other photo is ready), and about how
        many seconds are left in all."""
        with self.cv:
            now, waiting = self.now, [p for p in self.queue if p in S.photos]
            since = self.since
        total = len(S.photos)
        left = len(waiting) + (now is not None)
        secs = len(waiting) * CUT_SECONDS + (max(3, CUT_SECONDS - (time.time() - since)) if now is not None else 0)
        return {"now": now, "waiting": waiting, "done": max(0, total - left), "total": total,
                "left_s": round(secs), "each": CUT_SECONDS}

    def _loop(self) -> None:
        while True:
            with self.cv:
                while not self.queue:
                    self.cv.wait()
                pid = self.now = self.queue.pop(0)
                self.since = time.time()
            try:
                self.one(pid)
            except Exception:
                log.exception("Cutting out photo %s ahead failed", pid)
                try:
                    self.failed.add(str(S.photo(pid).path))
                except HTTPException:
                    pass
            finally:
                with self.cv:
                    self.now = None
                A.kick()  # (the looks built on its players, held back for it: made now)

    def one(self, pid: int) -> None:
        # (you're moving a slider, or the looks of the photo you have open are being made: after, so
        # nothing you're looking at slows down; the photo you have open itself goes at once)
        while time.time() - A.last_edit < 1.0 or (A.busy and (A.key or (None,))[0] != pid):
            time.sleep(0.25)
            with self.cv:
                if self.queue and self.queue[0] != pid and self.queue[0] == (A.key or (None,))[0]:
                    self.queue.insert(1, pid)  # (you opened another photo meanwhile: that one first, then this)
                    return
        try:
            path = S.photo(pid).path
        except HTTPException:
            return  # (removed meanwhile)
        if self.is_done(path) or E.removals.get(str(path)):
            return  # (a photo with distractions removed is cut out from its cleaned copy, when it's used)
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return
        p = W.submit(PREVIEW, E.unkept, path, "none").result()  # (finding the players: on the worker, which owns that model)
        if p.scene.subject_mask is None:
            key = ""  # (nobody to cut out)
        else:
            p.ensure_matte()  # (here, on this thread: the worker stays free for you)
            if p.matte_key is None or p._auto is None or p._auto[0] is None:
                return
            key = p.matte_key
        with self.cv:
            self.done[str(path)] = [stamp, key, scene.MATTE_VERSION]
            data = json.dumps(self.done)
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".part")
            tmp.write_text(data)
            tmp.replace(self.file)
        except OSError:
            pass


CUT = CutAhead((STATE or Path("~/.cache/photo-crops-presets").expanduser()) / "cut-ahead.json")
E.cut_ahead = lambda path: CUT.is_done(path)


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
    if name in presets.load_all() and not design and camera_photo(job.path):
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

app = FastAPI(title="VS Digital Pro")
from photo_presets.studio import check as _check  # the Check tab (how a clip or photo was shot, and fixes)
app.include_router(_check.router)
from photo_presets.studio import cull as _cull  # the Culling tab (pass 1 by the app, pass 2 by you)
app.include_router(_cull.router)
_cull.SEND["looks"] = S.add_photos  # the Culling tab's keepers go into Looks


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


@app.get("/brand/{name}.ttf")
def brand_font(name: str):
    """VS Digital Pro's own fonts (Big Shoulders Display, Chakra Petch, Manrope: open fonts, kept in the app)."""
    p = WEB / "fonts" / f"{name}.ttf"
    if not name.replace("-", "").isalnum() or not p.is_file():
        raise HTTPException(404)
    return Response(p.read_bytes(), media_type="font/ttf", headers={"Cache-Control": "max-age=86400"})


@app.get("/font/{key}.ttf")
def font_file(key: str):
    """One of the fonts words can be set in, for the page to show it as it's exported."""
    from photo_presets import fonts
    data = fonts.font_file(key)
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="font/ttf", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/restart")
def restart():
    """Restarts the app with the newer version (the looks are saved first, and come back)."""
    K.flush()

    def go():
        time.sleep(0.4)
        exe = Path(sys.executable)
        bundle = next((p for p in exe.parents if p.suffix == ".app"), None)
        new = Path("~/Applications/VS Digital Pro.app").expanduser()
        if bundle is not None and not bundle.exists() and new.exists():
            bundle = new  # (the app was renamed and moved: open it where it is now)
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


@app.get("/api/curves")
def tone_curves():
    """The ready-made tone curves, named by the situation they're for (see curves.py)."""
    from photo_presets import curves
    return {"situations": [{"key": k, "name": name, "about": about, "part": part,
                            "curves": {ch: curves.text(pts) for ch, pts in chans.items()}}
                           for k, (name, about, part, chans) in curves.SITUATIONS.items()]}


@app.get("/api/prep")
def prep():
    """Each photo getting ready (its players cut out once), for the Photos panel."""
    return CUT.board()


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
    return picture(_photo_picture(pid, size))


def _thumbs_ahead(pids: list[int]) -> None:
    """Each added photo's small picture made in the background now (kept on disk), so the strip and the
    whole-event preview never show an empty tile waiting for it."""
    for pid in pids:
        W.submit(PREVIEW, _photo_picture, pid, "thumb", False)


def _photo_picture(pid: int, size: str, remember: bool = True) -> bytes:
    """remember=False: only kept on disk (made ahead), not held in memory where it would push out
    the pictures you're working on."""
    path = S.photo(pid).path
    edge = THUMB if size == "thumb" else VIEW

    def make():
        kept = _kept_thumb(path, edge) if size == "thumb" else None  # (kept on disk: no camera file read after a restart)
        if kept is not None and kept.exists():
            return kept.read_bytes()
        try:
            data = jpeg(images.preview_image(path, edge), quality=86)
        except Exception:
            data = jpeg(images.load(path).image, edge, 86)
        if kept is not None:
            try:
                kept.parent.mkdir(parents=True, exist_ok=True)
                tmp = kept.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(kept)
                _trim(kept.parent, THUMBS_KEPT)
            except OSError:
                pass
        return data
    return PICTURES.get(("photo", pid, size), make) if remember else make()


THUMBS_KEPT = 3000  # photos' small pictures kept on disk (about 60 KB each), the oldest let go


def _kept_thumb(path: Path, edge: int) -> Path | None:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    digest = hashlib.sha1(json.dumps([str(path), stamp, edge]).encode()).hexdigest()
    return AHEAD_DIR.parent / "thumbs" / f"{digest}.jpg"


def _trim(folder: Path, keep: int) -> None:
    """At most `keep` files in the folder: the oldest go (checked now and then, not on every file)."""
    if random.random() > 0.02:
        return
    files = sorted((q for q in folder.glob("*.jpg") if not q.name.endswith((".chip.jpg", ".card.jpg"))), key=lambda q: q.stat().st_mtime)
    for old in files[:-keep]:
        old.unlink(missing_ok=True)
        old.with_suffix(".chip.jpg").unlink(missing_ok=True)  # (a preview's small copies go with it)
        old.with_suffix(".card.jpg").unlink(missing_ok=True)


@app.post("/api/swatches/{pid}")
async def swatches(pid: int, req: Request):
    """{names: [...], edits: bool}: starts making these looks' cards on the photo (or on the photo
    as edited), and says which are ready (the page asks again until all are)."""
    S.photo(pid)
    body = await req.json()
    token = edit_token(pid, bool(body.get("edits")))
    ready, failed = [], []
    ahead = A.key == (pid, token)  # (this photo's looks being made ahead: each card comes with its look, never drawn twice)
    made, plain = (set(A.ready(pid, token)), A.recipes or A.looks()) if ahead else (set(), {})
    with A.lock:
        gone = {n for (k, n) in A.failed if k == (pid, token)}
    for name in body.get("names", [])[:80]:
        if name in plain:
            if name in made or A.get(pid, token, name, card=True) is not None:
                ready.append(name)
            elif name in gone:
                failed.append(name)
            continue
        fut = swatch_future(pid, name, token)
        if fut.done():
            (failed if fut.cancelled() or fut.exception() or fut.result() is None else ready).append(name)
    return {"ready": ready, "failed": failed, "token": token}


@app.post("/api/ahead/{pid}")
async def ahead(pid: int, req: Request):
    """{order: [names], edits: bool}: make every look ahead for this photo, these first (the look under
    the mouse, then its neighbors). Says which are ready, so hovering shows them at once."""
    S.photo(pid)
    body = await req.json()
    token = edit_token(pid, bool(body.get("edits")))
    CUT.want([pid], first=True)  # (the photo you have open: its players cut out before the others')
    order = [str(n) for n in body.get("order", [])][:400]
    await asyncio.to_thread(A.want, pid, token, order, str(body.get("page", "")), int(body.get("seq", 0) or 0))
    focus = str(body.get("focus") or "")
    if focus and focus in (A.recipes or {}):  # (the look under the pointer, about to be made: answered once it is)
        until = time.time() + 1.2
        while time.time() < until and focus not in A.ready(pid, token) and (pid, token) == A.key:
            if not token and not CUT.settled(pid) and pipeline.needs_cutout(A.recipes.get(focus) or {}):
                break  # (it waits for this photo's players: said on the page, nothing to hold the answer for)
            await asyncio.sleep(0.03)
    with A.lock:  # (a look that couldn't be made is left out of the count: the rest still reach "all ready")
        failed = [n for (k, n) in A.failed if k == (pid, token)]
    total = len(A.looks()) - len(failed)
    return {"token": token, "ready": A.ready(pid, token), "total": total, "failed": failed,
            "cutting": CUT.status()["left"],  # (photos whose players are still to be cut out ahead)
            "cut": CUT.about(pid)}


@app.post("/api/event-ahead")
async def event_ahead(req: Request):
    """{order: [names], focus: name}: every look made ahead for every photo of the event (small), the
    look under the pointer first. Says which looks are ready on every photo."""
    body = await req.json()
    order = [str(n) for n in body.get("order", [])][:400]
    focus = body.get("focus")
    await asyncio.to_thread(EV.want, list(S.photos), ([focus] if focus else []) + order)
    return EV.status(focus)


@app.get("/img/event/{pid}/{name}.jpg")
async def event_image(pid: int, name: str):
    data = await asyncio.to_thread(EV.get, pid, name)
    if data is None:
        raise HTTPException(404, "Not made yet")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/img/ahead/{pid}/{name}.jpg")
async def ahead_image(pid: int, name: str, e: str = "", chip: int = 0):
    data = await asyncio.to_thread(A.get, pid, e, name, bool(chip))
    if data is None:
        raise HTTPException(404, "Not made yet")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/img/swatch/{pid}/{name}.jpg")
def swatch(pid: int, name: str, e: str = ""):
    fut = SWATCHES.get((pid, name, e))
    if fut is None:
        data = A.get(pid, e, name, card=True)  # (made ahead with the look)
        if data is not None:
            return picture(data)
        raise HTTPException(404, "Not made yet")
    if not fut.done() or fut.cancelled() or fut.exception() or fut.result() is None:
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
        want_original = "Original" in body.get("looks", [])
        if not names and not want_original:
            raise HTTPException(400, "Choose at least one look")
        slots = []
        if want_original:  # the photo as shot, to edit by hand: one per photo and framing, reused when it's there
            for p in pids:
                with S.lock:
                    have = next((s.id for s in S.slots.values() if s.photo == p and s.look == "Original"
                                 and s.crop == crop and s.state != "failed"), None)
                slots.append(have if have is not None else start_run([(p, Job(S.photo(p).path, dict(ORIGINAL), 0))], crop)[0])
        if names:
            jobs = [(p, Job(source[p], _for_team(dict(saved[n], name=n), n, run_tag), 0)) for n in names for p in pids]
            slots += start_run(jobs, crop, by_photo=pids)
        save_prefs({"crop": crop})
        return {"slots": slots}
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


def _variant(r: Result, kind: str, quick: bool = False) -> bytes:
    """after: the picture as edited, without its text (the page draws the text, to move it);
    thumb, full: with its text; before: the original, straightened and cropped the same;
    base: parts adjusted, not yet straightened or cropped (for cropping and brushing);
    area-N: base with part N shown in blue."""
    if kind in ("after", "thumb", "full") and E.needs_sharp(r) and (not (quick or kind == "thumb") or E.sharp_ready(r)):
        # a tight crop: the sharp one, every time (a thumbnail only when it's made already: never starts the AI)
        out = E.sharp_finished(r, texts=kind != "after")
        return jpeg(pipeline.to_image(out), THUMB, 84) if kind == "thumb" else jpeg(pipeline.to_image(out), quality=92 if kind == "full" else 90)
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
async def slot_image(sid: int, ver: int, kind: str, quick: int = 0):
    """quick=1: the picture at once from the preview (no waiting for a sharp crop to be made): shown
    while the sharp one is made, never blurred."""
    s = S.slot(sid)
    r = s.result
    if kind.startswith("fix"):  # fix, fix-black, fix-white, fix-mask: the cut-out as you check it
        view = kind[4:] or "tint"
        return picture(jpeg(await asyncio.to_thread(E.fix_view, r, view), quality=88))
    if kind not in ("after", "thumb", "full", "before", "base") and not re.fullmatch(r"area-\d+", kind):
        raise HTTPException(404)
    if kind == "after":
        _warm_cutout(r)
    if not edits.edited(r.edits):  # nothing to work out
        if kind == "before":
            return picture(PICTURES.get(("before", sid), lambda: jpeg(r.before, quality=90)))
        if kind == "thumb":
            return picture(PICTURES.get(("thumb", sid, s.ver), lambda: jpeg(r.after, THUMB, 84)))
        if kind in ("after", "full", "base"):
            return picture(PICTURES.get(("after", sid, s.ver), lambda: jpeg(r.after, quality=90)))
    await traced(r)
    if quick and kind in ("after", "full") and E.needs_sharp(r) and not E.sharp_ready(r):
        data = await asyncio.to_thread(PICTURES.get, (kind + "-quick", sid, s.ver), lambda: _variant(r, kind, quick=True))
        return picture(data)
    if kind in ("after", "full") and E.needs_sharp(r) and not E.sharp_ready(r):
        await asyncio.wrap_future(_start_sharpening(r))  # (made once, on the worker: it uses the AI model)
    data = await asyncio.to_thread(PICTURES.get, (kind, sid, s.ver), lambda: _variant(r, kind))
    return picture(data)


SHARPENING: dict = {}  # crops being made sharp: their one job


def _warm_up() -> None:
    """After a restart, in the background (lowest priority): the AI models loaded and each look's picture
    made, so the first click on a look shows it at once (not "Getting the picture ready" for seconds).
    A tight crop: its sharp copy loaded from disk when it was saved (no AI is started here)."""
    def one(sid: int):
        s = S.slots.get(sid)
        if s is None or s.result is None:
            return
        r = s.result
        quick = E.needs_sharp(r) and not E.sharp_ready(r)
        key = ("after-quick" if quick else "after", sid, s.ver)
        try:
            PICTURES.get(key, lambda: _variant(r, "after", quick=quick))
        except Exception:
            pass  # (only a head start: the picture is made when it's shown)
    for sid in list(S.slots):
        W.submit(PREVIEW, one, sid)


WARMING: set = set()


def _warm_cutout(r: Result) -> None:
    """Opening a photo whose players' cut-out it already uses (a player or background slider, or a look
    built on it): the cut-out is loaded in the background now, so the first slider after a restart is as
    quick as the rest. Only these (their cut-out is kept on disk: quick to load); browsing new photos
    never starts the cut-out model."""
    if not (pipeline.needs_cutout(r.recipe) or pipeline.needs_cutout({"adjust": r.recipe.get("adjust")})):
        return
    key = (str(r.source), r.crop, r.frame)
    if key in E._cutouts or key in WARMING:
        return
    WARMING.add(key)
    W.submit(RUN, E.cutout, r).add_done_callback(lambda f: WARMING.discard(key))  # (the photo you have open: before background work)


def _start_sharpening(r: Result):
    """The crop made sharp on the worker: one job per crop, however many ask for it."""
    key = E.sharp_key(r)
    job = SHARPENING.get(key)
    if job is None or job.done():
        job = SHARPENING[key] = W.submit(FIX, E.sharp_base, r)
    return job


@app.get("/api/slots/{sid}/sharp")
async def sharp_state(sid: int, start: int = 0):
    """Whether this picture's crop is made sharp (needed), and whether that's done (ready); start=1 starts
    making it in the background (the app shows the picture as it is meanwhile, and says so)."""
    r = S.slot(sid).result
    need = r is not None and E.needs_sharp(r)
    ready = bool(need and E.sharp_ready(r))
    if need and not ready and start:
        _start_sharpening(r)
    return {"on": E.sharp_on, "needed": need, "ready": ready}


@app.post("/api/prefs/sharp")
async def set_sharp(req: Request):
    """{on}: tight crops made sharp by the AI detail enlarger (view, poster and export), or not."""
    on = bool((await req.json()).get("on", True))
    E.sharp_on = on
    save_prefs({"sharp_crops": on})
    with PICTURES.lock:
        PICTURES.items.clear()  # (every picture shown again, as now set)
    for s in S.slots.values():
        s.ver += 1
    return {"on": on, "slots": [s.public() for s in S.slots.values() if s.result is not None]}


ZOOM_CROP = 2160  # px: a crop zoomed into is shown at least this big (twice an Instagram post's width)


def _zoomed(r: Result) -> tuple[bytes, bytes]:
    """The look and the photo at ZOOM px, for checking faces and focus (the AI
    drawing is reused, so this is quick). A crop is made from as many of the photo's
    own pixels as it has, and, when that is still small, enlarged by the AI detail
    enlarger, as its export will be: what you check is what you get."""
    if E.needs_sharp(r):  # a tight crop: its sharp picture (made once and kept), not made again for zoom
        after = pipeline.to_image(E.sharp_finished(r, texts=False))
        before = pipeline.to_image(edits.geometry(pipeline.to_array(r.before), r.edits)).resize(after.size, Image.LANCZOS)
        return jpeg(after, quality=90), jpeg(before, quality=90)
    p = E.ready(r.source, r.crop, r.recipe)
    img = p.image.copy()
    c = (r.edits or {}).get("crop")
    share = max(0.05, min(1.0, float(c[2]) - float(c[0]), float(c[3]) - float(c[1]))) if c else 1.0
    img.thumbnail((min(max(img.size), round(ZOOM / share)),) * 2)
    after, _ = pipeline.render(img, r.recipe, E.library, p.scene, r.seed, E.drawings,
                               E.memo_key(r.source, r.crop, r.recipe, p.frame))
    if edits.edited(r.edits):
        after = pipeline.to_image(E.finalize(r, pipeline.to_array(after), texts=False))
        img = pipeline.to_image(edits.geometry(pipeline.to_array(img), r.edits))
        if c and max(after.size) < ZOOM_CROP:  # a tight crop: enlarged as its export will be
            k = ZOOM_CROP / max(after.size)
            size = (round(after.width * k), round(after.height * k))
            after = enlarge.fit_pil(after, size)
            img = img.resize(size, Image.LANCZOS)
    return jpeg(after, quality=90), jpeg(img, quality=90)


@app.get("/api/slots/{sid}/fullsize")
async def full_size(sid: int):
    """The photo's own pixels (as framed), asked for when you crop: the crop's real size, and whether
    an export will need the AI detail enlarger."""
    s = S.slot(sid)
    size = await asyncio.to_thread(s.full_size)
    return {"full": list(size) if size else None}


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
    A.last_edit = time.time()  # (looks made ahead wait while you edit)
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


@app.post("/api/slots/{sid}/remove/fill")
async def removal_fill(sid: int, req: Request):
    """{fill: {"try": n} | {"from": [dx, dy]} | null, index}: how one removal of this look is filled
    (the last one unless index is given): another AI fill, or copied from another spot."""
    s = S.slot(sid)
    body = await req.json()
    rms = list((s.result.edits or {}).get("removals") or [])
    if not rms:
        raise HTTPException(400, "Nothing removed from this look yet")
    i = int(body.get("index", -1))
    i = i if 0 <= i < len(rms) else len(rms) - 1
    rm = {k: v for k, v in rms[i].items() if k != "fill"}
    if body.get("fill"):
        rm["fill"] = body["fill"]
    rms[i] = rm
    e = edits.clean({**(s.result.edits or {}), "removals": rms})
    new = dataclasses.replace(s.result, edits=e)
    await asyncio.wrap_future(W.submit(FIX, lambda: E.finished(new, texts=False)))  # (the slow part, before it shows)
    async with s.edit_lock:
        with S.lock:
            s.result, s.ver = dataclasses.replace(s.result, edits=e), s.ver + 1
    return {**s.public(), "fills": retouch.FILLS}


@app.get("/api/slots/{sid}/remove/mask/{ver}.png")
async def removal_mask_png(sid: int, ver: int, index: int = -1):
    """The area one removal took (the last by default), white on clear, at the look's size."""
    s = S.slot(sid)
    rms = (s.result.edits or {}).get("removals") or []
    if not rms:
        raise HTTPException(404, "Nothing removed")
    rm = rms[index if 0 <= index < len(rms) else -1]
    w, h = s.result.after.size

    def make() -> bytes:
        m = E.removal_mask(s.result, rm, h, w)
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[m] = (255, 255, 255, 255)
        buf = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, "PNG")
        return buf.getvalue()
    return Response(await asyncio.wrap_future(W.submit(FIX, make)), media_type="image/png")


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
    all_ = saved_posters()
    gone = next((p for p in all_ if p["name"] == name), None)
    POSTERS_FILE.write_text(json.dumps([p for p in all_ if p["name"] != name], indent=1))
    return {"ok": True, "poster": gone}


@app.post("/api/posters/restore")
async def restore_poster(req: Request):
    """{poster}: a deleted saved poster back (Undo)."""
    p = (await req.json()).get("poster")
    if not isinstance(p, dict) or not p.get("name"):
        raise HTTPException(400, "Nothing to bring back")
    all_ = [x for x in saved_posters() if x["name"] != p["name"]]
    POSTERS_FILE.write_text(json.dumps([p, *all_], indent=1))
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


@app.post("/api/slots/{sid}/swap")
async def swap_poster(sid: int, req: Request):
    """{photo} or {look}: this poster (its words, logo, pieces, everything) with another photo in it, or
    with another look on its photo. A new picture, opened for you; the first stays as it was."""
    s = S.slot(sid)
    body = await req.json()
    design = design_of(s.result.edits)
    if not design.get("poster"):
        raise HTTPException(400, "Make a poster on this picture first")
    if body.get("look"):
        saved = presets.load_all()
        name = body["look"]
        if name not in saved and name != "Original":
            raise HTTPException(404, "That look is no longer here")
        base = dict(saved[name]) if name in saved else dict(ORIGINAL)
        base.pop("design", None)
        recipe = {**base, "name": name if name != "Original" else "Poster", "design": design}
        pid, path = s.photo, Path(s.source) if s.source else S.photo(s.photo).path
    else:
        pid = int(body.get("photo", -1))
        if pid not in S.photos:
            raise HTTPException(404, "That photo is no longer here")
        first = {k: v for k, v in design["poster"].items() if k != "pic"}  # (the new photo framed on its player)
        recipe = {k: v for k, v in s.result.recipe.items() if k not in ("match", "design", "team_number")}
        recipe.update(name=s.look if s.look != "Original" else "Poster", design={**design, "poster": first})
        path = S.photo(pid).path
    return {"slot": start_run([(pid, Job(path, recipe, 0))], s.crop)[0]}


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
    """{x, y (shares of the picture), add} a click; {kind: "brush" | "edge", points, r (a share of the
    picture's width), add} a stroke; {kind: "tune", soft, shift} the whole edge; {undo: true}; {reset: true}."""
    s = S.slot(sid)
    body = await req.json()
    r = s.result
    fixes = E.fixes_for(r)
    kind = body.get("kind", "click")
    if body.get("reset"):
        fixes = []
    elif body.get("undo"):
        fixes = fixes[:-1]
    elif kind == "tune":  # (one setting for the whole edge: the last one counts)
        fixes = [f for f in fixes if f.kind != "tune"]
        soft, shift = float(body.get("soft", 0)), float(body.get("shift", 0))
        if soft or shift:
            fixes.append(Fix(round(min(max(soft, 0), 1), 3), round(min(max(shift, -1), 1), 3), True, "tune"))
    elif kind in ("brush", "edge"):
        pts = tuple(tuple(round(v, 4) for v in engine.from_frame(r.frame, float(x), float(y))) for x, y in (body.get("points") or [])[:2000])
        if not pts:
            return {"fixes": len(fixes)}
        width = (r.frame[2] - r.frame[0]) if r.frame else 1.0
        fixes.append(Fix(pts[0][0], pts[0][1], bool(body.get("add", True)), kind, pts, round(float(body.get("r", 0.02)) * width, 4)))
    else:
        x, y = engine.from_frame(r.frame, float(body["x"]), float(body["y"]))
        fixes.append(Fix(round(x, 4), round(y, 4), bool(body.get("add", True))))
    await asyncio.wrap_future(W.submit(FIX, E.set_fixes, r, fixes))
    for o in S.slots.values():  # a new background (or a poster) uses the cut-out: shown again with the fix
        if o.result is not None and o.result.source == r.source and o.result.crop == r.crop and \
                ((o.result.edits or {}).get("background") or (o.result.edits or {}).get("poster")):
            o.ver += 1
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
        stamp = f"VS Digital Pro {time.strftime('%Y-%m-%d %H.%M.%S')} ({photos})"
        # separate files go in a folder of their own (never scattered over the Desktop)
        into = Path(tempfile.mkdtemp(prefix="vsdigitalpro-zip-")) if how == ZIP else engine._unique(dest / stamp)
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
        notes = [n for n in notes if "fewer pixels than this print size" not in n]
        if notes:
            task.message += ". " + "; ".join(notes)
        task.detail = enlarge.summary(getattr(E, "last_enlarged", []))
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


# New backgrounds behind the player --------------------------------------------------------------

@app.get("/api/backgrounds")
def list_backgrounds():
    """The backgrounds made here, and your own pictures (newest first)."""
    from photo_presets import backgrounds
    own = sorted((p for p in E.bg_dir.glob("*.jpg")), key=lambda p: -p.stat().st_mtime) if E.bg_dir.is_dir() else []
    return {"made": [{"src": n, "about": backgrounds.ABOUT[n]} for n in backgrounds.NAMES],
            "own": [{"src": f"file:{p.name}", "about": p.stem} for p in own]}


@app.get("/img/bg/{src}.jpg")
async def background_preview(src: str, color: str = "#1f2a44"):
    """A small picture of a background (in this team color)."""
    from photo_presets import backgrounds

    def make():
        if src.startswith("file:"):
            p = E.bg_dir / src[5:]
            if "/" in src[5:] or not p.is_file():
                raise HTTPException(404)
            arr = backgrounds.from_image(p, 240, 300)
        elif src in backgrounds.NAMES:
            arr = backgrounds.make(src, 240, 300, color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#1f2a44")
        else:
            raise HTTPException(404)
        return jpeg(pipeline.to_image(arr), quality=84)
    return picture(PICTURES.get(("bg", src, color), make))


@app.post("/api/backgrounds")
async def add_background(file: UploadFile = File(...)):
    """Your own background picture (a stadium, a street, a famous field): kept for every photo."""
    data = await file.read()

    def keep():
        import io
        from photo_crops import images as ims
        tmp = E.bg_dir / ("." + (Path(file.filename or "bg").name or "bg"))
        E.bg_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        try:
            img = ims.load(tmp).image.convert("RGB")
        except Exception:
            raise HTTPException(400, "That file isn't a picture VS Digital Pro can open")
        finally:
            tmp.unlink(missing_ok=True)
        img.thumbnail((4096, 4096))
        name = re.sub(r"[^A-Za-z0-9 _-]", "", Path(file.filename or "Background").stem)[:40].strip() or "Background"
        dest = E.bg_dir / f"{name}.jpg"
        n = 2
        while dest.exists():
            dest, n = E.bg_dir / f"{name} {n}.jpg", n + 1
        img.save(dest, quality=93)
        return {"src": f"file:{dest.name}"}
    return await asyncio.to_thread(keep)


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


@app.post("/api/logos/{lid}/restore")
def restore_logo(lid: str):
    if not brand.restore_logo(E.brand_dir, lid):
        raise HTTPException(404, "That logo can no longer be brought back")
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
    """Is VS Digital Pro already running on this port?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/looks", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def _older(port: int) -> bool:
    """Is the VS Digital Pro running on this port an older version than the code here?"""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1.5) as r:
            return float(json.loads(r.read())["code"]) < _code_time() - 1
    except (OSError, ValueError, KeyError):
        return True  # from before versions were asked: older


def _retire(port: int) -> None:
    """Asks the older VS Digital Pro to save and quit (or ends it, if it is too old to be asked)."""
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
                if any(n in cmd for n in ("VS Digital Pro", "vsdigitalpro", "AllProPhoto", "allprophoto", "photo_presets")):  # (its old name too)
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


def _let_page_undo() -> None:
    """⌘Z to the page (the app's own undo of your edits). pywebview's Mac window otherwise catches ⌘Z for
    its text undo and the page never sees it (⇧⌘Z got through, so only redo worked)."""
    try:
        import AppKit
        import objc
        from webview.platforms import cocoa
        host = cocoa.BrowserView.WebKitHost
        if getattr(host, "_vs_undo", False):
            return
        original = host.keyDown_

        def keyDown_(self, event):
            cmd = event.modifierFlags() & AppKit.NSCommandKeyMask
            if cmd and (event.charactersIgnoringModifiers() or "").lower() == "z":
                objc.super(host, self).keyDown_(event)  # (to the web page: its keydown handles undo and redo)
                return
            original(self, event)

        host.keyDown_ = keyDown_
        host._vs_undo = True
    except Exception:  # another pywebview: its own handling stays
        pass


def _window(url: str) -> None:
    """VS Digital Pro in its own Mac window, named and with its icon in the Dock."""
    import webview
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = info["CFBundleDisplayName"] = "VS Digital Pro"
        icon = WEB / "icon.png"
        if icon.exists():
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initWithContentsOfFile_(str(icon)))
    except Exception:
        pass
    _let_page_undo()
    win = webview.create_window("VS Digital Pro", url, width=1480, height=920, min_size=(980, 620),
                                background_color="#0b0c0e", text_select=False)
    win.events.closed += _shut_down  # closing the window quits the whole app, engine included
    webview.start()


def main() -> int:
    """uv run vsdigitalpro [--window] [--port N] [--no-browser]"""
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
    E.sharp_on = bool(prefs().get("sharp_crops", True))  # (tight crops made sharp by the AI: your setting)
    _classic()
    S.restore()
    _thumbs_ahead(list(S.photos))  # (from disk: a moment)
    CUT.want(list(S.photos))  # (the ones not cut out yet: the rest are on disk)
    _warm_up()
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
