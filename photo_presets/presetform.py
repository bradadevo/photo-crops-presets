"""The preset manager's form: its fields, and turning them into a recipe and back.

The form covers every built-in step; the recipe text in the app stays the
source of truth for anything else (plugins, extra steps).
"""

from contextlib import contextmanager

import gradio as gr

from photo_presets import blend
from photo_presets.effects import SMOKE_PLACES

NONE = "None"
PLACES = ["ball", "feet", "center", "random"]
CORNERS = ["top_left", "top_right", "bottom_left", "bottom_right"]
BLENDS = list(blend.MODES)
BEHIND, FRONT = "Behind the player (depth)", "In front of everything"
COLOR_KINDS = [NONE, "LUT", "Neon", "B&W", "Duotone"]
SMOKE_LABELS = {"sides": "At the sides", "behind": "Behind the player", "floor": "Along the floor",
                "sides_floor": "Sides and floor"}
PLACE_LABELS = {"ball": "The ball", "feet": "The feet", "center": "The center", "random": "Anywhere"}

# name: default
DEFAULTS = {
    "protect": True, "skin_protect": 0.7, "clean_on": False,
    "color_kind": "LUT", "lut": NONE, "lut_strength": 0.9,
    "neon_dark": "#5b1aff", "neon_light": "#00f0ff", "neon_amount": 0.7,
    "bw_r": 0.45, "bw_g": 0.4, "bw_b": 0.15, "bw_contrast": 1.3,
    "duo_dark": "#0b1d3a", "duo_light": "#ffb347",
    "split_on": False, "split_shadows": "#1f4e79", "split_highlights": "#ffb347", "split_amount": 0.5,
    "split_balance": 0.0, "split_blacks": 0.3,
    "contrast": 0.0, "saturation": 1.0, "hk_on": False, "hk_amount": 0.5,
    "clarity_on": False, "clarity_amount": 0.6, "clarity_radius": 0.004,
    "hp_on": False, "hp_amount": 0.7,
    "sep_on": False, "subj_exposure": 0.2, "subj_clarity": 0.5, "bg_exposure": -0.5, "bg_blur": 0.0,
    "bg_saturation": 1.0, "subj_saturation": 1.0, "bg_bw": False, "bg_high_key": 0.0,
    "bd_on": False, "bd_top": "#3d86c6", "bd_bottom": "#000000", "bd_glow": 0.5,
    "t1": NONE, "t1_blend": "overlay", "t1_opacity": 0.4,
    "t2": NONE, "t2_blend": "soft_light", "t2_opacity": 0.3,
    "fog_on": False, "fog_density": 0.5, "fog_height": 0.65, "fog_color": "#d9dee6",
    "sm_on": False, "sm_color": "#f4f1ee", "sm_two": False, "sm_color2": "#d9a520", "sm_place": "sides",
    "sm_amount": 0.85, "sm_size": 1.0, "sm_front": 0.0,
    "lights_on": False, "lights_count": 2, "lights_amount": 0.8,
    "st_on": False, "st_height": 0.7, "st_amount": 0.9, "st_color": "#fff3dc",
    "rain_on": False, "rain_amount": 0.5, "rain_angle": 12.0,
    "ov": NONE, "ov_place": "ball", "ov_blend": "screen", "ov_opacity": 0.9, "ov_size": 1.0, "ov_depth": BEHIND,
    "leak_on": False, "leak_color": "#ff7a1a", "leak_corner": "top_right", "leak_amount": 0.5,
    "glow_on": False, "glow_amount": 0.35,
    "bloom_on": False, "bloom_amount": 0.5, "bloom_threshold": 0.8, "bloom_size": 0.02,
    "spot_on": False, "spot_amount": 0.3,
    "edge_on": False, "edge_amount": 0.5,
    "grain_on": False, "grain_amount": 0.2,
    "vig_on": True, "vig_amount": 0.35,
    "sv_on": False, "sv_amount": 0.6, "sv_spread": 0.3,
    "pa_on": False, "pa_levels": 7, "pa_mottle": 0.35, "pa_lines": 0.6, "pa_shading": 0.45, "pa_glow": 0.7,
    "pa_outline": "#ff6f7d", "pa_bg": "#9a6a44", "pa_bg_amount": 0.85, "pa_crisp": False,
    "ps_on": False, "ps_amount": 0.85, "ps_strokes": 0.7, "ps_front": 0.25, "ps_whips": 0.0,
    "nl_on": False, "nl_darkness": 0.6, "nl_lines": 1.0, "nl_detail": 0.6, "nl_rim": 1.0, "nl_glow": 0.5,
    "pb_on": False, "pb_amount": 0.9, "pb_size": 1.0, "pb_direction": 0.0, "pb_splash": 1.0, "pb_lines": 0.0,
    "pb_specks": 0.0,
    "dr_on": False, "dr_colors": "#fff1d9,#ff9fc8,#a6ecd3,#7b4a32", "dr_amount": 0.8, "dr_length": 1.0,
    "dr_gloss": 0.8, "dr_front": 0.0,
}
FIELDS = list(DEFAULTS)


