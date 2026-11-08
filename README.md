# Photo Crops Presets

Everything in [photo-crops](https://github.com/bradadevo/photo-crops)
(professional crops, face close-ups, screenshots rebuilt from the camera
files), plus **Photo Presets**: a creative looks engine for sports photos
with a Gradio app.

- **Random exploration**: drop in photos and get a gallery of different,
  outside-the-box looks, each mixing one of your LUTs (or a neon split-tone,
  B&W channel mix or duotone) with textures, blend modes, impact overlays,
  lighting and edge effects.
- **Preset pipeline**: save looks as named presets (like "Grit & Glory") and
  run photos straight through them.

Premium tools: the player cut out from the background (each edited on its
own), athletic clarity, specular bloom, skin-tone protection, split toning,
and fog, rain and smoke layered behind the player for real depth.

Faces are kept clean of textures and effects, originals are never changed,
and everything runs free on your Mac: no AI service, no cost.

This repo started as a copy of photo-crops and is self-contained; the two
change separately.

## Setup

```bash
uv sync
```

The first run downloads two free models (about 250 MB, once) to
`~/.cache/photo-crops`, and the player cut-out model BiRefNet (about 970 MB,
once) to `~/.rembg` the first time a look separates player and background
(already there if you use ai-versions). Video overlays need ffmpeg
(`brew install ffmpeg`).

## Photo Presets app

```bash
uv run photo-presets
```

It opens in your browser on this Mac.

**Make looks**

1. Add photos (any mix, including RAW and HEIC), or type a folder or press
   **Choose…**.
2. Pick **Random exploration** (how many looks per photo, and an optional seed
   so the same seed gives the same looks again) or **Preset pipeline** (pick a
   preset).
3. **Crop first**: the whole photo, a photo-crops pro crop, or a face close-up.
4. **Make looks**. Click any result to compare it with the original on the
   before/after slider. Its recipe is shown; give it a name and **Save preset**
   to keep any look you like.
5. **Export full size** saves every result (or just the selected one) at full
   resolution to your export folder (default `~/Pictures/Photo Presets`), each
   with its recipe beside it as `.json`. **Open folder** shows them in Finder.

Results are made at 1600 px for speed; export renders each again from the
full-size photo.

**Preset manager**: load, edit, preview, save and delete presets. The form
has toggles and sliders for:

- **Color**: LUT and strength, neon, B&W channel mix, duotone, the clean pro
  edit, skin tone protection, saturation, high key, and **split toning** (shadow and highlight
  tones, amount, balance, compressed blacks), extra contrast
- **Player and background**: edit them separately: player brightness,
  clarity and color; background brightness, blur (depth of field), color,
  black and white (color pop), high key, or a studio backdrop instead
- **Athletic clarity and bloom**: micro-contrast amount and size, high-pass
  detail, specular bloom amount, starting brightness and size
- **Depth**: fog or stadium haze, rain, and an impact overlay, each behind the
  player (or in front of everything)
- **Textures**: two, each with its own blend mode and opacity
- **Lighting and edges**: light leak, glow, spotlight, edge distressing, film
  grain, vignette

The recipe underneath can be edited directly for anything the form does not
show; it is what gets saved.

**Assets**: what was found, and where to look (folders and zip packs).

### Command line

```bash
uv run photo-presets-batch --list
uv run photo-presets-batch ~/Movies/"Game day" --random 6 --crop crop
uv run photo-presets-batch ~/Movies/"Game day" --preset "Grit & Glory" --out ~/Pictures/Grit
```

## Starter presets

| Preset | What it does |
|---|---|
| Grit & Glory | High-contrast B&W channel mix, high-pass detail, smoke at the player's feet, generated grit, distressed edges, vignette |
| Friday Night Lights | Your Friday Night Lights LUT, spotlight on the player, glow, grain, vignette |
| Neon Rush | Neon split-tone, high-pass detail, specular bloom, glow |
| Hall of Famer | Your Hall of Famer LUT, paper texture, grain, vignette |
| Stadium Night | Cool shadows and warm highlights, darker blurred background with haze behind the player, the player brighter and crisper, specular bloom |
| Rain Game | Cool split toning, a muted darker background with rain falling behind the player, a crisper player |
| Clean Pro | photo-crops' light clean edit |

**Editorial looks** (clean, no textures, after pro academy and MLS NEXT photography):

| Preset | What it does |
|---|---|
| Color Pop | The player in color against a bright, hazy black-and-white background |
| Studio Backdrop | The background replaced by a blue-to-black studio gradient lit from above the player |
| Shallow Focus | Strong background blur (depth of field), crisp player, rich color, vignette |
| Bright & Airy | High key: lifted, airy tones, a softer background, a vivid player |
| Mono Editorial | Clean high-key black and white |
| Vivid Pro | Punchy, saturated color, slightly bright, crisp player |
| Silver Mono | Soft silver black and white with a blurred background |
| Punch Mono | Hard, gritty, high-contrast black and white |
| Dark Mono | Black and white with the background dropped to near black |
| Muted Portrait | Soft, muted color with matte lifted blacks, a darker blurred background |
| Night Portrait | Rich color, the player lit against a dark blurred background |

The black-and-white looks lean on blue in their mix (like a red filter on
film) so sunlit grass stays gray instead of going white.

Saving a preset with a starter's name replaces it for you; deleting yours
brings the starter back. Presets live in `~/.config/photo-crops-presets/presets.json`.

## Assets

Found automatically (change them on the Assets tab):

| Kind | Default sources |
|---|---|
| LUTs (`.cube`) | Final Cut's Custom LUTs folder, and `~/Movies/Ultimate+Sports+Editing+Bundle.zip` |
| Textures | `~/Movies/Textures.zip` (marker and paper), plus generated grit, grain, scratches, smoke, paper and dust |
| Overlays | `~/Movies/Sports_Impact_Essentials.zip` (smoke, dust, debris, sparks, fire, lightning, glitch, fireworks, water, cartoon; confetti and electricity are left out) |

Zip packs are never unpacked whole: only the files a look uses are taken out
and cached in `~/.cache/photo-crops-presets/assets`. Overlay packs made of
transparent ProRes clips are turned into a still from each clip's strongest
frame (the most visible effect).

## How a look works

A look is a recipe: a list of steps, run in order.

```json
{"protect_faces": true,
 "steps": [
  {"op": "bw", "red": 0.6, "green": 0.3, "blue": 0.1, "contrast": 1.5},
  {"op": "overlay", "asset": "overlay:Smoke", "place": "feet", "blend": "normal", "opacity": 0.85, "size": 1.4},
  {"op": "texture", "asset": "generated:grit", "blend": "overlay", "opacity": 0.45}
 ]}
```

| Step | Settings |
|---|---|
| `lut` | `asset` (`lut:<name>`), `strength`, `guard_shadows` (keeps dark skin and kits from being crushed) |
| `neon` | `shadows`, `highlights` (colors), `amount`, `saturation` |
| `bw` | `red`, `green`, `blue` (channel mix), `contrast`, `tint` |
| `duotone` | `dark`, `light`, `amount` |
| `contrast`, `saturation` | `amount` |
| `clean` | `strength` (`light` or `full`): photo-crops' clean pro edit |
| `high_pass` | `radius` (share of the long edge), `amount`, `blend` |
| `texture` | `asset` (`texture:<name>` or `generated:<kind>`), `blend`, `opacity` |
| `overlay` | `asset` (`overlay:<name>`), `place` (`ball`, `feet`, `center`, `random`), `blend`, `opacity`, `size` (x the player's height) |
| `light_leak` | `color`, `corner`, `amount` |
| `glow` | `amount`, `threshold` |
| `spotlight`, `vignette`, `grain` | `amount` |
| `edge_distress` | `amount`, `color` |
| `athletic_clarity` | `amount`, `radius` (share of the long edge), `fine` (fine vs medium detail) |
| `specular_bloom` | `amount`, `threshold`, `size` |
| `split_tone` | `shadows`, `highlights` (colors), `amount`, `balance`, `compress_blacks` |
| `exposure` | `stops` |
| `lens_blur` | `radius` (background by default) |
| `fog` | `color`, `density`, `height` (background by default) |
| `rain` | `amount`, `angle` (background by default) |
| `high_key` | `amount`: bright and airy; adapts to the photo (a sunny photo is lifted less) and only pale, colorless areas like an overcast sky go white |
| `backdrop` | `top`, `bottom` (colors), `glow`, `amount`: a studio gradient instead of the background (needs the player cut-out) |

Any step can also take `"layer"`: `"all"` (the whole photo), `"subject"`
(the players only) or `"background"` (everything behind them). Overlays, fog,
rain and lens blur default to the background. A recipe can also set
`"skin_protect"` (0-1, default 0.7).

Blend modes: normal, multiply, screen, overlay, soft light, hard light, color
dodge, color burn, linear dodge, difference, lighten, darken.

**Player and background (subject isolation)**: the players in the play are
cut out with BiRefNet, an open-source subject segmentation model, run on your
Mac through rembg (it traces hair and limbs precisely). photo-crops' YOLO
outlines decide which traced pieces are the players in the play, so
background people, poles and signs stay in the background; the ball joins
the players. Steps on the `subject` layer change only the players, steps on
the `background` layer only what is behind them. The cut-out is made only
when a look needs it.

**Depth (Z-sandwiching)**: fog, stadium smoke, rain and impact overlays go on
the background layer by default, so they sit behind the players but in front
of the field: a 3D look in a 2D photo. The background blur leaves the
players' own colors out, so bright kits do not smear into a halo.

**Athletic clarity** is frequency separation on brightness: fine detail
(jersey weave, sweat, turf) and medium detail are boosted, limited on strong
edges so there are no halos, and weighted to the midtones so blacks and
whites do not move.

**Specular bloom** glows only small, near-white highlights (sun on skin,
sweat, shiny kit) with a soft three-layer halo, added with screen and rolled
off at the top so nothing blows out. Pale colored kits and big bright areas
(a sunlit white-striped shirt) are left out, so the player gets no halo.

**Skin tone protection**: skin is found by the human skin-tone vector (in
YCrCb color space, covering all skin colors) inside people's outlines. Color
looks (LUTs, neon, duotone, split toning) leave skin its own color while it
still takes the look's brightness.

**Split toning** pushes rich cool tones into slightly lifted, compressed blacks
and warm tones into the highlights, in Lab color so brightness is kept.

**Keeping faces clean**: heads are found with photo-crops' pose model;
textures, overlays, high-pass, grain, glow, light leaks and edge wear fade away
from them. Color looks (LUT, B&W, neon, duotone) apply to the whole photo.

**Placing overlays**: the ball and the main player are found with photo-crops'
models and subject rules (goalie first, then your team, then whoever is in
focus), so smoke lands at the player's feet and sparks around the ball.

**Random looks** come from a seed: one color look, then a random mix of
split toning, contrast, athletic clarity, player/background separation
(darker or blurred background, crisper player), fog or rain behind the
player, high-pass, up to two textures with random blend modes, maybe an
impact overlay, light leak, glow or bloom, spotlight, grain, distressed edges
and a vignette.

### Adding your own steps

Put a Python file in `~/.config/photo-crops-presets/plugins/`; every `.py`
there is loaded at start. Register a step with the `op` decorator:

```python
from photo_presets.pipeline import op

@op("invert", protect=True, label="Invert", amount=1.0)
def invert(image, params, ctx):        # image: floats (H, W, 3) in 0-1
    return image + (1 - 2 * image) * params["amount"]
```

It can then be used in any recipe as `{"op": "invert", "amount": 0.5}`.

## photo-crops (included)

```bash
uv run photo-crops-ui                # the crop questionnaire
uv run photo-crops ~/Movies/"Game day"
```

Pro crops, face close-ups and rebuilt screenshots, exactly as in the
[photo-crops README](https://github.com/bradadevo/photo-crops#readme).

## Development

```bash
uv run pytest
```

The tests never load the large models.

```text
photo_crops/          photo-crops (see its README)
photo_presets/
  app.py              The Gradio app
  cli.py              photo-presets-batch
  engine.py           Random and preset modes, previews, full-size export
  pipeline.py         Running recipes, the step registry, plugins, keeping faces clean
  effects.py          The built-in steps
  blend.py            Blend modes
  luts.py             .cube LUTs (from match-cull)
  procedural.py       Generated textures
  assets.py           Finding, fetching and caching LUTs, textures and overlays
  scene.py            Faces, ball, feet, outlines and the player cut-out; crop first
  presetform.py       The preset manager's form, to and from recipes
  explore.py          Random looks
  presets.py          Saved and starter presets
tests/
```
