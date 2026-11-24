# Instant Looks: hover a look, see it now, on one photo or the whole event

Status: in progress (started 2026-11-23). Each phase must pass its bar, measured on the
MacBook Pro M5 with real event photos, before the next starts. If a bar can't be met, the
feature is dropped, not shipped "almost".

## Why

Lightroom and Capture One already preview a preset on the main picture when you hover over it.
Matching them is table stakes. VS Digital Pro only builds this if it clearly beats them:

1. **Exact, not approximate.** The hover preview is the real look made by the real engine. It is
   never a color-only stand-in, and smoke, stadium lights, fog, new backgrounds and player-aware
   looks included. Competitors' presets can only change color and tone.
2. **The whole event at once.** Hover a look and every photo in the event grid shows it, so you
   can see whether it holds up across day, night and indoor shots. No editor we know does this.
3. **Scales to hundreds of looks.** A compact, searchable list (favorites and recently used on
   top) replaces a panel that renders a picture card for every look.
4. **No waiting, no blur.** Previews are made ahead of time in the background, nearest the mouse
   first. Nothing is ever blurred. A look that isn't ready says so in words, and the photo stays
   as it is.

AI drawing looks (watercolor, anime, oil, comic, pencil) take 10 s or more per photo, so they
can't be instant without faking it. They stay "click to make", clearly labelled, with their
example picture.

## How (one idea: make every look ahead of time, then hovering is only showing a picture)

- **Current photo:** each non-AI look is made in the background at screen size (the same
  engine and settings as Make, the photo's edits included) and kept. Hover swaps the big
  picture to the kept one: a picture already decoded in memory, so it's instant.
- **Event grid:** each look is made for every photo at grid size and kept. Hover swaps every
  grid picture at once.
- **Order:** the look under the mouse first, then its neighbors in the list, then favorites,
  then the rest. Moving the mouse re-orders the queue. Lowest priority: editing never waits.
- **Gentle on the Mac:** previews pause while you edit or export, and stop once everything is
  made (no endless work, the fan stays quiet).
- **Kept on disk** per photo and look, so after a restart nothing is made twice.

## Who it must run on (updated 2026-11-23)

**Any Apple Silicon Mac, M2 or newer, with 16 GB or more.** 8 GB Macs are not supported for now
(decided 2026-11-23): normal editing peaks at 9.5–11 GB when it cuts out a new photo.
Every bar below is budgeted for the base M2 with 16 GB:

- **Time:** background work runs on 2 cores, so per-core speed is what counts; an M5 core is about
  1.7x an M2 core. M5 timings are multiplied by 2 for the M2 estimate, and a bar only passes if that
  estimate passes too.
- **Memory:** background work must never raise the app's peak above what normal editing already
  needs, and it hands its memory back when done.
- **Background work:** at most 2 processor cores, lowest priority, paused while you edit, stopped
  when everything is made.
- A real M2 test before release is still needed: that's a known gap, not a pass.

**Using newer Macs fully (machine levels).** The app is not held back to the oldest Mac it supports.
At start it reads the Mac's chip, memory and core count and picks a level:
- *Base (M2, 16 GB):* everything works, kept light. This level must pass every bar.
- *High (newer chips, more memory):* heavier versions switch on by themselves (for example the
  full-quality cut-out in places where the base level uses a lighter one, more cores for background
  work).
- A feature that needs something only newer chips have is checked for at start and switched off
  where it can't run, with a plain note saying so: it never crashes or quietly runs slowly.
- Built when the first feature needs it (the cut-out below is the likely first), not before.

## How it's tested (no spot checks)

- The browser click tests (Playwright, real Chrome, a separate test copy, real event photos)
  live in the repo under `tests/ui/` and run with one command, each with its time and memory
  budget written in as a pass/fail line. They run before every change reaches the app:
  `uv run --with playwright --with psutil --with requests python tests/ui/run.py --photos "<folder>"`
  (about 10 minutes for 40 photos: cold, then quit and reopen, then warm).
- Every number in this plan comes from those runs. If a bar fails, the phase isn't done.

## Findings that changed the plan

- **Whole-event preview, first try:** each photo was prepared with the full camera file and the
  full cut-out model (3 runs): 15 to 24 s per photo and 6.8 GB of memory. Fails the M2 budget.
- **Cut-out options measured (8 real photos, 2 cores):** CoreML (graphics chip / Neural Engine):
  the model conversion hung, so not usable. BiRefNet Lite: 4.2 s a photo and 11 GB peak: out.
  u2net_human_seg: 0.32 s a photo, 1.9 GB, cut-outs matching BiRefNet at grid size (it leaves out
  corner flags; the ball is added back as everywhere else). isnet left a see-through ghost player;
  silueta and u2netp picked up corner flags. **Chosen: u2net_human_seg, only for the small event
  previews**, with the app's own steps (only pieces touching the players, the ball, team grouping),
  from a 1024 px copy. Make and the big hover preview keep the full cut-out.
- **Result (41 real photos, 117 looks):** the look under the pointer on every photo in 30 s; every
  look on every photo in about 2 minutes; about 1 core used; peak 4.4 GB; models let go after.
  After a restart: everything back from disk in 2 s, nothing made again.
- **Bigger finding, outside Instant Looks:** the app's normal editing already peaks at 9.5 GB the
  first time it cuts out a photo (BiRefNet on the main processor). An 8 GB Mac would swap heavily
  on every new photo, so 8 GB Macs are not supported for now (decided 2026-11-23); 16 GB fits.
- **Bugs found by the click tests and fixed:** the page counted looks named twice, so "all ready"
  never came; one failed look stopped "all ready" for ever; a failed status check stopped checking
  silently; thousands of kept previews would overflow the queue (it called itself per preview);
  the queue re-read the looks list per preview (6 s after a restart) and did it on the web
  server's own thread; every kept preview was loaded into memory; kept previews and sharp crops
  weren't tied to the drawing code (an update could show an old version's look); thumbnails were
  re-made from the camera file after every restart (black tiles); the first slider after a restart
  waited for the cut-out (0.85 s); the "making this look" overlay still blurred the photo.

