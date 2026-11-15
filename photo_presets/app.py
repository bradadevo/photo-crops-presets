"""The Gradio app: make looks (random or preset), compare before/after,
fine-tune them, save looks as presets, manage presets and assets, and export
full-size files.

It serves two ways of working:
- One photo: tick many looks, compare them, fine-tune the best, export it.
- A batch (a whole game): try looks on one photo first, then use the favorite
  on every photo, fine-tune it once for all of them, export them all (and make
  a reel).

    uv run allprophoto
"""

import base64
import html
import io
import json
import re
import shutil
import subprocess
import tempfile
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
import uuid
from pathlib import Path

import gradio as gr

from photo_crops.ui import choose_folder
from photo_presets import deliver, engine, lightroom, pipeline, presets, presetform, reel, timing
from photo_presets.assets import Library, Sources
from photo_presets.engine import CROPS, Engine
from photo_presets.scene import Fix

RANDOM, PRESET = "Random exploration", "Preset pipeline"
ONE, ALL = "one", "all"
RUN_ON = [("Try looks on one photo first", ONE), ("All photos", ALL)]
MODES = [("Use presets", PRESET), ("Explore random looks", RANDOM)]
CROP_LABELS = {v: k for k, v in CROPS.items()}
DEFAULT_EXPORT = str(Path.home() / "Pictures" / "Photo Presets")
NONE = presetform.NONE

ENGINE: Engine | None = None


def eng() -> Engine:
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine()
    return ENGINE


# Make looks -----------------------------------------------------------------------

# Pictures the app shows are saved here as dated JPEGs (with the photo's camera
# data), so a downloaded look is properly named and keeps the date it was taken
PREVIEWS = Path(tempfile.mkdtemp(prefix="photo-presets-"))


def _jpeg(img, name: str, exif: bytes | None) -> str:
    from photo_crops import images
    folder = PREVIEWS / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (re.sub(r'[/:\\]+', "-", name) + ".jpg")
    images.save_jpeg(img, dest, exif)
    return str(dest)


def _inputs(files, folder) -> list[Path]:
    items = [f if isinstance(f, str) else f.name for f in (files or [])]
    if folder and folder.strip():
        items.append(folder.strip())
    return engine.collect(items)


def _picked(groups) -> list[str]:
    return [n for g in groups for n in (g or [])]


def photo_status(files, folder):
    """What step 1 holds, and the step 3 choice that suits it: one photo, or a
    batch (try looks on one photo first)."""
    paths = _inputs(files, folder)
    n = len(paths)
    if not n:
        text = "No photos yet."
    elif n == 1:
        text = "**1 photo.** Tick as many looks as you like in step 2, then compare them in step 4."
    else:
        text = (f"**{n} photos.** Tip: try looks on one photo first (step 3), pick your favorite, then use it "
                f"on all {n} with one click.")
    choices = [(q.name, str(q)) for q in paths]
    preview = gr.update(value=_single_preview(paths[0]) if n == 1 else None, visible=n == 1)
    return (text, gr.update(visible=n > 1, value=ONE if n > 1 else ALL),
            gr.update(choices=choices, value=choices[0][1] if choices else None, visible=n > 1), preview)


_PREVIEWED: dict[str, str] = {}


def _single_preview(path: Path) -> str | None:
    """The one photo in step 1, shown (RAW included), with its date and camera kept."""
    key = f"{path}:{path.stat().st_mtime if path.exists() else 0}"
    if key not in _PREVIEWED:
        from photo_crops import images
        try:
            photo = images.load(path)
        except Exception:
            return None
        img = photo.image.copy()
        img.thumbnail((1400, 1400))
        _PREVIEWED[key] = _jpeg(img, path.stem, photo.exif)
    return _PREVIEWED[key]


def make_looks(files, folder, mode, count, seed, crop_label, run_on, try_photo, show_cut, *groups):
    """Makes the looks one by one, showing them on the progress card as they come
    (see _card); everything else in step 4 is filled in at the end."""
    paths = _inputs(files, folder)
    if not paths:
        raise gr.Error("Step 1: add photos, or choose a folder with photos.")
    crop = CROP_LABELS.get(crop_label, "none")
    trial = []
    if len(paths) > 1 and run_on == ONE:
        trial = [str(q) for q in paths]
        paths = [q for q in paths if str(q) == try_photo][:1] or paths[:1]
    e = eng()
    if mode == RANDOM:
        chosen = []
        jobs = e.explore_jobs(paths, int(count), None if seed in (None, "") else int(seed))
    else:
        available = presets.load_all()
        chosen = [n for n in _picked(groups) if n in available]
        if not chosen:
            raise gr.Error("Step 2: tick at least one preset (or press Select all).")
        jobs = e.preset_jobs(paths, chosen)
    results = yield from _stream(jobs, crop)
    if len(paths) > 1 and chosen:
        # a batch reads look by look: every photo in one look, then the next look
        results.sort(key=lambda r: chosen.index(r.name))
    yield _shown(results, trial, show_cut) + (HIDE_CARD,)


SHOWN = 19  # how many things step 4 shows (_shown); the progress card comes after them
HIDE_CARD = gr.update(value="", visible=False)


def _stream(jobs, crop):
    """Makes the jobs' looks one by one (in a worker, so the card can update every
    second), yielding the progress card; returns the results. Each look's time is
    learned for its preset, unless it included getting the photo ready or loading
    the models."""
    e = eng()
    waiting = SHOWN
    tiles = [{"title": j.title, "look": j.recipe.get("name", "Random look"), "state": "wait"} for j in jobs]
    expect = [timing.seconds(j.recipe.get("name", ""), j.recipe) for j in jobs]
    results, took = [], []
    clean = []  # (took, expected) of looks with nothing one-off in them: how this run's pace compares
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(1) as pool:
            for i, job in enumerate(jobs):
                extra = 0.0
                fresh = not e.is_prepared(job.path, crop)
                if fresh:
                    extra += timing.PHOTO_READY
                if pipeline.needs_cutout(job.recipe) and not e.is_cut_out(job.path, crop):
                    extra += timing.CUT_OUT
                    fresh = True  # not this look's own time
                loading = timing.uses_ai(job.recipe) and not timing.models_loaded()
                if loading:
                    extra += timing.MODEL_LOAD
                tiles[i]["state"] = "now"
                t0 = time.perf_counter()
                future = pool.submit(e.look, job, crop)
                while True:
                    try:
                        r = future.result(timeout=1.0)
                        break
                    except TimeoutError:
                        pass
                    spent = time.perf_counter() - t0
                    tiles[i]["pct"] = min(95, int(100 * spent / (expect[i] + extra)))
                    tiles[i]["note"] = "loading the AI models" if loading and not timing.models_loaded() else ""
                    yield (gr.skip(),) * waiting + (_card(tiles, expect, took, clean, i, spent, extra, started),)
                spent = time.perf_counter() - t0
                if not fresh and not loading:
                    timing.learn(job.recipe.get("name", ""), spent)  # random looks have no name: not kept
                    clean.append((spent, expect[i]))
                took.append(spent)
                results.append(r)
                tiles[i].update(state="done", thumb=_thumb(r.after), secs=spent)
                yield (gr.skip(),) * waiting + (_card(tiles, expect, took, clean, i + 1, 0.0, 0.0, started),)
    except Exception:
        yield (gr.skip(),) * waiting + (HIDE_CARD,)
        raise
    return results


def _thumb(img) -> str:
    """A small JPEG of a result for the progress card, as a data URL."""
    small = img.copy()
    small.thumbnail((180, 180))
    buf = io.BytesIO()
    small.convert("RGB").save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _card(tiles, expect, took, clean, current, spent, extra, started):
    """The floating progress card: one small tile per look (waiting, being made with
    its %, or done with its picture), how many are done and about how long is left.
    The time left is the looks' times, scaled by how this run is going so far (only
    looks without one-off work, like getting a photo ready, count toward the pace)."""
    done = len(took)
    pace = min(2.5, max(0.5, sum(t for t, _ in clean) / max(1e-6, sum(x for _, x in clean)))) if clean else 1.0
    left = max(0.0, (expect[current] + extra) * pace - spent) if current < len(tiles) else 0.0
    left += sum(expect[current + 1:]) * pace
    whole = 100 * (done + (tiles[current].get("pct", 0) / 100 if current < len(tiles) else 0)) / len(tiles)
    cells = []
    for t in tiles:
        tip = html.escape(t["title"], quote=True)
        name = html.escape(t["look"])
        if t["state"] == "done":
            cells.append(f"<div class='qt done' title='{tip}'><img src='{t['thumb']}' alt='{tip}'>"
                         f"<span class='qs'>{round(t['secs'])} s</span></div>")
        elif t["state"] == "now":
            note = f"<span class='qn'>{html.escape(t['note'])}</span>" if t.get("note") else ""
            cells.append(f"<div class='qt now' title='{tip}'><span class='qp'>{t.get('pct', 0)}%</span>"
                         f"<span class='ql'>{name}</span>{note}"
                         f"<i style='width:{t.get('pct', 0)}%'></i></div>")
        else:
            cells.append(f"<div class='qt wait' title='{tip}'><span class='ql'>{name}</span></div>")
    elapsed = time.perf_counter() - started
    status = (f"{done} of {len(tiles)} done · {timing.say(left)} left" if left >= 1
              else f"{done} of {len(tiles)} done · finishing")
    return gr.update(visible=True, value=(
        f"<div class='q-card'><div class='q-head'><b>Making looks</b><span>{status}</span></div>"
        f"<div class='q-bar'><i style='width:{whole:.0f}%'></i></div>"
        f"<div class='q-grid'>{''.join(cells)}</div>"
        f"<div class='q-foot'>{timing.say(elapsed)} so far · results open in step 4 when all are done</div></div>"))


