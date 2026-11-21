"""The Check tab: how a video or photo was shot, what is holding it back, fixes for the file itself
(a new copy next to it, the original never changed) and what to change next time; files compared side
by side, and the assessment exported as a Word report or a spreadsheet. No AI (see photo_presets.clipcheck)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path
from queue import Queue

import numpy as np
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image

from photo_presets.clipcheck import analyze, fixes, moments, recommend, report, still

router = APIRouter()
VERSION = 3  # bump when the measurements change, so old results are measured again
_STATE = Path(os.environ["ALLPROPHOTO_STATE"]) if os.environ.get("ALLPROPHOTO_STATE") else None
HOME = _STATE or Path("~/.config/photo-crops-presets").expanduser()
LIST_FILE = HOME / "check.json"
ADDED = HOME / "check-added"  # files dropped on the page (a copy: the page can't see where they came from)
CACHE = (_STATE / "check-cache") if _STATE else Path("~/.cache/photo-crops-presets/check").expanduser()
FALLBACK_OUT = (_STATE / "out") if _STATE else Path("~/Movies/Clip Analysis").expanduser()  # (a test copy: never beside your files)
JPEG_HEADERS = {"Cache-Control": "private, max-age=86400"}


class Files:
    """The files in the Check tab, their results and their fixes; kept across restarts."""

    def __init__(self):
        self.lock = threading.RLock()
        self.items: dict[int, dict] = {}
        self.next = 1
        self.queue: Queue = Queue()
        self.loaded = False

    def load(self):
        with self.lock:
            if self.loaded:
                return
            self.loaded = True
            try:
                saved = json.loads(LIST_FILE.read_text())
            except (OSError, ValueError):
                saved = []
            for e in saved:
                if Path(e["path"]).exists():
                    self._put(e["path"], e.get("id"), e.get("fixes"), e.get("fixed"))
            threading.Thread(target=self._work, daemon=True).start()

    def save(self):
        with self.lock:
            data = [{"id": i, "path": e["path"], "fixes": e.get("fixes"), "fixed": e.get("fixed", [])}
                    for i, e in self.items.items()]
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = LIST_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(LIST_FILE)

    def _put(self, path: str, fid: int | None = None, saved_fixes=None, fixed=None) -> int:
        fid = fid or self.next
        self.next = max(self.next, fid + 1)
        self.items[fid] = {"id": fid, "path": path, "kind": analyze.kind_of(path), "state": "wait", "added": time.time(),
                           "fixes": saved_fixes, "fixed": fixed or [], "job": None}
        self.queue.put(fid)
        return fid

    def add(self, paths: list[str]) -> list[int]:
        self.load()
        with self.lock:
            have = {e["path"]: i for i, e in self.items.items()}
            ids = [have.get(p) or self._put(p) for p in analyze.find_files(paths)]
        self.save()
        return ids

    def get(self, fid: int) -> dict:
        self.load()
        e = self.items.get(fid)
        if not e:
            raise HTTPException(404, "That file is no longer in the list")
        return e

    def _work(self):
        while True:
            fid = self.queue.get()
            e = self.items.get(fid)
            if not e or e["state"] == "done":
                continue
            e["state"], e["started"] = "now", time.time()
            try:
                e.update(measure(e["path"]))
                e["state"] = "done" if not e.get("error") else "failed"
            except Exception as x:  # one bad file never stops the others
                e["state"], e["error"] = "failed", f"{type(x).__name__}: {x}"[:200]


F = Files()


def _key(path: str) -> str:
    st = Path(path).stat()
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:20]


def measure(path: str) -> dict:
    """The file's results (kept on disk: measured once)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    keep = CACHE / f"{_key(path)}.pkl"
    if keep.exists():
        try:
            return pickle.loads(keep.read_bytes())
        except Exception:
            pass
    r = analyze.analyze(path)
    if isinstance(r, analyze.Failed):
        return {"error": r.error}
    out = {"result": r}
    if r.kind == "video":
        out["moments"] = moments.find(r.stats, r.info.fps, r.info.duration)
        out["look"] = fixes.measure_look(path, "video", r.info.duration)
        shaky = sum(m.end - m.start for m in out["moments"] if m.kind == "shaky") / max(0.1, r.info.duration)
    else:
        out["moments"] = []
        out["look"] = fixes.measure_look(path, "photo")
        shaky = 0.0
    out["suggested"] = fixes.suggest(r.kind, r.stats, out["look"], r.camera, shaky, path)
    keep.write_bytes(pickle.dumps(out))
    return out


