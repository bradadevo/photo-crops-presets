# Culling audit

The Culling tab of VS Digital Pro, audited on 2026-11-24 from the source (`cull.js`, `cull.py`,
`photo_presets/cull/`) and from a scripted walkthrough in Chrome (`tests/ui/cull_walk.py`).

**The walkthrough setup:**
- A test copy of the app, on a scratch folder of 349 photos: copies of the Lake Nona and PSG event
  photos (JPEG + 27 RAW), padded with renamed copies.
- Window sizes 1440 × 900 and 1280 × 800.
- Restore point: the git tag `pre-culling-audit`.

**Safety during the audit:**
- No real photo was touched, and the camera card (kingston256, 9 photos) was only listed.
- Gemini was never called.

**Commits:**
- `db7f4e2`: the delete box (folder, ORIGINAL or copy);
- `cf6881f`: the audit fixes.

**Two passes:**
- **Pass 1 – Designer:** a ruthless product-design read.
- **Pass 2 – Shooter:** an 11 pm shooter after a tournament weekend, and a first-time parent or
  volunteer.

---

## 1. Critical: broken flows and safety risks

- [x] **Card import writes over a different photo that has the same name** `[Pass 2 - Shooter]`
  - **Location:** `cull/files.py` `import_card`
  - **The problem:** Two cameras, or one camera whose numbers start again at DSC00001, give two
    different photos one name. The second import replaced the first card's photo in the import folder
    (`tmp.replace(target)`). Proven on scratch files: the first photo was gone. That copy is often the
    only one once the card is formatted.
  - **Actionable fix:** Never write over a file. A different photo with a name already used gets a new
    name, and its JPEG and RAW get it together (`DSC00001-2.JPG` / `.ARW`). Re-importing the same card
    still skips what is already there.
- [x] **Card import skips a different photo of the same name and size** `[Pass 2 - Shooter]`
  - **Location:** `cull/files.py` `import_card`
  - **The problem:** "Already copied" meant the same name and the same size. Uncompressed RAW files
    are all one size, so a new photo could be silently left on the card.
  - **Actionable fix:** "Same photo" now means the same size and the same bytes at the start and the
    end of the file (`same_file`). That covers the camera data and the time to 1/100 s.
- [x] **Export writes one keeper over another with the same file name** `[Pass 1 - Designer]`
  - **Location:** `studio/cull.py` `export_keepers`, `cull/export.py` `edit_one`, `copy_files`
  - **The problem:** In an event made of two folders (two cameras) that both have DSC00001,
    "Crop them for posting" saved both keepers as `DSC00001_natural.jpg`. The second replaced the
    first, so you got fewer pictures than keepers with no warning. "Copy them as they are" skipped the
    second photo when the sizes matched.
  - **Actionable fix:** Each keeper in one export gets its own name (`DSC00001-2_natural.jpg`). A copy
    is skipped only when it is the same bytes.
- [x] **Delete rejects trusted the browser's list** `[Pass 1 - Designer]`
  - **Location:** `studio/cull.py` `trash`
  - **The problem:** The server moved whatever ids the page sent, without checking they were still
    rejects. A keep made in another window, a mark still on its way, or pass 1 run again could put a
    keeper in the Trash.
  - **Actionable fix:** At the moment of deleting, the server re-checks each photo's mark (yours, else
    pass 1's) and moves only rejects. Any other photo is left alone, and the page says so.
- [x] **Delete rejects said "Moved" for photos it couldn't move, and could split a JPEG from its RAW**
  `[Pass 1 - Designer]`
  - **Location:** `studio/cull.py` `trash`, `cull.js` `cuDeleteRejects`
  - **The problem:** A file that couldn't be moved (a read-only drive, a file open elsewhere) was still
    hidden on screen and counted as moved. When only the RAW failed, the JPEG was in the Trash and the
    RAW in the folder.
  - **Actionable fix:** The server returns exactly which photos went. If one file of a pair fails, the
    other is put back, so a pair never splits. The page hides only what went and shows a lasting
    warning naming any photo that stayed ("nothing lost").