def _shown(results, trial, show_cut, index=0):
    """Everything step 4 shows for a new set of results."""
    thumbs = [(_jpeg(r.after, r.title, r.exif), r.title) for r in results]
    photos = len(trial)
    use_all = gr.update(visible=bool(trial and results),
                        value=f"Use the selected look on all {photos} photos")
    several = len({(str(r.source), r.crop) for r in results}) > 1
    return ((results, index, thumbs, thumbs, trial, use_all, gr.update(visible=bool(results)),
             gr.update(visible=several))
            + _show(results, index) + _controls(results, index) + (_fix_picture(results, index, show_cut),))


def _pair(r):
    return (_jpeg(r.before, f"{r.source.stem} · original", r.exif), _jpeg(r.after, r.title, r.exif))


def _show(results, index):
    if not results:
        return None, "", "", ""
    r = results[index]
    name = r.recipe.get("name", "")
    about = presets.describe(name, r.recipe) if name else ""
    notes = ("\n\n**Notes:** " + "; ".join(r.notes)) if r.notes else ""
    info = (f"**{r.title}**" + (f" — {about}" if about else "")
            + f"\n\n<span class='meta'>Seed {r.seed} · {CROPS[r.crop]}</span>{notes}")
    return _pair(r), info, json.dumps(r.recipe, indent=1), name


def built_in(recipe: dict) -> str:
    """What the look itself already does to the player's and background's brightness."""
    found = {}
    for st in recipe.get("steps", []):
        if st.get("op") == "exposure" and st.get("layer") in ("subject", "background"):
            found[st["layer"]] = found.get(st["layer"], 0.0) + float(st.get("stops", 0.3))
    if not found:
        return "This look leaves the player's and background's brightness as they are; the sliders change them."
    words = {"subject": "player", "background": "background"}
    parts = " · ".join(f"{words[k]} {v:+.2f} stops" for k, v in found.items())
    return f"Built into this look: {parts}. The sliders add to that."


def _controls(results, index):
    """The fine-tune sliders for the selected look."""
    if not results:
        return (gr.skip(),) * 5 + ("",)
    adj = pipeline.adjustments(results[index].recipe)
    return (round(adj["strength"] * 100), adj["subject"], adj["background"], adj["warmth"], adj["auto_fill"],
            built_in(results[index].recipe))


def _adj(strength, subject, background, warmth, auto_fill) -> dict:
    return {"strength": float(strength) / 100, "subject": float(subject), "background": float(background),
            "warmth": float(warmth), "auto_fill": bool(auto_fill)}


def fine_tune(results, thumbs, index, strength, subject, background, warmth, auto_fill):
    """The sliders on the selected look: instant, the look is not made again."""
    if not results:
        return (gr.skip(),) * 6
    r = eng().adjust(results[index], _adj(strength, subject, background, warmth, auto_fill))
    results, thumbs = list(results), list(thumbs)
    results[index] = r
    thumbs[index] = (_jpeg(r.after, r.title, r.exif), r.title)
    pair, info, recipe, _ = _show(results, index)
    return results, thumbs, thumbs, pair, info, recipe


def copy_to_look(results, thumbs, index, strength, subject, background, warmth, auto_fill,
                 progress=gr.Progress()):
    """These settings on every photo with the selected look, so a game stays consistent."""
    if not results:
        raise gr.Error("Make some looks first.")
    name = results[index].name
    adj = _adj(strength, subject, background, warmth, auto_fill)
    results, thumbs = list(results), list(thumbs)
    same = [i for i, r in enumerate(results) if r.name == name]
    for k, i in enumerate(same):
        progress(k / len(same), desc=f"Fine-tuning {k + 1}/{len(same)} {results[i].source.name}")
        results[i] = eng().adjust(results[i], adj)
        thumbs[i] = (_jpeg(results[i].after, results[i].title, results[i].exif), results[i].title)
    gr.Info(f"Fine-tuned all {len(same)} photo(s) with \"{name}\"")
    return results, thumbs, thumbs


def use_on_all(results, index, trial, show_cut):
    """The selected look (with its fine-tuning) on every photo from step 1."""
    if not results or not trial:
        raise gr.Error("Try looks on one photo first.")
    r = results[index]
    jobs = [engine.Job(Path(q), dict(r.recipe, name=r.name), i) for i, q in enumerate(trial)]
    out = yield from _stream(jobs, r.crop)
    yield _shown(out, [], show_cut) + (HIDE_CARD,)


# Fixing the cut-out ------------------------------------------------------------------

ADD, REMOVE = "add", "remove"
FIX_MODES = [("Add what I click", ADD), ("Take out what I click", REMOVE)]


def _fix_picture(results, index, show_cut):
    """The cut-out to click on, when it is shown."""
    if not show_cut or not results:
        return gr.skip()
    r = results[index]
    return _jpeg(eng().fix_view(r), f"{r.source.stem} · cut-out", r.exif)


def show_cutout(results, index, show_cut):
    return gr.update(visible=bool(show_cut)), _fix_picture(results, index, show_cut)


def _fix_note(r) -> str:
    n = len(eng().fixes_for(r))
    if not n:
        return "Automatic cut-out. Click the photo to add or take out an object."
    return (f"{n} fix(es) on {r.source.name}. Press **Remake this photo's looks** to see them in the looks "
            "(the brightness sliders use them straight away).")


def fix_click(results, index, mode, evt: gr.SelectData):
    """A click on the cut-out picture: adds or takes out the object there."""
    if not results:
        raise gr.Error("Make some looks first.")
    r = results[index]
    x, y = engine.from_frame(r.frame, evt.index[0] / r.before.width, evt.index[1] / r.before.height)
    eng().set_fixes(r, eng().fixes_for(r) + [Fix(round(x, 4), round(y, 4), mode == ADD)])
    return _fix_picture(results, index, True), _fix_note(r)


def fix_undo(results, index):
    if not results:
        return gr.skip(), ""
    r = results[index]
    eng().set_fixes(r, eng().fixes_for(r)[:-1])
    return _fix_picture(results, index, True), _fix_note(r)


def fix_reset(results, index):
    if not results:
        return gr.skip(), ""
    r = results[index]
    eng().set_fixes(r, [])
    return _fix_picture(results, index, True), _fix_note(r)


def remake_photo(results, thumbs, index, progress=gr.Progress()):
    """Every look of the selected photo made again with its fixed cut-out."""
    if not results:
        raise gr.Error("Make some looks first.")
    r = results[index]
    same = [i for i, q in enumerate(results) if q.source == r.source and q.crop == r.crop]
    results, thumbs = list(results), list(thumbs)
    for k, i in enumerate(same):
        progress(k / len(same), desc=f"Remaking {k + 1}/{len(same)} {results[i].title}")
        results[i] = eng().remake(results[i])
        thumbs[i] = (_jpeg(results[i].after, results[i].title, results[i].exif), results[i].title)
    pair, info, recipe, _ = _show(results, index)
    return results, thumbs, thumbs, pair, info, recipe


def picker_choices() -> list[list[tuple[str, str]]]:
    """Each group's presets as (name — description, name)."""
    all_presets = presets.load_all()
    return [[(f"{n} — {presets.describe(n, all_presets[n])}".rstrip(" —")
              + f" · ⏱ {timing.say(timing.seconds(n, all_presets[n]))} a photo", n) for n in names]
            for names in presets.grouped(all_presets).values()]


def picker_updates(ticked=None):
    """The preset checklists, one per group, each preset with its description.
    ticked: names to tick (None keeps what is ticked)."""
    out = []
    for choices in picker_choices():
        kw = {} if ticked is None else {"value": [n for _, n in choices if n in ticked]}
        out.append(gr.update(choices=choices, visible=bool(choices), **kw))
    return out


def save_look(results, index, name, recipe_text):
    try:
        recipe = json.loads(recipe_text)
        recipe.pop("match", None)  # a game match belongs to its photo, not to the look
        presets.save(name, recipe)
    except (ValueError, json.JSONDecodeError) as e:
        raise gr.Error(f"Could not save: {e}")
    gr.Info(f"Saved preset \"{name.strip()}\" (under My presets)")
    return [gr.update(choices=list(presets.load_all()), value=name.strip())] + picker_updates()


FILE_KINDS = [("JPEG: web, Instagram and clients", engine.JPEG),
              ("16-bit TIFF: print and further editing", engine.TIFF), ("Both", engine.BOTH)]


SIZE_CHOICES = [("Full size", deliver.FULL)] + [(s.label, k) for k, s in deliver.SIZES.items()]
WATERMARK_STYLES = [("Corner: small text, bottom right", deliver.CORNER),
                    ("Across: large, repeated (for client proofs)", deliver.ACROSS)]