def _estimate(e: dict) -> float:
    """Seconds measuring takes (a 4K video about a third of its length; a photo a second or two)."""
    if e["kind"] == "photo":
        return 2.5 if Path(e["path"]).suffix.lower() in still.RAW_EXTENSIONS else 1.5
    from photo_presets.clipcheck.video import duration_of
    if "duration" not in e:
        e["duration"] = duration_of(e["path"])
    return 4 + e["duration"] * 0.45


def summary_line(r) -> str:
    c = r.camera
    bits = [" ".join(x for x in [c.get("make"), c.get("camera")] if x), c.get("lens", "")]
    if r.kind == "video":
        bits += [f"{r.info.width}×{r.info.height}", f"{r.info.fps:g} fps", f"{r.info.duration:.1f} s"]
    else:
        bits += [f"{r.info.width}×{r.info.height}"]
    if c.get("aperture"):
        bits.append(f"f/{c['aperture']:g}")
    if c.get("shutter"):
        bits.append(still.shutter_text(c["shutter"]))
    if c.get("iso"):
        bits.append(f"ISO {c['iso']}")
    return " · ".join(b for b in bits if b)


def _settings(e: dict) -> dict:
    """The fixes as you set them (or as suggested)."""
    sug = {f["id"]: {"on": f["on"], "value": f["value"]} for f in e.get("suggested", [])}
    return {**sug, **(e.get("fixes") or {})}


def _rec_input(e: dict) -> dict:
    """What the recommendations are made from: the findings, the fixes turned on, the settings and habits."""
    r, on = e["result"], _settings(e)
    return {"name": Path(e["path"]).name, "kind": r.kind, "findings": r.advice.findings,
            "fixes_on": [f for f in e.get("suggested", []) if on.get(f["id"], {}).get("on")],
            "settings": [list(s) for s in r.advice.settings], "habits": r.advice.habits}


def _row(e: dict) -> dict:
    out = {"id": e["id"], "name": Path(e["path"]).name, "path": e["path"], "kind": e["kind"], "state": e["state"],
           "error": e.get("error")}
    if e["state"] in ("wait", "now"):
        est = _estimate(e)
        out["left"] = max(1, est - (time.time() - e.get("started", time.time()))) if e["state"] == "now" else est
    if e["state"] == "done":
        r = e["result"]
        problems = [f for f in r.advice.findings if not f.startswith(("No problems", "Focus:", "Focus mode", "The sharpest detail"))
                    and "fps: smooth motion" not in f and "holds up well" not in f]
        out.update(problems=len(problems), summary=summary_line(r), fixes_on=sum(1 for v in _settings(e).values() if v.get("on")))
    if e.get("job"):
        out["job"] = {k: v for k, v in e["job"].items() if k != "thread"}
    return out


@router.get("/api/check/state")
def state():
    F.load()
    with F.lock:
        rows = [_row(e) for e in sorted(F.items.values(), key=lambda x: x["added"])]
    waiting = [r for r in rows if r["state"] in ("wait", "now")]
    return {"files": rows, "left": sum(r.get("left", 0) for r in waiting)}


@router.get("/api/check/file/{fid}")
def detail(fid: int):
    e = F.get(fid)
    out = _row(e)
    if e["state"] != "done":
        return out
    r = e["result"]
    settings = _settings(e)
    out.update(
        findings=r.advice.findings, advice=[list(s) for s in r.advice.settings], habits=r.advice.habits,
        camera=[list(x) for x in analyze.settings_rows(r)], measured=[list(x) for x in analyze.measurement_rows(r)],
        moments=[{**asdict(m), "clock": moments.clock(m.start)} for m in e.get("moments", [])],
        fixes=[{**f, **settings.get(f["id"], {})} for f in e.get("suggested", [])],
        width=r.info.width, height=r.info.height, fixed=e.get("fixed", []),
        raw=Path(e["path"]).suffix.lower() in still.RAW_EXTENSIONS)
    if r.kind == "video":
        out.update(duration=r.info.duration, fps=r.info.fps)
    else:
        out["focus_spot"] = list(r.stats.focus_spot)
    out["estimate"] = fixes.estimate_seconds(r.kind, settings, r.info)
    x = _rec_input(e)
    out["recommend"] = recommend.for_file(x["findings"], x["fixes_on"], x["settings"], x["habits"])
    return out


