# VS Digital Pro: UI/UX audit

Audited 2026-11-20 on branch `studio-ui` (commit `d389e8e`, tagged `pre-ui-audit` as a safe restore point).

**Method.** Two passes over the source (`photo_presets/studio/web/*.js`, `app.css`, `index.html`, `studio/server.py`) and a scripted
walk-through of the running app at 1440 × 900 with real event photos. The walk-through covered:
- the empty app;
- adding photos;
- picking and making looks;
- compare;
- the contact sheet;
- Edit;
- Export;
- Reel, Culling and Check;
- a wrong file type.

Every finding below was seen on screen or confirmed in the code, not guessed.

Tiers:
- **Critical:** broken, misleading, or a missing essential state.
- **High Impact:** clarity, hierarchy and friction.
- **Nice to Have:** polish.

---

## 1. Critical: launch blockers and broken flows

### [x] C1. The progress ring for a queued look is pinned to the picture's top-left corner
- **Pass:** [Pass 1 - Designer]
- **Location:** `studio/web/app.css` rule `.frame .wait`; markup in `app.js` `renderViewer()` (the "Waiting to make …" overlay)
- **The Problem:** The overlay and the ring share the class name `wait`. The overlay rule (`position: absolute; inset: 0`) also matches the ring, so it shrinks to a 64 px disc stuck in the corner. Meanwhile "Waiting to make Prime Time" floats in the centre with no indicator above it. It reads as a rendering glitch, at exactly the moment the user is waiting and judging whether the app is working. Measured: ring box = overlay box = 262,106 64 × 64.
- **Actionable Fix:** Scope the overlay rule to the overlay only (`.frame > .wait`), so the ring stays centred above the text.

### [x] C2. "Make" silently makes the same looks again
- **Pass:** [Pass 2 - User]
- **Location:** `studio/web/app.js` `renderMake()` and `make()`; Looks panel → **Make N looks**
- **The Problem:** After the looks are made, the picks stay selected and the big blue button still says **Make 3 looks**. A first-time user who presses it again thinking "did that work?" gets three identical copies in the strip. Nothing says the looks already exist, and the time estimate still promises "about 40 s" of work that was already done.
- **Actionable Fix:**
  - Count only the picked looks not yet made for the chosen photos with the current framing.
  - The button says **Make 2 new looks**, and the summary says how many are already made.
  - When every pick already exists, the button turns secondary and reads **Make again**, so a re-run is a deliberate choice.

### [x] C3. Dropping or pasting a file that isn't a photo does nothing at all
- **Pass:** [Pass 2 - User]
- **Location:** `studio/web/app.js` `upload()`; drag-and-drop and ⌘V anywhere on the window
- **The Problem:** Non-photos are filtered out and the function returns with no message. Files the server can't read come back as `added: []`, also with no message. Example: drop a video, a PDF or a corrupted JPG and nothing happens. The user can't tell a wrong file from a broken app, which is the worst kind of dead end.
- **Actionable Fix:**
  - Say which files were left out and why, e.g. "notes.txt isn't a photo. JPG, HEIC, PNG and RAW work."
  - When the server keeps fewer than were sent, say "2 of 5 couldn't be read".

### [x] C4. The Culling tab is a blank black screen while it loads
- **Pass:** [Pass 2 - User]
- **Location:** `studio/web/cull.js` `renderCull()` (first build)
- **The Problem:** The tab's frame is built at once, but its contents wait for the event list and photos to load. For about 2 seconds the user sees an empty black panel with only the key legend at the bottom. It looks broken, so first-time users click away.
- **Actionable Fix:** Show a loading line ("Opening your events…" with a spinner) in the empty panels until the first paint replaces it.

### [x] C5. Escape doesn't close the Export dialog (found while checking the Nice to Have fixes)
- **Pass:** [Pass 2 - User]
- **Location:** `studio/web/app.js`: `modal()` (where the cursor starts) and the window key handler
- **The Problem:**
  - The dialog opened with the cursor on the "Add my logo" switch.
  - The key handler ignores every key while the cursor is in a field, so Escape did nothing and the user was stuck until they found Cancel.
  - The first audit walk-through also got stuck right here.
