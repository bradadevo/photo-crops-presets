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

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from photo_crops import images
from photo_crops.ui import choose_folder
from photo_presets import deliver, edits, engine, pipeline, presets, reel, timing
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
SESSION = (STATE or CONFIG) / "studio-session.json"  # the photos you are working on, kept for next time
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
    started: float = 0.0
    extra: float = 0.0  # one-off work in this look's time (getting the photo ready, loading models)
    loading: bool = False
    secs: float = 0.0
    error: str = ""
    future: Future | None = None

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

    def save(self) -> None:
        try:
            SESSION.parent.mkdir(parents=True, exist_ok=True)
            SESSION.write_text(json.dumps({"photos": [str(p.path) for p in self.photos.values()]}, indent=1))
        except OSError:
            pass

    def restore(self) -> None:
        """The photos from last time (those still there)."""
        try:
            paths = [Path(p) for p in json.loads(SESSION.read_text()).get("photos", [])]
        except (OSError, ValueError, AttributeError):
            return
        self.add_photos([p for p in paths if p.is_file()])

    def busy(self) -> bool:
        return any(s.state in ("wait", "now") for s in self.slots.values()) or any(
            t.state == "running" for t in self.tasks.values())

    def left(self) -> float:
        """About how many seconds the looks still waiting take."""
        pace = 1.0
        if self.pace:
            pace = min(2.5, max(0.5, sum(t for t, _ in self.pace) / max(1e-6, sum(x for _, x in self.pace))))
        total = 0.0
        for s in self.slots.values():
            if s.state == "wait":
                total += s.expect * pace
            elif s.state == "now":
                total += max(0.0, (s.expect + s.extra) * pace - (time.time() - s.started))
        return total


E = Engine()
S = Session()
W = Worker()


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


def _swatch(pid: int, name: str) -> bytes | None:
    recipe = presets.load_all().get(name)
    if recipe is None or timing.uses_ai(recipe):
        return None  # the AI looks take 20 s each: shown by their example instead
    recipe = dict(recipe, name=name)
    path = S.photo(pid).path
    p = E.ready(path, "none", recipe)
    small = p.image.copy()
    small.thumbnail((SWATCH, SWATCH))
    img, _ = pipeline.render(small, recipe, E.library, p.scene, 0)
    keep_example(name, img)
    return jpeg(img, quality=84)


SWATCHES: dict[tuple[int, str], Future] = {}


def swatch_future(pid: int, name: str) -> Future:
    key = (pid, name)
    with S.lock:
        fut = SWATCHES.get(key)
        if fut is None or fut.cancelled():
            for k, f in list(SWATCHES.items()):  # another photo's previews: not needed now
                if k[0] != pid and not f.done():
                    f.cancel()
            recipe = presets.load_all().get(name, {})
            slow = pipeline.needs_cutout(recipe) or bool(recipe.get("frame"))  # wait for the cut-out: after the quick ones
            fut = SWATCHES[key] = W.submit(PREVIEW + slow, _swatch, pid, name)
        return fut


def _try(pid: int, name: str) -> bytes | None:
    recipe = presets.load_all().get(name)
    if recipe is None or timing.uses_ai(recipe):
        return None
    recipe = dict(recipe, name=name)
    p = E.ready(S.photo(pid).path, "none", recipe)
    small = p.image.copy()
    small.thumbnail((TRY, TRY))
    img, _ = pipeline.render(small, recipe, E.library, p.scene, 0)
    return jpeg(img, quality=86)


TRIES: dict[tuple[int, str], Future] = {}


def try_future(pid: int, name: str) -> Future:
    """One look tried on at a time: moving to another card drops the one not started."""
    key = (pid, name)
    with S.lock:
        for k, f in list(TRIES.items()):
            if k != key and not f.done():
                f.cancel()
        fut = TRIES.get(key)
        if fut is None or fut.cancelled():
            fut = TRIES[key] = W.submit(RUN, _try, pid, name)
        return fut


# Making looks ------------------------------------------------------------------------------

def _make(slot: Slot, job: Job, crop: str) -> None:
    """One look, on the worker."""
    fresh = not E.is_prepared(job.path, crop)
    extra = timing.PHOTO_READY if fresh else 0.0
    if pipeline.needs_cutout(job.recipe) and not E.is_cut_out(job.path, crop):
        extra += timing.CUT_OUT
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
    if name in presets.load_all():
        keep_example(name, r.after)
    slot.result, slot.secs, slot.state = r, took, "done"


