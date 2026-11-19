"""The Culling tab. Pass 1: the app looks at every photo of a shoot (free, on this Mac) and marks it
keep or reject, with why, how sure it is and a crop on the action. Pass 2: you go through it (the
unsure ones first if you like), keep and reject, then delete the rejects (to the Trash, with undo),
copy the keepers, crop and edit them, or send them to Looks / Reel. Your own marks always win over
pass 1's, and teach it your taste for the next shoot."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps

from photo_crops import images
from photo_presets.cull import ai, export, files, measure, rank, taste

router = APIRouter()
_STATE = Path(os.environ["ALLPROPHOTO_STATE"]) if os.environ.get("ALLPROPHOTO_STATE") else None
HOME = _STATE or Path("~/.config/photo-crops-presets").expanduser()
STATE_FILE = HOME / "cull.json"
CACHE = (_STATE / "cull-cache") if _STATE else Path("~/.cache/photo-crops-presets/cull").expanduser()
IMPORTS = (_STATE / "imports") if _STATE else Path("~/Pictures/AllProPhoto Imports").expanduser()
TEST_OUT = (_STATE / "out") if _STATE else None  # a test copy never writes beside your photos
VIEW_EDGE = 2048
JPEG_HEADERS = {"Cache-Control": "private, max-age=604800"}
SEND = {"looks": None}  # set by the server: adds photos to the Looks tab

# hooks the server fills in
def _noop(paths):
    return []


class Shoot:
    def __init__(self, sid: int, name: str, folders: list[str], settings: dict | None = None,
                 auto: dict | None = None):
        self.id, self.name, self.folders = sid, name, folders
        self.settings = {"keep": "", "strict": 0.5, "per_burst": True, "size": "instagram", "saved": [],
                         **(settings or {})}  # saved: the folders your keepers went to, newest first
        self.photos: list[dict] = []
        self.by_path: dict[str, dict] = {}
        self.auto: dict[str, list] = auto or {}  # path -> [flag, sure, why]: pass 1's marks, kept as made
        self.rev = 0
        self.job: dict | None = None
        self.pass1_at: float | None = None
        self.ranked: dict = {}

    def bump(self, p: dict):
        self.rev += 1
        p["rev"] = self.rev

    def add(self, shots: list[dict]) -> list[dict]:
        new = []
        for s in shots:
            if s["path"] in self.by_path:
                continue
            p = {"id": len(self.photos), "path": s["path"], "files": s["files"], "name": s["name"], "raw": s["raw"],
                 "state": "new", "m": None, "rev": 0, "size": None}
            self.photos.append(p)
            self.by_path[p["path"]] = p
            self.bump(p)
            new.append(p)
        return new


class Cull:
    def __init__(self):
        self.lock = threading.RLock()
        self.shoots: dict[int, Shoot] = {}
        self.marks: dict[str, dict] = {}  # path -> {"flag": keep/reject, "stars": n, "crop": box}: yours
        self.ai: dict[str, dict] = {}  # path -> Gemini's rating {score, reason, crop}
        self.next = 1
        self.loaded = False
        self.queue: Queue = Queue()
        self.taste = taste.Taste(HOME / "cull-taste.json")
        self._pending = False
        self.trashed: dict[str, list] = {}  # undo tokens
        self.state_file = STATE_FILE

    # -- keeping it across restarts
    def load(self):
        with self.lock:
            if self.loaded:
                return
            self.loaded = True
            try:
                data = json.loads(self.state_file.read_text())
            except (OSError, ValueError):
                data = {}
            self.marks = data.get("marks", {})
            self.ai = data.get("ai", {})
            self.next = data.get("next", 1)
            for s in data.get("shoots", []):
                sh = Shoot(s["id"], s["name"], s["folders"], s.get("settings"), s.get("auto"))
                sh.pass1_at = s.get("pass1_at")
                if not sh.settings.get("saved"):  # (exports made before the app remembered them)
                    sh.settings["saved"] = sorted((str(d) for f in sh.folders if Path(f).is_dir() for d in Path(f).iterdir()
                                                   if d.is_dir() and (d.name == "Picks" or d.name.startswith("Culled - "))),
                                                  key=lambda d: -Path(d).stat().st_mtime)[:5]
                self.shoots[sh.id] = sh
                sh.add(files.shots_in([Path(f) for f in sh.folders]))
                self.queue.put(sh.id)
            threading.Thread(target=self._work, daemon=True).start()

    def save(self, soon: bool = False):
        """Writes the shoots and your marks. soon: a burst of marks is written once, a moment later."""
        if soon:
            with self.lock:
                if self._pending:
                    return
                self._pending = True
            threading.Timer(0.8, self.save).start()
            return
        with self.lock:
            self._pending = False
            data = {"next": self.next, "marks": self.marks, "ai": self.ai,
                    "shoots": [{"id": s.id, "name": s.name, "folders": s.folders, "settings": s.settings,
                                "auto": s.auto, "pass1_at": s.pass1_at} for s in self.shoots.values()]}
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(self.state_file)

    def shoot(self, sid: int) -> Shoot:
        self.load()
        sh = self.shoots.get(sid)
        if not sh:
            raise HTTPException(404, "That shoot is no longer here")
        return sh

    def new_shoot(self, folders: list[str], name: str | None = None) -> Shoot:
        self.load()
        with self.lock:
            for sh in self.shoots.values():
                if sh.folders == folders:
                    return sh
            sh = Shoot(self.next, name or Path(folders[0]).name, folders)
            self.next += 1
            self.shoots[sh.id] = sh
            sh.add(files.shots_in([Path(f) for f in folders]))
        self.save()
        self.queue.put(sh.id)
        return sh

    # -- the worker: thumbnails for the whole shoot first (quick), then pass 1's measurements
    def _work(self):
        pool = ThreadPoolExecutor(4)
        while True:
            sid = self.queue.get()
            sh = self.shoots.get(sid)
            if not sh:
                continue
            try:
                self._shoot_work(sh, pool)
            except Exception as x:  # (logged; the next shoot still gets looked at)
                print(f"culling: {sh.name}: {type(x).__name__}: {x}", flush=True)

    def _shoot_work(self, sh: "Shoot", pool):
        sid = sh.id
        todo = [p for p in sh.photos if p["state"] == "new"]

        def one_thumb(p):
            try:
                p["size"] = measure.thumb(Path(p["path"]), thumb_path(p))
                p["state"] = "thumb"
            except Exception as x:
                p["state"], p["error"] = "failed", f"{type(x).__name__}: {x}"[:160]
            with self.lock:
                sh.bump(p)
        list(pool.map(one_thumb, todo))
        last = time.time()
        for p in [p for p in sh.photos if p["state"] == "thumb"]:
            if sid not in self.shoots:
                break
            try:
                p["m"] = measure.measure(Path(p["path"]), CACHE / "m")
                p["state"] = "done"
            except Exception as x:
                p["state"], p["error"] = "failed", f"{type(x).__name__}: {x}"[:160]
            with self.lock:
                sh.bump(p)
            if time.time() - last > 2.0:
                self.rerank(sh)
                last = time.time()
        self.rerank(sh)
        if sh.pass1_at is None and all(p["state"] in ("done", "failed", "gone") for p in sh.photos):
            self.pass1(sh)
        elif sh.pass1_at is not None:
            # new photos (from a card still copying, or added to the folder): pass 1 marks just them
            fresh = [p for p in sh.photos if p["path"] not in sh.auto and p["state"] == "done"]
            if fresh:
                self.pass1(sh, only=[p["path"] for p in fresh])

    def rerank(self, sh: Shoot):
        items = [(p["path"], measure.when(p["m"], Path(p["path"])), p["m"]) for p in sh.photos
                 if p.get("m") and p["state"] != "gone"]
        ranked = rank.rank(items, self.taste if self.taste.ready else None)
        with self.lock:
            for p in sh.photos:
                r = ranked.get(p["path"])
                old = sh.ranked.get(p["path"])
                if r and (old is None or (round(old.score), old.burst, old.burst_best, old.issues)
                          != (round(r.score), r.burst, r.burst_best, r.issues)):
                    sh.bump(p)
            sh.ranked = ranked

    def pass1(self, sh: Shoot, only: list[str] | None = None):
        """Pass 1's marks for the whole shoot (or just new photos). Yours are never touched."""
        self.rerank(sh)
        ranked = sh.ranked
        if not ranked:
            return
        s = sh.settings
        rank.suggest(ranked, rank.parse_keep(s.get("keep"), len(ranked)), s.get("per_burst", True),
                     float(s.get("strict", 0.5)))
        with self.lock:
            for path, r in ranked.items():
                if only is not None and path not in only:
                    continue
                before = sh.auto.get(path)
                sh.auto[path] = [r.suggest, round(r.sure, 2), r.why]
                if before != sh.auto[path] and path in sh.by_path:
                    sh.bump(sh.by_path[path])
            sh.pass1_at = time.time()
        self.save()

    def view(self, sh: Shoot, p: dict) -> dict:
        m = p.get("m") or {}
        r = sh.ranked.get(p["path"])
        mine = self.marks.get(p["path"], {})
        auto = sh.auto.get(p["path"])
        aiv = self.ai.get(p["path"])
        return {
            "id": p["id"], "name": p["name"], "path": p["path"], "raw": p["raw"], "n": len(p["files"]), "state": p["state"],
            "err": p.get("error"), "size": p.get("size") or (m.get("size")),
            "t": measure.when(m, Path(p["path"])) if m else None,
            "score": round(r.score) if r else None, "issues": r.issues if r else [], "good": r.good if r else [],
            "burst": r.burst if r else None, "bsize": r.burst_size if r else 1, "best": r.burst_best if r else True,
            "auto": auto, "flag": mine.get("flag"), "stars": mine.get("stars", 0), "crop": mine.get("crop"),
            "crops": m.get("crops") or {}, "full": m.get("full"), "faces": [f for f in m.get("faces", []) if f.get("box")],
            "focus": m.get("focus_point"), "subject": m.get("group") or m.get("subject"),
            "cam": {k: m.get(k) for k in ("iso", "shutter", "aperture", "focal", "camera")} if m else {},
            "rel": round(r.parts.get("rel", 0), 2) if r else None, "taste": round(r.parts["taste"], 2) if r and "taste" in r.parts else None,
            "ai": aiv,
        }

    def summary(self, sh: Shoot) -> dict:
        here = [p for p in sh.photos if p["state"] != "gone"]  # (deleted ones are in the Trash: not waiting)
        total = len(here)
        done = sum(1 for p in here if p["state"] in ("done", "failed"))
        thumbs = sum(1 for p in here if p["state"] != "new")
        keep = reject = 0
        for p in here:
            f = self.marks.get(p["path"], {}).get("flag") or (sh.auto.get(p["path"]) or [None])[0]
            keep += f == "keep"
            reject += f == "reject"
        yours = sum(1 for p in here if self.marks.get(p["path"], {}).get("flag"))
        left = (total - done) * 0.45
        return {"id": sh.id, "name": sh.name, "folders": sh.folders, "total": total, "measured": done,
                "thumbs": thumbs, "keep": keep, "reject": reject, "yours": yours, "settings": sh.settings,
                "pass1": sh.pass1_at is not None, "left": round(left), "job": sh.job, "rev": sh.rev}


