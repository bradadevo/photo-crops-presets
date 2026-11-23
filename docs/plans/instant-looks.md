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

## Bars (measured, all must pass)

| Phase | What | Bar |
|---|---|---|
| 0 | Spike: make every non-AI look at screen and grid size | screen ≤ 1.5 s/look, grid ≤ 0.35 s/look on average; all 50 looks of one photo in ≤ 75 s |
| 1 | Hover on the current photo | hover → picture ≤ 50 ms once made; identical to Make (pixel check); no blur; editing never slowed (slider ≤ 0.15 s during warm-up) |
| 2 | Compact look list | 100+ looks: scroll at 60 fps, search ≤ 30 ms, ↑/↓ steps with live preview, Return makes it, Esc reverts |
| 3 | Whole-event hover | grid of 40 photos swaps ≤ 300 ms once made; event warm-up runs in the background without slowing editing |
| 4 | Restart | after quit and reopen, previews come back from disk (no remaking) |

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
