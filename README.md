# AllProPhoto

Everything in [photo-crops](https://github.com/bradadevo/photo-crops)
(professional crops, face close-ups, screenshots rebuilt from the camera
files), plus **AllProPhoto**: a creative looks engine for sports photos
with a Gradio app.

- **Random exploration**: drop in photos and get a gallery of different,
  outside-the-box looks, each mixing one of your LUTs (or a neon split-tone,
  B&W channel mix or duotone) with textures, blend modes, impact overlays,
  lighting and edge effects.
- **Preset pipeline**: save looks as named presets (like "Grit & Glory") and
  run photos straight through them. 47 starter presets come built in, in
  groups, each with a one-line description; tick any or all of them,
  including 20 illustration looks (watercolor, anime, oil, comic, pencil)
  drawn by a free AI model on this Mac.
- **Instagram reels**: turn the looks into a vertical video under a minute
  (2 seconds per photo, cuts on your song's beat), ready to post.

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
(already there if you use ai-versions). The illustration looks download
their drawing models (about 5 GB, once) to `~/.cache/huggingface` the first
time one is used. Reels and video overlays need ffmpeg
(`brew install ffmpeg`).

## The AllProPhoto app

```bash
uv run allprophoto
```

It opens in your browser on this Mac. (`uv run photo-presets` still works too.)

**Make looks** walks you through six numbered steps (left: set up, right:
results). It suits both ways of working:

- **One photo**: tick as many looks as you like, compare them, fine-tune the
  best one, export it.
- **A batch (a whole game)**: try looks on one good photo first, then press
  **Use the selected look on all N photos**; fine-tune once and use the
  settings on every photo with that look; export them all and make a reel.

1. **Add photos** (any mix, including RAW and HEIC): paste a copied image with
   **⌘V** (a screenshot, or a photo copied from Photos, a browser or Finder;
   each paste adds to the list), drag photos in, click to browse, or type a
   folder or press **Browse…**. On Preset manager, ⌘V puts the image in the
   sample photo box. It says how many photos you added, and with more than one
   suggests trying looks on one photo first.
2. **Choose looks**: **Use presets** lists every preset in groups (Bold and
   dramatic, Clean editorial, Studio smoke and lights, Watercolor, Anime, Oil
   painting, Comic book, Pencil and ink, My presets), each with a
   one-line description and about how long it takes per photo (⏱). Tick
   any, or **Select all**; every photo goes through each one, and it shows how
   many looks that makes and about how long the run takes. The times were
   measured on this Mac and keep learning from your own runs (in
   `~/.config/photo-crops-presets/timings.json`). **Explore random looks** invents new looks instead (how many per
   photo, and an optional seed to repeat a run).
3. **Make looks on** (with more than one photo): **Try looks on one photo
   first** (pick which) or **All photos**. **Crop first**, then **Make looks**:
   - **Whole photo**: as shot.
   - **Pro crop: no zoom (keeps the scene)**: the photo's own shape, at
     least 90% of its width and height, moved so the players sit on a
     rule-of-thirds point (their upper body toward the upper third), never
     cutting them; a photo already well composed stays whole.
   - **Pro crop: zoomed in on the action**: the photo-crops pro crop, framed
     tightly around the players in the play (often a third of the photo).
   - **Face close-up**: head and shoulders.

   While the looks are made, a small **Making looks** card floats in the
   corner of the screen (no scrolling needed): a tile for every look, waiting,
   being made with its %, or done with its picture and how long it took; how
   many are done and about how long is left. The results open in step 4 when
   all are done. With many photos, results are grouped look by look.
4. **Compare, fine-tune and export**: every result is a picture with a ✓ in
   its corner. Tick ✓ the good ones (leave the bad ones out) and press
   **Export selected**, or press ⬇ on one picture to export just that one.
   **Select all**, **Select this look** (every photo in the look you are
   viewing) and **Clear** help with big batches. **Export as**: **Files in my
   export folder**, or **One zip file** (saved in the export folder and shown
   in Finder). Exports are full size, made with the sizes, file type and your
   name in step 5, with a progress card in the corner.
   Click any result to see it against the original

   on the before/after slider, with its description. After a one-photo trial,
   **Use the selected look on all N photos** makes it (with its fine-tuning) on
   every photo. **Fine-tune the selected look** changes it instantly, without
   making the look again:
   - **Look strength** (0-100 %), **Warmth**
   - **Player brightness** and **Background brightness** (stops), using the
     player's cut-out; it says what the look itself already does to them
   - **Auto fill light on the player**: lifts a player darker than the scene
     around them (backlit or in shade), up to +0.75 stops, photo by photo. It
     compares the player with their own background, so it corrects the light,
     not anyone's skin tone or kit.
   - **Show and fix the player cut-out**: shows in blue what the app treats
     as the player (at first only the main players of the play; others count
     as background). **Click to fix it**: with **Add what I click**, click a
     teammate, the ball or a flag to make it part of the player; with **Take
     out what I click**, click a pole or a sign to put it back in the
     background. Each click is traced with SAM 2.1 (Meta's free Segment
     Anything model, run on this Mac; about 1 s, 160 MB downloaded once to
     `~/.cache/photo-crops`), first on the whole photo and then closer around
     the object for sharp edges. **Undo last click**, **Back to automatic**,
     and **Remake this photo's looks** (to see the fix in effects such as
     Color Pop or the neon looks; the brightness sliders use it at once).
     Fixes stay with the photo for all its looks and the full-size export,
     and are listed in the export's `.json` (`cutout_fixes`).
   - **Reset**, and **Use these settings on every photo with this look**

   Fine-tuning is part of the look's recipe (`"adjust"`), so it is kept when
   you export, make a reel, or save the look as a preset.

   **Match the game** (with more than one photo): **Match all photos to the
   selected one** evens out exposure and white balance across the set, so a
   gallery looks like one shoot instead of changing light. Each photo is
   measured before any look (its middle brightness, and the color of its
   near-neutral tones: white kits, lines, haze; a green field or a blue sky
   does not count) and gently corrected toward the selected photo (three
   quarters of the difference, at most 0.75 stops and 8% per color), then its
   looks are made again. The correction is in each result's recipe as
   `"match"` (left out when you save a preset). **Undo matching** puts every
   photo back as shot.
5. **Save a preset, export settings**: name a look and **Save preset** to
   keep it. The export settings used by step 4: the export folder (default `~/Pictures/Photo Presets`), each
   with its recipe beside it as `.json`. **Open folder** shows them in Finder.
   **Sizes** (tick any): **Full size**, **Instagram post 4:5** (1080 x
   1350), **Instagram square** (1080 x 1080), **Instagram story / reel cover
   9:16** (1080 x 1920), and prints at 300 ppi: **4 x 6**, **5 x 7**, **8 x 10**,
   **11 x 14** (turned to match the photo). Each size is cropped to its shape
   around the players (kept whole whenever the shape allows; a cut-out fix
   that adds a teammate keeps them in too), then resized; Instagram sizes get
   a light output sharpening. A print size bigger than the photo's own pixels
   is enlarged, and the export says so. Files are named with the size, e.g.
   `DSC03424_vivid-pro_ig-4x5.jpg`.
   **File type**: **JPEG** (web, Instagram, clients), **16-bit TIFF** (big
   prints, further editing in Lightroom or Photoshop; about 6 times bigger),
   or **Both**.
   **Your name, copyright and watermark**: your name, a copyright notice
   (empty: `© <year taken> <your name>`) and contact (email, website or
   handle) go into every file: EXIF Artist and Copyright, and XMP (creator,
   rights, IPTC creator contact), where Lightroom, Photo Mechanic, Photos and
   print labs look. They are remembered (in
   `~/.config/photo-crops-presets/delivery.json`). **Add a watermark** for
   client proofs or posts: **Corner** (small text, bottom right) or **Across**
   (large and repeated), with its text (empty: your copyright notice) and
   strength.

6. **Make an Instagram reel**: a vertical MP4 (1080 x 1920, 30 fps) under a
   minute, ready to post, made from the looks above or from a folder of photos
   (such as your exports). Every photo is on screen for 2 seconds (shortened so
   the reel fits; never under 1.5 s), slowly pushes in and dissolves into the
   next. With a song, the cuts land on its beat (the song can start later to
   skip a slow intro) and it fades out at the end. Add an optional opening
   title (lower third) and closing text (such as your handle). Landscape
   photos show about half their width, centered on the players, on a blurred
   copy of themselves; portrait photos fill the screen. Reels are saved in
   `Reels` inside your export folder.

**Quality and color** (for paid and print work):
- RAW (and 16-bit TIFF) photos keep a 16-bit copy, and full-size exports make
  the look from it, in floating point to the end, so smooth gradients (neon
  glows on black, smoke, skies, blurred backgrounds) have no bands.
- Every 8-bit picture is finely dithered when it is rounded, which also
  breaks up bands; untouched pixels keep their exact values.
- Every saved file carries the standard sRGB color profile (IEC61966-2.1),
  what Instagram, phones and print labs expect; JPEGs are saved at quality 95
  with full color detail. TIFFs are tagged 300 ppi.
- Photos in another color space (an iPhone's Display P3, a camera set to
  Adobe RGB) are converted to sRGB with their own profile when they load, so
  their colors stay true.

Every picture keeps the photo's real date and camera details (date taken, camera, lens, exposure), Sony RAW files included, and saved files are dated when the photo was taken. Results are made at 1600 px for speed; export renders each again from the
full-size photo.

**Preset manager**: load a preset to start from, adjust it, preview it on a
photo (the preview stays beside the settings), then save it with a name and a
one-line description (shown next to it on Make looks). The settings are in
tabs (Color, Player & background, Detail, Atmosphere, Overlays, Finishing),
each setting has a short explanation, and an effect's settings only appear
once you turn it on. The form covers:

- **Color**: LUT and strength, neon, B&W channel mix, duotone, the clean pro
  edit, skin tone protection, saturation, high key, and **split toning** (shadow and highlight
  tones, amount, balance, compressed blacks), extra contrast
- **Player and background**: the final player and background brightness,
  look strength, warmth and auto fill light (the same as Fine-tune), and
  inside the look, edit them separately: player brightness,
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

**Lightroom presets**: turn presets you own (Lightroom, or any app's look)
into looks here, with the HALD color-chart method:
1. **Download the color chart** (a 512 x 512 16-bit TIFF holding a 64 x 64 x
   64 cube of colors).
2. In Lightroom (Classic, desktop or mobile; or darktable, Photoshop,
   Affinity, Capture One), apply your preset to the chart and export it full
   size as a 16-bit TIFF in sRGB, with no resizing, sharpening or watermark,
   named after the preset.
3. **Add the exported charts** and press **Make LUTs**: each becomes a `.cube`
   in `~/.config/photo-crops-presets/luts` (added to your LUT folders), and
   optionally a preset under My presets, previewed on your first photo.

It captures what a preset does to color and tone (white balance, exposure,
contrast, curves, color mixer, color grading, profiles, B&W), not what depends
on where a pixel is (masks, vignette, grain, texture, clarity, dehaze,
sharpening): the app warns when a chart looks like those were on, when the
preset was not applied, or when the chart was resized. LUT steps run in full
precision (floats), so LUT looks keep 16-bit photos smooth.

**Assets**: what was found, and where to look (folders and zip packs).

### Command line

```bash
uv run allprophoto-batch --list
uv run allprophoto-batch ~/Movies/"Game day" --random 6 --crop crop
uv run allprophoto-batch ~/Movies/"Game day" --preset "Grit & Glory" --out ~/Pictures/Grit
uv run allprophoto-batch ~/Movies/"Game day" --preset "Color Pop" --preset "Dark Mono"
uv run allprophoto-batch ~/Movies/"Game day" --all-presets
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

**Studio and smoke looks** (team colors are set in the preset manager):

| Preset | What it does |
|---|---|
| Smoke Studio | A red studio backdrop, white smoke billowing at the player's sides and rolling across the floor in front of their feet, stage lights above |
| Color Smoke | A dark night background with team-colored smoke bombs (blue left, gold right) behind the player |
| Stadium Smoke | A dark night stadium, gray smoke at the player's sides and over the floor, and two banks of floodlights glowing through the haze |
| Neon Pop Art | The player as a neon pop-art painting (indigo, cyan, pink, orange and yellow-green paint, painted lines, a glowing outline) with paint splatter and swooping strokes, on a dark sepia background |
| Neon Pop Art Sharp | Neon Pop Art with crisp, screen-print edges: hard-edged paint shapes, thin ink and bright etched lines, a thin outline, whip lines flying outward, and a near-black background |
| Neon Pop Art Sharp Black | Neon Pop Art Sharp on a true black background instead of sepia brown |
| Neon Splash | The player as glowing neon line art (a dark body, crisp neon lines, a neon rim) on black, with a hard-edged rainbow paint explosion behind them |
| Neon Streaks | Neon line art on black like Neon Splash, but the background is mostly fine paint streaks ending in drops and tiny specks, with only a little solid paint |
| Player Vignette | Darkens away from the player's own outline, wherever they are in the frame |

The black-and-white looks lean on blue in their mix (like a red filter on
film) so sunlit grass stays gray instead of going white.

Saving a preset with a starter's name replaces it for you; deleting yours
brings the starter back. Presets live in `~/.config/photo-crops-presets/presets.json`.

## Illustration presets (drawn on this Mac)

Five groups of four, each listed under its own heading on Make looks:

| Group | Presets |
|---|---|
| Watercolor | Ink & Wash · Rainbow Silhouette · Team Splash · Stadium |
| Anime | Sky Hero · Sunset · Speed Lines · Night Lights |
| Oil painting | Dark Studio · Golden Hour · Palette Knife · Old Master |
| Comic book | Hero Burst · Pop Art · Noir Ink · Manga Action |
| Pencil and ink | Graphite · Charcoal · Colored · Pen and Ink |

How they are made (all free, all on this Mac; no paid service):
- **Framing:** each frames itself as a 4:5 portrait around the main player
  and the ball in play; a teammate sliced by the frame edge becomes background.
- **The players drawn:** Stable Diffusion 1.5 (DreamShaper 8) with a
  ControlNet line-art model redraws the players, following the photo's own
  outlines; Real-ESRGAN enlarges the drawing for full-size exports; the ball
  and hands get a closer, gentler pass (a hand only where bare skin shows, so
  a wrist hidden behind the body never gets one drawn). The models (about
  5 GB) download once to `~/.cache/huggingface`.
- **Drawing size:** the AI draws at 768 px (the comic_redraw step's `size`);
  at 1024 it starts inventing details and drifting skin tones.
- **Time:** about 25 s per look on the M5 (each preset shows its own time),
  plus about a minute for the first illustration look of a session while
  the models load. Other heavy
  work on the Mac at the same time (another render) can make it much slower.
- **Drawn once:** exporting a look or putting it in a reel reuses the
  drawing from its preview (kept per photo, crop, framing, cut-out fixes and
  look settings), so the export matches the preview and is quick; faces,
  hair, techniques and backgrounds are still made at full size.
- **Faces are the child's:** the whole head (face, hair, ears, the back of the
  head) is the photo's own, never redrawn by the AI, rendered in the look's
  technique at the face's own scale with portrait rules (no black shadow
  shapes, light hatching, fine brushwork). The real head also covers the neck,
  fading softly into the drawing, so there is no seam under the chin.
- **Hair:** each head is traced again on its own, close up, so curly hair and
  afros keep their curls against the background; the cut-out stays tight
  (it may not grow past the first trace). Edge colors are cleaned of the old
  background (no light or dark halos), and the drawing stops just inside the
  outline (no drawn rim).
- **Techniques** (the `technique` step): oil brushwork that follows the forms
  with lit impasto, palette knife, graphite and pen cross-hatching driven by
  tone, charcoal on toned paper, colored pencil, anime cel shading, comic
  halftone.
- **Watercolor** (procedural): paper, washes with pooled wet edges,
  granulation, blooms, splatter and drips; splash or full-sheet backgrounds;
  the real scene painted loose; pen-and-ink lines; the players blended into
  the painting (edges lost in places, washes crossing the outline).

## Assets

Found automatically (change them on the Assets tab):

| Kind | Default sources |
|---|---|
| LUTs (`.cube`) | Final Cut's Custom LUTs folder, and `~/Movies/Ultimate+Sports+Editing+Bundle.zip` |
| Textures | `~/Movies/Textures.zip` (marker and paper), plus generated grit, grain, scratches, smoke, paper and dust |
| Overlays | `~/Movies/Sports_Impact_Essentials.zip` (smoke, dust, debris, sparks, fire, lightning, water; confetti, electricity, cartoon, glitch and fireworks are left out) |

Zip packs are never unpacked whole: only the files a look uses are taken out
and cached in `~/.cache/photo-crops-presets/assets`. Overlay packs made of
transparent ProRes clips are turned into a still from each clip's strongest
frame (the most visible effect).

## How a look works

A look is a recipe: a list of steps, run in order, then its quick
adjustments (`"adjust"`: `strength` 0-1, `subject` and `background` stops,
`warmth` -1 to 1, `auto_fill` true/false), applied over the finished look.

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
| `smoke_cloud` | `color`, `color2` (right cloud, for two team colors), `place` (`sides`, `behind`, `floor`, `sides_floor`), `amount`, `size`, `front` (floor smoke over the feet): generated billowing smoke behind the players |
| `stage_lights` | `count`, `amount`: studio lights along the top |
| `stadium_lights` | `height` (share of the player's height above their feet), `amount`, `color`: two floodlight banks near the left and right edges |
| `pop_art` | `levels`, `mottle`, `lines`, `shading`, `glow`, `outline`, `palette`, `background`, `background_amount`, `lift` (the background's darkest tone; #000000 for true black), `smooth` (1: crisp edges drawn at 2x, no stair steps), `crisp` (1: sharp screen-print edges, ink and etched lines): the player as a neon pop-art painting; the background turns a dark tone |
| `paint_splatter` | `amount`, `strokes`, `front`, `whips`, `palette`, `stroke_colors`: paint splats, droplets and swooping strokes around the player |
| `neon_lineart` | `darkness`, `lines`, `detail`, `rim`, `glow`, `colors`, `background`, `clean` (1: bold, clean lines without texture scribbles): the player as neon line art with a glowing rim; the background goes black |
| `paint_burst` | `amount`, `size`, `direction`, `colors`, `splash` (solid paint, 0-1), `lines` (streaks ending in drops, 0-1), `specks` (0-1): a hard-edged explosion of neon paint behind the player |
| `neon_drip` | `amount`, `length`, `inner`, `gloss`, `glow`, `rain`, `grid`, `coat`, `outline` (crisp dark drip edges), `density` (drips side by side), `width`, `colors`: a melted coat of paint on the players' lower edges and glossy drips growing out of it (thick at the edge, swelling and thinning, fat drops, in clusters) (and some over them, never over faces), with falling streaks and a grid behind |
| `neon_drip2` | as `neon_drip` (`amount`, `length`, `width`, `inner`, `gloss`, `glow`, `rain`, `grid`, `coat`, `outline`): every drip its own outlined, glossy shape, spaced apart, from sideways lower edges only, drawn at 2x for smooth edges |
| `subject_vignette` | `amount`, `spread`: darkens away from the player's outline |
| `backdrop` | `top`, `bottom` (colors), `glow`, `amount`: a studio gradient instead of the background (needs the player cut-out) |
| `comic_redraw` | `prompt`, `strength`, `lines`, `steps`, `seed`, `size` (drawing size, default 768), `real_face`, `face_style`: the AI illustration of the players (see Illustration presets) |
| `technique` | `kind` (`oil`, `knife`, `graphite`, `charcoal`, `colored_pencil`, `pen`, `cel`, `comic`), `amount`, `detail`, `where` (`all` or `players`): an artist's technique over the picture, faces by portrait rules |
| `art_backdrop` | `kind` (`speedlines`, `halftone`, `bokeh` (night lights), `sunset`, `paper`), `colors`, `ink`, `amount`: an illustration background |
| `wc_backdrop`, `wc_scene`, `wc_silhouette`, `wc_ink`, `wc_integrate`, `wc_finish` | watercolor: splash or full-sheet background, the real scene painted loose, rainbow-bloom silhouette, pen-and-ink lines, blending the players into the painting, paper grain |

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
background people, poles and signs stay in the background; the ball in the
play joins the players (only a ball near them and about as big as a ball at
their distance: one far behind them, in another game, is left out). Steps on the `subject` layer change only the players, steps on
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
  cli.py              allprophoto-batch
  engine.py           Random and preset modes, previews, full-size export
  pipeline.py         Running recipes, the step registry, plugins, keeping faces clean
  effects.py          The built-in steps
  blend.py            Blend modes
  luts.py             .cube LUTs (from match-cull)
  procedural.py       Generated textures
  assets.py           Finding, fetching and caching LUTs, textures and overlays
  scene.py            Faces, ball, feet, outlines and the player cut-out; crop first
  presetform.py       The preset manager's form (tabs, explanations), to and from recipes
  explore.py          Random looks
  presets.py          Saved and starter presets, their groups and descriptions
  art_presets.py      The 20 illustration presets
  comic.py            The AI drawing of the players (Stable Diffusion + ControlNet), real heads, hair
  technique.py        Artist techniques (oil, pencil, charcoal, ink, cel, comic)
  art.py              Illustration backgrounds
  watercolor.py       The watercolor steps
  match.py            Match the game (exposure and white balance across photos)
  deliver.py          Export sizes, file types, name, copyright and watermark
  lightroom.py        Lightroom presets to LUTs (HALD charts)
  reel.py             Instagram reels: timing, beat sync, framing, titles, MP4
  timing.py           How long each look takes (measured, then learned from your runs)
tests/
```