C = Cull()


def thumb_path(p: dict) -> Path:
    return CACHE / "thumbs" / f"{measure.cache_key(Path(p['path']))}.jpg"


def _photo(sid: int, pid: int) -> tuple[Shoot, dict]:
    sh = C.shoot(sid)
    if not 0 <= pid < len(sh.photos):
        raise HTTPException(404, "No such photo")
    return sh, sh.photos[pid]


def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _out_folder(sh: Shoot, name: str) -> Path:
    base = TEST_OUT if TEST_OUT else Path(sh.folders[0])
    return base / name


# -- the API ------------------------------------------------------------------------------------

@router.get("/api/cull/state")
def state():
    C.load()
    k, r = C.taste.counts()
    return {"shoots": [C.summary(s) for s in sorted(C.shoots.values(), key=lambda s: -s.id)],
            "cards": files.cards(), "taste": {"kept": k, "rejected": r, "ready": C.taste.ready, "need": taste.MIN_EACH},
            "ai": ai.key_ready(), "sizes": {k: v.label for k, v in export.SIZES.items()}, "fits": export.FITS,
            "versions": export.VERSIONS}


@router.post("/api/cull/shoots")
async def add_shoot(req: Request):
    body = await req.json()
    folders = body.get("folders")
    if not folders:
        out = _osascript('set fs to choose folder with prompt "Choose the folder (or folders) of a shoot to cull" '
                         'with multiple selections allowed\nset out to ""\nrepeat with f in fs\n'
                         'set out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
        folders = [p.strip().rstrip("/") for p in out.splitlines() if p.strip()]
    folders = [f for f in folders if Path(f).is_dir()]
    if not folders:
        return {"id": None}
    sh = C.new_shoot(folders, body.get("name"))
    return {"id": sh.id, "total": len(sh.photos)}


@router.patch("/api/cull/shoots/{sid}")
async def edit_shoot(sid: int, req: Request):
    sh = C.shoot(sid)
    body = await req.json()
    if body.get("name"):
        sh.name = str(body["name"])[:80]
    if isinstance(body.get("settings"), dict):
        sh.settings.update({k: v for k, v in body["settings"].items() if k in sh.settings})
    C.save()
    return C.summary(sh)


@router.delete("/api/cull/shoots/{sid}")
def forget_shoot(sid: int):
    """Takes the shoot out of the list (the photos and your marks stay)."""
    C.load()
    with C.lock:
        C.shoots.pop(sid, None)
    C.save()
    return {"ok": True}


@router.get("/api/cull/shoots/{sid}/photos")
def photos(sid: int, since: int = 0):
    sh = C.shoot(sid)
    with C.lock:
        changed = [C.view(sh, p) for p in sh.photos if p["rev"] > since]
    return {"rev": sh.rev, "total": len(sh.photos), "photos": changed, "shoot": C.summary(sh)}


@router.post("/api/cull/shoots/{sid}/pass1")
async def run_pass1(sid: int, req: Request):
    sh = C.shoot(sid)
    body = await req.json()
    sh.settings.update({k: body[k] for k in ("keep", "strict", "per_burst") if k in body})
    if any(p["state"] not in ("done", "failed") for p in sh.photos):
        C.save()
        return {"waiting": True}
    await _thread(C.pass1, sh)
    return {"ok": True, "shoot": C.summary(sh)}


@router.post("/api/cull/shoots/{sid}/mark")
async def mark(sid: int, req: Request):
    """Your marks: items [{id, flag: keep/reject/None (back to pass 1's), stars, crop}] (only the keys given change)."""
    sh = C.shoot(sid)
    items = (await req.json()).get("items", [])
    with C.lock:
        for it in items:
            pid = int(it["id"])
            if not 0 <= pid < len(sh.photos):
                continue
            p = sh.photos[pid]
            mine = dict(C.marks.get(p["path"], {}))
            for k in ("flag", "stars", "crop"):
                if k in it:
                    if it[k] in (None, 0, "") and k != "stars":
                        mine.pop(k, None)
                    else:
                        mine[k] = it[k]
            if mine.get("stars") == 0:
                mine.pop("stars", None)
            if mine:
                C.marks[p["path"]] = mine
            else:
                C.marks.pop(p["path"], None)
            if "flag" in it and p.get("m") and p["path"] in sh.ranked:
                C.taste.learn(p["path"], sh.ranked[p["path"]].parts, p["m"],
                              None if not it["flag"] else it["flag"] == "keep")
            sh.bump(p)
    C.save(soon=True)
    threading.Thread(target=C.taste.save, daemon=True).start()
    return {"rev": sh.rev}


@router.post("/api/cull/shoots/{sid}/trash")
async def trash(sid: int, req: Request):
    """Moves these photos (every file of each shot: JPEG and RAW) to the Trash."""
    sh = C.shoot(sid)
    ids = [int(i) for i in (await req.json()).get("ids", [])]
    chosen = [sh.photos[i] for i in ids if 0 <= i < len(sh.photos) and sh.photos[i].get("state") != "gone"]
    moved = await _thread(files.to_trash, [f for p in chosen for f in p["files"]])
    gone = {was for was, _ in moved}
    with C.lock:
        for p in chosen:
            if all(f in gone for f in p["files"]):
                p["state"] = "gone"
                sh.bump(p)
    token = f"{sid}-{time.time():.3f}"
    C.trashed[token] = moved
    return {"moved": len(chosen), "files": len(moved), "token": token}


@router.post("/api/cull/shoots/{sid}/untrash")
async def untrash(sid: int, req: Request):
    sh = C.shoot(sid)
    moved = C.trashed.pop((await req.json()).get("token", ""), [])
    n = await _thread(files.from_trash, moved)
    back = {was for was, _ in moved}
    with C.lock:
        for p in sh.photos:
            if p["state"] == "gone" and any(f in back for f in p["files"]):
                p["state"] = "done" if p.get("m") else "thumb"
                sh.bump(p)
    return {"restored": n}


@router.post("/api/cull/shoots/{sid}/export")
async def export_keepers(sid: int, req: Request):
    """what: copy (the files as they are) or edit (cropped and edited versions). Runs in the background."""
    sh = C.shoot(sid)
    body = await req.json()
    ids = [int(i) for i in body.get("ids", [])]
    chosen = [sh.photos[i] for i in ids if 0 <= i < len(sh.photos) and sh.photos[i]["state"] != "gone"]
    if not chosen:
        raise HTTPException(400, "No keepers to export")
    if sh.job and sh.job.get("state") == "now":
        raise HTTPException(409, "Still busy with the last export")
    what = body.get("what", "copy")
    size = body.get("size") or sh.settings.get("size", "instagram")
    versions = "".join(v for v in (body.get("versions") or "A") if v in "OABCD")
    fit = body.get("fit") if body.get("fit") in export.FITS else "widen"
    shown = {int(k): tuple(v) for k, v in (body.get("crops") or {}).items() if v}  # the crops the Finish page showed
    if what == "edit":
        sh.settings["size"] = size
    folder = _out_folder(sh, body.get("folder") or ("Picks" if what == "copy" else f"Culled - {export.FOLDER_NAMES[size]}"))
    sh.job = {"state": "now", "what": what, "done": 0, "total": len(chosen), "folder": str(folder), "started": time.time()}

    def run():
        try:
            for i, p in enumerate(chosen, 1):
                if what == "copy":
                    export.copy_files([Path(f) for f in p["files"]], folder)
                else:
                    a = C.ai.get(p["path"]) or {}
                    ai_crop = (tuple(a["crop"]), a.get("shape", "4:5")) if a.get("crop") else None
                    adjust_fn = (lambda img: ai.adjustments(img)) if "D" in versions else None
                    crop = shown.get(p["id"]) if size != "ai" or not ai_crop else None
                    if crop is None and size != "ai":
                        crop = C.marks.get(p["path"], {}).get("crop")
                    export.edit_one(Path(p["path"]), p.get("m") or {}, size, versions, folder, crop, ai_crop, adjust_fn, fit)
                sh.job["done"] = i
            sh.job["state"] = "done"
        except Exception as x:
            sh.job.update(state="failed", error=f"{type(x).__name__}: {x}"[:200])
        sh.job["ended"] = time.time()
        if sh.job.get("done"):  # remembered, so the folder can always be found again
            sh.settings["saved"] = [str(folder)] + [f for f in sh.settings.get("saved", []) if f != str(folder)][:4]
            C.save()
        sh.rev += 1
    threading.Thread(target=run, daemon=True).start()
    return {"folder": str(folder), "total": len(chosen)}


@router.post("/api/cull/shoots/{sid}/ai")
async def ask_ai(sid: int, req: Request):
    """Gemini rates these photos (score, reason, its best crop). estimate: only the count and cost."""
    sh = C.shoot(sid)
    body = await req.json()
    ids = [int(i) for i in body.get("ids", [])]
    chosen = [sh.photos[i] for i in ids if 0 <= i < len(sh.photos) and sh.photos[i]["state"] == "done"]
    todo = [p for p in chosen if p["path"] not in C.ai]
    if body.get("estimate"):
        return {"calls": len(todo), "rated": len(chosen) - len(todo), "cost": ai.cost(len(todo)), "key": ai.key_ready()}
    if not ai.key_ready():
        raise HTTPException(400, "No Gemini key found: add export GEMINI_API_KEY=... to ~/.zshrc")
    if sh.job and sh.job.get("state") == "now":
        raise HTTPException(409, "Still busy with the last job")
    sh.job = {"state": "now", "what": "ai", "done": 0, "total": len(todo), "started": time.time(), "tokens": 0}

    def run():
        try:
            for i, p in enumerate(todo, 1):
                usage: list = []
                try:
                    a = ai.rate(images.preview_image(Path(p["path"]), 1536), usage)
                    C.ai[p["path"]] = {"score": a.score, "reason": a.reason, "moment": a.subject_description,
                                       "crop": [a.crop_xmin, a.crop_ymin, a.crop_xmax, a.crop_ymax], "shape": a.crop_shape}
                except Exception as x:
                    C.ai[p["path"]] = {"error": f"{type(x).__name__}: {str(x)[:80]}"}
                sh.job["tokens"] += sum(usage)
                sh.job["done"] = i
                with C.lock:
                    sh.bump(p)
            sh.job["state"] = "done"
        except Exception as x:
            sh.job.update(state="failed", error=str(x)[:200])
        sh.job["ended"] = time.time()
        C.save()
    threading.Thread(target=run, daemon=True).start()
    return {"total": len(todo)}


@router.post("/api/cull/shoots/{sid}/send")
async def send(sid: int, req: Request):
    """The keepers into the Looks tab (and from there, Reel)."""
    sh = C.shoot(sid)
    ids = [int(i) for i in (await req.json()).get("ids", [])]
    paths = [Path(sh.photos[i]["path"]) for i in ids if 0 <= i < len(sh.photos) and sh.photos[i]["state"] != "gone"]
    added = (SEND["looks"] or _noop)(paths)
    return {"added": len(added), "asked": len(paths)}


@router.get("/api/cull/cards")
def cards():
    return {"cards": files.cards()}


@router.post("/api/cull/import")
async def import_card(req: Request):
    """Copies a camera card into a new folder and starts a shoot on it while it copies."""
    body = await req.json()
    vol = Path(body.get("volume", ""))
    if not (vol / "DCIM").is_dir():
        raise HTTPException(400, "That card is no longer plugged in")
    parent = Path(body.get("parent") or IMPORTS).expanduser()
    if body.get("choose"):
        out = _osascript('POSIX path of (choose folder with prompt "Where should the card\'s photos go?")')
        if not out.strip():
            return {"id": None}
        parent = Path(out.strip())
    dest = parent / (body.get("name") or files.import_folder_name(vol))
    dest.mkdir(parents=True, exist_ok=True)
    sh = C.new_shoot([str(dest)], dest.name)
    sh.job = {"state": "now", "what": "import", "done": 0, "total": 0, "folder": str(dest), "started": time.time()}

    def progress(done, total):
        sh.job.update(done=done, total=total)
        sh.rev += 1

    def on_file(path: Path):
        with C.lock:
            shots = [s for s in files.shots_in([dest]) if path.stem == Path(s["path"]).stem]
            for s in shots:  # (a RAW arriving after its JPEG joins the same shot)
                if s["path"] in sh.by_path:
                    sh.by_path[s["path"]]["files"] = s["files"]
            if sh.add(shots):
                C.queue.put(sh.id)

    def run():
        try:
            copied, skipped = files.import_card(vol, dest, progress, on_file)
            sh.job.update(state="done", copied=copied, skipped=skipped)
        except Exception as x:
            sh.job.update(state="failed", error=f"{type(x).__name__}: {x}"[:200])
        sh.job["ended"] = time.time()
        sh.rev += 1
        C.queue.put(sh.id)
    threading.Thread(target=run, daemon=True).start()
    return {"id": sh.id, "folder": str(dest)}


async def _thread(fn, *a):
    import asyncio
    return await asyncio.get_running_loop().run_in_executor(None, fn, *a)


# -- pictures -----------------------------------------------------------------------------------

@router.get("/img/cull/{sid}/{pid}/thumb.jpg")
def thumb(sid: int, pid: int):
    _, p = _photo(sid, pid)
    t = thumb_path(p)
    if not t.exists():
        try:
            measure.thumb(Path(p["path"]), t)
        except Exception:
            raise HTTPException(404, "No picture")
    return FileResponse(t, media_type="image/jpeg", headers=JPEG_HEADERS)


@router.get("/img/cull/{sid}/{pid}/view.jpg")
def view(sid: int, pid: int):
    _, p = _photo(sid, pid)
    v = CACHE / "views" / f"{measure.cache_key(Path(p['path']))}.jpg"
    if not v.exists():
        img = images.preview_image(Path(p["path"]), VIEW_EDGE)
        v.parent.mkdir(parents=True, exist_ok=True)
        tmp = v.with_suffix(".tmp")
        img.save(tmp, "JPEG", quality=88)
        tmp.replace(v)
    return FileResponse(v, media_type="image/jpeg", headers=JPEG_HEADERS)


_full: dict[str, Image.Image] = {}
_full_lock = threading.Lock()


def _full_image(path: str) -> Image.Image:
    """The photo at full size (kept for the last two looked at: zooming around one is quick)."""
    with _full_lock:
        if path in _full:
            return _full[path]
    p = Path(path)
    img = images.develop_raw(p) if images.is_raw(p) else ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    with _full_lock:
        if len(_full) >= 2:
            _full.pop(next(iter(_full)))
        _full[path] = img
    return img


@router.get("/img/cull/{sid}/{pid}/zoom.jpg")
def zoom(sid: int, pid: int, x: float = 0.5, y: float = 0.5, w: int = 900, h: int = 700):
    """The photo at 100% around (x, y) (shares of it): to check focus and eyes."""
    _, p = _photo(sid, pid)
    img = _full_image(p["path"])
    W, H = img.size
    w, h = min(w, W, 2400), min(h, H, 2400)
    left = int(min(max(x * W - w / 2, 0), W - w))
    top = int(min(max(y * H - h / 2, 0), H - h))
    import io
    buf = io.BytesIO()
    img.crop((left, top, left + w, top + h)).save(buf, "JPEG", quality=90)
    return Response(buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600", "X-Box": f"{left / W},{top / H},{(left + w) / W},{(top + h) / H}"})