def to_recipe(v: dict) -> dict:
    """The form as a recipe, steps in a fixed order."""
    s = []
    if v["clean_on"]:
        s.append({"op": "clean", "strength": "light"})
    kind = v["color_kind"]
    if kind == "LUT" and v["lut"] and v["lut"] != NONE:
        s.append({"op": "lut", "asset": v["lut"], "strength": v["lut_strength"]})
    elif kind == "Neon":
        s.append({"op": "neon", "shadows": v["neon_dark"], "highlights": v["neon_light"], "amount": v["neon_amount"]})
    elif kind == "B&W":
        s.append({"op": "bw", "red": v["bw_r"], "green": v["bw_g"], "blue": v["bw_b"], "contrast": v["bw_contrast"]})
    elif kind == "Duotone":
        s.append({"op": "duotone", "dark": v["duo_dark"], "light": v["duo_light"], "amount": 1.0})
    if v["split_on"]:
        s.append({"op": "split_tone", "shadows": v["split_shadows"], "highlights": v["split_highlights"],
                  "amount": v["split_amount"], "balance": v["split_balance"], "compress_blacks": v["split_blacks"]})
    if v["hk_on"]:
        s.append({"op": "high_key", "amount": v["hk_amount"]})
    if v["contrast"]:
        s.append({"op": "contrast", "amount": v["contrast"]})
    if v["saturation"] != 1.0:
        s.append({"op": "saturation", "amount": v["saturation"]})
    if v["clarity_on"]:
        s.append({"op": "athletic_clarity", "amount": v["clarity_amount"], "radius": v["clarity_radius"]})
    if v["hp_on"]:
        s.append({"op": "high_pass", "radius": 0.006, "amount": v["hp_amount"]})
    if v["sep_on"]:
        if v["bd_on"]:
            s.append({"op": "backdrop", "top": v["bd_top"], "bottom": v["bd_bottom"], "glow": v["bd_glow"],
                      "layer": "background"})
        if v["bg_bw"]:
            s.append({"op": "bw", "red": 0.3, "green": 0.35, "blue": 0.35, "contrast": 1.2, "layer": "background"})
        if v["bg_high_key"]:
            s.append({"op": "high_key", "amount": v["bg_high_key"], "layer": "background"})
        if v["subj_saturation"] != 1.0:
            s.append({"op": "saturation", "amount": v["subj_saturation"], "layer": "subject"})
        if v["subj_exposure"]:
            s.append({"op": "exposure", "stops": v["subj_exposure"], "layer": "subject"})
        if v["subj_clarity"]:
            s.append({"op": "athletic_clarity", "amount": v["subj_clarity"], "layer": "subject"})
        if v["bg_exposure"]:
            s.append({"op": "exposure", "stops": v["bg_exposure"], "layer": "background"})
        if v["bg_blur"]:
            s.append({"op": "lens_blur", "radius": v["bg_blur"], "layer": "background"})
        if v["bg_saturation"] != 1.0:
            s.append({"op": "saturation", "amount": v["bg_saturation"], "layer": "background"})
    if v["pa_on"]:
        s.append({"op": "pop_art", "levels": int(v["pa_levels"]), "mottle": v["pa_mottle"], "lines": v["pa_lines"],
                  "shading": v["pa_shading"], "glow": v["pa_glow"], "outline": v["pa_outline"],
                  "background": v["pa_bg"], "background_amount": v["pa_bg_amount"],
                  "crisp": 1.0 if v["pa_crisp"] else 0.0})
    if v["nl_on"]:
        s.append({"op": "neon_lineart", "darkness": v["nl_darkness"], "lines": v["nl_lines"], "detail": v["nl_detail"],
                  "rim": v["nl_rim"], "glow": v["nl_glow"]})
    if v["pb_on"]:
        s.append({"op": "paint_burst", "amount": v["pb_amount"], "size": v["pb_size"], "direction": v["pb_direction"],
                  "splash": v["pb_splash"], "lines": v["pb_lines"], "specks": v["pb_specks"]})
    if v["dr_on"]:
        s.append({"op": "drip", "colors": v["dr_colors"], "amount": v["dr_amount"], "length": v["dr_length"],
                  "gloss": v["dr_gloss"], "front": v["dr_front"]})
    if v["ps_on"]:
        s.append({"op": "paint_splatter", "amount": v["ps_amount"], "strokes": v["ps_strokes"], "front": v["ps_front"],
                  "whips": v["ps_whips"]})
    for n in ("t1", "t2"):
        if v[n] and v[n] != NONE:
            s.append({"op": "texture", "asset": v[n], "blend": v[f"{n}_blend"], "opacity": v[f"{n}_opacity"]})
    if v["fog_on"]:
        s.append({"op": "fog", "density": v["fog_density"], "height": v["fog_height"], "color": v["fog_color"]})
    if v["sm_on"]:
        s.append({"op": "smoke_cloud", "color": v["sm_color"], "color2": v["sm_color2"] if v["sm_two"] else "",
                  "place": v["sm_place"], "amount": v["sm_amount"], "size": v["sm_size"], "front": v["sm_front"]})
    if v["lights_on"]:
        s.append({"op": "stage_lights", "count": int(v["lights_count"]), "amount": v["lights_amount"],
                  "layer": "background"})
    if v["st_on"]:
        s.append({"op": "stadium_lights", "height": v["st_height"], "amount": v["st_amount"],
                  "color": v["st_color"], "layer": "background"})
    if v["rain_on"]:
        s.append({"op": "rain", "amount": v["rain_amount"], "angle": v["rain_angle"]})
    if v["ov"] and v["ov"] != NONE:
        s.append({"op": "overlay", "asset": v["ov"], "place": v["ov_place"], "blend": v["ov_blend"],
                  "opacity": v["ov_opacity"], "size": v["ov_size"],
                  "layer": "background" if v["ov_depth"] == BEHIND else "all"})
    if v["leak_on"]:
        s.append({"op": "light_leak", "color": v["leak_color"], "corner": v["leak_corner"], "amount": v["leak_amount"]})
    if v["glow_on"]:
        s.append({"op": "glow", "amount": v["glow_amount"]})
    if v["bloom_on"]:
        s.append({"op": "specular_bloom", "amount": v["bloom_amount"], "threshold": v["bloom_threshold"],
                  "size": v["bloom_size"]})
    if v["spot_on"]:
        s.append({"op": "spotlight", "amount": v["spot_amount"]})
    if v["edge_on"]:
        s.append({"op": "edge_distress", "amount": v["edge_amount"]})
    if v["grain_on"]:
        s.append({"op": "grain", "amount": v["grain_amount"]})
    if v["vig_on"]:
        s.append({"op": "vignette", "amount": v["vig_amount"]})
    if v["sv_on"]:
        s.append({"op": "subject_vignette", "amount": v["sv_amount"], "spread": v["sv_spread"]})
    return {"protect_faces": bool(v["protect"]), "skin_protect": v["skin_protect"], "steps": s}