# The results board (step 4): pick, tick and export pictures right where they are --------

BOARD_THUMB = 360  # px: sharp at the board's tile size on a Retina screen
FILES, ZIP = "files", "zip"
HOW = [("Files in my export folder", FILES), ("One zip file", ZIP)]


def _board_thumb(r) -> str:
    """The result's picture for the board, as a data URL (made once per result)."""
    t = getattr(r, "_board_thumb", None)
    if t is None:
        small = r.after.copy()
        small.thumbnail((BOARD_THUMB, BOARD_THUMB))
        buf = io.BytesIO()
        small.convert("RGB").save(buf, "JPEG", quality=82)
        t = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        r._board_thumb = t
    return t


def _ticked_text(picked, n) -> str:
    if not n:
        return ""
    if not picked:
        return "Tick pictures to export them together, or press ⬇ on one to export just that one."
    return f"**{len(picked)} of {n}** selected"


def render_board(results, index, picked, shown):
    """The board's tiles: each result's picture, ticked or not, the one shown in the
    before/after outlined. Ticks are kept while the results are the same photos and
    looks (fine-tuning keeps them); a new set of looks starts with none ticked.
    shown: the titles the ticks were made for."""
    titles = [r.title for r in results or []]
    picked = [i for i in (picked or []) if i < len(titles)] if titles == shown else []
    tiles = [{"i": i, "src": _board_thumb(r), "title": r.title, "picked": i in picked, "current": i == index}
             for i, r in enumerate(results or [])]
    return tiles, picked, titles, _ticked_text(picked, len(titles))


def board_open(results, show_cut, evt: gr.EventData):
    """A picture clicked on the board: shown in before/after, ready to fine-tune."""
    i = int(evt.index)
    if not results or not 0 <= i < len(results):
        return (gr.skip(),) * 12
    return (i,) + _show(results, i) + _controls(results, i) + (_fix_picture(results, i, show_cut),)


def board_tick(results, evt: gr.EventData):
    picked = sorted(int(i) for i in evt.picked)
    return picked, _ticked_text(picked, len(results or []))


def tick_all(results, index, shown):
    return render_board(results, index, list(range(len(results or []))), shown)


def tick_look(results, index, shown):
    """Every picture in the same look as the one shown in before/after."""
    if not results:
        return render_board(results, index, [], shown)
    name = results[index].name
    return render_board(results, index, [i for i, r in enumerate(results) if r.name == name], shown)


def tick_none(results, index, shown):
    return render_board(results, index, [], shown)


def _deliver(chosen, how, folder, kind, sizes, creator, notice, contact, marked, mark_text, mark_style,
             mark_opacity):
    """Exports the chosen results at full size (as files, or one zip), showing the
    progress card; yields (card, message)."""
    if not chosen:
        raise gr.Error("Tick at least one picture to export (or press ⬇ on one).")
    if not sizes:
        raise gr.Error("Export settings: tick at least one size.")
    dest = Path(folder or DEFAULT_EXPORT).expanduser()
    credit = deliver.Credit(creator or "", notice or "", contact or "")
    if credit != deliver.Credit.load():
        credit.save()  # remembered for next time
    mark = None
    if marked:
        text = (mark_text or "").strip() or credit.notice() or "PROOF"
        mark = deliver.Watermark(text, mark_style, float(mark_opacity))
    into = Path(tempfile.mkdtemp(prefix="allprophoto-zip-")) if how == ZIP else dest
    state = {"done": 0, "name": chosen[0].title}

    def tick(done, total, name):
        state.update(done=done, name=name)

    started = time.perf_counter()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(eng().export, chosen, into, tick, kind, list(sizes), credit, mark)
        while True:
            try:
                saved, notes = future.result(timeout=1.0)
                break
            except TimeoutError:
                yield _export_card(state["done"], len(chosen), state["name"], started), gr.skip()
    what = {engine.JPEG: "JPEG", engine.TIFF: "16-bit TIFF", engine.BOTH: "JPEG and 16-bit TIFF"}[kind]
    names = [label.split(" (")[0] for label, key in SIZE_CHOICES if key in sizes]
    extras = ["your name and copyright"] if not credit.empty else []
    if mark:
        extras.append("a watermark")
    photos = f"{len(chosen)} picture{'s' if len(chosen) != 1 else ''}"
    if how == ZIP:
        dest.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H.%M.%S")
        zipped = dest / f"AllProPhoto {stamp} ({photos}).zip"
        with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(into.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(into))
        shutil.rmtree(into, ignore_errors=True)
        subprocess.run(["open", "-R", str(zipped)])  # shows the zip in Finder
        text = f"Saved **{zipped.name}** ({photos}: {', '.join(names)}, {what}) to `{dest}`; it is shown in Finder."
    else:
        text = (f"Saved {len(saved)} file(s) ({photos} × {', '.join(names)}, {what}) to `{dest}`"
                + (f", with {' and '.join(extras)}" if extras else "") + ". **Open folder** shows them.")
    if notes:
        text += "\n\n**Note:** " + "; ".join(notes)
    yield HIDE_CARD, text


def _export_card(done, total, name, started):
    whole = 100 * done / max(total, 1)
    return gr.update(visible=True, value=(
        f"<div class='q-card'><div class='q-head'><b>Exporting full size</b>"
        f"<span>{done} of {total} done · {timing.say(time.perf_counter() - started)} so far</span></div>"
        f"<div class='q-bar'><i style='width:{whole:.0f}%'></i></div>"
        f"<div class='q-foot'>Now: {html.escape(name)}</div></div>"))


def export_ticked(results, picked, *settings):
    yield from _deliver([results[i] for i in sorted(picked or []) if i < len(results or [])], *settings)


def export_one(results, how, folder, kind, sizes, creator, notice, contact, marked, mark_text, mark_style,
               mark_opacity, evt: gr.EventData):
    """⬇ on one picture: just that one."""
    i = int(evt.index)
    yield from _deliver([results[i]] if results and 0 <= i < len(results) else [], how, folder, kind, sizes,
                        creator, notice, contact, marked, mark_text, mark_style, mark_opacity)


def match_game(results, thumbs, index, progress=gr.Progress()):
    """Every photo's exposure and white balance evened out to the selected one."""
    if not results:
        raise gr.Error("Make some looks first.")

    def tick(done, total, title):
        progress(done / max(total, 1), desc=f"Matching {done}/{total} {title}")

    out, changed = eng().match_game(results, results[index], tick)
    thumbs = [(_jpeg(r.after, r.title, r.exif), r.title) if r is not old else t
              for r, old, t in zip(out, results, thumbs)]
    pair, info, recipe, _ = _show(out, index)
    photos = len({(str(r.source), r.crop) for r in out})
    msg = (f"Matched {changed} of {photos} photos to **{results[index].source.name}** (the others already agreed). "
           "Each photo's correction is in its recipe as `match`.")
    return out, thumbs, thumbs, pair, info, recipe, msg


def clear_match(results, thumbs, index, progress=gr.Progress()):
    if not results:
        raise gr.Error("Make some looks first.")

    def tick(done, total, title):
        progress(done / max(total, 1), desc=f"Undoing {done}/{total} {title}")

    out = eng().clear_match(results, tick)
    thumbs = [(_jpeg(r.after, r.title, r.exif), r.title) if r is not old else t
              for r, old, t in zip(out, results, thumbs)]
    pair, info, recipe, _ = _show(out, index)
    return out, thumbs, thumbs, pair, info, recipe, "Matching undone: every photo as it was shot."


def open_folder(folder):
    dest = Path(folder or DEFAULT_EXPORT).expanduser()
    if dest.is_dir():
        subprocess.run(["open", str(dest)])
    else:
        gr.Warning("Nothing exported there yet.")


def toggle_mode(mode):
    return gr.update(visible=mode == RANDOM), gr.update(visible=mode == PRESET)


def preset_estimate(files, folder, run_on, *groups):
    """How many looks the ticked presets make, and about how long they take."""
    names = _picked(groups)
    n = len(names)
    photos = len(_inputs(files, folder)) or 1
    if photos > 1 and run_on == ONE:
        photos = 1
    looks = n * photos
    if not looks:
        return "No presets ticked yet."
    available = presets.load_all()
    each = [(m, available[m]) for m in names if m in available]
    when = timing.say(timing.run_seconds(each * photos, photos))
    if any(timing.uses_ai(r) for _, r in each) and not timing.models_loaded():
        when += " (including about a minute to load the AI models, once per session)"
    trying = " (on one photo)" if photos == 1 and run_on == ONE else ""
    return f"**{n}** preset(s) × **{photos}** photo(s){trying} = **{looks}** looks, {when}."


# Reel ---------------------------------------------------------------------------------

LOOKS, FOLDER = "looks", "folder"
REEL_SOURCES = [("The looks made above", LOOKS), ("Photos in a folder (e.g. your exports)", FOLDER)]


def _folder_photos(folder) -> list[Path]:
    d = Path(folder or DEFAULT_EXPORT).expanduser()
    return sorted(engine.collect([str(d)])) if d.is_dir() else []


