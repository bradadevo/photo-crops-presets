"""The preset manager's form: its fields, and turning them into a recipe and back.

The form covers every built-in step; the recipe text in the app stays the
source of truth for anything else (plugins, extra steps).
"""

import gradio as gr

from photo_presets import blend

NONE = "None"
PLACES = ["ball", "feet", "center", "random"]
CORNERS = ["top_left", "top_right", "bottom_left", "bottom_right"]
BLENDS = list(blend.MODES)
BEHIND, FRONT = "Behind the player (depth)", "In front of everything"
COLOR_KINDS = [NONE, "LUT", "Neon", "B&W", "Duotone"]

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
    "rain_on": False, "rain_amount": 0.5, "rain_angle": 12.0,
    "ov": NONE, "ov_place": "ball", "ov_blend": "screen", "ov_opacity": 0.9, "ov_size": 1.0, "ov_depth": BEHIND,
    "leak_on": False, "leak_color": "#ff7a1a", "leak_corner": "top_right", "leak_amount": 0.5,
    "glow_on": False, "glow_amount": 0.35,
    "bloom_on": False, "bloom_amount": 0.5, "bloom_threshold": 0.8, "bloom_size": 0.02,
    "spot_on": False, "spot_amount": 0.3,
    "edge_on": False, "edge_amount": 0.5,
    "grain_on": False, "grain_amount": 0.2,
    "vig_on": True, "vig_amount": 0.35,
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
    for n in ("t1", "t2"):
        if v[n] and v[n] != NONE:
            s.append({"op": "texture", "asset": v[n], "blend": v[f"{n}_blend"], "opacity": v[f"{n}_opacity"]})
    if v["fog_on"]:
        s.append({"op": "fog", "density": v["fog_density"], "height": v["fog_height"], "color": v["fog_color"]})
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
    """Builds the form inside the current Gradio layout; returns name -> component."""
    d = DEFAULTS
    c = {}

    def slider(name, lo, hi, label, step=0.05):
        c[name] = gr.Slider(lo, hi, d[name], step=step, label=label)

    def check(name, label):
        c[name] = gr.Checkbox(d[name], label=label)

    def color(name, label):
        c[name] = gr.ColorPicker(d[name], label=label)

    def drop(name, choices, label):
        c[name] = gr.Dropdown(choices, value=d[name], label=label)

    with gr.Row():
        with gr.Column(min_width=300):
            gr.Markdown("### Color")
            check("protect", "Keep faces clean of textures and effects")
            slider("skin_protect", 0, 1, "Skin tone protection (keeps skin its own color under LUTs and toning)")
            check("clean_on", "Start with the clean pro edit (photo-crops)")
            c["color_kind"] = gr.Radio(COLOR_KINDS, value=d["color_kind"], label="Color look")
            drop("lut", [NONE] + ids["lut"], "LUT")
            slider("lut_strength", 0, 1, "LUT strength")
            with gr.Row():
                color("neon_dark", "Neon shadows")
                color("neon_light", "Neon highlights")
            slider("neon_amount", 0, 1, "Neon amount")
            with gr.Row():
                slider("bw_r", 0, 1, "B&W red")
                slider("bw_g", 0, 1, "B&W green")
                slider("bw_b", 0, 1, "B&W blue")
            slider("bw_contrast", 0.5, 2.5, "B&W contrast")
            with gr.Row():
                color("duo_dark", "Duotone dark")
                color("duo_light", "Duotone light")
            gr.Markdown("### Split toning")
            check("split_on", "Cool shadows, warm highlights")
            with gr.Row():
                color("split_shadows", "Shadow tone")
                color("split_highlights", "Highlight tone")
            slider("split_amount", 0, 1, "Amount")
            slider("split_balance", -1, 1, "Balance (shadows ← → highlights)")
            slider("split_blacks", 0, 1, "Compress blacks")
            slider("contrast", 0, 1, "Extra contrast")
            slider("saturation", 0, 2, "Color saturation")
            check("hk_on", "High key (bright and airy, white skies, deep blacks)")
            slider("hk_amount", 0, 1, "High key amount")
        with gr.Column(min_width=300):
            gr.Markdown("### Player and background (subject isolation)")
            check("sep_on", "Edit the player and the background separately")
            slider("subj_exposure", -1, 1, "Player brightness (stops)")
            slider("subj_clarity", 0, 1, "Player clarity")
            slider("subj_saturation", 0, 2, "Player color")
            slider("bg_exposure", -2, 1, "Background brightness (stops)")
            slider("bg_blur", 0, 0.03, "Background blur (depth of field)", step=0.001)
            slider("bg_saturation", 0, 1.5, "Background color")
            check("bg_bw", "Black-and-white background (color pop)")
            slider("bg_high_key", 0, 1, "Background high key")
            check("bd_on", "Studio backdrop instead of the background")
            with gr.Row():
                color("bd_top", "Backdrop top")
                color("bd_bottom", "Backdrop bottom")
            slider("bd_glow", 0, 1, "Backdrop light")
            gr.Markdown("### Athletic clarity and bloom")
            check("clarity_on", "Athletic clarity (micro-contrast: jersey, sweat, turf)")
            slider("clarity_amount", 0, 1, "Clarity amount")
            slider("clarity_radius", 0.001, 0.015, "Clarity size", step=0.001)
            check("hp_on", "High-pass detail")
            slider("hp_amount", 0, 1, "High-pass amount")
            check("bloom_on", "Specular bloom (soft glow on the brightest highlights)")
            slider("bloom_amount", 0, 1, "Bloom amount")
            slider("bloom_threshold", 0.5, 0.98, "Bloom starts at brightness", step=0.01)
            slider("bloom_size", 0.005, 0.06, "Bloom size", step=0.005)
        with gr.Column(min_width=300):
            gr.Markdown("### Depth: fog, rain and overlays")
            check("fog_on", "Fog / stadium haze (behind the player)")
            with gr.Row():
                slider("fog_density", 0, 1, "Density")
                slider("fog_height", 0.1, 1, "Reaches up")
            color("fog_color", "Fog color")
            check("rain_on", "Rain (behind the player)")
            with gr.Row():
                slider("rain_amount", 0, 1, "Amount")
                slider("rain_angle", -40, 40, "Angle", step=1)
            drop("ov", [NONE] + ids["overlay"], "Impact overlay")
            c["ov_depth"] = gr.Radio([BEHIND, FRONT], value=d["ov_depth"], label="Overlay layer")
            with gr.Row():
                drop("ov_place", PLACES, "Place on")
                drop("ov_blend", BLENDS, "Blend")
            with gr.Row():
                slider("ov_opacity", 0, 1, "Opacity")
                slider("ov_size", 0.2, 2.5, "Size (x player height)")
            gr.Markdown("### Textures")
            drop("t1", [NONE] + ids["texture"], "Texture 1")
            with gr.Row():
                drop("t1_blend", BLENDS, "Blend")
                slider("t1_opacity", 0, 1, "Opacity")
            drop("t2", [NONE] + ids["texture"], "Texture 2")
            with gr.Row():
                drop("t2_blend", BLENDS, "Blend")
                slider("t2_opacity", 0, 1, "Opacity")
        with gr.Column(min_width=300):
            gr.Markdown("### Lighting and edges")
            check("leak_on", "Light leak")
            with gr.Row():
                color("leak_color", "Color")
                drop("leak_corner", CORNERS, "From")
            slider("leak_amount", 0, 1, "Amount")
            check("glow_on", "Glow")
            slider("glow_amount", 0, 1, "Amount")
            check("spot_on", "Spotlight on the player")
            slider("spot_amount", 0, 1, "Amount")
            check("edge_on", "Edge distressing")
            slider("edge_amount", 0, 1, "Amount")
            check("grain_on", "Film grain")
            slider("grain_amount", 0, 1, "Amount")
            check("vig_on", "Vignette")
            slider("vig_amount", 0, 1, "Amount")
    return c