def from_recipe(recipe: dict) -> dict:
    """Best effort: the form for a recipe."""
    v = dict(DEFAULTS)
    v.update(protect=recipe.get("protect_faces", True), skin_protect=recipe.get("skin_protect", 0.7),
             color_kind=NONE, vig_on=False)
    textures = []
    sep = {"subj_exposure": 0.0, "subj_clarity": 0.0, "bg_exposure": 0.0, "bg_blur": 0.0, "bg_saturation": 1.0,
           "subj_saturation": 1.0, "bg_high_key": 0.0}
    for st in recipe.get("steps", []):
        op, layer = st.get("op"), st.get("layer", "all")
        g = st.get
        if op == "clean":
            v["clean_on"] = True
        elif op == "lut":
            v.update(color_kind="LUT", lut=g("asset", NONE), lut_strength=g("strength", 0.9))
        elif op == "neon":
            v.update(color_kind="Neon", neon_dark=g("shadows", v["neon_dark"]), neon_light=g("highlights", v["neon_light"]),
                     neon_amount=g("amount", 0.7))
        elif op == "bw" and layer == "background":
            v.update(sep_on=True, bg_bw=True)
        elif op == "bw":
            v.update(color_kind="B&W", bw_r=g("red", 0.45), bw_g=g("green", 0.4), bw_b=g("blue", 0.15),
                     bw_contrast=g("contrast", 1.3))
        elif op == "duotone":
            v.update(color_kind="Duotone", duo_dark=g("dark", v["duo_dark"]), duo_light=g("light", v["duo_light"]))
        elif op == "split_tone":
            v.update(split_on=True, split_shadows=g("shadows", v["split_shadows"]),
                     split_highlights=g("highlights", v["split_highlights"]), split_amount=g("amount", 0.5),
                     split_balance=g("balance", 0.0), split_blacks=g("compress_blacks", 0.3))
        elif op == "contrast":
            v["contrast"] = g("amount", 0.3)
        elif op == "high_key" and layer == "background":
            v["sep_on"] = True
            sep["bg_high_key"] = g("amount", 0.5)
        elif op == "high_key":
            v.update(hk_on=True, hk_amount=g("amount", 0.5))
        elif op == "backdrop":
            v.update(sep_on=True, bd_on=True, bd_top=g("top", v["bd_top"]), bd_bottom=g("bottom", v["bd_bottom"]),
                     bd_glow=g("glow", 0.5))
        elif op == "saturation" and layer == "subject":
            v["sep_on"] = True
            sep["subj_saturation"] = g("amount", 1.0)
        elif op == "saturation" and layer == "all":
            v["saturation"] = g("amount", 1.0)
        elif op == "athletic_clarity" and layer == "subject":
            v["sep_on"] = True
            sep["subj_clarity"] = g("amount", 0.5)
        elif op == "athletic_clarity":
            v.update(clarity_on=True, clarity_amount=g("amount", 0.6), clarity_radius=g("radius", 0.004))
        elif op == "high_pass":
            v.update(hp_on=True, hp_amount=g("amount", 0.7))
        elif op == "exposure" and layer in ("subject", "background"):
            v["sep_on"] = True
            sep["subj_exposure" if layer == "subject" else "bg_exposure"] = g("stops", 0.0)
        elif op == "lens_blur":
            v["sep_on"] = True
            sep["bg_blur"] = g("radius", 0.006)
        elif op == "saturation" and layer == "background":
            v["sep_on"] = True
            sep["bg_saturation"] = g("amount", 1.0)
        elif op == "texture":
            textures.append(st)
        elif op == "fog":
            v.update(fog_on=True, fog_density=g("density", 0.5), fog_height=g("height", 0.65),
                     fog_color=g("color", v["fog_color"]))
        elif op == "smoke_cloud":
            v.update(sm_on=True, sm_color=g("color", v["sm_color"]), sm_two=bool(g("color2")),
                     sm_color2=g("color2") or v["sm_color2"], sm_place=g("place", "sides"),
                     sm_amount=g("amount", 0.85), sm_size=g("size", 1.0), sm_front=g("front", 0.0))
        elif op == "stage_lights":
            v.update(lights_on=True, lights_count=g("count", 2), lights_amount=g("amount", 0.8))
        elif op == "stadium_lights":
            v.update(st_on=True, st_height=g("height", 0.7), st_amount=g("amount", 0.9),
                     st_color=g("color", v["st_color"]))
        elif op == "pop_art":
            v.update(pa_on=True, pa_levels=g("levels", 7), pa_mottle=g("mottle", 0.35), pa_lines=g("lines", 0.6),
                     pa_shading=g("shading", 0.45), pa_glow=g("glow", 0.7), pa_outline=g("outline", "#ff6f7d"),
                     pa_bg=g("background", "#9a6a44"), pa_bg_amount=g("background_amount", 0.85),
                     pa_crisp=float(g("crisp", 0.0)) >= 0.5)
        elif op == "neon_lineart":
            v.update(nl_on=True, nl_darkness=g("darkness", 0.6), nl_lines=g("lines", 1.0), nl_detail=g("detail", 0.6),
                     nl_rim=g("rim", 1.0), nl_glow=g("glow", 0.5))
        elif op == "paint_burst":
            v.update(pb_on=True, pb_amount=g("amount", 0.9), pb_size=g("size", 1.0), pb_direction=g("direction", 0.0),
                     pb_splash=g("splash", 1.0), pb_lines=g("lines", 0.0), pb_specks=g("specks", 0.0))
        elif op == "drip":
            v.update(dr_on=True, dr_colors=g("colors", v["dr_colors"]), dr_amount=g("amount", 0.8),
                     dr_length=g("length", 1.0), dr_gloss=g("gloss", 0.8), dr_front=g("front", 0.0))
        elif op == "paint_splatter":
            v.update(ps_on=True, ps_amount=g("amount", 0.85), ps_strokes=g("strokes", 0.7), ps_front=g("front", 0.25),
                     ps_whips=g("whips", 0.0))
        elif op == "subject_vignette":
            v.update(sv_on=True, sv_amount=g("amount", 0.6), sv_spread=g("spread", 0.3))
        elif op == "rain":
            v.update(rain_on=True, rain_amount=g("amount", 0.5), rain_angle=g("angle", 12.0))
        elif op == "overlay":
            v.update(ov=g("asset", NONE), ov_place=g("place", "ball"), ov_blend=g("blend", "screen"),
                     ov_opacity=g("opacity", 0.9), ov_size=g("size", 1.0),
                     ov_depth=FRONT if g("layer", "background") == "all" else BEHIND)
        elif op == "light_leak":
            v.update(leak_on=True, leak_color=g("color", v["leak_color"]), leak_corner=g("corner", "top_right"),
                     leak_amount=g("amount", 0.5))
        elif op == "glow":
            v.update(glow_on=True, glow_amount=g("amount", 0.35))
        elif op == "specular_bloom":
            v.update(bloom_on=True, bloom_amount=g("amount", 0.5), bloom_threshold=g("threshold", 0.8),
                     bloom_size=g("size", 0.02))
        elif op == "spotlight":
            v.update(spot_on=True, spot_amount=g("amount", 0.3))
        elif op == "edge_distress":
            v.update(edge_on=True, edge_amount=g("amount", 0.5))
        elif op == "grain":
            v.update(grain_on=True, grain_amount=g("amount", 0.2))
        elif op == "vignette":
            v.update(vig_on=True, vig_amount=g("amount", 0.35))
    if v["sep_on"]:
        v.update(sep)
    for n, st in zip(("t1", "t2"), textures):
        v.update({n: st.get("asset", NONE), f"{n}_blend": st.get("blend", "overlay"), f"{n}_opacity": st.get("opacity", 0.4)})
    return v