## Bars (measured, all must pass)

| Phase | What | Bar |
|---|---|---|
| 0 | Spike: make every non-AI look at screen and grid size | screen ≤ 1.5 s/look, grid ≤ 0.35 s/look on average; all 50 looks of one photo in ≤ 75 s |
| 1 | Hover on the current photo | hover → picture ≤ 50 ms once made; identical to Make (pixel check); no blur; editing never slowed (slider ≤ 0.15 s during warm-up) |
| 2 | Compact look list | 100+ looks: scroll at 60 fps, search ≤ 30 ms, ↑/↓ steps with live preview, Return makes it, Esc reverts |
| 3 | Whole-event hover | grid of 40 photos swaps ≤ 300 ms once made; event warm-up runs in the background without slowing editing (slider ≤ 0.15 s); the first time, photos fill in one by one, each showing the photo as it is meanwhile (never blank, never blurred) |
| 4 | Restart | after quit and reopen, previews come back from disk (no remaking); first slider as quick as the rest; disk use bounded |

Every phase is click-tested in a real browser (Playwright with Chrome) on a separate test copy,
with real photos, before it reaches the app.

## Phases

0. **Spike (measure only).** Time every non-AI look at screen size (1400 px) and grid size
   (360 px) on two real photos (a single player and a team photo). Decide go / no-go from the
   numbers.
1. **Hover on the current photo.** Background "make ahead" queue on the worker at the lowest
   priority, keyed by photo, look and edits; kept in memory and on disk. Hover shows the kept
   picture at once; "Making… N of 50" in words when not ready. Replaces today's on-demand
   try-on (which made you wait).
2. **Compact look list.** Names grouped as now, a search box, favorites (star), recently used,
   keyboard stepping. Each row: a small color chip of the look on this photo once made (from
   the kept preview, never a separate render).
3. **Whole-event hover.** In the grid view, hovering a look swaps every photo's picture to it,
   from the kept grid previews; photos not made yet show a quiet "making" corner tag.
4. **Restart and cleanup.** Previews on disk (bounded, oldest removed), the queue resumes where
   it left off, and pictures are dropped when a photo's edits change.

## Not doing

- GPU or LUT "approximations" of looks: they wouldn't match the real look exactly.
- Instant AI drawings.