- [x] **A mark that failed to save was silently dropped** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuSet`, undo
  - **The problem:** `api(...).catch(() => {})`: when the app was busy or restarting, the mark showed
    on screen but was never saved. After a restart it was gone, and you'd never know.
  - **Actionable fix:** Marks go into a save queue (`cuSave` / `cuFlush`) and are retried in order
    until saved. After two failures a lasting note says "N marks not saved yet… leave this window
    open", and "Your marks are saved" follows when they are. Closing the window with marks unsaved
    asks first.
- [x] **A background refresh could undo a just-made mark on screen** `[Pass 1 - Designer]`
  - **Location:** `cull.js` `cuPhotos`
  - **The problem:** The page refreshes every 1–4 s. A refresh that left before your mark arrived
    replaced the photo with the old mark: the mark flipped back for a few seconds, and ⌘Z could then
    record the wrong "before".
  - **Actionable fix:** Marks on their way stay laid over whatever a refresh brings, until the app
    has them.
- [x] **"That's every photo pass 1 was unsure about" after 17 of 222** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuSort`, `cuEndOfList`
  - **The problem:** In **Pass 1 unsure**, bursts were still stacked, so most close calls hid inside
    stacks. The shooter believes the close calls are done, and **Delete rejects** then removes frames
    they never saw.
  - **Actionable fix:** **Pass 1 unsure** shows every unsure frame, unstacked. At the end of **Not
    checked by you**, the note counts the frames still inside bursts and offers **Show every frame**.
- [x] **The export folder name could be any path** `[Pass 1 - Designer]`
  - **Location:** `studio/cull.py` `_out_folder`
  - **The problem:** The Finish page's folder box was joined as a path. `../..` or `/…` wrote copies
    or edits outside the event, and an empty name wrote into the event folder itself, among the
    originals.
  - **Actionable fix:** The box is only ever a folder name, next to the photos (slashes and `..`
    removed). Empty becomes `Picks`.

## 2. High impact: speed, trust and clarity

- [x] **The delete box didn't say where files are deleted from, or that they are the originals**
  `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuDeleteRejects`, the Finish page, `studio/cull.py` `trash_preview`
  - **The problem:** "11 photos move to the Trash" didn't say which folder, or whether they were the
    camera originals or copies.
  - **Actionable fix:** Done in `db7f4e2`, before this audit:
    - The box names each folder (with **Show in Finder**), JPEG + RAW counts and every file name.
    - It says **ORIGINAL photos** or **copies, not your originals**, with the reason for each copy.
    - The button reads "Move N originals to Trash".
- [x] **The gallery re-made every thumbnail on each refresh** `[Pass 1 - Designer]`
  - **Location:** `cull.js` `cuPaintGrid`
  - **The problem:** Every refresh (each second while pass 1 works) and every mark rebuilt all visible
    tiles with `innerHTML`. Pictures blinked, and the work grew with tile count.
  - **Actionable fix:** Tiles are kept and only the ones that changed are made again. Measured below:
    0 tiles re-made while idle.
- [x] **The big photo waited on every other →** `[Pass 1 - Designer]`
  - **Location:** `cull.js` `cuPaintMain`
  - **The problem:** Only the next photo was preloaded. Holding → through a burst alternated between
    0.01 s and 0.2 s waits (measured).
  - **Actionable fix:** The next three are preloaded (and the one before), once each.
- [x] **100% zoom on a RAW-only photo took 3.6 s** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuPaintMain`, `studio/cull.py` `_full_image`
  - **The problem:** A RAW is developed at full size only when you press Z (about 3 s). Checking
    focus on RAW-only frames dragged.
  - **Actionable fix:**
    - After 0.6 s on a big photo, its full size starts getting ready.
    - Each photo is developed once (a second ask waits for the first rather than starting again).
    - The last three are kept.

    Measured: 3.6 s → 1.7 s after a 2.5 s look, and instant after about 4 s. JPEG zoom was already
    instant.
- [x] **Losing your place after marking in a filtered list** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuSort`
  - **The problem:** In **Pass 1 unsure** or **Not checked by you**, the photo you marked leaves the
    list on the next refresh. With "Next after marking" off, or after a click, you were thrown back to
    the first photo of the list.
  - **Actionable fix:** When the current photo leaves the list, you move to the next one that is
    still there (else the one before), never back to the start.
