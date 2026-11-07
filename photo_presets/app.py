"""The Gradio app: make looks (random or preset), compare before/after,
save looks as presets, manage presets and assets, and export full-size files.

    uv run photo-presets
"""

import json
import subprocess
import sys
from pathlib import Path

import gradio as gr

from photo_crops.ui import choose_folder
from photo_presets import engine, presets, presetform
from photo_presets.assets import Library, Sources
from photo_presets.engine import CROPS, Engine

RANDOM, PRESET = "Random exploration", "Preset pipeline"
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

def _inputs(files, folder) -> list[Path]:
    items = [f if isinstance(f, str) else f.name for f in (files or [])]
    if folder and folder.strip():
        items.append(folder.strip())
    return engine.collect(items)


def make_looks(files, folder, mode, count, seed, preset_name, crop_label, progress=gr.Progress()):
    paths = _inputs(files, folder)
    if not paths:
        raise gr.Error("Add photos, or choose a folder with photos.")
    crop = CROP_LABELS.get(crop_label, "none")

    def tick(done, total, title):
        progress(done / max(total, 1), desc=f"{done}/{total} {title}")

    if mode == RANDOM:
        seed_value = None if seed in (None, "") else int(seed)
        results = eng().explore(paths, int(count), crop, seed_value, tick)
    else:
        if preset_name not in presets.load_all():
            raise gr.Error("Choose a preset.")
        results = eng().preset(paths, preset_name, crop, progress=tick)
    gallery = [(r.after, r.title) for r in results]
    first = _show(results, 0)
    return (results, 0, gallery) + first


def _show(results, index):
    if not results:
        return None, "", "", ""
    r = results[index]
    notes = ("\n\n**Notes:** " + "; ".join(r.notes)) if r.notes else ""
    info = f"**{r.title}**  ·  seed {r.seed}  ·  {CROPS[r.crop]}{notes}"
    return (r.before, r.after), info, json.dumps(r.recipe, indent=1), r.recipe.get("name", "")


def pick(results, evt: gr.SelectData):
    return (evt.index,) + _show(results, evt.index)


def save_look(results, index, name, recipe_text):
    try:
        recipe = json.loads(recipe_text)
        presets.save(name, recipe)
    except (ValueError, json.JSONDecodeError) as e:
        raise gr.Error(f"Could not save: {e}")
    gr.Info(f"Saved preset \"{name.strip()}\"")
    names = list(presets.load_all())
    return gr.update(choices=names, value=name.strip()), gr.update(choices=names, value=name.strip())


def export(results, index, folder, scope, progress=gr.Progress()):
    if not results:
        raise gr.Error("Make some looks first.")
    chosen = results if scope == "All results" else [results[index]]
    dest = Path(folder or DEFAULT_EXPORT).expanduser()

    def tick(done, total, name):
        progress(done / max(total, 1), desc=f"Exporting {done}/{total} {name}")

    saved = eng().export(chosen, dest, tick)
    return f"Saved {len(saved)} full-size photo(s), each with its recipe (.json), to `{dest}`"


def open_folder(folder):
    dest = Path(folder or DEFAULT_EXPORT).expanduser()
    if dest.is_dir():
        subprocess.run(["open", str(dest)])
    else:
        gr.Warning("Nothing exported there yet.")


def toggle_mode(mode):
    return gr.update(visible=mode == RANDOM), gr.update(visible=mode == RANDOM), gr.update(visible=mode == PRESET)


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
    return [name] + form_from_recipe(recipe) + [json.dumps(recipe, indent=1)]


def save_preset(name, recipe_text):
    try:
        presets.save(name, json.loads(recipe_text))
    except (ValueError, json.JSONDecodeError) as e:
        raise gr.Error(f"Could not save: {e}")
    gr.Info(f"Saved preset \"{name.strip()}\"")
    names = list(presets.load_all())
    return gr.update(choices=names, value=name.strip()), gr.update(choices=names, value=name.strip())


def delete_preset(name):
    if presets.delete(name):
        gr.Info(f"Deleted \"{name}\"" + (" (the built-in starter is back)" if name in presets.STARTERS else ""))
    else:
        gr.Warning("Only presets you saved can be deleted; built-in starters stay.")
    names = list(presets.load_all())
    return gr.update(choices=names, value=None), gr.update(choices=names)


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
    return (r.before, r.after), notes


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


# Layout ---------------------------------------------------------------------------------