- **Actionable Fix:**
  - Escape closes any open dialog, wherever the cursor is.
  - Dialogs start with the cursor on their first visible main button or text box. Never a switch or tick box, and never one inside a folded section.

---

## 2. High Impact: craft, clarity and polish

### [x] H1. Copy says "game" where the product says "event"
- **Pass:** [Pass 1 - Designer]
- **Location:**
  - `app.js` empty state "Start with your game photos"
  - `index.html` add menu "A whole game"
  - `check.js` cards "Shoot better next game" and "Compare cameras, settings or games"
- **The Problem:** Culling, the docs and the rest of the UI call a set of photos an *event*. A tournament, a practice or a portrait day isn't a "game", so mixed vocabulary reads as unfinished.
- **Actionable Fix:** Change these to "event" ("Start with your event photos", "A whole event", "Shoot better next time", "Compare cameras, settings or events").

### [x] H2. The empty app shows the same "Add photos" call to action twice, with awkward copy
- **Pass:** [Pass 1 - Designer]
- **Location:** `index.html` `#rail-empty`; `app.js` `render()` (where `#rail-empty` is shown)
- **The Problem:** On the empty Looks screen, the left rail repeats "Add photos… / Add a folder…" right next to the hero card's own primary buttons. Two competing calls to action split attention, which Linear and Raycast never do. The rail's sentence also wraps mid-thought: "Drop photos anywhere, paste with ⌘V, or".
- **Actionable Fix:**
  - On Looks, where the hero card already carries the action, the rail says only "No photos yet. Drop them anywhere or paste with ⌘V."
  - The rail's buttons stay on Reel, which has no hero card.

### [x] H3. Sliders whose zero isn't in the middle look already changed
- **Pass:** [Pass 1 - Designer]
- **Location:** `studio/web/edit.js` slider markup (`input[type=range][data-k]`); `app.css` range styles
- **The Problem:** "Background brightness" reads **0.00 ev**, but its thumb sits at about 65% of the track because the range is lopsided. With no marker, a user can't see where "no change" is, or that a slider is untouched. Lightroom and Capture One mark the zero point.
- **Actionable Fix:**
  - On every slider that runs from negative to positive, draw a small tick under the track at zero.
  - Double-click already resets to it (keep that); say so in the slider's tooltip.

### [x] H4. Corner radii drift across ten values
- **Pass:** [Pass 1 - Designer]
- **Location:** `studio/web/app.css` (2, 3, 4, 5, 6, 7, 8, 9, 10 and 12 px all in use)
- **The Problem:** Neighbouring controls with 7, 8 and 9 px corners make the surface feel hand-assembled rather than built from one system. It's the "vibe-coded" tell the brief asks about.
- **Actionable Fix:** Snap the odd values onto one scale (2 · 4 · 6 · 8 · 10 · 12): 3 → 4, 5 → 6, 7 → 6 or 8, 9 → 8. It's a mechanical, visual-only change.

---

## 3. Nice to Have: delight and micro-interactions (done in a second pass)

### [x] N1. Type scale has 20 sizes, including half pixels
- **Pass:** [Pass 1 - Designer]
- **Location:** `app.css` (10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5 px…)
- **The Problem:** Too many near-identical sizes blur the hierarchy.
- **Actionable Fix:** Collapse to about seven steps (11 · 12 · 13 · 15 · 19 · 26 · 34) with tokens. Do it in a dedicated pass with a visual check of every panel: changing text widths can re-break tight bars like the crop bar.

### [x] N2. The header's Tools menu jumps sideways on the Culling tab
- **Pass:** [Pass 2 - User]
- **Location:** `app.css` `.cull-mode #export-btn { display: none; }`
- **The Problem:** Culling has its own export, so the header's Export button is removed, and Tools shifts right when switching tabs.
- **Actionable Fix:** Reserve the space (`visibility: hidden`) or put Culling's own export in that slot.

### [x] N3. Look cards show initials on a gradient until their sample is made
- **Pass:** [Pass 1 - Designer]
- **Location:** `app.js` `renderLooks()` (cards without an example image)
- **The Problem:** "PT", "GH" on green blocks reads as a placeholder.
- **Actionable Fix:** A neutral shimmer skeleton, or a bundled sample photo per look.

