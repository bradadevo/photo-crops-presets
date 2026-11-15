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

import json
import re
import shutil
import subprocess
import tempfile
import sys
import uuid
from pathlib import Path

import gradio as gr

from photo_crops.ui import choose_folder
from photo_presets import deliver, engine, lightroom, pipeline, presets, presetform, reel
from photo_presets.assets import Library, Sources
from photo_presets.engine import CROPS, Engine
from photo_presets.scene import Fix

RANDOM, PRESET = "Random exploration", "Preset pipeline"
ONE, ALL = "one", "all"
RUN_ON = [("Try looks on one photo first", ONE), ("All photos", ALL)]
ALL_RESULTS, SAME_LOOK, SELECTED, PICKED = ("All results", "Every photo with the selected look",
                                            "Selected look only", "The ones I tick")
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


def make_looks(files, folder, mode, count, seed, crop_label, run_on, try_photo, show_cut, *groups,
               progress=gr.Progress()):
    paths = _inputs(files, folder)
    if not paths:
        raise gr.Error("Step 1: add photos, or choose a folder with photos.")
    crop = CROP_LABELS.get(crop_label, "none")
    trial = []
    if len(paths) > 1 and run_on == ONE:
        trial = [str(q) for q in paths]
        paths = [q for q in paths if str(q) == try_photo][:1] or paths[:1]

    def tick(done, total, title):
        progress(done / max(total, 1), desc=f"{done}/{total} {title}")

    if mode == RANDOM:
        seed_value = None if seed in (None, "") else int(seed)
        results = eng().explore(paths, int(count), crop, seed_value, tick)
    else:
        available = presets.load_all()
        chosen = [n for n in _picked(groups) if n in available]
        if not chosen:
            raise gr.Error("Step 2: tick at least one preset (or press Select all).")
        results = eng().presets(paths, chosen, crop, progress=tick)
        if len(paths) > 1:
            # a batch reads look by look: every photo in one look, then the next look
            results.sort(key=lambda r: chosen.index(r.name))
    return _shown(results, trial, show_cut)


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


def pick(results, show_cut, evt: gr.SelectData):
    return ((evt.index,) + _show(results, evt.index) + _controls(results, evt.index)
            + (_fix_picture(results, evt.index, show_cut),))


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