def build() -> gr.Blocks:
    lib = eng().library
    ids = lib.ids()
    names = list(presets.load_all())
    src = lib.sources
    with gr.Blocks(title="Photo Presets") as demo:
        results = gr.State([])
        selected = gr.State(0)
        gr.Markdown("# Photo Presets\nCreative looks for your sports photos: explore random looks, or run your "
                    "saved presets. Faces are kept clean of textures and effects; originals are never changed.")
        with gr.Tab("Make looks"):
            with gr.Row():
                with gr.Column(scale=1, min_width=300):
                    files = gr.File(label="Photos", file_count="multiple", type="filepath")
                    with gr.Row():
                        folder = gr.Textbox(label="…or a folder of photos", scale=4)
                        choose = gr.Button("Choose…", scale=1, min_width=90)
                    mode = gr.Radio([RANDOM, PRESET], value=RANDOM, label="Mode")
                    count = gr.Slider(1, 24, value=6, step=1, label="Random looks per photo")
                    seed = gr.Number(label="Seed (leave empty for new looks each time)", precision=0)
                    preset_pick = gr.Dropdown(names, value=names[0] if names else None, label="Preset",
                                              visible=False)
                    crop = gr.Radio(list(CROPS.values()), value=CROPS["none"], label="Crop first")
                    go = gr.Button("Make looks", variant="primary")
                with gr.Column(scale=2):
                    gallery = gr.Gallery(label="Results (click one to compare)", columns=4, height=360,
                                         allow_preview=False)
                    compare = gr.ImageSlider(label="Before / after", height=520)
                    info = gr.Markdown()
                    with gr.Accordion("This look's recipe", open=False):
                        recipe_box = gr.Code(language="json", label="Recipe (you can edit it before saving)")
                    with gr.Row():
                        look_name = gr.Textbox(label="Save this look as a preset named", scale=4)
                        save_btn = gr.Button("Save preset", scale=1, min_width=120)
            with gr.Row():
                export_dir = gr.Textbox(value=DEFAULT_EXPORT, label="Export folder", scale=4)
                export_choose = gr.Button("Choose…", scale=1, min_width=90)
                scope = gr.Radio(["All results", "Selected look only"], value="All results", label="Export", scale=2)
                export_btn = gr.Button("Export full size", variant="primary", scale=1, min_width=150)
            with gr.Row():
                export_msg = gr.Markdown()
                open_btn = gr.Button("Open folder", scale=0, min_width=130)

        with gr.Tab("Preset manager"):
            with gr.Row():
                pm_pick = gr.Dropdown(names, label="Preset", scale=3)
                pm_load = gr.Button("Load", scale=1)
                pm_delete = gr.Button("Delete", scale=1, variant="stop")
            pm_name = gr.Textbox(label="Name")
            fields = presetform.components(ids)
            with gr.Accordion("Recipe (advanced: edit any step directly; this is what is saved)", open=False):
                pm_recipe = gr.Code(language="json", label="Recipe")
            with gr.Row():
                sample = gr.File(label="Sample photo for preview (optional)", type="filepath", scale=2)
                pm_crop = gr.Radio(list(CROPS.values()), value=CROPS["none"], label="Crop first", scale=2)
                with gr.Column(scale=1):
                    pm_preview = gr.Button("Preview")
                    pm_save = gr.Button("Save preset", variant="primary")
            pm_compare = gr.ImageSlider(label="Before / after", height=520)
            pm_notes = gr.Markdown()

        with gr.Tab("Assets"):
            summary = gr.Markdown(assets_summary())
            gr.Markdown("One folder or zip per line. Zips are never unpacked whole; only the files a look uses "
                        "are taken out and cached in `~/.cache/photo-crops-presets`.")
            with gr.Row():
                lut_folders = gr.Textbox("\n".join(src.lut_folders), label="LUT folders", lines=3)
                lut_zips = gr.Textbox("\n".join(src.lut_zips), label="LUT zips", lines=3)
            with gr.Row():
                texture_folders = gr.Textbox("\n".join(src.texture_folders), label="Texture folders", lines=3)
                texture_zips = gr.Textbox("\n".join(src.texture_zips), label="Texture zips", lines=3)
            with gr.Row():
                overlay_folders = gr.Textbox("\n".join(src.overlay_folders), label="Overlay folders (PNG with transparency)",
                                             lines=3)
                overlay_zips = gr.Textbox("\n".join(src.overlay_zips), label="Overlay zips (PNG or transparent video)",
                                          lines=3)
            rescan = gr.Button("Save and rescan", variant="primary")

        # Wiring
        mode.change(toggle_mode, mode, [count, seed, preset_pick])
        choose.click(lambda f: choose_folder("Choose a folder of photos", f) or f, folder, folder)
        export_choose.click(lambda f: choose_folder("Choose where to export", f) or f, export_dir, export_dir)
        go.click(make_looks, [files, folder, mode, count, seed, preset_pick, crop],
                 [results, selected, gallery, compare, info, recipe_box, look_name])
        gallery.select(pick, results, [selected, compare, info, recipe_box, look_name])
        save_btn.click(save_look, [results, selected, look_name, recipe_box], [preset_pick, pm_pick])
        export_btn.click(export, [results, selected, export_dir, scope], export_msg)
        open_btn.click(open_folder, export_dir, None)

        form = [fields[n] for n in presetform.FIELDS]
        # .input fires only when you change a field, not when a loaded preset fills the
        # form, so a loaded recipe keeps any steps the form cannot show
        for field in form:
            field.input(build_recipe, form, pm_recipe)
        pm_load.click(load_preset, pm_pick, [pm_name] + form + [pm_recipe])
        pm_save.click(save_preset, [pm_name, pm_recipe], [pm_pick, preset_pick])
        pm_delete.click(delete_preset, pm_pick, [pm_pick, preset_pick])
        pm_preview.click(preview_preset, [sample, files, folder, pm_recipe, pm_crop], [pm_compare, pm_notes])
        rescan.click(save_sources, [lut_folders, lut_zips, texture_folders, texture_zips, overlay_folders, overlay_zips],
                     [summary, fields["lut"], fields["t1"], fields["t2"], fields["ov"]])
        demo.load(build_recipe, form, pm_recipe)
    return demo


def main() -> int:
    build().queue().launch(inbrowser=True, server_name="127.0.0.1", show_error=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