- [x] **The toolbar wraps to two rows, and step names vanish** `[Pass 1 - Designer]`
  - **Location:** `app.css` `.cu-bar`, `cull.js` `cuPaintBar`
  - **The problem:** At 1440 × 900 the Finish button wrapped to a second row. At 1280 × 800 the steps
    shrank to bare "1 2 3", which a first-time parent can't read.
  - **Actionable fix:** One row always. The extras give way first:
    - the counts;
    - step 3, which the Finish button repeats;
    - the keeper count on Finish;
    - the Spray can label, which keeps its tooltip;
    - the word "rejects" on Delete, so it reads "Delete (326)". It never shrinks to a bare red count.

    The step names only hide below 600 px.
- [x] **Notes pile up over the photo's buttons and over dialogs** `[Pass 2 - Shooter]`
  - **Location:** `app.js` `toast`, `app.css`
  - **The problem:** Holding → at the end of a list stacked three identical "That's every photo…"
    notes over Keep / Reject. One note covered a dialog's Cancel button (the walkthrough couldn't
    click it).
  - **Actionable fix:**
    - The same note again replaces the one showing.
    - At most three short notes show at once.
    - While a dialog is open, notes move to the top.
- [x] **"? all keys" didn't show all keys, and jargon went unexplained** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuHelp`
  - **The problem:** Missing keys:
    - U (back to pass 1's mark), 6–9 labels, L, B, R, M;
    - Home / End, ⌘A, redo.

    A first-time parent never learns what "pass 1", "burst" or "taste" mean.
  - **Actionable fix:** **Every key** is a table in the help, followed by a short **Words** paragraph:
    pass 1, burst, your taste.
- [x] **The import box didn't say the card is left alone** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuImport`
  - **The problem:** A first-timer fears that importing moves or erases the card.
  - **Actionable fix:** It says photos are **copied**, nothing on the card is changed or deleted, and a
    same-named photo from a second camera gets a new name.

## 3. Nice to have: polish (not done)

- [ ] **Two old copies of the compare code** `[Pass 1 - Designer]`
  - **Location:** `cull.js`, the first `cuCompareIds` / `cuPaintCompare`
  - **The problem:** Dead code from before Survey, which the later definitions replace.
  - **Actionable fix:** Delete it.
- [ ] **The pickiness slider has no reading** `[Pass 2 - Shooter]`
  - **Location:** `cull.js` `cuPass1`
  - **The problem:** No sense of how many photos a setting will keep.
  - **Actionable fix:** Show "about N keepers" live as it moves.
- [ ] **The floating Make bar covers the folder box** `[Pass 1 - Designer]`
  - **Location:** `app.css` `.cu-make`
  - **The problem:** "Where they go" sits under the Make bar until you scroll to the end.
  - **Actionable fix:** Put the folder line inside the Make bar.
- [ ] **A long folder path in "Clear out the rejects"** `[Pass 1 - Designer]`
  - **Location:** `cull.js` `cuPaintFinish`
  - **The problem:** A deep path wraps over three lines.
  - **Actionable fix:** Show the folder's name plus **Show in Finder**; the full path in the tooltip.
- [ ] **Delete rejects is always on the toolbar, in red** `[Pass 1 - Designer]`
  - **Location:** `cuPaintBar`
  - **The problem:** A destructive button sits in the main bar the whole time.
  - **Actionable fix:** Consider showing it only on Finish. It is safe today, behind the explicit box
    and undo.
- [ ] **The "Pass 1 is done!" box takes the keyboard** `[Pass 2 - Shooter]`
  - **Location:** `cuReveal`
  - **The problem:** Space on its focused button starts **Your pass**.
  - **Actionable fix:** Let P / X / → close it and act.
- [ ] **The score on each tile is unexplained** `[Pass 2 - Shooter]`
  - **Location:** `cuTile`
  - **The problem:** "48" means nothing to a parent.
  - **Actionable fix:** Tooltip "Pass 1's score out of 100".
- [ ] **The thumbnail size slider has no label** `[Pass 1 - Designer]`
  - **Location:** `cuPaintKeys`
  - **The problem:** Only an icon.
  - **Actionable fix:** Add "Size".

---

## Summary

### What changed

- **Import from a card:** never writes over a photo and never skips a new one.
  - A same-named photo from a second camera gets a new name, with its RAW.
  - "Already copied" means the same bytes.
- **Export:**
  - Every keeper gets its own file, even with two cameras' same names.
  - The folder box is only ever a name next to the event, never a path.
- **Delete rejects:**
  - The box names the folder and says ORIGINAL or copy (`db7f4e2`).
  - The server re-checks each is still a reject, moves only those, and never splits a JPEG from its
    RAW.
  - The page shows exactly what went and what couldn't.
- **Marks:**
  - Saved in order with retry, and a visible note if the app isn't answering.
  - Never flipped back by a refresh.
  - You keep your place when a marked photo leaves a filtered list.
- **Pass 1 unsure:** shows every close call (none hidden in burst stacks). The end of **Not checked
  by you** says how many frames are still inside bursts.
- **Speed:**
  - The gallery only redraws tiles that changed.
  - Three big photos are preloaded ahead.
  - The full size is got ready while you look.
- **Clarity:**
  - The toolbar stays one row at 1280 and 1440.
  - Notes don't pile up or cover dialogs.
  - Help lists every key and explains pass 1, burst and taste.
  - The import box says the card is never changed.

Files: `cull/files.py`, `cull/export.py`, `studio/cull.py`, `studio/web/cull.js`, `studio/web/app.js`
(notes), `studio/web/app.css`, tests.

### Test results

- `uv run pytest`: **247 passed**. New tests:
  - card import never writes over or skips a photo;
  - export of same-named keepers from two folders;
  - the folder name can't be a path;
  - delete moves only what is still a reject;
  - the delete box's preview.
- `tests/ui/delete_click.py` (Chrome, a test copy with its own Trash): **ALL OK**. It covers the
  folder, ORIGINAL vs copy, the counts, undo, and a folder of copies.
- `tests/ui/cull_walk.py` on 349 scratch photos, 1440 × 900 and 1280 × 800:

  | Check | 1440 | 1280 |
  |---|---|---|
  | First thumbnail after adding the folder | 1.0 s | |
  | Pass 1 done (349 photos) | 162 s | |
  | Thumbnails re-made while idle (before: every visible one, each second) | 0 | 0 |
  | Thumbnails re-made by one mark | 5 | 5 |
  | The mark saved by the app | yes | yes |
  | Toolbar height (one row) | 53 px | 53 px |
  | Next big photo, each | 0.01–0.03 s, about 0.15 s every fourth | 0.01–0.03 s |
  | Unsure shown / unsure counted | 221 / 221 | 221 / 221 |
  | Notes after pressing → three times at the end | 1 | 1 |
  | Page errors | none | none |

### Checks to do yourself on a real event

1. **Import a card twice.** The second time should say "N were already copied" and add nothing. If
   you have two cameras, import both cards into one folder and check no photo is missing (a
   same-named one becomes `DSC00001-2.JPG` next to its `.ARW`).
2. **Your pass on Pass 1 unsure.** Hold → through it. The count on the left should match what you
   step through. P / X should move on, with no flicker in the gallery.
3. **Quit the app mid-pass** (or turn off Wi-Fi if the app runs remotely) and mark a few. A red
   "not saved yet" note should appear, then "Your marks are saved" once it's back.
4. **Delete rejects.** Read the box: the folder, ORIGINAL, the counts. Delete, then ⌘Z, and check
   the files are back in Finder.
5. **Finish → Crop them for posting** with an event made of two camera folders. The output folder
   should hold one picture per keeper.
6. **At your laptop size,** check the top bar is one row and readable.

Not done (Nice to Have, above): the pickiness preview, the old compare code, the Make bar covering the
folder box, and the rest.