@router.post("/api/check/summary")
async def summary(req: Request):
    """The recommendations across these files (all checked files when none are given)."""
    ids = (await req.json()).get("ids") or []
    F.load()
    with F.lock:
        es = [e for e in (F.items.values() if not ids else (F.items.get(i) for i in ids)) if e and e["state"] == "done"]
        rows = [{**_rec_input(e), "id": e["id"]} for e in sorted(es, key=lambda x: x["added"])]
    out = recommend.across(rows)
    ids_by_name = {r["name"]: r["id"] for r in rows}
    out["ids"] = ids_by_name
    return out


@router.put("/api/check/file/{fid}/fixes")
async def set_fixes(fid: int, req: Request):
    e = F.get(fid)
    body = (await req.json()).get("fixes") or {}
    clean = {}
    for k, v in body.items():
        if k in fixes.CATALOG and isinstance(v, dict):
            f = fixes.CATALOG[k]
            clean[k] = {"on": bool(v.get("on")), "value": float(np.clip(float(v.get("value", 0)), f.lo, f.hi))}
    e["fixes"] = clean
    F.save()
    r = e.get("result")
    return {"ok": True, "estimate": fixes.estimate_seconds(r.kind, _settings(e), r.info) if r else 0}


@router.delete("/api/check/file/{fid}")
def remove(fid: int):
    e = F.get(fid)
    with F.lock:
        F.items.pop(fid, None)
    F.save()
    return {"entry": {"id": fid, "path": e["path"], "fixes": e.get("fixes"), "fixed": e.get("fixed", [])}}


@router.post("/api/check/restore")
async def restore(req: Request):
    entry = (await req.json()).get("entry") or {}
    if not entry.get("path") or not Path(entry["path"]).exists():
        raise HTTPException(404, "That file is no longer there")
    F.load()
    with F.lock:
        fid = F._put(entry["path"], entry.get("id") if entry.get("id") not in F.items else None,
                     entry.get("fixes"), entry.get("fixed"))
    F.save()
    return {"id": fid}


# Adding files -------------------------------------------------------------------------------------

def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