### [x] N4. The looks list keeps its scroll position after Make
- **Pass:** [Pass 2 - User]
- **Location:** `app.js` `renderLooks()`
- **The Problem:** The group title can be scrolled out of view, so the picked badges are partly hidden.
- **Actionable Fix:** Scroll the first picked look into view after Make.

---

## Checked and fine (no change)
- **Undo/redo:** on every Edit tool bar, plus ⌘Z / ⇧⌘Z.
- **Before/after:** C or the split handle, with Before/After tags.
- **Errors from the server:** shown as a toast (`api()`).
- **A picture that fails to load:** offers Retry (`watchPicture`).
- **Disabled buttons:** say why when clicked (`explain()`).
- **Export:** a clear dialog, with the AI enlarger reported afterwards.
- **Shortcuts:** "?" opens the list.
- **Reel's empty state:** explains itself ("Make some looks first.").
- **Check:** has a full empty state with steps.

---

## Summary of what changed

All four Critical and all four High Impact items are fixed. 203 automated tests pass. A scripted check in the running app passed 14 of 14: C1, C2, C3, H1, H2 and H3, no page errors, and C4 (tested with Culling's data slowed on purpose, since on a quiet Mac it loads too fast to see). The full app was walked through again before and after.

Changes by item:
- **C1** `app.css`: the overlay rule is `.frame > .wait`, so the ring is centred.
- **C2** `app.js`: `renderMake()` counts looks already made (same photo, look and framing).
  - The button reads "Make N new looks" and the summary says how many are already made.
  - When every pick exists, the button turns secondary and reads "Make again".
  - `make()` sends only the new ones unless it's a deliberate re-run.
- **C3** `app.js`: `upload()` names files that aren't photos, and says when some couldn't be read.
- **C4** `cull.js` / `app.css`: "Opening your events…" shows until Culling's first paint.
- **H1** `app.js`, `index.html`, `check.js`: "game" → "event".
- **H2** `index.html`, `app.js`, `app.css`: the rail on the empty Looks screen is one quiet line; its buttons appear only on Reel.
- **H3** `edit.js`, `app.css`:
  - Every negative-to-positive slider has a tick at zero.
  - Its tooltip says "double-click to reset".
- **H4** `app.css`: radii snapped to 2 · 4 · 6 · 8 · 10 · 12.

**Second pass: the Nice to Have items, plus one more Critical found while testing them.**
- **C5** `app.js`:
  - Escape closes any dialog.
  - Dialogs open with the cursor on their main button (Export: Enter exports).
- **N1** `app.css`: one type scale, 10 · 11 · 12 · 13 · 14 · 15 · 16 · 17 · 19 · 22 · 26 · 34 px, with no half pixels. It's written at the top of the file. The tool-bar overflow test still passes 32 of 32 at three window sizes.
- **N2** `app.css`: the header's Export space is kept on Culling, so Tools no longer jumps.
- **N3** `app.js` / `app.css`: look tiles without a sample are a calm tinted tile without initials. They shimmer only while their preview is being made.
- **N4** `app.js`: after Make, the first picked look is scrolled into view.

The second pass's checks passed 5 of 5, plus 2 of 2 for Escape and the starting cursor, and all 203 automated tests pass.

Restore point: `git checkout pre-ui-audit` returns to the version before this audit.

### Please check by eye in the app (restart it first)
1. Make two or three looks: while they wait, the ring sits **centred above** "Waiting to make …".
2. Press **Make** again with the same picks: it should say **Make again** (grey), not offer three new looks.
3. Drop a non-photo (a PDF or text file) on the window: a note names it.
4. Open **Culling**: "Opening your events…" shows for a moment instead of black.
5. **Edit → Background brightness**: a small tick marks zero under the track.
6. Glance over the panels for the slightly tidier corners and the even text sizes: nothing should look out of place.
7. **Export → Escape** closes the dialog; **Enter** exports.
8. Switch to **Culling** and back: Tools stays where it is.