def _reel_count(results, source, folder) -> int:
    return len(results or []) if source == LOOKS else len(_folder_photos(folder))


def reel_estimate(results, source, folder, photo_sec, max_sec):
    n = _reel_count(results, source, folder)
    if not n:
        return ("Make some looks first (steps 1 to 3)." if source == LOOKS
                else "No photos in that folder yet.")
    sec, keep = reel.fit(n, float(photo_sec), float(max_sec))
    text = f"**{keep}** photos × {sec:.1f} s = **{keep * sec:.0f} s** reel"
    if keep < n:
        text += f". Only {keep} of {n} fit; the last {n - keep} are left out (fewer looks, or a longer reel, fit more)"
    minutes = (keep * 1.5 + keep * sec * 0.4 + 15) / 60
    return text + f". Takes about {max(1, round(minutes))} minute(s)."


def _folder_shots(paths: list[Path], progress) -> list[reel.Shot]:
    """Photos from a folder; exported looks (with their recipe .json beside
    them) are framed on their player."""
    from photo_crops import images
    shots = []
    for i, path in enumerate(paths):
        focus = (0.5, 0.5)
        info = path.with_suffix(".json")
        if info.exists():
            try:
                meta = json.loads(info.read_text())
                focus = engine.focus(eng().prepared(Path(meta["source"]), meta.get("crop", "none")).scene)
            except (OSError, ValueError, KeyError):
                pass
        img = images.load(path).image
        img.thumbnail((engine.REEL_EDGE, engine.REEL_EDGE))
        shots.append(reel.Shot(img, focus, path.stem))
        progress(i + 1, len(paths), path.name)
    return shots


def make_reel(results, source, folder, song, start, title, closing, photo_sec, max_sec, export_dir,
              progress=gr.Progress()):
    def tick(what):
        def f(done, total, name=""):
            progress(done / max(total, 1), desc=f"{what} {done}/{total} {name}".strip())
        return f

    if source == LOOKS:
        if not results:
            raise gr.Error("Make some looks first (steps 1 to 3), or pick Photos in a folder.")
        count = len(results)
    else:
        paths = _folder_photos(folder)
        if not paths:
            raise gr.Error("No photos in that folder.")
        count = len(paths)
    beat, beats = None, []
    if song:
        progress(0, desc="Finding the song's beat")
        beat, beats = reel.song_beat(song)
    sec, keep = reel.fit(count, float(photo_sec), float(max_sec), beat)
    shots = (eng().reel_shots(results[:keep], tick("Preparing photo")) if source == LOOKS
             else _folder_shots(paths[:keep], tick("Preparing photo")))
    plan = reel.Plan(shots, sec, [])
    name = re.sub(r"[/:\\]+", "-", " ".join((title or "").split())) or "Reel"
    dest = engine._unique(Path(export_dir or DEFAULT_EXPORT).expanduser() / "Reels" / f"{name}.mp4")
    reel.render(plan, dest, song, reel.song_start(beats, float(start or 0)) if song else 0.0,
                title, closing, tick("Making frames"))
    left = f" The last {count - keep} photo(s) did not fit and were left out." if keep < count else ""
    beat_note = f", cuts on the beat ({60 / beat:.0f} BPM)" if beat else ""
    # the app can only play files in its own temporary folder
    preview = Path(tempfile.mkdtemp(prefix="reel-")) / dest.name
    shutil.copy2(dest, preview)
    return str(preview), (f"Saved a {plan.length:.0f} s reel ({keep} photos at {sec:.2f} s{beat_note}) to "
                       f"`{dest}`.{left}")


def open_reels(folder):
    open_folder(str(Path(folder or DEFAULT_EXPORT).expanduser() / "Reels"))


# Preset manager -------------------------------------------------------------------

def build_recipe(*values):
    """The form as a recipe (see presetform)."""
    return json.dumps(presetform.to_recipe(dict(zip(presetform.FIELDS, values))), indent=1)


def form_from_recipe(recipe: dict) -> list:
    """Best effort: the form fields for a recipe (anything the form cannot
    show stays in the recipe text, which is what gets saved)."""
    v = presetform.from_recipe(recipe)
    return [v[n] for n in presetform.FIELDS]


def load_preset(name):
    all_presets = presets.load_all()
    if name not in all_presets:
        raise gr.Error("Choose a preset to load.")
    recipe = all_presets[name]
    return [name, presets.describe(name, recipe)] + form_from_recipe(recipe) + [json.dumps(recipe, indent=1)]


def save_preset(name, description, recipe_text):
    try:
        recipe = json.loads(recipe_text)
        if description and description.strip():
            recipe["description"] = description.strip()
        presets.save(name, recipe)
    except (ValueError, json.JSONDecodeError, AttributeError) as e:
        raise gr.Error(f"Could not save: {e}")
    gr.Info(f"Saved preset \"{name.strip()}\"")
    return [gr.update(choices=list(presets.load_all()), value=name.strip())] + picker_updates()


def delete_preset(name):
    if presets.delete(name):
        gr.Info(f"Deleted \"{name}\"" + (" (the built-in starter is back)" if name in presets.STARTERS else ""))
    else:
        gr.Warning("Only presets you saved can be deleted; built-in starters stay.")
    return [gr.update(choices=list(presets.load_all()), value=None)] + picker_updates(ticked=[])


def preview_preset(sample, files, folder, recipe_text, crop_label):
    paths = engine.collect([sample]) if sample else _inputs(files, folder)
    if not paths:
        raise gr.Error("Add a sample photo here, or photos on the Make looks tab.")
    try:
        recipe = json.loads(recipe_text)
    except json.JSONDecodeError as e:
        raise gr.Error(f"The recipe is not valid JSON: {e}")
    r = eng().preset(paths[:1], "preview", CROP_LABELS.get(crop_label, "none"), recipe=recipe)[0]
    notes = ("Notes: " + "; ".join(r.notes)) if r.notes else ""
    return (_jpeg(r.before, f"{r.source.stem} · original", r.exif), _jpeg(r.after, f"{r.source.stem} · preview", r.exif)), notes


# Assets ------------------------------------------------------------------------------

def assets_summary() -> str:
    lib = eng().library
    ids = lib.ids()
    def listing(items):
        return ", ".join(i.split(":", 1)[1] for i in items) or "(none)"
    generated = [i for i in ids["texture"] if i.startswith("generated:")]
    files = [i for i in ids["texture"] if not i.startswith("generated:")]
    return (f"**LUTs ({len(ids['lut'])}):** {listing(ids['lut'])}\n\n"
            f"**Textures ({len(files)}):** {listing(files)}\n\n"
            f"**Generated textures ({len(generated)}):** {listing(generated)}\n\n"
            f"**Overlays ({len(ids['overlay'])}):** {listing(ids['overlay'])}")


def save_sources(lut_folders, lut_zips, texture_folders, texture_zips, overlay_folders, overlay_zips):
    def lines(t):
        return [x.strip() for x in (t or "").splitlines() if x.strip()]
    s = Sources(lines(lut_folders), lines(lut_zips), lines(texture_folders), lines(texture_zips),
                lines(overlay_folders), lines(overlay_zips))
    s.save()
    eng().library = Library(s)
    return assets_summary(), *choices_updates()


def choices_updates():
    ids = eng().library.ids()
    return (gr.update(choices=[NONE] + ids["lut"]), gr.update(choices=[NONE] + ids["texture"]),
            gr.update(choices=[NONE] + ids["texture"]), gr.update(choices=[NONE] + ids["overlay"]))


# Lightroom presets ----------------------------------------------------------------------

CHART_FILE = PREVIEWS / "chart" / "AllProPhoto color chart.tif"

LR_STEPS = """
**In Lightroom Classic**
1. **File → Import** the chart (no other edits, no import preset).
2. In **Develop**, click your preset (one per copy of the chart: right-click → **Create Virtual Copy** to do
   several).
3. **File → Export**: *File Settings* **TIFF**, *Bit Depth* **16 bits/component**, *Color Space* **sRGB**;
   *Image Sizing* **off**; *Output Sharpening* **off**; *Watermark* **off**. Name each file after its preset,
   e.g. `Moody Film.tif`.

**In Lightroom (desktop or mobile)**: open the chart, apply the preset, then **Export** as **TIFF**, *Dimensions*
**Full size**, no watermark.

**No Lightroom on this Mac?** Any app that applies a look and exports full size works the same way: Lightroom
mobile on your phone (AirDrop the chart over and back), darktable (free), Photoshop or Affinity (adjustment layers
only), Capture One. Export as **TIFF** (or PNG), full size, sRGB. Many preset packs also include `.cube` LUTs:
add their folder on the Assets tab instead.

What comes across: white balance, exposure, contrast, curves, color mixer, color grading, profiles, B&W.
What cannot (it depends on where a pixel is): masks, vignette, grain, texture, clarity, dehaze, sharpening. Turn
those off on the chart; the app's own grain, vignette and clarity can add them back.
"""


