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

def _inputs(files, folder) -> list[Path]:
    items = [f if isinstance(f, str) else f.name for f in (files or [])]
    if folder and folder.strip():
        items.append(folder.strip())
    return engine.collect(items)


def _picked(groups) -> list[str]:
    return [n for g in groups for n in (g or [])]


def make_looks(files, folder, mode, count, seed, crop_label, *groups, progress=gr.Progress()):
    paths = _inputs(files, folder)
    if not paths:
        raise gr.Error("Step 1: add photos, or choose a folder with photos.")
    crop = CROP_LABELS.get(crop_label, "none")

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
    gallery = [(r.after, r.title) for r in results]
    first = _show(results, 0)
    return (results, 0, gallery) + first


def _show(results, index):
    if not results:
        return None, "", "", ""
    r = results[index]
    name = r.recipe.get("name", "")
    about = presets.describe(name, r.recipe) if name else ""
    notes = ("\n\n**Notes:** " + "; ".join(r.notes)) if r.notes else ""
    info = (f"**{r.title}**" + (f" — {about}" if about else "")
            + f"\n\n<span class='meta'>Seed {r.seed} · {CROPS[r.crop]}</span>{notes}")
    return (r.before, r.after), info, json.dumps(r.recipe, indent=1), name


def pick(results, evt: gr.SelectData):
    return (evt.index,) + _show(results, evt.index)


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
        presets.save(name, recipe)
    except (ValueError, json.JSONDecodeError) as e:
        raise gr.Error(f"Could not save: {e}")
    gr.Info(f"Saved preset \"{name.strip()}\" (under My presets)")
    return [gr.update(choices=list(presets.load_all()), value=name.strip())] + picker_updates()


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
    return gr.update(visible=mode == RANDOM), gr.update(visible=mode == PRESET)


def preset_estimate(files, folder, *groups):
    """How many looks the ticked presets make, and about how long they take."""
    n = len(_picked(groups))
    photos = len(_inputs(files, folder)) or 1
    looks = n * photos
    if not looks:
        return "No presets ticked yet."
    seconds = looks * 2 + photos * 10
    when = f"about {seconds} seconds" if seconds < 90 else f"about {round(seconds / 60)} minutes"
    return f"**{n}** preset(s) × **{photos}** photo(s) = **{looks}** looks, {when}."


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
    with gr.Blocks(title="Photo Presets") as demo:
        results = gr.State([])
        selected = gr.State(0)
        gr.Markdown(
            "# Photo Presets\n"
            "Pro looks for your sports photos. Faces stay clean of effects, and your originals are never "
            "changed.\n\n"
            "<div class='steps-strip'><span>1 · Add photos</span><span>2 · Choose looks</span>"
            "<span>3 · Make looks</span><span>4 · Compare</span><span>5 · Save or export</span></div>",
            elem_classes="app-header")

        with gr.Tab("Make looks"):
            with gr.Row(equal_height=False):
                # Left: the steps to set up a run, top to bottom
                with gr.Column(scale=2, min_width=340, elem_classes="panel"):
                    step(1, "Add photos", "Drop photos here (JPG or RAW), or choose a whole folder.")
                    files = gr.File(label="Photos", file_count="multiple", type="filepath", height=150)
                    with gr.Row(equal_height=False, elem_classes="row-end"):
                        folder = gr.Textbox(label="Or a folder of photos", placeholder="~/Pictures/Game day",
                                            scale=4)
                        choose = gr.Button("Browse…", scale=1, min_width=90)

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
                    crop = gr.Radio(list(CROPS.values()), value=CROPS["none"], label="Crop first",
                                    info="Optionally crop around the action or a face before styling.")
                    go = gr.Button("Make looks", variant="primary", size="lg", elem_classes="go-button")

                # Right: the results, then what to do with them
                with gr.Column(scale=3, min_width=420):
                    with gr.Column(elem_classes="panel"):
                        step(4, "Compare", "Click a result to compare it with the original; drag the slider.")
                        gallery = gr.Gallery(label="Results", columns=4, height=230, allow_preview=False,
                                             show_label=False)
                        compare = gr.ImageSlider(label="Before / after", height=480)
                        info = gr.Markdown()
                    with gr.Column(elem_classes="panel"):
                        step(5, "Save or export")
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            look_name = gr.Textbox(label="Save the selected look as a preset",
                                                   placeholder="Preset name", scale=4)
                            save_btn = gr.Button("Save preset", scale=1, min_width=140)
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            export_dir = gr.Textbox(value=DEFAULT_EXPORT, label="Export folder", scale=4)
                            export_choose = gr.Button("Browse…", scale=1, min_width=90)
                        with gr.Row(equal_height=False, elem_classes="row-end"):
                            scope = gr.Radio(["All results", "Selected look only"], value="All results",
                                             label="Export", scale=3)
                            export_btn = gr.Button("Export full size", variant="primary", scale=2, min_width=150)
                            open_btn = gr.Button("Open folder", scale=1, min_width=140)
                        export_msg = gr.Markdown(elem_classes="hint")
                        with gr.Accordion("Advanced: this look's recipe", open=False):
                            recipe_box = gr.Code(language="json", label="Recipe (edit before saving if you like)")

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
                    sample = gr.File(label="Sample photo (optional; else your first photo on Make looks)",
                                     type="filepath", height=110)
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
        mode.change(toggle_mode, mode, [random_box, preset_box])
        select_all.click(lambda: picker_updates(ticked=set(presets.load_all())), None, pickers)
        clear_all.click(lambda: picker_updates(ticked=[]), None, pickers)
        for p in pickers:
            p.change(preset_estimate, [files, folder] + pickers, estimate, show_progress="hidden")
        files.change(preset_estimate, [files, folder] + pickers, estimate, show_progress="hidden")
        choose.click(lambda f: choose_folder("Choose a folder of photos", f) or f, folder, folder)
        export_choose.click(lambda f: choose_folder("Choose where to export", f) or f, export_dir, export_dir)
        go.click(make_looks, [files, folder, mode, count, seed, crop] + pickers,
                 [results, selected, gallery, compare, info, recipe_box, look_name])
        gallery.select(pick, results, [selected, compare, info, recipe_box, look_name])
        save_btn.click(save_look, [results, selected, look_name, recipe_box], [pm_pick] + pickers)
        export_btn.click(export, [results, selected, export_dir, scope], export_msg)
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
        rescan.click(save_sources, [lut_folders, lut_zips, texture_folders, texture_zips, overlay_folders, overlay_zips],
                     [summary, fields["lut"], fields["t1"], fields["t2"], fields["ov"]])
        demo.load(build_recipe, form, pm_recipe)
        demo.load(lambda: picker_updates(ticked=[]), None, pickers)
    return demo


def main() -> int:
    build().queue().launch(inbrowser=True, server_name="127.0.0.1", show_error=True, theme=THEME, css=CSS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
