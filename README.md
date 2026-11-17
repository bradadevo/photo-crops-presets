# AllProPhoto

Everything in [photo-crops](https://github.com/bradadevo/photo-crops)
(professional crops, face close-ups, screenshots rebuilt from the camera
files), plus **AllProPhoto**: a creative looks engine for sports photos
with its own Mac app.

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
uv run allprophoto-install-app     # once: puts AllProPhoto.app in ~/Applications
```

Then open **AllProPhoto** like any Mac app (Finder, Spotlight or the Dock: drag
it there to keep it). It opens in its own window, no Terminal or browser
needed. Run the install again after updating Python or the project's
packages. Without the app: `uv run allprophoto` opens the same thing in your
browser (`--window` for the app window).

It is dark and photo-first, like Lightroom: **your photos** on the left, the
**picture** big in the middle with the **looks made** in a strip under it, and
the **looks** to choose from on the right. It suits both ways of working:

- **One photo**: pick as many looks as you like, compare them, star the best,
  export.
- **A whole game**: try looks on one good photo first, then **Use this look on
  all N photos**; fine-tune once and use the settings on every photo with that
  look; export them all and make a reel.

**1. Add photos** (any mix, RAW and HEIC included): drop photos or whole
folders anywhere on the window, paste with **⌘V**, or press **+** → **Add
photos…** / **Add a folder…** (the Mac's own dialogs; your photos stay where
they are). A shot saved as both JPEG and RAW is used once (the camera's JPEG),
and a photo added twice is added once. Your photos are still there next time
you open the app (dropped and pasted ones are kept in
`~/.cache/photo-crops-presets/added`). Click a photo to work on it.

**Find a player** (the person button above your photos): click your player
once on a photo, and every photo with them is found: by their face (a free
face-recognition model run on this Mac: OpenCV's YuNet and SFace, about 40 MB,
downloaded once to `~/.cache/photo-crops`), their jersey number when it shows
(the Mac's own text reading) and their kit (a player of the other team is
never taken for them). Kids' faces at a distance look alike, so close calls
are asked, **Is this your player?** with ✓ and ✗, and each answer sharpens the
rest. **Theirs** shows only their photos, best first; **Best** one per moment
(of a burst a moment apart, the sharpest, biggest, facing the camera, near the
ball); **Choose the best N** chooses them, so the looks are made on just those
(**Photos: Chosen N**). Each photo is looked at once (remembered in
`~/.cache/photo-crops/players`). Any photo can be chosen by hand too: the ✓ on
it, or ⌘-click.

**2. Pick looks**: every look is a card showing **your own photo in that
look** (the quick looks are made on it in the background, a fraction of a
second each, once the players are cut out). Rest the pointer on a card to
**try the look on** the big picture, full size. The AI illustration looks take
about 20 s each, so their cards show their most recent picture instead (kept
in `~/.cache/photo-crops-presets/examples`). Search, or filter by group (Bold,
Editorial, Studio, Watercolor, Anime, Oil painting, Comic book, Pencil and
ink, Mine). Each card says about how long it takes (**instant**, or seconds;
learned from your own runs, in `~/.config/photo-crops-presets/timings.json`).
Tap cards to pick them (numbered in order), then choose:
- **Photos**: **This photo**, or **All N**.
- **Framing**: **Whole** (as shot); **Pro** (no zoom: the photo's own shape, at
  least 90% of it, moved so the players sit on a rule-of-thirds point, never
  cutting them); **Tight** (zoomed in on the action); **Face** (head and
  shoulders).

and press **Make N looks** (it says about how long, the first AI look of a
session included: about a minute to load the drawing models). The shuffle
button beside it makes six random looks, to discover new styles.

**3. Watch them come in**: each look gets a tile in the strip at once, with a
ring showing its %, and turns into its picture when done; you can open, star
and export finished ones while the rest are still being made. The top bar
shows how many are done and about how long is left (**Stop** keeps what is
made). When you are in another app, the tab title shows the progress and a
Mac notification says when the looks (or an export, or a reel) are ready.

**4. Look, compare, pick the keepers**:
- **← →** go through the looks; **Space** (or **P**) **picks** one; **1**–**5** rate
  it in stars (**0** clears). The strip's **Show** menu narrows it to the picks
  or to 3 stars and up, for big batches. **G** switches to the **contact sheet**
  (every look big, pick and ⬇ on each).
- **Compare** (**C**) puts a before/after slider on the picture; hold **B** to
  see the original.
- **Zoom** (**Z** or double-click; drag to move) to check faces and focus: the
  look is made again at 3600 px for it, so it is sharp. Compare works zoomed
  in too.
- **⌘-click** 2 to 6 pictures to see them **side by side**, each with its pick.
- **Share** (the arrow-out-of-a-box button): **AirDrop** (to your iPhone, full
  size), **Messages**, **Mail**, **Add to Photos** (it reaches your iPhone
  through iCloud Photos), or **Copy** (**⌘C**). What is shared is the finished
  picture, full size, with its edits, text, your name and copyright.
- **Remove a look** you do not want: the bin button, or **Delete**; **Undo**
  is right there. **Remove unpicked** clears every look you did not pick, and
  **Remove all** everything.

**5. Edit** (the **Edit** tab, or **A**). Everything changes the picture as you
drag, and **⌘Z** / **⇧⌘Z** undo and redo every step (the arrows at the top of
the tab too). Tools used on the picture itself:
- **Crop** (**R**): drag the box or its handles, in **Free**, **Original**,
  **4:5**, **1:1**, **9:16** or **16:9**; **straighten** with the dial (up to
  20°; the picture is enlarged so no corner is empty), or **Auto**, which
  levels it from the field lines, the horizon and the goal posts. **Apply**.
- **Remove**: **Click** a person or a thing (a bag, a cone, the goal cart) and
  all of it is taken (their edge and their shadow on the grass too), or
  **Brush** over it (brushing over most of a person takes the whole person).
  **Background people** selects, in one click, everyone who is not one of the
  players kept. What will go shows in red before anything is removed; then
  **Remove it**, from **This look** or **All N looks** of this photo (and the
  looks made of it later). It never takes the players kept in the look unless
  you brush right over them. It is filled by LaMa, a free object-removal model
  run on this Mac (downloaded once, about 200 MB, to `~/.cache/photo-crops`, or
  reused from ai-versions), with the light matched at the seam, the picture
  mirrored at its edges for context, and the fine texture (grass blades)
  borrowed from the ground right around it. It takes seconds: the looks are not
  made again; each export does it again at full size. **⌘Z** puts it back.
- **Adjust a part**: click a face, the player, the sky or the grass; the part
  is traced (with SAM 2.1, as for the cut-out) and shown in blue, and gets its
  own **Brightness**, **Warmth** and **Saturation**, with a soft edge. Several
  parts can be adjusted; each is listed in the tab.
- **White balance**: click something that should be white or gray (a white
  kit, a line); Warmth and Tint are set so it is.
- **Text** (**T**): a name, a score or a date, dragged into place (it snaps
  to the middle), typed in the tab (two lines are fine), in **Clean**,
  **Bold**, **Spaced** or **Banner** (on a dark bar), its size and color.
  The page draws it with the same font as the export, so what you place is
  what you get; every export size has it in the same place.
- **Logo**: your **brand kit** (a team crest, a sponsor, your own mark).
  **Add a logo** (or drop it on the kit): a PNG, a JPG on white, or a
  screenshot; its background is taken away (keyed out of a plain color with a
  clean edge, or cut out) and it is trimmed. Click a logo to put it on the
  picture (bottom right), drag it, or pick a corner; its **Size**,
  **Strength**, and **Auto** (a one-color mark goes white on dark spots and
  black on light ones; a crest shows as it is), **As it is**, **White** or
  **Black**. Logos are kept in `~/.config/photo-crops-presets/logos`. The
  export window's **Add my logo** puts one in a corner of every picture that
  has none placed, sized to each export size.
- **Poster**: makes the picture a social post, as a team's designer would.
  **Game Day** (the player in front of a big title, a line under it), **Spotlight**
  (team color, their number behind, the picture in a card with the player
  breaking out over its edge, their name and position), **Final Score** (the
  score on a clean panel) and **MVP** (a cover title behind the player); as an
  Instagram **Post** (4:5) or **Story** (9:16), in a team color, with your logo.
  The player's cut-out gives the depth: they are drawn again in front of the
  title or the card. Works on any look, and the export is full size.
- **Cut-out**: fix what counts as the player (below).

Sliders:
- **Light**: **Exposure**, **Contrast**, **Highlights** (bring back a white kit
  or the sky), **Shadows** (open up a shaded face).
- **Color**: **Warmth**, **Tint**, **Saturation**.
- **The look**: **Look strength**, **Player brightness** and **Background
  brightness** (stops, using the player's cut-out), **Auto fill light** (lifts
  a player darker than the scene around them, backlit or in shade, up to +0.75
  stops; it compares the player with their own background, so it corrects the
  light, not anyone's skin tone or kit). Double-click a slider to reset it.
- **Reset all**, and **Use on all N** (these sliders on every picture with
  this look; crops, parts and text stay with each picture).

And for the photo:
- **Fix the player cut-out** (**Cut-out**): the picture shows in blue what the
  app treats as the player. With **Add**, click a teammate, the ball or a flag
  to make it part of the player; with **Take out**, click a pole or a sign.
  Each click is traced with SAM 2.1 (Meta's free Segment Anything model, run
  on this Mac; about 1 s, 160 MB downloaded once to `~/.cache/photo-crops`).
  **Undo**, **Automatic**, and **Remake this photo's looks**. Fixes stay with
  the photo for all its looks and the full-size export, and are listed in the
  export's `.json` (`cutout_fixes`).
- **Use this look on all N photos** (with its fine-tuning).
- **Match every photo's light to this one**: evens out exposure and white
  balance across the set, so a gallery looks like one shoot. Each photo is
  measured before any look (its middle brightness, and the color of its
  near-neutral tones: white kits, lines, haze; a green field or a blue sky does
  not count) and gently corrected toward this one (three quarters of the
  difference, at most 0.75 stops and 8% per color), then its looks are made
  again. The correction is in each recipe as `"match"`. **Undo matching**
  puts every photo back as shot.
- **Save as a preset**: the look with its sliders, under **Mine** (crops,
  parts, text and removals belong to the picture and are not saved in it).

The sliders are part of the look's recipe (`"adjust"`); crops, parts, text and
removals are the picture's `"edits"`. All are
kept when you export, share, zoom or make a reel, and written in each
export's `.json`.

**6. Export**: **Export N picks** (top right, or **E**) exports the picked
pictures; with none picked, the one you are looking at. ⬇ on a picture
exports just that one. The export window:
- **Save to**: your export folder (default `~/Pictures/Photo Presets`;
  **Change…**). Each picture is saved with its recipe beside it as `.json`.
- **As**: **Separate files**, or **One zip file** (named with the date and how
  many pictures).
- **Sizes** (any): **Full size**, **Instagram post 4:5** (1080 x 1350),
  **Instagram square** (1080 x 1080), **Instagram story / reel cover 9:16**
  (1080 x 1920), and prints at 300 ppi: **4 x 6**, **5 x 7**, **8 x 10**, **11 x
  14** (turned to match the photo). Each size is cropped to its shape around
  the players (kept whole whenever the shape allows; a cut-out fix that adds a
  teammate keeps them in too), then resized; Instagram sizes get a light
  output sharpening. A print size bigger than the photo's own pixels is
  enlarged, and the export says so. Files are named with the size, e.g.
  `DSC03424_vivid-pro_ig-4x5.jpg`.
- **File type**: **JPEG** (web, Instagram, clients), **16-bit TIFF** (big
  prints, further editing in Lightroom or Photoshop; about 6 times bigger), or
  **Both**.
- **Your name, copyright and watermark**: your name, a copyright notice (empty:
  `© <year taken> <your name>`) and contact go into every file: EXIF Artist and
  Copyright, and XMP (creator, rights, IPTC creator contact), where Lightroom,
  Photo Mechanic, Photos and print labs look. Remembered (in
  `~/.config/photo-crops-presets/delivery.json`). **Add a watermark** for
  client proofs or posts: **Corner** (small text, bottom right) or **Across
  (proofs)** (large and repeated), with its text (empty: your copyright
  notice) and strength.

The window remembers your choices. A progress note shows the export; when it
is done, **Show in Finder**.

**7. Reel** (the **Reel** tab): a vertical MP4 (1080 x 1920, 30 fps) under a
minute, ready to post, from your **Picks** or **All looks**. Drag the
pictures into the order you want; × leaves one out. Every picture is on screen
for 2 seconds (shortened so the reel fits; never under 1.5 s), slowly pushes in
and dissolves into the next. With a song, the cuts land on its beat (it can
start later to skip a slow intro) and it fades out at the end. Add an optional
opening title (lower third) and closing text (such as your handle). Landscape
photos show about half their width, centered on the players, on a blurred copy
of themselves; portrait photos fill the screen. The reel plays in the phone on
the right, and is saved in `Reels` inside your export folder.

**Help as you go**: rest the pointer on any button, slider or choice for a
short explanation (on a look's card: its full description, how long it takes
and whether it is drawn by AI). Resting on **Pro**, **Tight** or **Face**
draws where that framing would cut your photo, on the photo itself. Nothing
is ever silently greyed out: a button you cannot use yet says why, and what
to do, when you click or point at it (Make with no look picked, Export with
nothing made, Undo with nothing to undo...). **Edit** works on any photo:
with no look made, the photo itself opens for editing (as the look
**Original**).

**Every word on a poster can be changed or taken off**: click a word on the
picture (GAME DAY, the line under it, a number) and its box opens in the
panel with the words selected, ready to type over. The **×** beside a box
takes those words off the poster (type in the box to put them back).

**Resizable panels**: drag the edge between the photos panel (left) or the
side panel (right) and the photo to make it wider or narrower; the photo fits
the space left, the photos, looks, tools and poster layouts flow into more
columns, and the widths are remembered. Double-click an edge for the normal
width.

**Export**: separate files go in a new folder of their own ("AllProPhoto
<date> (<n> pictures)") inside the folder you choose, like the zip; each file
is dated when it was exported (the date the photo was taken stays inside it,
where Photos reads it). A small .json beside each picture (how it was made)
is saved only with **Also save how each was made** ticked (under "Your name,
copyright, watermark and more"); the command line always saves it.

**Posters in any shape**: pick **Post** (Instagram 4:5), **Square** (1:1),
**Story** (Instagram or TikTok story or reel, 9:16) or **Wide** (YouTube, X,
Facebook, 16:9); the picture you edit is that shape, as it will be exported.
Every word and banner fits the shape (on a tall story they are smaller, to its
width), and **Words and banners size** makes them all smaller or bigger.
Exporting a poster in other sizes lays it out again for each size's shape
(nothing is cropped off), and export has a **Wide 16:9** size too.

**Edit anything on a poster, at any time** (Poster tool):
- every word: click it to type, drag it to move it, its corner to resize it,
  Delete to take it off (**Words back to their places** undoes the moving);
- the logo: drag it, its corner resizes it, Delete takes it off;
- **Add to this poster** on every layout: text, a number, a score banner, a
  panel, a line, a logo and **stripes** (ready sets such as red · white ·
  blue, navy · gold or your team color, any 2 to 6 colors of your own, across
  or up and down), each dragged and resized freely;
- drag a logo from your kit, or drop a logo file (SVG, PDF, PNG…), onto the
  picture where you want it; a photo dropped on a poster asks once whether it
  is the poster's new photo or a graphic on it;
- **In this poster** (top of the Poster panel): **Change photo…** puts another
  photo in it, **Change look…** another look on its photo, its words and
  pieces kept (a new picture; the first is kept too).
⌘Z / ⇧⌘Z undo and redo every change, typing included (a run of typing is one
step), also with the cursor in a box, and keep you in the tool you are in.
The tool bar sits below the picture, so all of it can be reached.

**A poster for the whole team**: make a poster on one player's picture
(Spotlight, Name Stack, Goal, a custom one…), then press **Make this poster
for the team** and pick the other players' photos. Each gets the same design
and look; each player's number is read off their shirt when it can be seen,
and the names are left for you. **This poster for the team** (top of the
Poster panel) lists them all: type each name and number (Return goes to the
next), click a picture to open it and drag its photo to place that player.
Making a saved poster preset on several photos lists them the same way.

**Moving things on a poster**: in the Poster tool, drag the photo to move it in
the poster (or in Spotlight's card), pinch or use **Photo zoom** to zoom, and
**Photo back to its place** undoes it. Drag the logo anywhere on any layout,
its corner to resize it. On a poster, Crop opens the Poster tool (what you see
is what is exported).

**Custom posters**: **Custom ✦** (or **Customize this layout**) turns the
layout you are on into your own: every word, panel and band becomes a piece.
**Add** a title, text, number badge, score banner, color band, panel, line or
logo. Drag a piece on the picture to move it (it snaps to the middle), drag
its corner to make it bigger or smaller, arrow keys nudge it, Delete removes
it. In the panel: its words, style (Heavy, Bold, Clean, Spaced, Outline,
Banner), size and color, **Behind the players** (they stand in front of it),
forward and back, duplicate. A dark fade at the top and bottom helps words
read. It is drawn like every layout, so what you see is what is exported (in
any shape), and it can be saved with **Save poster**.

**Any word, any color**: the round dot beside each poster word opens its
colors (white, black, gold, red, blue, navy, green, orange, purple, sky, or
any color with the rainbow dot); **A** puts back the layout's own color.
Champions' gold lines follow its title's color. Spotlight's number is a solid
badge on the card's corner by default (**Number: Big, behind** for the large
number behind the card).

**The edit panel puts what you are working on first**: with Poster, Text,
Logo or Adjust a part open, its options sit right under the tools, and
Light, Color and The look fold away below (click one to open it).

**Logos in any format**: SVG, PDF and Illustrator (.ai, saved with PDF
compatibility) are drawn sharp at full size with their clear background kept;
PNG, JPG (on white), HEIC and screenshots work too. Add one with **Add a
logo**, or drop the file anywhere on the window (an SVG, PDF or .ai file
always goes to your logos). EPS cannot be read: save it as SVG, PDF or PNG.
**White** and **Black** make a two-tone crest one color, its light parts
see-through (its letters show the picture), not a blank shape.

**Click what you built to edit it**: a text, a logo or a poster on the
picture opens its tool with it chosen (a text is ready to type in).

Posters come in nine layouts: Game Day, Spotlight, Final Score, MVP, Name
Stack (the name three times behind the player), Goal (GOAL behind the scorer,
their name and the minute), Team Color (the background in the team color, the
player in full color), Matchday (the opponent on a team-color band, when and
where below) and Champions (a gold title, the event between gold rules).

**Save a poster, put any picture in it**: in the Poster panel, name it and
press **Save poster** (its layout, words, color, text and logo are kept in
`~/.config/photo-crops-presets/posters.json`). On any other picture, open
Poster and click it under **Your posters**. Saving a preset with **Keep the
poster in it** ticked does the same together with the look: pick the preset
under **Mine** and Make, and every photo comes out in that design.

**Looks on top of your edits**: edit the photo first (for a night shot, lower
the player's light), then press **Add a look on top of this edit**, or in the
Looks panel set **From: My edit**, and pick a look such as Stadium Night. The
look starts from your edited photo (its light, color, crop and removals; its
text, logos and poster are left for the finished picture), saved once at full
size in 16 bits in `~/.cache/photo-crops-presets/edited`. **From: Original
photo** makes looks from the photo as shot.

**Nothing is lost when you quit**: your photos, the looks made, their edits,
picks and stars, cut-out fixes and removals are saved as you go (looks at
preview size in `~/.cache/photo-crops-presets/session-looks`) and are all
there when the app opens again. **Remove all** (and removing a look) clears
them. When a newer version of AllProPhoto is installed, a green **Restart to
update** button appears at the top: the app closes and opens again in a few
seconds, with everything as it was. (The app keeps using the version it
started with until then, so it never mixes old and new.)

Press **?** for every keyboard shortcut.

**Tools** (top right) opens the preset editor, Lightroom presets and assets in
your browser: they are the classic app's pages (below), working on the same
looks. The classic app on its own: `uv run allprophoto-classic`.

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

### Tools: preset editor, Lightroom presets, assets

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
- **No made-up text:** image models cannot write: they invent jersey numbers
  and garble sponsor names. After each drawing, the Mac's own text detection
  (Apple Vision, free, on this Mac) compares it with the photo: text the AI
  invented is painted out, and the photo's real text is put back so it reads
  as it really does (`honest_text` on the comic_redraw step). The AI is also
  told to avoid numbers, labels, tags and patches.
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
  studio/             The AllProPhoto app
    server.py         Its local server: the session (photos, looks made, kept), the worker, the page's API
    web/              The page: index.html, app.css, app.js, edit.js (plain JavaScript, no build step)
    macapp.py         allprophoto-install-app: AllProPhoto.app in ~/Applications
    share.py          AirDrop, Messages and Mail, the Mac's own share windows
  edits.py            Edits after the look: crop and straighten, parts, text, white balance, leveling
  retouch.py          Removing distractions with LaMa
  app.py              The classic Gradio app (Tools: preset editor, Lightroom presets, assets)
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
  textguard.py        No invented numbers or letters in AI drawings; the photo's real text kept
tests/
```