def make_luts(charts, name, as_presets, files, folder, progress=gr.Progress()):
    """Exported charts to LUTs in your LUT folder, each optionally a preset,
    previewed on your first photo."""
    paths = [Path(c if isinstance(c, str) else c.name) for c in (charts or [])]
    if not paths:
        raise gr.Error("Add the chart(s) you exported from Lightroom.")
    sources = eng().library.sources
    home = str(lightroom.LUT_FOLDER).replace(str(Path.home()), "~", 1)
    if not any(Path(f).expanduser() == lightroom.LUT_FOLDER for f in sources.lut_folders):
        sources.lut_folders.append(home)
        sources.save()
    lines, made = [], []
    for i, path in enumerate(paths):
        progress(i / len(paths), desc=f"Converting {path.name}")
        given = name.strip() if name and len(paths) == 1 else None
        try:
            lut_name, dest, notes = lightroom.convert(path, given)
        except (ValueError, OSError) as e:
            lines.append(f"- **{path.name}**: not converted: {e}")
            continue
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            notes.append("JPEG compression blurs the chart's colors together; export it as TIFF for an exact LUT")
        made.append((lut_name, dest))
        line = f"- **{lut_name}** → `{dest}`"
        if notes:
            line += "  \n  ⚠ " + "; ".join(notes)
        lines.append(line)
    eng().library = Library(sources)
    preview = []
    sample = _inputs(files, folder)[:1]
    for lut_name, dest in made:
        recipe = {"description": "From your Lightroom preset", "protect_faces": False, "skin_protect": 0.0,
                  "steps": [{"op": "lut", "asset": f"lut:{dest.stem}", "strength": 1.0, "guard_shadows": False}]}
        if as_presets:
            presets.save(lut_name, recipe)
        if sample:
            r = eng().preset(sample, lut_name, recipe=recipe)[0]
            preview.append((_jpeg(r.after, r.title, r.exif), lut_name))
    if sample and made:
        preview.insert(0, (_jpeg(r.before, f"{sample[0].stem} · original", r.exif), "Original"))
    done = f"Made {len(made)} of {len(paths)} LUT(s)"
    if as_presets and made:
        done += ", each also a preset under **My presets** on Make looks"
    text = done + ":\n\n" + "\n".join(lines)
    if made and not sample:
        text += "\n\nAdd a photo on Make looks (step 1) to preview them here."
    return ([text, preview] + [gr.update(choices=list(presets.load_all()))] + picker_updates()
            + [assets_summary()] + list(choices_updates()))


# Pasting ------------------------------------------------------------------------------

# ⌘V anywhere puts copied images (a screenshot, a photo copied from Photos, a
# browser or Finder) into the upload box on screen: Photos on Make looks, the
# sample photo on Preset manager. Pasting text into a text box works as usual.
PASTE_JS = r"""
<script>
document.addEventListener("paste", (e) => {
  const PHOTO = /\.(jpe?g|png|heic|heif|webp|tiff?|arw|dng|cr2|cr3|nef|raf|orf)$/i;
  const files = [...((e.clipboardData && e.clipboardData.files) || [])]
    .filter(f => f.type.startsWith("image/") || PHOTO.test(f.name));
  if (!files.length) return;  // text: paste as usual
  const shown = id => { const el = document.getElementById(id); return el && el.offsetParent !== null ? el : null; };
  const box = shown("sample-upload") || shown("photos-upload");
  const input = box && box.querySelector('input[type="file"]');
  if (!input) return;
  e.preventDefault();
  const now = new Date(), two = n => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())} ` +
                `${two(now.getHours())}.${two(now.getMinutes())}.${two(now.getSeconds())}`;
  const dt = new DataTransfer();
  files.forEach((f, i) => {
    // a copied picture arrives as "image.png": give it a name you can find later
    const generic = /^image\.\w+$/i.test(f.name) || !f.name;
    const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg");
    const name = generic ? `Pasted ${stamp}${files.length > 1 ? "-" + (i + 1) : ""}.${ext}` : f.name;
    dt.items.add(generic ? new File([f], name, { type: f.type }) : f);
  });
  input.files = dt.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
});
</script>
"""


# Layout ---------------------------------------------------------------------------------

THEME = gr.themes.Soft(
    primary_hue="blue", neutral_hue="slate", radius_size="md",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
).set(
    button_large_text_weight="600",
    # quiet, readable field labels instead of colored chips
    block_title_background_fill="transparent", block_title_background_fill_dark="transparent",
    block_title_text_color="*neutral_700", block_title_text_color_dark="*neutral_200",
    block_title_text_weight="600", block_title_padding="0", block_title_radius="0",
    block_label_background_fill="transparent", block_label_background_fill_dark="transparent",
    block_label_text_color="*neutral_600", block_label_text_color_dark="*neutral_300",
    block_label_border_width="0", block_info_text_size="*text_sm",
)

BOARD_HTML = """<div class="rb">{{#each value}}<div class="rt{{#if this.current}} cur{{/if}}{{#if this.picked}} on{{/if}}"
 data-i="{{this.i}}" title="{{this.title}}"><img src="{{this.src}}" alt="{{this.title}}" draggable="false">
<button type="button" class="rt-tick" data-act="tick" aria-label="Select for export">✓</button>
<button type="button" class="rt-dl" data-act="export" aria-label="Export this picture">⬇</button>
<span class="rt-name">{{this.title}}</span></div>{{/each}}</div>"""

BOARD_CSS = """
.rb { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.rt { position: relative; aspect-ratio: 4 / 5; border-radius: 10px; overflow: hidden; cursor: pointer;
    background: var(--background-fill-secondary); border: 2px solid transparent; }
.rt img { width: 100%; height: 100%; object-fit: cover; display: block; user-select: none; }
.rt.cur { border-color: var(--color-accent); }
.rt.on { box-shadow: 0 0 0 3px var(--color-accent-soft); }
.rt button { position: absolute; top: 6px; width: 28px; height: 28px; border-radius: 50%; border: 0;
    display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700;
    cursor: pointer; background: rgba(0, 0, 0, 0.45); color: rgba(255, 255, 255, 0.85);
    box-shadow: 0 0 0 1.5px rgba(255, 255, 255, 0.8); transition: opacity 0.15s; }
.rt-tick { left: 6px; }
.rt-dl { right: 6px; opacity: 0; }
.rt:hover .rt-dl, .rt-dl:focus-visible { opacity: 1; }
.rt.on .rt-tick { background: var(--color-accent); color: white; box-shadow: 0 0 0 1.5px white; }
.rt button:hover { background: rgba(0, 0, 0, 0.7); }
.rt.on .rt-tick:hover { background: var(--color-accent); filter: brightness(1.1); }
.rt-name { position: absolute; left: 0; right: 0; bottom: 0; padding: 14px 7px 5px; font-size: 0.72rem;
    color: white; background: linear-gradient(transparent, rgba(0, 0, 0, 0.65)); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
@media (hover: none) { .rt-dl { opacity: 1; } }
"""

# clicks on the board: ✓ ticks a picture (kept on the server), ⬇ exports it, anywhere else opens it
BOARD_JS = """
element.addEventListener('click', (ev) => {
  const tile = ev.target.closest('.rt');
  if (!tile) return;
  const i = parseInt(tile.dataset.i, 10);
  const act = ev.target.closest('[data-act]')?.dataset.act;
  if (act === 'tick') {
    props.value = props.value.map(t => t.i === i ? {...t, picked: !t.picked} : t);
    trigger('input', {picked: props.value.filter(t => t.picked).map(t => t.i)});
  } else if (act === 'export') {
    trigger('submit', {index: i});
  } else {
    props.value = props.value.map(t => ({...t, current: t.i === i}));
    trigger('click', {index: i});
  }
});
"""