def start_run(jobs: list[tuple[int, Job]], crop: str, by_photo: list[int] | None = None) -> list[int]:
    """The jobs (photo id, job) as slots, listed in the order given. by_photo: made
    photo by photo in this order instead (so each photo is prepared once)."""
    run = next(S.runs)
    slots = []
    with S.lock:
        for pid, job in jobs:
            name = job.recipe.get("name", "")
            sid = next(S.ids)
            S.slots[sid] = Slot(sid, run, pid, name or "Random look", job.title, timing.seconds(name, job.recipe),
                                crop=crop)
            slots.append(S.slots[sid])
        order = range(len(jobs))
        if by_photo:
            order = sorted(order, key=lambda i: by_photo.index(jobs[i][0]))
        for i in order:
            slots[i].future = W.submit(RUN, _make, slots[i], jobs[i][1], crop)
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
                        "cutout": pipeline.needs_cutout(r), "example": example_file(name).exists(),
                        "mine": group == presets.MINE})
    return out


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/state")
def state():
    with S.lock:
        photos = [{"id": p.id, "name": p.name} for p in S.photos.values()]
        slots = [s.public() for s in S.slots.values()]
        tasks = [t.public() for t in S.tasks.values() if t.state == "running" or time.time() - t.started < 600]
    credit = deliver.Credit.load()
    return {"photos": photos, "slots": slots, "tasks": tasks, "busy": S.busy(), "left": round(S.left()),
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
    """{names: [...]}: starts making these looks' cards on the photo, and says which are ready
    (the page asks again until all are; nothing waits on an open connection)."""
    S.photo(pid)
    ready, failed = [], []
    for name in (await req.json()).get("names", [])[:80]:
        fut = swatch_future(pid, name)
        if fut.done():
            (failed if fut.cancelled() or fut.exception() or fut.result() is None else ready).append(name)
    return {"ready": ready, "failed": failed}


@app.get("/img/swatch/{pid}/{name}.jpg")
def swatch(pid: int, name: str):
    fut = SWATCHES.get((pid, name))
    if fut is None or not fut.done() or fut.cancelled() or fut.exception() or fut.result() is None:
        raise HTTPException(404, "Not made yet")
    return picture(fut.result())


@app.get("/img/try/{pid}/{name}.jpg")
async def try_on(pid: int, name: str):
    S.photo(pid)
    try:
        data = await asyncio.wrap_future(try_future(pid, name))
    except CancelledError:
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
    paths = [S.photo(p).path for p in pids]
    if body.get("random"):
        made = E.explore_jobs(paths, int(body["random"]))
        by_path = {str(S.photo(p).path): p for p in pids}
        jobs = [(by_path[str(j.path)], j) for j in made]
    else:
        saved = presets.load_all()
        names = [n for n in body.get("looks", []) if n in saved]
        if not names:
            raise HTTPException(400, "Choose at least one look")
        jobs = [(p, Job(S.photo(p).path, dict(saved[n], name=n), 0)) for n in names for p in pids]
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


@app.post("/api/photos/{pid}/original")
def original(pid: int):
    """The photo itself as a picture to edit (no look): made once, then reused."""
    S.photo(pid)
    with S.lock:
        for s in S.slots.values():
            if s.photo == pid and s.look == "Original" and s.crop == "none" and s.state != "failed":
                return {"slot": s.id}
    return {"slot": start_run([(pid, Job(S.photo(pid).path, dict(ORIGINAL), 0))], "none")[0]}


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
    ids = set((await req.json()).get("ids", []))
    with S.lock:
        for sid in ids:
            s = S.slots.get(sid)
            if s and s.state not in ("now",) and (s.future is None or s.future.done() or s.future.cancel()):
                del S.slots[sid]
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
    arr = pipeline.to_array(r.after)
    if kind == "before":
        return jpeg(pipeline.to_image(edits.geometry(pipeline.to_array(r.before), r.edits)), quality=90)
    if kind == "base":
        return jpeg(pipeline.to_image(E.finalize(r, arr, geometry=False, texts=False)), quality=90)
    if kind.startswith("area-"):
        base = E.finalize(r, arr, geometry=False, texts=False)
        areas = (r.edits or {}).get("areas", [])
        i = int(kind[5:])
        if 0 <= i < len(areas):
            m = E.part(r, areas[i]["x"], areas[i]["y"], *base.shape[:2])[..., None] * 0.5
            base = base * (1 - m) + engine.CUTOUT_TINT * m
        return jpeg(pipeline.to_image(base), quality=88)
    if kind == "thumb":
        return jpeg(pipeline.to_image(E.finalize(r, arr)), THUMB, 84)
    if kind == "full":
        return jpeg(pipeline.to_image(E.finalize(r, arr)), quality=92)
    return jpeg(pipeline.to_image(E.finalize(r, arr, texts=False)), quality=90)


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
    r = s.result
    if "adjust" in body:
        r = await asyncio.to_thread(E.adjust, r, _adj(body["adjust"]))
    if "edits" in body:
        r = dataclasses.replace(r, edits=edits.clean(body["edits"]))
    await traced(r)
    with S.lock:
        s.result, s.ver = r, s.ver + 1
    return s.public()


@app.post("/api/slots/{sid}/whitebalance")
async def white_balance(sid: int, req: Request):
    """{x, y}: a click on something that should be white or gray (shares of the picture shown)."""
    s = S.slot(sid)
    body = await req.json()
    r = s.result
    await traced(r)
    shown = await asyncio.to_thread(E.finalize, r, pipeline.to_array(r.after), True, True, False)
    adj = pipeline.adjustments(r.recipe)
    adj["warmth"], adj["tint"] = edits.white_balance(shown, float(body["x"]), float(body["y"]), adj["warmth"], adj["tint"])
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


async def _remake_photo(source: Path) -> int:
    """Every look of this photo made again (after a removal), keeping each one's tuning and edits."""
    same = [o for o in S.slots.values() if o.result is not None and o.result.source == source]
    for o in same:
        o.state, o.started, o.extra, o.loading = "now", time.time(), 0.0, False
    for o in same:
        try:
            r = await asyncio.wrap_future(W.submit(RUN, E.remake, o.result))
            o.result, o.ver = r, o.ver + 1
        finally:
            o.state = "done"
    return len(same)


@app.post("/api/slots/{sid}/remove")
async def remove_distraction(sid: int, req: Request):
    """{strokes: [{pts: [[x, y]...], r}]} brushed on the picture (shares, before straightening and
    cropping): what is under them is removed from the photo, and its looks are made again."""
    s = S.slot(sid)
    r = s.result
    strokes = (await req.json()).get("strokes", [])
    if not strokes:
        raise HTTPException(400, "Brush over what should go")
    scale = E.photo_scale(r)
    removal = [{"pts": [list(E.to_photo(r, float(x), float(y))) for x, y in st.get("pts", [])],
                "r": float(st.get("r", 0.02)) * scale} for st in strokes]
    removals = E.removals.get(str(r.source), []) + [removal]
    await asyncio.wrap_future(W.submit(FIX, E.set_removals, r.source, removals))
    count = await _remake_photo(r.source)
    return {"photo": s.photo, "removals": removals, "count": count}


@app.post("/api/photos/{pid}/removals")
async def set_removals(pid: int, req: Request):
    """{removals: [...]}: the photo's removals as given (undo and redo)."""
    path = S.photo(pid).path
    removals = (await req.json()).get("removals", [])
    await asyncio.wrap_future(W.submit(FIX, E.set_removals, path, removals))
    return {"removals": removals, "count": await _remake_photo(path)}


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
    name = ((await req.json()).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Give the preset a name")
    recipe = dict(S.slot(sid).result.recipe)
    recipe.pop("match", None)  # a game match belongs to its photo, not to the look
    recipe.pop("name", None)
    presets.save(name, recipe)
    keep_example(name, S.slot(sid).result.after)
    return {"name": name}


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
    save_prefs({"folder": str(dest), "how": how, "kind": kind, "sizes": sizes,
                "watermark": {k: w.get(k) for k in ("on", "text", "style", "opacity")}})
    task = Task(next(S.ids), "export", len(chosen), now=chosen[0].title)
    S.tasks[task.id] = task
    W.submit(OUTPUT, _export, task, chosen, dest, how, kind, sizes, credit, mark)
    return task.public()


def _export(task: Task, chosen, dest: Path, how, kind, sizes, credit, mark) -> None:
    def tick(done, total, name):
        task.done, task.now = done, name
    try:
        into = Path(tempfile.mkdtemp(prefix="allprophoto-zip-")) if how == ZIP else dest
        saved, notes = E.export(chosen, into, tick, kind, sizes, credit, mark)
        n = len(chosen)
        photos = f"{n} picture{'s' if n != 1 else ''}"
        if how == ZIP:
            dest.mkdir(parents=True, exist_ok=True)
            zipped = engine._unique(dest / f"AllProPhoto {time.strftime('%Y-%m-%d %H.%M.%S')} ({photos}).zip")
            with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(into.rglob("*")):
                    if f.is_file():
                        z.write(f, f.relative_to(into))
            shutil.rmtree(into, ignore_errors=True)
            task.path, task.message = str(zipped), f"Saved {photos} in {zipped.name}"
        else:
            task.path = str(saved[0]) if saved else str(dest)
            task.message = f"Saved {photos} to {dest.name}" + (f" ({len(saved)} files)" if len(saved) != n else "")
        if notes:
            task.message += ". " + "; ".join(notes)
        task.state = "done"
    except Exception as e:
        task.state, task.message = "failed", f"Export failed: {e}"


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


app.mount("/static", StaticFiles(directory=WEB), name="static")


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
    webview.create_window("AllProPhoto", url, width=1480, height=920, min_size=(980, 620),
                          background_color="#0b0c0e", text_select=False)
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
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