@router.post("/api/check/choose")
async def choose(req: Request):
    """The Mac's own dialog: files (videos and photos) or a folder."""
    kind = (await req.json()).get("kind", "files")
    if kind == "folder":
        out = _osascript('POSIX path of (choose folder with prompt "Choose a folder of clips or photos")')
    else:
        out = _osascript('set fs to choose file with prompt "Choose clips or photos to check" of type '
                         '{"public.movie", "public.image", "public.camera-raw-image"} with multiple selections allowed\n'
                         'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    paths = [p.strip() for p in out.splitlines() if p.strip()]
    return {"added": F.add(paths) if paths else []}


@router.post("/api/check/upload")
async def upload(files: list[UploadFile] = File(...)):
    folder = ADDED / time.strftime("%Y-%m-%d %H.%M.%S")
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        dest = folder / Path(f.filename or "file").name
        with open(dest, "wb") as out:
            while chunk := await f.read(8 << 20):
                out.write(chunk)
        paths.append(str(dest))
    return {"added": F.add(paths)}


# Pictures -----------------------------------------------------------------------------------------

_PICS: dict = {}


def _jpeg(rgb: np.ndarray, quality: int = 86) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _kept(key, make) -> bytes:
    if key not in _PICS:
        if len(_PICS) > 300:
            _PICS.pop(next(iter(_PICS)))
        _PICS[key] = make()
    return _PICS[key]


@router.get("/img/check/{fid}/thumb.jpg")
def thumb(fid: int):
    e = F.get(fid)

    def make():
        if e["kind"] == "video":
            f = fixes.frame_at(e["path"], 1.0, 360)
            if f is None:
                raise HTTPException(404)
            return _jpeg(f, 80)
        return _jpeg(fixes.load_rgb(e["path"], 360), 80)
    return Response(_kept(("thumb", fid, e["path"]), make), media_type="image/jpeg", headers=JPEG_HEADERS)


@router.get("/img/check/{fid}/view.jpg")
def view(fid: int, t: float = 0.0, fixed: int = 0, s: str = ""):
    """The picture (at time t of a video), as it is or with the fixes switched on (s: their settings)."""
    e = F.get(fid)
    settings = json.loads(s) if s else _settings(e)
    look = e.get("look", {})

    def make():
        if e["kind"] == "video":
            fps = e["result"].info.fps if e.get("result") else 30
            f = fixes.video_preview(e["path"], t, settings, look, fps) if fixed else fixes.frame_at(e["path"], t, fixes.PREVIEW_EDGE)
        else:
            f = fixes.photo_preview(e["path"], settings) if fixed else fixes.load_rgb(e["path"], fixes.PREVIEW_EDGE)
        if f is None:
            raise HTTPException(404, "Could not read that moment")
        return _jpeg(f)
    key = ("view", fid, round(t, 2), fixed, json.dumps(settings, sort_keys=True) if fixed else "")
    return Response(_kept(key, make), media_type="image/jpeg", headers=JPEG_HEADERS)


@router.get("/img/check/{fid}/marks.jpg")
def marks(fid: int):
    e = F.get(fid)
    return Response(_kept(("marks", fid), lambda: _jpeg(fixes.marks(e["path"]))), media_type="image/jpeg",
                    headers=JPEG_HEADERS)


@router.get("/media/check/{fid}/moment/{i}.mp4")
def moment_clip(fid: int, i: int):
    e = F.get(fid)
    ms = e.get("moments") or []
    if not 0 <= i < len(ms):
        raise HTTPException(404)
    dest = CACHE / "moments" / f"{_key(e['path'])}-{i}.mp4"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        fixes.moment_clip(e["path"], ms[i].start, ms[i].end, dest)
    return FileResponse(dest, media_type="video/mp4")


# Fixing -------------------------------------------------------------------------------------------

@router.post("/api/check/file/{fid}/fix")
def make_fixed(fid: int):
    """A fixed copy of the file, made in the background (its progress is in the file's row)."""
    e = F.get(fid)
    if e.get("job") and e["job"]["state"] == "now":
        raise HTTPException(409, "A fixed copy of this file is already being made")
    r = e.get("result")
    if not r:
        raise HTTPException(400, "This file hasn't been checked yet")
    settings = _settings(e)
    if not any(v.get("on") and v.get("value") for v in settings.values()):
        raise HTTPException(400, "Switch on at least one fix first")
    ext = ".mp4" if r.kind == "video" else ".jpg"
    dest = fixes.fixed_path(e["path"] if not _STATE else str(FALLBACK_OUT / Path(e["path"]).name), FALLBACK_OUT / "Fixed", ext)
    est = fixes.estimate_seconds(r.kind, settings, r.info)
    job = {"state": "now", "pct": 0.0, "dest": str(dest), "started": time.time(), "estimate": est,
           "fixes": [fixes.CATALOG[k].label for k, v in settings.items() if v.get("on") and v.get("value")]}
    e["job"] = job

    def run():
        try:
            def step(p):
                job["pct"] = round(float(p), 3)
            if r.kind == "video":
                fixes.fix_video(e["path"], settings, e.get("look", {}), r.info, dest, step)
                if settings.get("steady", {}).get("on"):  # did steadying help? measured, said plainly
                    job["phase"] = "Checking the result"
                    before = fixes.jitter(e["path"], r.info)
                    after = fixes.jitter(str(dest), r.info)
                    job["note"] = (f"Steadying cut the jitter by {1 - after / before:.0%}." if after < before * 0.9 else
                                   "Steadying didn't help this clip (moving players or a fast follow can fill the frame, "
                                   "so there's no still background to lock onto). Try it switched off.")
            else:
                fixes.fix_photo(e["path"], settings, dest)
            job.update(state="done", pct=1.0, took=round(time.time() - job["started"]))
            e.setdefault("fixed", []).append({"path": str(dest), "name": dest.name, "at": time.time(),
                                              "fixes": job["fixes"], "note": job.get("note", "")})
            F.save()
        except Exception as x:
            job.update(state="failed", error=f"{type(x).__name__}: {x}"[:200])
            Path(dest).unlink(missing_ok=True)
    threading.Thread(target=run, daemon=True).start()
    return {"dest": str(dest), "estimate": est}


@router.post("/api/check/open")
async def open_file(req: Request):
    """Opens a checked file or one of its fixed copies in its own app (QuickTime, Preview…)."""
    path = (await req.json()).get("path", "")
    known = {e["path"] for e in F.items.values()} | {x["path"] for e in F.items.values() for x in e.get("fixed", [])}
    if path not in known or not Path(path).exists():
        raise HTTPException(404, "That file is no longer there")
    subprocess.run(["open", path])
    return {"ok": True}


# Comparing and exporting --------------------------------------------------------------------------

def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 3)