CSS = """
.gradio-container { max-width: 1440px !important; margin: auto; }
.app-header h1 { font-size: 1.9rem; font-weight: 700; margin-bottom: 0.15rem; letter-spacing: -0.01em; }
.app-header p { color: var(--body-text-color-subdued); margin: 0; }
.steps-strip { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.6rem; }
.steps-strip span { background: var(--background-fill-secondary); border: 1px solid var(--border-color-primary);
    border-radius: 999px; padding: 0.2rem 0.75rem; font-size: 0.85rem; color: var(--body-text-color-subdued); }
.step h3 { display: flex; align-items: center; gap: 0.55rem; font-size: 1.05rem; font-weight: 650;
    margin: 0.4rem 0 0.1rem; }
.step h3 .num { display: inline-flex; align-items: center; justify-content: center; width: 1.6rem; height: 1.6rem;
    border-radius: 50%; background: var(--color-accent); color: white; font-size: 0.85rem; font-weight: 700; }
.hint, .hint p { color: var(--body-text-color-subdued); font-size: 0.9rem; margin: 0 0 0.35rem; }
.meta { color: var(--body-text-color-subdued); font-size: 0.85rem; }
.panel { border: 1px solid var(--border-color-primary); border-radius: var(--radius-lg);
    padding: 1rem 1.1rem !important; background: var(--background-fill-primary); }
.reveal { border-left: 3px solid var(--color-accent-soft) !important; margin: -0.2rem 0 0.6rem 0.4rem; }
.picker label { font-size: 0.92rem; }
.go-button { font-size: 1.05rem !important; padding: 0.8rem !important; }
.sticky { position: sticky; top: 0.75rem; align-self: flex-start; }
.row-end { align-items: flex-end !important; }
.row-end > button { flex-grow: 0 !important; height: 2.6rem; white-space: nowrap; }
.picker .wrap { flex-direction: column; gap: 0.25rem !important; }
.picker .wrap label { width: 100%; padding: 0.35rem 0.6rem !important; font-size: 0.86rem; line-height: 1.3; }
.picker-groups .label-wrap span { font-weight: 650; }
.export-bar { border-top: 1px solid var(--border-color-primary); padding-top: 0.6rem !important; gap: 0.5rem !important; }
.export-bar .ticked { align-self: center; margin: 0 0 0 0.4rem; }
.export-bar .ticked p { margin: 0; }
/* the progress card: pinned to the corner, so a run can be watched without scrolling */
.q-card { position: fixed; right: 18px; bottom: 18px; z-index: 1000; width: min(440px, calc(100vw - 32px));
    max-height: 62vh; display: flex; flex-direction: column; gap: 0.5rem; padding: 0.85rem 0.95rem;
    background: var(--background-fill-primary); border: 1px solid var(--border-color-primary);
    border-radius: 14px; box-shadow: 0 10px 32px rgba(0, 0, 0, 0.22); font-size: 0.85rem; }
.q-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.6rem; }
.q-head b { font-size: 0.98rem; }
.q-head span, .q-foot { color: var(--body-text-color-subdued); }
.q-foot { font-size: 0.78rem; }
.q-bar { height: 5px; border-radius: 3px; background: var(--background-fill-secondary); overflow: hidden; }
.q-bar i, .qt.now i { display: block; height: 100%; background: var(--color-accent); transition: width 0.9s linear; }
.q-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); gap: 6px;
    overflow-y: auto; padding-right: 2px; }
.qt { position: relative; aspect-ratio: 1; border-radius: 8px; overflow: hidden; display: flex;
    flex-direction: column; align-items: center; justify-content: center; text-align: center;
    background: var(--background-fill-secondary); border: 1px solid var(--border-color-primary); }
.qt img { width: 100%; height: 100%; object-fit: cover; }
.qt .ql { font-size: 0.68rem; line-height: 1.15; padding: 0 4px; color: var(--body-text-color-subdued);
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.qt.wait { opacity: 0.55; }
.qt.now { border-color: var(--color-accent); }
.qt.now .qp { font-size: 1rem; font-weight: 700; color: var(--color-accent); }
.qt.now .qn { font-size: 0.6rem; color: var(--body-text-color-subdued); }
.qt.now i { position: absolute; left: 0; bottom: 0; height: 4px; }
.qt .qs { position: absolute; right: 3px; bottom: 3px; font-size: 0.62rem; padding: 0 4px; border-radius: 4px;
    background: rgba(0, 0, 0, 0.6); color: white; }
"""


def step(num, title, hint=None):
    """A numbered step heading with an optional one-line explanation."""
    gr.Markdown(f"### <span class='num'>{num}</span> {title}", elem_classes="step")
    if hint:
        gr.Markdown(hint, elem_classes="hint")