def components(ids: dict) -> dict:
    """Builds the form inside the current Gradio layout; returns name -> component.

    The settings are in tabs, each with a short explanation, and an effect's
    settings only show once it is turned on, so the form stays calm."""
    d = DEFAULTS
    c = {}

    def slider(name, lo, hi, label, step=0.05, info=None):
        c[name] = gr.Slider(lo, hi, d[name], step=step, label=label, info=info)

    def check(name, label, info=None):
        c[name] = gr.Checkbox(d[name], label=label, info=info)

    def color(name, label, info=None):
        c[name] = gr.ColorPicker(d[name], label=label, info=info)

    def drop(name, choices, label, info=None):
        c[name] = gr.Dropdown(choices, value=d[name], label=label, info=info)

    def hint(text):
        gr.Markdown(text, elem_classes="hint")

    @contextmanager
    def when(trigger, show=bool):
        """Settings that show only while their switch is on."""
        with gr.Group(visible=show(d[trigger]), elem_classes="reveal") as group:
            yield
        c[trigger].change(lambda v: gr.update(visible=show(v)), c[trigger], group,
                          show_progress="hidden", queue=False)

    with gr.Tabs():
        with gr.Tab("Color"):
            hint("The overall color of the photo. Start here: pick one color look, then fine-tune contrast "
                 "and saturation.")
            with gr.Row():
                check("protect", "Keep faces clean", "Textures and effects never cover the players' faces.")
                check("clean_on", "Start from the clean pro edit",
                      "Balances brightness and color first (the photo-crops edit).")
            slider("skin_protect", 0, 1, "Skin tone protection",
                   info="Keeps skin its natural color under color looks. 0 = off, 1 = full.")
            c["color_kind"] = gr.Radio(COLOR_KINDS, value=d["color_kind"], label="Color look",
                                       info="One main color treatment. Its settings appear below.")
            with when("color_kind", lambda v: v == "LUT"):
                drop("lut", [NONE] + ids["lut"], "LUT", "A ready-made color grade from your asset library.")
                slider("lut_strength", 0, 1, "Strength")
            with when("color_kind", lambda v: v == "Neon"):
                with gr.Row():
                    color("neon_dark", "Shadow color")
                    color("neon_light", "Highlight color")
                slider("neon_amount", 0, 1, "Amount")
            with when("color_kind", lambda v: v == "B&W"):
                hint("How bright each color turns in black and white. More blue keeps sunny grass from "
                     "going white.")
                with gr.Row():
                    slider("bw_r", 0, 1, "Reds")
                    slider("bw_g", 0, 1, "Greens")
                    slider("bw_b", 0, 1, "Blues")
                slider("bw_contrast", 0.5, 2.5, "Contrast", info="1 = as shot; higher is punchier.")
            with when("color_kind", lambda v: v == "Duotone"):
                with gr.Row():
                    color("duo_dark", "Dark color")
                    color("duo_light", "Light color")
            with gr.Row():
                slider("contrast", 0, 1, "Extra contrast", info="Deeper shadows and brighter highlights.")
                slider("saturation", 0, 2, "Saturation", info="1 = as shot, 0 = gray, 2 = very vivid.")
            check("split_on", "Split toning", "Tints the shadows one color and the highlights another "
                  "(for example cool shadows, warm highlights).")
            with when("split_on"):
                with gr.Row():
                    color("split_shadows", "Shadow tone")
                    color("split_highlights", "Highlight tone")
                slider("split_amount", 0, 1, "Amount")
                slider("split_balance", -1, 1, "Balance", info="Left favors the shadow tone, right the highlights.")
                slider("split_blacks", 0, 1, "Soften blacks", info="Lifts the darkest tones for a matte, film look.")
            check("hk_on", "High key", "Bright and airy: pale areas go clean white, blacks stay deep. "
                  "Adjusts itself to how bright the photo already is.")
            with when("hk_on"):
                slider("hk_amount", 0, 1, "Amount")

        with gr.Tab("Player & background"):
            hint("Edit the player and the background separately, like a pro retoucher. The player is cut "
                 "out automatically (hair, limbs and the ball included).")
            check("sep_on", "Edit the player and the background separately")
            with when("sep_on"):
                gr.Markdown("**Player**")
                with gr.Row():
                    slider("subj_exposure", -1, 1, "Brightness (stops)", info="+1 doubles the light.")
                    slider("subj_clarity", 0, 1, "Clarity", info="Crisper jersey, hair and skin texture.")
                    slider("subj_saturation", 0, 2, "Color", info="1 = as shot.")
                gr.Markdown("**Background**")
                with gr.Row():
                    slider("bg_exposure", -2, 1, "Brightness (stops)", info="Negative darkens, e.g. -2 for night.")
                    slider("bg_blur", 0, 0.03, "Blur", step=0.001, info="Depth of field, like a fast lens.")
                    slider("bg_saturation", 0, 1.5, "Color", info="1 = as shot, 0 = gray.")
                with gr.Row():
                    check("bg_bw", "Black-and-white background", "Color pop: only the player keeps color.")
                    slider("bg_high_key", 0, 1, "Brighten to white", info="High key on the background only.")
                check("bd_on", "Studio backdrop", "Replaces the background with a smooth studio gradient.")
                with when("bd_on"):
                    with gr.Row():
                        color("bd_top", "Top color")
                        color("bd_bottom", "Bottom color")
                    slider("bd_glow", 0, 1, "Light behind the player")

        with gr.Tab("Detail"):
            hint("Sharpness and shine. A little goes a long way.")
            check("clarity_on", "Athletic clarity", "Micro-contrast that brings out jersey fabric, sweat and turf.")
            with when("clarity_on"):
                with gr.Row():
                    slider("clarity_amount", 0, 1, "Amount")
                    slider("clarity_radius", 0.001, 0.015, "Detail size", step=0.001,
                           info="Small = fine texture, large = bolder shapes.")
            check("hp_on", "High-pass detail", "A harder, gritty sharpening for dramatic looks.")
            with when("hp_on"):
                slider("hp_amount", 0, 1, "Amount")
            check("bloom_on", "Specular bloom", "A soft glow around the brightest highlights.")
            with when("bloom_on"):
                with gr.Row():
                    slider("bloom_amount", 0, 1, "Amount")
                    slider("bloom_threshold", 0.5, 0.98, "Starts at brightness", step=0.01,
                           info="Higher = only the very brightest spots glow.")
                    slider("bloom_size", 0.005, 0.06, "Size", step=0.005)

        with gr.Tab("Atmosphere"):
            hint("Smoke, haze, lights and rain. They all sit behind the player, so the player stays clear.")
            check("sm_on", "Smoke clouds", "Billowing smoke shaped around the player.")
            with when("sm_on"):
                with gr.Row():
                    drop("sm_place", [(SMOKE_LABELS[k], k) for k in SMOKE_PLACES], "Where")
                    color("sm_color", "Smoke color")
                check("sm_two", "Two colors", "Left and right clouds in different colors, like team colors.")
                with when("sm_two"):
                    color("sm_color2", "Right cloud color")
                with gr.Row():
                    slider("sm_amount", 0, 1, "Thickness")
                    slider("sm_size", 0.4, 2, "Size", info="Relative to the player's height.")
                    slider("sm_front", 0, 1, "Over the feet", info="How much floor smoke rolls in front of the feet.")
            check("st_on", "Stadium floodlights", "Two banks of stadium lights near the left and right edges.")
            with when("st_on"):
                with gr.Row():
                    slider("st_height", 0.3, 1.2, "Height", info="Share of the player's height above their feet.")
                    slider("st_amount", 0, 1, "Brightness")
                    color("st_color", "Light color")
            check("lights_on", "Studio lights along the top", "Bright lamps above the player.")
            with when("lights_on"):
                with gr.Row():
                    slider("lights_count", 1, 4, "Number of lights", step=1)
                    slider("lights_amount", 0, 1, "Brightness")
            check("fog_on", "Fog / stadium haze", "A soft haze rising from the ground behind the player.")
            with when("fog_on"):
                with gr.Row():
                    slider("fog_density", 0, 1, "Density")
                    slider("fog_height", 0.1, 1, "Reaches up", info="Share of the photo's height.")
                    color("fog_color", "Color")
            check("rain_on", "Rain", "Falling rain behind the player.")
            with when("rain_on"):
                with gr.Row():
                    slider("rain_amount", 0, 1, "Amount")
                    slider("rain_angle", -40, 40, "Angle", step=1, info="Degrees from straight down.")

        with gr.Tab("Pop art"):
            hint("Turn the player into a neon pop-art painting, with paint splattered around them.")
            check("pa_on", "Neon pop-art painting", "The player in neon paint (indigo, cyan, pink, orange, "
                  "yellow-green) with painted lines and a glowing outline.")
            with when("pa_on"):
                check("pa_crisp", "Sharp, screen-print edges", "Hard-edged paint shapes, thin ink and bright etched "
                      "lines, and a thin outline, at full resolution. Off: softer, blended paint with a wide glow.")
                with gr.Row():
                    slider("pa_levels", 3, 12, "Paint bands", step=1, info="Fewer = bolder, poster-like areas.")
                    slider("pa_mottle", 0, 0.8, "Brush mottling", info="How patchy the colors are.")
                    slider("pa_shading", 0, 1, "Shading", info="Keeps faces and folds readable.")
                with gr.Row():
                    slider("pa_lines", 0, 1, "Painted lines")
                    slider("pa_glow", 0, 1, "Outline glow")
                    color("pa_outline", "Line and glow color")
                with gr.Row():
                    color("pa_bg", "Background tone", "The background turns a dark shade of this.")
                    slider("pa_bg_amount", 0, 1, "Background tone amount")
            check("nl_on", "Neon line art", "The player as glowing neon lines on a dark body, on black.")
            with when("nl_on"):
                with gr.Row():
                    slider("nl_darkness", 0, 1, "Body darkness")
                    slider("nl_lines", 0, 1, "Lines")
                    slider("nl_detail", 0, 1, "Fine detail lines")
                with gr.Row():
                    slider("nl_rim", 0, 1, "Rim light")
                    slider("nl_glow", 0, 1, "Glow")
            check("pb_on", "Paint explosion", "A big burst of neon paint behind the player.")
            with when("pb_on"):
                with gr.Row():
                    slider("pb_amount", 0, 1, "Amount")
                    slider("pb_size", 0.4, 2, "Size")
                    slider("pb_direction", -180, 180, "Trails toward (degrees)", step=5, info="0 = right, 90 = down.")
                with gr.Row():
                    slider("pb_splash", 0, 1, "Solid paint", info="Lower: lighter, smaller splashes.")
                    slider("pb_lines", 0, 1, "Streak lines", info="Fine lines flying out, ending in drops.")
                    slider("pb_specks", 0, 1, "Specks", info="Tiny drops scattered across the dark.")
            check("dr_on", "Ice cream drip", "Glossy melting ice cream running down from the top, behind the player.")
            with when("dr_on"):
                c["dr_colors"] = gr.Textbox(DEFAULTS["dr_colors"], label="Flavors (colors, back to front)",
                                            info="Comma-separated colors, e.g. vanilla, strawberry, mint, chocolate.")
                with gr.Row():
                    slider("dr_amount", 0, 1, "Drips")
                    slider("dr_length", 0.3, 2, "Drip length")
                    slider("dr_gloss", 0, 1, "Shine")
                    slider("dr_front", 0, 1, "Over the player", info="0 keeps the player (and faces) clear.")
            check("ps_on", "Paint splatter and strokes", "Splashes, droplets and swooping strokes around the player.")
            with when("ps_on"):
                with gr.Row():
                    slider("ps_amount", 0, 1, "Splatter")
                    slider("ps_strokes", 0, 1, "Brush strokes")
                    slider("ps_front", 0, 1, "Over the player", info="How much paint lands over the player's edges.")
                    slider("ps_whips", 0, 1, "Whip lines", info="Fast flicks flying outward from the player.")

        with gr.Tab("Overlays"):
            hint("Effects and textures from your asset library (see the Assets tab).")
            drop("ov", [NONE] + ids["overlay"], "Impact overlay", "An effect such as sparks, dust or fire.")
            with when("ov", lambda v: bool(v) and v != NONE):
                c["ov_depth"] = gr.Radio([BEHIND, FRONT], value=d["ov_depth"], label="Layer")
                with gr.Row():
                    drop("ov_place", [(PLACE_LABELS[k], k) for k in PLACES], "Place on")
                    drop("ov_blend", BLENDS, "Blend", "How it mixes with the photo; screen suits bright effects.")
                with gr.Row():
                    slider("ov_opacity", 0, 1, "Opacity")
                    slider("ov_size", 0.2, 2.5, "Size", info="Times the player's height.")
            drop("t1", [NONE] + ids["texture"], "Texture 1", "A surface such as paper, grit or film dust.")
            with when("t1", lambda v: bool(v) and v != NONE):
                with gr.Row():
                    drop("t1_blend", BLENDS, "Blend")
                    slider("t1_opacity", 0, 1, "Opacity")
            drop("t2", [NONE] + ids["texture"], "Texture 2")
            with when("t2", lambda v: bool(v) and v != NONE):
                with gr.Row():
                    drop("t2_blend", BLENDS, "Blend")
                    slider("t2_opacity", 0, 1, "Opacity")

        with gr.Tab("Finishing"):
            hint("Final touches that guide the eye to the player.")
            check("sv_on", "Vignette around the player", "Darkens outward from the player's own outline.")
            with when("sv_on"):
                with gr.Row():
                    slider("sv_amount", 0, 1, "Amount")
                    slider("sv_spread", 0.05, 0.6, "How far out it builds")
            check("vig_on", "Vignette", "Darkens the corners of the frame.")
            with when("vig_on"):
                slider("vig_amount", 0, 1, "Amount")
            check("spot_on", "Spotlight on the player", "A soft pool of light on the player.")
            with when("spot_on"):
                slider("spot_amount", 0, 1, "Amount")
            check("grain_on", "Film grain", "Fine film-like grain.")
            with when("grain_on"):
                slider("grain_amount", 0, 1, "Amount")
            check("glow_on", "Glow", "A dreamy glow over the bright areas.")
            with when("glow_on"):
                slider("glow_amount", 0, 1, "Amount")
            check("leak_on", "Light leak", "A warm burst of light from a corner, like old film.")
            with when("leak_on"):
                with gr.Row():
                    color("leak_color", "Color")
                    drop("leak_corner", [(k.replace("_", " ").capitalize(), k) for k in CORNERS], "From")
                slider("leak_amount", 0, 1, "Amount")
            check("edge_on", "Edge distressing", "Rough, worn edges for gritty looks.")
            with when("edge_on"):
                slider("edge_amount", 0, 1, "Amount")
    return c