def _metrics(e: dict) -> dict:
    """Numbers to compare, by label: (shown text, number, which way is better: 'low', 'high', 'mid' or None)."""
    r = e["result"]
    c, s = r.camera, r.stats
    m = {}
    look = e.get("look", {})
    m["Average brightness"] = (f"{look.get('brightness', 0) * 255:.0f} of 255", _num(look.get("brightness")), "mid")
    if r.kind == "video":
        m["Sharpness (camera still)"] = ("-" if s.sharp_still is None else f"{s.sharp_still:.0f}", _num(s.sharp_still), "high")
        m["Sharpness lost in fast pans"] = ("-" if s.pan_sharpness_loss is None else f"{s.pan_sharpness_loss:.0%}",
                                           _num(s.pan_sharpness_loss), "low")
        m["Grain"] = ("-" if s.grain_still is None else f"{s.grain_still:.2f}", _num(s.grain_still), "low")
        m["Biggest brightness swing (2 s)"] = (f"{s.brightness_swing:.0f} of 255", _num(s.brightness_swing), "low")
        m["Time panning fast"] = (f"{s.fast_share:.0%}", _num(s.fast_share), None)
        ms = e.get("moments", [])
        shaky = sum(x.end - x.start for x in ms if x.kind == "shaky")
        m["Shaky moments"] = (f"{shaky:.1f} s", _num(shaky), "low")
        m["Problem moments"] = (str(len(ms)), len(ms), "low")
    else:
        m["Sharpest detail"] = (f"{s.focus_sharpness:.0f} ({advice_where(s.focus_spot)})", _num(s.focus_sharpness), "high")
        m["Grain"] = (f"{s.grain:.2f}", _num(s.grain), "low")
        m["Pure white"] = (f"{s.highlights_clipped:.1%}", _num(s.highlights_clipped), "low")
        m["Pure black"] = (f"{s.shadows_crushed:.1%}", _num(s.shadows_crushed), "low")
    m["ISO"] = (str(c.get("iso", "-")), _num(c.get("iso")), "low")
    n = _row(e).get("problems", 0)
    m["Things to improve"] = (str(n) if n else "None", n, "low")
    return m


def advice_where(spot) -> str:
    from photo_presets.clipcheck.advice import where
    return where(*spot)


GROUPS = [("How it came out", ["Things to improve", "Problem moments", "Sharpness (camera still)", "Sharpest detail",
                               "Sharpness lost in fast pans", "Shaky moments", "Grain", "Average brightness", "Pure white",
                               "Pure black", "Biggest brightness swing (2 s)"]),
          ("Settings", ["Exposure mode", "Aperture", "Shutter", "ISO", "Gain", "Exposure compensation", "Metering",
                        "White balance", "Focus mode", "Focal length", "Stabilization", "Drive mode", "Picture style"]),
          ("Movement", ["Time panning fast"]),
          ("Camera and file", ["Camera", "Lens", "Recorded", "Resolution", "Frame rate", "Length", "Format", "Bitrate",
                               "Color"])]