def build() -> gr.Blocks:
    lib = eng().library
    ids = lib.ids()
    names = list(presets.load_all())
    src = lib.sources
    with gr.Blocks(title="AllProPhoto") as demo:
        results = gr.State([])
        selected = gr.State(0)
        card = gr.HTML("", visible=False, elem_id="progress-card")  # floats over the page while looks are made
        thumbs = gr.State([])  # the gallery's pictures, so one fine-tuned look updates alone
        trial = gr.State([])  # every photo from step 1, while looks were tried on one of them
        gr.Markdown(
            "# AllProPhoto\n"
            "Pro looks for your sports photos. Faces stay clean of effects, and your originals are never "
            "changed.\n\n"
            "<div class='steps-strip'><span>1 · Add photos</span><span>2 · Choose looks</span>"
            "<span>3 · Make looks</span><span>4 · Compare and fine-tune</span><span>5 · Save or export</span>"
            "<span>6 · Instagram reel</span></div>",
            elem_classes="app-header")

        with gr.Tab("Make looks"):
            with gr.Row(equal_height=False):
                # Left: the steps to set up a run, top to bottom
                with gr.Column(scale=2, min_width=340, elem_classes="panel"):
                    step(1, "Add photos", "Paste a copied image (⌘V), drag photos in (JPG or RAW), click to "
                         "browse, or choose a whole folder.")
                    files = gr.File(label="Photos", file_count="multiple", type="filepath", height=150,
                                    elem_id="photos-upload")
                    with gr.Row(equal_height=False, elem_classes="row-end"):
                        folder = gr.Textbox(label="Or a folder of photos", placeholder="~/Pictures/Game day",
                                            scale=4)
                        choose = gr.Button("Browse…", scale=1, min_width=90)
                    photo_count = gr.Markdown("No photos yet.", elem_classes="hint")
                    one_photo = gr.Image(label="Your photo", interactive=False, visible=False, height=300)

                    step(2, "Choose looks")
                    mode = gr.Radio(MODES, value=PRESET, show_label=False,
                                    info="Presets give you the same look every time. Random looks invent new "
                                         "ones to discover a style you like.")
                    with gr.Group(visible=True) as preset_box:
                        with gr.Row():
                            select_all = gr.Button("Select all", size="sm")
                            clear_all = gr.Button("Clear", size="sm")
                        pickers = []
                        for i, (g, choices) in enumerate(zip(presets.GROUPS, picker_choices())):
                            with gr.Accordion(g, open=i == 1, elem_classes="picker-groups"):
                                if g == presets.MINE:
                                    gr.Markdown("Looks you save appear here.", elem_classes="hint")
                                pickers.append(gr.CheckboxGroup(choices, show_label=False, visible=bool(choices),
                                                                 elem_classes="picker"))
                        estimate = gr.Markdown("No presets ticked yet.", elem_classes="hint")
                    with gr.Group(visible=False) as random_box:
                        count = gr.Slider(1, 24, value=6, step=1, label="Looks per photo")
                        seed = gr.Number(label="Seed (optional)", precision=0,
                                         info="Leave empty for new looks each time; reuse a seed to repeat a run.")

                    step(3, "Crop and make looks")
                    run_on = gr.Radio(RUN_ON, value=ALL, label="Make looks on", visible=False,
                                      info="With many photos, try looks on one good photo first: it is quick, "
                                           "and then one click uses your favorite on all of them.")
                    try_photo = gr.Dropdown([], label="Photo to try looks on", visible=False)
                    crop = gr.Radio(list(CROPS.values()), value=CROPS["none"], label="Crop first",
                                    info="No zoom: trims at most 10% to place the players on a rule-of-thirds "
                                         "point, keeping the scene. Zoomed in: frames the action tightly. Face: "
                                         "head and shoulders.")
                    go = gr.Button("Make looks", variant="primary", size="lg", elem_classes="go-button")

                # Right: the results, then what to do with them
                with gr.Column(scale=3, min_width=420):
                    with gr.Column(elem_classes="panel"):
                        step(4, "Compare, fine-tune and export", "Click a picture to compare it with the "
                             "original. Tick ✓ the ones to export together, or press ⬇ on one to export just "
                             "that one.")
                        gallery = gr.State([])  # the results' pictures, kept for the handlers that update them
                        board = gr.HTML([], html_template=BOARD_HTML, css_template=BOARD_CSS, js_on_load=BOARD_JS,
                                        elem_id="results-board")
                        with gr.Column(visible=False, elem_classes="export-bar") as export_bar:
                            with gr.Row(equal_height=True, elem_classes="row-end"):
                                tick_all_btn = gr.Button("Select all", size="sm", min_width=90)
                                tick_look_btn = gr.Button("Select this look", size="sm", min_width=120)
                                tick_none_btn = gr.Button("Clear", size="sm", min_width=70)
                                ticked_msg = gr.Markdown(elem_classes="hint ticked")
                            with gr.Row(equal_height=True, elem_classes="row-end"):
                                how = gr.Radio(HOW, value=FILES, label="Export as", scale=3)
                                export_btn = gr.Button("Export selected", variant="primary", scale=2,
                                                       min_width=150)
                                open_btn = gr.Button("Open folder", scale=1, min_width=120)
                            export_msg = gr.Markdown(elem_classes="hint")
                            gr.Markdown("Full-size files, made with the sizes, file type and your name in "
                                        "**Export settings** (step 5).", elem_classes="hint")
                        use_all = gr.Button("Use the selected look on all photos", variant="primary",
                                            visible=False)
                        with gr.Group(visible=False) as match_box:
                            gr.Markdown("**Match the game.** Evens out exposure and white balance across the "
                                        "photos, to the selected photo, so the gallery looks like one shoot. "
                                        "Gentle: it evens out the light, it does not force every frame alike.",
                                        elem_classes="hint")
                            with gr.Row():
                                match_btn = gr.Button("Match all photos to the selected one", size="sm")
                                unmatch_btn = gr.Button("Undo matching", size="sm")
                            match_msg = gr.Markdown(elem_classes="hint")
                        # no download button: it saves a preview; export (above) saves full size
                        compare = gr.ImageSlider(label="Before / after", height=480, buttons=["fullscreen"])
                        info = gr.Markdown()
                        with gr.Group(visible=False) as tune_box:
                            gr.Markdown("**Fine-tune the selected look.** Changes show instantly and are kept "
                                        "when you export, make a reel or save it as a preset.",
                                        elem_classes="hint")
                            tune_note = gr.Markdown(elem_classes="hint")
                            with gr.Row():
                                t_strength = gr.Slider(0, 100, 100, step=5, label="Look strength (%)",
                                                       info="Tone the look down; 0 shows the photo as it was.")
                                t_warmth = gr.Slider(-1, 1, 0, step=0.05, label="Warmth",
                                                     info="Left cooler (blue), right warmer (amber).")
                            with gr.Row():
                                t_subject = gr.Slider(-1, 1, 0, step=0.05, label="Player brightness (stops)",
                                                      info="+1 doubles the light on the player.")
                                t_background = gr.Slider(-2, 1, 0, step=0.05, label="Background brightness (stops)",
                                                         info="Negative darkens everything behind the player.")
                            with gr.Row():
                                t_auto = gr.Checkbox(False, label="Auto fill light on the player",
                                                     info="Lifts a player who is darker than the scene around "
                                                          "them (backlit or in shade), photo by photo.")
                                show_cut = gr.Checkbox(False, label="Show and fix the player cut-out",
                                                       info="See in blue what the app treats as the player, and "
                                                            "click to add what it missed or take out what it "
                                                            "should not have.")
                            with gr.Row():
                                t_reset = gr.Button("Reset", size="sm")
                                t_copy = gr.Button("Use these settings on every photo with this look", size="sm")
                        with gr.Group(visible=False) as fix_box:
                            gr.Markdown("**Fix the cut-out.** Blue is the player: it gets the brightness sliders and "
                                        "stays clear of effects. Click a teammate, the ball or a flag to add it; "
                                        "click a pole or a sign to take it out. Each fix stays with this photo, "
                                        "for all its looks and the full-size export.", elem_classes="hint")
                            fix_mode = gr.Radio(FIX_MODES, value=ADD, show_label=False)
                            fix_img = gr.Image(label="Click to fix", interactive=False, height=480, elem_id="fix-img")
                            fix_msg = gr.Markdown(elem_classes="hint")
                            with gr.Row():
                                fix_undo_btn = gr.Button("Undo last click", size="sm")
                                fix_reset_btn = gr.Button("Back to automatic", size="sm")
                                fix_remake = gr.Button("Remake this photo's looks", variant="primary", size="sm")
                    with gr.Column(elem_classes="panel"):
                        step(5, "Save a preset, export settings")
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            look_name = gr.Textbox(label="Save the selected look as a preset",
                                                   placeholder="Preset name", scale=4)
                            save_btn = gr.Button("Save preset", scale=1, min_width=140)
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            export_dir = gr.Textbox(value=DEFAULT_EXPORT, label="Export folder", scale=4)
                            export_choose = gr.Button("Browse…", scale=1, min_width=90)
                        sizes = gr.CheckboxGroup(SIZE_CHOICES, value=[deliver.FULL], label="Sizes",
                                                 info="Each size is cropped to its shape around the players. "
                                                      "Instagram sizes get a light sharpening for phones; print "
                                                      "sizes are exact at 300 ppi.")
                        file_kind = gr.Radio(FILE_KINDS, value=engine.JPEG, label="File type",
                                             info="Both are full size, in the sRGB color profile. A TIFF keeps 16 "
                                                  "bits (from RAW photos), for big prints and editing in "
                                                  "Lightroom or Photoshop; it is about 6 times bigger.")
                        saved_credit = deliver.Credit.load()
                        with gr.Accordion("Your name, copyright and watermark", open=saved_credit.empty):
                            gr.Markdown("Written into every file, where Lightroom, Photo Mechanic, Photos and print "
                                        "labs look. Remembered for next time.", elem_classes="hint")
                            with gr.Row():
                                c_creator = gr.Textbox(saved_credit.creator, label="Photographer",
                                                       placeholder="Your name or studio")
                                c_contact = gr.Textbox(saved_credit.contact, label="Contact",
                                                       placeholder="Email, website or @handle")
                            c_notice = gr.Textbox(saved_credit.copyright, label="Copyright notice",
                                                  placeholder="Leave empty for: © <year taken> <photographer>")
                            w_on = gr.Checkbox(False, label="Add a watermark",
                                               info="For client proofs or posts; the files you keep stay clean "
                                                    "unless this is on.")
                            with gr.Group(visible=False) as w_box:
                                w_style = gr.Radio(WATERMARK_STYLES, value=deliver.CORNER, show_label=False)
                                with gr.Row():
                                    w_text = gr.Textbox(label="Watermark text", placeholder="Empty: your copyright notice "
                                                        "(or PROOF)")
                                    w_opacity = gr.Slider(0.1, 1, 0.5, step=0.05, label="Strength")
                        with gr.Accordion("Advanced: this look's recipe", open=False):
                            recipe_box = gr.Code(language="json", label="Recipe (edit before saving if you like)")
                    with gr.Column(elem_classes="panel"):
                        step(6, "Make an Instagram reel",
                             "A vertical video under a minute, ready to post: each photo slowly pushes in, "
                             "dissolves into the next, and cuts on the beat of your song.")
                        reel_source = gr.Radio(REEL_SOURCES, value=LOOKS, label="Photos for the reel",
                                               info="A folder uses the export folder above unless you type another.")
                        reel_folder = gr.Textbox(value=DEFAULT_EXPORT, label="Folder", visible=False)
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            reel_song = gr.File(label="Song (optional)", type="filepath", file_types=["audio"],
                                                height=110, scale=3)
                            reel_start = gr.Number(0, label="Start the song at (seconds)", precision=1, scale=2,
                                                   info="Skip a slow intro.")
                        with gr.Row():
                            reel_title = gr.Textbox(label="Opening title (optional)",
                                                    placeholder="e.g. PSG 11U vs West Park",
                                                    info="Shown in the lower third for the first 3 seconds.")
                            reel_closing = gr.Textbox(label="Closing text (optional)",
                                                      placeholder="e.g. @yourhandle",
                                                      info="Shown over the last photo.")
                        with gr.Row():
                            reel_sec = gr.Slider(1.5, 4, value=2.0, step=0.1, label="Seconds per photo",
                                                 info="Shortened automatically so the reel fits.")
                            reel_max = gr.Slider(15, 59, value=59, step=1, label="Longest reel (seconds)",
                                                 info="Instagram reels under a minute.")
                        reel_estimate_box = gr.Markdown("Make some looks first (steps 1 to 3).",
                                                        elem_classes="hint")
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            reel_btn = gr.Button("Make reel", variant="primary", scale=2)
                            reel_open = gr.Button("Open reels folder", scale=1, min_width=170)
                        reel_video = gr.Video(label="Your reel", height=520, interactive=False)
                        reel_msg = gr.Markdown(elem_classes="hint")

        with gr.Tab("Preset manager"):
            gr.Markdown("Build or change a preset: load one to start from, adjust the settings, preview it on a "
                        "photo, then save it under a name.", elem_classes="hint")
            with gr.Row(equal_height=False, elem_classes=["panel", "row-end"]):
                pm_pick = gr.Dropdown(names, label="Start from a preset", scale=3)
                pm_load = gr.Button("Load", scale=1, min_width=90)
                pm_delete = gr.Button("Delete", scale=1, min_width=90, size="sm", variant="stop")
            with gr.Row(equal_height=False):
                with gr.Column(scale=3, min_width=420):
                    fields = presetform.components(ids)
                with gr.Column(scale=2, min_width=340, elem_classes=["panel", "sticky"]):
                    gr.Markdown("**Preview**", elem_classes="hint")
                    sample = gr.File(label="Sample photo (optional; paste with ⌘V, or your first photo on Make looks)",
                                     type="filepath", height=110, elem_id="sample-upload")
                    pm_crop = gr.Radio(list(CROPS.values()), value=CROPS["none"], label="Crop first")
                    pm_preview = gr.Button("Preview")
                    pm_compare = gr.ImageSlider(label="Before / after", height=380)
                    pm_notes = gr.Markdown(elem_classes="hint")
                    gr.Markdown("**Save**", elem_classes="hint")
                    pm_name = gr.Textbox(label="Name", placeholder="e.g. PSG Night")
                    pm_desc = gr.Textbox(label="Description", placeholder="One line: what the look does",
                                         info="Shown next to the preset on Make looks.")
                    pm_save = gr.Button("Save preset", variant="primary")
                    with gr.Accordion("Advanced: recipe (this is what is saved)", open=False):
                        pm_recipe = gr.Code(language="json", label="Recipe")

        with gr.Tab("Lightroom presets"):
            gr.Markdown("Turn the Lightroom presets you own (or any app's look) into looks here. The app makes a color "
                        "chart; you apply your preset to it in Lightroom and export it; the app reads back what the "
                        "preset does to every color, saved as a LUT (and a preset).", elem_classes="hint")
            with gr.Row(equal_height=False):
                with gr.Column(scale=3, elem_classes="panel"):
                    step(1, "Download the color chart", "A 512 x 512 picture of every color, as a 16-bit TIFF.")
                    lightroom.save_chart(CHART_FILE)
                    gr.DownloadButton("Download the color chart", value=str(CHART_FILE), variant="primary")
                    step(2, "Apply your preset in Lightroom and export")
                    gr.Markdown(LR_STEPS)
                with gr.Column(scale=3, elem_classes="panel"):
                    step(3, "Add the exported charts")
                    lr_charts = gr.File(label="Exported charts (TIFF, or PNG)", file_count="multiple",
                                        type="filepath", height=140)
                    lr_name = gr.Textbox(label="Name (one chart)", placeholder="Empty: the file's name",
                                         info="With several charts, each is named after its file.")
                    lr_presets = gr.Checkbox(True, label="Also add each as a preset",
                                             info="Listed under My presets on Make looks, ready to tick.")
                    lr_go = gr.Button("Make LUTs", variant="primary")
                    lr_msg = gr.Markdown(elem_classes="hint")
                    lr_preview = gr.Gallery(label="On your first photo", columns=3, height=260, allow_preview=True)

        with gr.Tab("Assets"):
            gr.Markdown("Your LUTs, textures and overlays. Add one folder or zip per line, then press Save and "
                        "rescan. Zips are never unpacked whole; only the files a look uses are taken out and "
                        "cached in `~/.cache/photo-crops-presets`.", elem_classes="hint")
            with gr.Row(equal_height=False):
                with gr.Column(scale=3, elem_classes="panel"):
                    with gr.Row():
                        lut_folders = gr.Textbox("\n".join(src.lut_folders), label="LUT folders", lines=3)
                        lut_zips = gr.Textbox("\n".join(src.lut_zips), label="LUT zips", lines=3)
                    with gr.Row():
                        texture_folders = gr.Textbox("\n".join(src.texture_folders), label="Texture folders",
                                                     lines=3)
                        texture_zips = gr.Textbox("\n".join(src.texture_zips), label="Texture zips", lines=3)
                    with gr.Row():
                        overlay_folders = gr.Textbox("\n".join(src.overlay_folders),
                                                     label="Overlay folders (PNG with transparency)", lines=3)
                        overlay_zips = gr.Textbox("\n".join(src.overlay_zips),
                                                  label="Overlay zips (PNG or transparent video)", lines=3)
                    rescan = gr.Button("Save and rescan", variant="primary")
                with gr.Column(scale=2, elem_classes="panel"):
                    gr.Markdown("**In your library**", elem_classes="hint")
                    summary = gr.Markdown(assets_summary())

        # Wiring
        reel_inputs = [results, reel_source, reel_folder, reel_sec, reel_max]
        for trigger in (reel_source.change, reel_folder.change, reel_sec.change, reel_max.change, results.change):
            trigger(reel_estimate, reel_inputs, reel_estimate_box, show_progress="hidden")
        reel_source.change(lambda v: gr.update(visible=v == FOLDER), reel_source, reel_folder)
        export_dir.change(lambda f: f, export_dir, reel_folder)
        reel_btn.click(make_reel, [results, reel_source, reel_folder, reel_song, reel_start, reel_title,
                                   reel_closing, reel_sec, reel_max, export_dir], [reel_video, reel_msg])
        reel_open.click(open_reels, export_dir, None)
        mode.change(toggle_mode, mode, [random_box, preset_box])
        select_all.click(lambda: picker_updates(ticked=set(presets.load_all())), None, pickers)
        clear_all.click(lambda: picker_updates(ticked=[]), None, pickers)
        estimate_inputs = [files, folder, run_on] + pickers
        for p in pickers + [run_on]:
            p.change(preset_estimate, estimate_inputs, estimate, show_progress="hidden")
        for source in (files.change, folder.change):
            source(photo_status, [files, folder], [photo_count, run_on, try_photo, one_photo],
                   show_progress="hidden").then(
                preset_estimate, estimate_inputs, estimate, show_progress="hidden")
        run_on.change(lambda v, f, d: gr.update(visible=v == ONE and len(_inputs(f, d)) > 1),
                      [run_on, files, folder], try_photo, show_progress="hidden")
        choose.click(lambda f: choose_folder("Choose a folder of photos", f) or f, folder, folder)
        export_choose.click(lambda f: choose_folder("Choose where to export", f) or f, export_dir, export_dir)
        tune = [t_strength, t_subject, t_background, t_warmth, t_auto]
        shown = ([results, selected, thumbs, gallery, trial, use_all, tune_box, match_box, compare, info, recipe_box,
                  look_name]
                 + tune + [tune_note, fix_img])
        assert len(shown) == SHOWN
        # the progress card shows how the run is going; no loading boxes over step 4
        go.click(make_looks, [files, folder, mode, count, seed, crop, run_on, try_photo, show_cut] + pickers,
                 shown + [card], show_progress="hidden").then(
            picker_updates, None, pickers, show_progress="hidden")  # the presets' times, as learned
        use_all.click(use_on_all, [results, selected, trial, show_cut], shown + [card], show_progress="hidden")
        board.click(board_open, [results, show_cut],
                    [selected, compare, info, recipe_box, look_name] + tune + [tune_note, fix_img],
                    show_progress="hidden")
        tuned = [results, thumbs, gallery, compare, info, recipe_box]
        tune_inputs = [results, thumbs, selected] + tune
        for slider in (t_strength, t_subject, t_background, t_warmth):
            slider.release(fine_tune, tune_inputs, tuned, show_progress="minimal")
        t_auto.input(fine_tune, tune_inputs, tuned, show_progress="minimal")
        t_reset.click(lambda: (100, 0, 0, 0, False), None, tune).then(fine_tune, tune_inputs, tuned)
        t_copy.click(copy_to_look, [results, thumbs, selected] + tune, [results, thumbs, gallery])
        show_cut.input(show_cutout, [results, selected, show_cut], [fix_box, fix_img])
        fix_img.select(fix_click, [results, selected, fix_mode], [fix_img, fix_msg])
        fix_undo_btn.click(fix_undo, [results, selected], [fix_img, fix_msg])
        fix_reset_btn.click(fix_reset, [results, selected], [fix_img, fix_msg])
        fix_remake.click(remake_photo, [results, thumbs, selected], tuned)
        save_btn.click(save_look, [results, selected, look_name, recipe_box], [pm_pick] + pickers)
        picked, pick_titles = gr.State([]), gr.State([])
        boarded = [board, picked, pick_titles, ticked_msg]
        results.change(render_board, [results, selected, picked, pick_titles], boarded, show_progress="hidden")
        results.change(lambda r: gr.update(visible=bool(r)), results, export_bar, show_progress="hidden")
        board.input(board_tick, results, [picked, ticked_msg], show_progress="hidden")
        tick_all_btn.click(tick_all, [results, selected, pick_titles], boarded, show_progress="hidden")
        tick_look_btn.click(tick_look, [results, selected, pick_titles], boarded, show_progress="hidden")
        tick_none_btn.click(tick_none, [results, selected, pick_titles], boarded, show_progress="hidden")
        settings = [how, export_dir, file_kind, sizes, c_creator, c_notice, c_contact, w_on, w_text, w_style,
                    w_opacity]
        export_btn.click(export_ticked, [results, picked] + settings, [card, export_msg], show_progress="hidden")
        board.submit(export_one, [results] + settings, [card, export_msg], show_progress="hidden")
        w_on.change(lambda v: gr.update(visible=v), w_on, w_box, show_progress="hidden", queue=False)
        match_btn.click(match_game, [results, thumbs, selected], tuned + [match_msg])
        unmatch_btn.click(clear_match, [results, thumbs, selected], tuned + [match_msg])
        open_btn.click(open_folder, export_dir, None)

        form = [fields[n] for n in presetform.FIELDS]
        # .input fires only when you change a field, not when a loaded preset fills the
        # form, so a loaded recipe keeps any steps the form cannot show
        for field in form:
            field.input(build_recipe, form, pm_recipe)
        pm_load.click(load_preset, pm_pick, [pm_name, pm_desc] + form + [pm_recipe])
        pm_save.click(save_preset, [pm_name, pm_desc, pm_recipe], [pm_pick] + pickers)
        pm_delete.click(delete_preset, pm_pick, [pm_pick] + pickers)
        pm_preview.click(preview_preset, [sample, files, folder, pm_recipe, pm_crop], [pm_compare, pm_notes])
        lr_go.click(make_luts, [lr_charts, lr_name, lr_presets, files, folder],
                    [lr_msg, lr_preview, pm_pick] + pickers + [summary, fields["lut"], fields["t1"], fields["t2"],
                                                                fields["ov"]])
        rescan.click(save_sources, [lut_folders, lut_zips, texture_folders, texture_zips, overlay_folders, overlay_zips],
                     [summary, fields["lut"], fields["t1"], fields["t2"], fields["ov"]])
        demo.load(build_recipe, form, pm_recipe)
        demo.load(lambda: picker_updates(ticked=[]), None, pickers)
    return demo


def main() -> int:
    build().queue().launch(inbrowser=True, server_name="127.0.0.1", show_error=True, theme=THEME, css=CSS,
                           head=PASTE_JS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