def use_on_all(results, index, trial, show_cut, progress=gr.Progress()):
    """The selected look (with its fine-tuning) on every photo from step 1."""
    if not results or not trial:
        raise gr.Error("Try looks on one photo first.")
    r = results[index]
    paths = [Path(q) for q in trial]

    def tick(done, total, title):
        progress(done / max(total, 1), desc=f"{done}/{total} {title}")

    out = eng().preset(paths, r.name, r.crop, recipe=r.recipe, progress=tick)
    return _shown(out, [], show_cut)


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
    return [[(f"{n} — {presets.describe(n, all_presets[n])}".rstrip(" —"), n) for n in names]
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


def export_choices(results, index, picked, shown):
    """The tick list for exporting some results: one row per result. Ticks are kept while the
    results are the same photos and looks (fine-tuning one keeps them); a new set of looks
    starts with the selected one ticked. shown: the titles the list was made for."""
    titles = [r.title for r in results or []]
    if titles == shown:
        return gr.skip(), shown
    choices = [(f"{i + 1}. {t}", i) for i, t in enumerate(titles)]
    ticked = [index] if 0 <= index < len(titles) else []
    return gr.update(choices=choices, value=ticked), titles


def export(results, index, folder, scope, picked, kind, sizes, creator, notice, contact, marked, mark_text,
           mark_style, mark_opacity, progress=gr.Progress()):
    if not results:
        raise gr.Error("Make some looks first.")
    if scope == ALL_RESULTS:
        chosen = results
    elif scope == PICKED:
        chosen = [results[i] for i in sorted(picked or []) if 0 <= i < len(results)]
        if not chosen:
            raise gr.Error("Tick at least one photo to export.")
    elif scope == SAME_LOOK:
        chosen = [r for r in results if r.name == results[index].name]
    else:
        chosen = [results[index]]
    dest = Path(folder or DEFAULT_EXPORT).expanduser()

    def tick(done, total, name):
        progress(done / max(total, 1), desc=f"Exporting {done}/{total} {name}")

    if not sizes:
        raise gr.Error("Tick at least one size.")
    credit = deliver.Credit(creator or "", notice or "", contact or "")
    if credit != deliver.Credit.load():
        credit.save()  # remembered for next time
    mark = None
    if marked:
        text = (mark_text or "").strip() or credit.notice() or "PROOF"
        mark = deliver.Watermark(text, mark_style, float(mark_opacity))
    saved, notes = eng().export(chosen, dest, tick, kind, list(sizes), credit, mark)
    what = {engine.JPEG: "JPEG", engine.TIFF: "16-bit TIFF", engine.BOTH: "JPEG and 16-bit TIFF"}[kind]
    names = [label.split(" (")[0] for label, key in SIZE_CHOICES if key in sizes]
    extras = ["sRGB color profile", "the date taken"]
    if not credit.empty:
        extras.append("your name and copyright")
    if mark:
        extras.append("a watermark")
    text = (f"Saved {len(saved)} file(s) ({len(chosen)} photo(s) × {', '.join(names)}) as {what}, with "
            f"{', '.join(extras)}, each with its recipe (.json), to `{dest}`")
    if notes:
        text += "\n\n**Note:** " + "; ".join(notes)
    return text


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
    n = len(_picked(groups))
    photos = len(_inputs(files, folder)) or 1
    if photos > 1 and run_on == ONE:
        photos = 1
    looks = n * photos
    if not looks:
        return "No presets ticked yet."
    seconds = looks * 2 + photos * 10
    when = f"about {seconds} seconds" if seconds < 90 else f"about {round(seconds / 60)} minutes"
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
                        step(4, "Compare and fine-tune", "Click a result to compare it with the original; "
                             "drag the slider.")
                        # no download buttons: they give 1600 px previews (as a zip); Export (step 5) saves full size
                        gallery = gr.Gallery(label="Results", columns=4, height=230, allow_preview=False,
                                             show_label=False, buttons=[])
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
                        compare = gr.ImageSlider(label="Before / after", height=480)
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
                        step(5, "Save or export")
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            look_name = gr.Textbox(label="Save the selected look as a preset",
                                                   placeholder="Preset name", scale=4)
                            save_btn = gr.Button("Save preset", scale=1, min_width=140)
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            export_dir = gr.Textbox(value=DEFAULT_EXPORT, label="Export folder", scale=4)
                            export_choose = gr.Button("Browse…", scale=1, min_width=90)
                        scope = gr.Radio([ALL_RESULTS, SAME_LOOK, SELECTED, PICKED], value=ALL_RESULTS,
                                         label="Export")
                        export_pick = gr.CheckboxGroup([], label="Tick the photos to export", visible=False,
                                                       info="The one you clicked in the results is ticked; "
                                                            "tick one or as many as you like.")
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
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            export_btn = gr.Button("Export full size", variant="primary", scale=2, min_width=150)
                            open_btn = gr.Button("Open folder", scale=1, min_width=140)
                        export_msg = gr.Markdown(elem_classes="hint")
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
        go.click(make_looks, [files, folder, mode, count, seed, crop, run_on, try_photo, show_cut] + pickers, shown)
        use_all.click(use_on_all, [results, selected, trial, show_cut], shown)
        gallery.select(pick, [results, show_cut],
                       [selected, compare, info, recipe_box, look_name] + tune + [tune_note, fix_img])
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
        scope.change(lambda v: gr.update(visible=v == PICKED), scope, export_pick, show_progress="hidden",
                     queue=False)
        pick_titles = gr.State([])
        results.change(export_choices, [results, selected, export_pick, pick_titles], [export_pick, pick_titles],
                       show_progress="hidden")
        export_btn.click(export, [results, selected, export_dir, scope, export_pick, file_kind, sizes, c_creator, c_notice,
                                  c_contact, w_on, w_text, w_style, w_opacity], export_msg)
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