@router.post("/api/check/compare")
async def compare(req: Request):
    """Files side by side: rows grouped (camera, exposure, focus, motion, grain), each number marked best
    and worst where that makes sense, plus plain notes on what differs (each against the first)."""
    ids = (await req.json()).get("ids") or []
    es = [F.get(i) for i in ids]
    es = [e for e in es if e["state"] == "done"]
    if len(es) < 2:
        raise HTTPException(400, "Pick two or more checked files to compare")
    texts = [dict(analyze.settings_rows(e["result"])) for e in es]
    nums = [_metrics(e) for e in es]
    groups = []
    seen = set()
    for g, labels in GROUPS:
        rows = []
        for label in labels:
            vals, ns, better = [], [], None
            for t, m in zip(texts, nums):
                if label in m:
                    vals.append(m[label][0]); ns.append(m[label][1]); better = better or m[label][2]
                else:
                    vals.append(t.get(label, "-")); ns.append(None)
            if all(v in ("-", "") for v in vals):
                continue
            if label == "ISO":
                ns = [_num(e["result"].camera.get("iso")) for e in es]
            seen.add(label)
            rows.append({"label": label, "values": vals, "nums": ns, "better": better,
                         "same": len(set(vals)) == 1})
        if rows:
            groups.append({"name": g, "rows": rows})
    notes = []
    ref = es[0]["result"]
    for e in es[1:]:
        r = e["result"]
        if r.kind == ref.kind:
            notes.append({"title": f"{r.name} vs {ref.name}", "notes": analyze.pair_differences(r, ref)})
    files = [{"id": e["id"], "name": Path(e["path"]).name, "kind": e["kind"], "summary": summary_line(e["result"]),
              "problems": _row(e).get("problems", 0)} for e in es]
    return {"files": files, "groups": groups, "notes": notes}


@router.post("/api/check/export")
async def export(req: Request):
    """The assessment as a Word report and a spreadsheet, in a Clip Analysis folder next to the first file."""
    body = await req.json()
    es = [F.get(i) for i in body.get("ids") or []]
    es = [e for e in es if e["state"] == "done"]
    if not es:
        raise HTTPException(400, "Nothing checked to export yet")
    folder = (FALLBACK_OUT if _STATE else Path(es[0]["path"]).parent) / "Clip Analysis"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".write-test").touch()
        (folder / ".write-test").unlink()
    except OSError:
        folder = FALLBACK_OUT
        folder.mkdir(parents=True, exist_ok=True)
    stem = Path(es[0]["path"]).stem + (f" and {len(es) - 1} more" if len(es) > 1 else "")
    name = f"{stem} - {time.strftime('%Y-%m-%d %H%M')}"
    results = [e["result"] for e in es]
    together = recommend.across([_rec_input(e) for e in es])
    extras = {}
    for e in es:
        on = _settings(e)
        extras[e["path"]] = {"moments": [{"clock": moments.clock(m.start), "label": m.label, "detail": m.detail}
                                         for m in e.get("moments", [])],
                             "fixes": [f for f in e.get("suggested", []) if on.get(f["id"], {}).get("on")]}
        x = _rec_input(e)
        extras[e["path"]]["recommend"] = recommend.for_file(x["findings"], x["fixes_on"], x["settings"], x["habits"])
    out = []
    what = body.get("format", "both")
    if what in ("docx", "both"):
        out.append(str(report.write_docx(results, folder / f"{name}.docx", compare=len(es) > 1 and body.get("compare", True),
                                         extras=extras, summary=together if len(es) > 1 else None)))
    if what in ("csv", "both"):
        out.append(str(report.write_csv(results, folder / f"{name}.csv")))
    return {"files": out, "folder": str(folder)}


@router.post("/api/check/add")
async def add_paths(req: Request):
    """{paths}: files or folders already on this Mac (as typed or pasted)."""
    paths = [str(Path(p).expanduser()) for p in (await req.json()).get("paths") or [] if isinstance(p, str)]
    return {"added": F.add([p for p in paths if Path(p).exists()])}
