# Assessor audit

The **Assessor** tab of VS Digital Pro (named "Check" until this audit; `check` in the code), audited on
2026-11-24 to the same standard as [CULLING_AUDIT.md](CULLING_AUDIT.md).

**Sources:**
- The code: `studio/check.py`, `studio/web/check.js`, `clipcheck/`.
- A scripted walkthrough in Chrome (`tests/ui/check_walk.py`): a test copy of the app, a scratch
  folder of copies (2 clips; 4 photos including a JPEG and its own RAW), at 1440 × 900 and
  1280 × 800.

**Safety:**
- Restore point: the git tag `pre-check-audit`.
- No real file was touched, and no Gemini was called. The Assessor uses no AI.

**Two passes:**
- **Pass 1 – Designer:** a ruthless product-design read.
- **Pass 2 – Shooter:** a coach or parent who wants to know "why does my clip look bad, and what do
  I change?"

---

## 1. Critical: broken flows and safety risks

- [x] **Two fixed copies made at once could share a name, so one replaced the other**
  `[Pass 2 - Shooter]`
  - **Location:** `clipcheck/fixes.py` `fixed_path`
  - **The problem:** The name was chosen when a fix started but the file only appeared when it ended.
    A JPEG and its RAW (one name, a very common pair after **Add a folder**) fixed together were both
    written to `DSC03375 fixed.jpg`. Proven in the walkthrough.
  - **Actionable fix:** The name is taken the moment it is chosen (an empty file, created only if no
    file is there). The second gets `DSC03375 fixed 2.jpg`. A failed fix removes only its own file.
- [x] **Two dropped files with one name became one** `[Pass 2 - Shooter]`
  - **Location:** `studio/check.py` `upload`
  - **The problem:** Dropping `same.JPG` from two folders wrote both into one file. The first was
    lost, and the list showed a single entry assessing the wrong photo. Proven in the walkthrough.
  - **Actionable fix:** The second gets `same (2).JPG`, so both are kept and both are assessed.
- [x] **A second report in the same minute replaced the first** `[Pass 1 - Designer]`
  - **Location:** `studio/check.py` `export`
  - **The problem:** Reports are named to the minute (`… - 2026-11-24 1745.docx`). Exporting the
    ticked files, then all of them, within a minute wrote over the first report. Proven.
  - **Actionable fix:** A report whose name is taken gets ` (2)`, ` (3)`… (Word and spreadsheet
    together).

## 2. High impact: speed, trust and clarity

- [x] **The list said "Looks good" while "In short" said "Fix now"** `[Pass 2 - Shooter]`
  - **Location:** `studio/check.py` `_row`, `check.js` `ckStatus`
  - **The problem:** The list counted problems; **In short** used the verdict. clip1 read "Looks good"
    on the left and "Good, with a quick fix · Fix now: Neutral color" on the right. Two answers make
    a shooter trust neither.
  - **Actionable fix:** The list shows the same verdict as **In short** (green ready, blue quick fix,
    amber needs attention). Checked on all 8 files.
- [x] **"No problems found" sat above a timeline full of problem moments** `[Pass 2 - Shooter]`
  - **Location:** `check.js` `renderCkMain`
  - **The problem:** A video with brightness jumps, soft pans and shake still said "No problems
    found."
  - **Actionable fix:** With problem moments, the card is **What's holding it back** and starts with
    "3 moments to look at: brightness jumps, soft while panning, shaky camera".
- [x] **A JPEG compared with its own RAW was called "weakest" on sharpness** `[Pass 1 - Designer]`
  - **Location:** `studio/check.py` `compare`
  - **The problem:** "DSC03375.JPG's sharpest detail is 3.7x crisper than DSC03375.ARW's". The camera
    sharpens its JPEG and the RAW is measured as it comes. It is the same shot, so the comparison
    misleads.
  - **Actionable fix:** The first note says it is the same photo, and why the RAW measures softer
    ("not a real difference in the shot").
- [x] **Double-clicking a slider did nothing** `[Pass 1 - Designer]`
  - **Location:** `check.js` `renderCkSide`
  - **The problem:** The code meant to put a fix back to its suggested value, but read a value the
    server never sent.
  - **Actionable fix:** The server sends each fix's suggested value. Double-click works, and its
    tooltip says so.
- [x] **Copies of dropped files piled up on disk, out of sight** `[Pass 2 - Shooter]`
  - **Location:** `studio/check.py` (`check-added`), `check.js`
  - **The problem:** A dropped video is copied into the app's settings folder and was kept forever,
    even after you took it out of the list. Gigabytes could build up where nobody looks.
  - **Actionable fix:** When you take a dropped file out of the list, the app's own copy goes to the
    Trash the next time the app starts. Undo works until then, and your original is never touched.
    The note and the guide say so.
- [x] **The section numbers were 2, 3, 4 with no 1** `[Pass 2 - Shooter]`
  - **Location:** `check.js`
  - **The problem:** "2 How it looks", "3 Fix this file", "4 Next time": a first-timer looks for
    step 1.
  - **Actionable fix:** The numbers are gone from the file page; the guide keeps its numbered steps.
- [x] **The tab's name** (your request)
  - **Location:** `index.html`, `app.js`, `check.js`, README, `AI.md`
  - **Actionable fix:** **Assessor** everywhere on screen: the tab, Tools → Assessor, the panel title,
    the guide, the drop text. The code keeps `check`.

## 3. Nice to have: polish (not done)

- [ ] **The file list is rebuilt on every refresh while files are checked** `[Pass 1 - Designer]`
  - **Location:** `check.js` `renderCkFiles`
  - **The problem:** The time left changes each 0.9 s, so the whole list is redrawn. Thumbnails may
    blink. This was not measured: the walkthrough's added file was already in the list.
  - **Actionable fix:** Keep the rows; update only the status text, as Culling's gallery now does.
- [ ] **The row tooltip shows the whole path and covers the rows below** `[Pass 1 - Designer]`
  - **Location:** `renderCkFiles`
  - **The problem:** A deep path wraps over four lines.
  - **Actionable fix:** Show `~/…/folder/name`.
- [ ] **No keys** `[Pass 2 - Shooter]`
  - **Location:** `check.js`
  - **The problem:** ↑ / ↓ don't move through files.
  - **Actionable fix:** ↑ ↓ for files, Space for before/after.
- [ ] **The top bar's Export button shows, greyed out** `[Pass 1 - Designer]`
  - **Location:** `app.js` `renderTop`
  - **The problem:** Two "Export" buttons on one screen, one dead.
  - **Actionable fix:** Hide the Looks export on this tab.
- [ ] **The before/after line is only a mouse drag** `[Pass 1 - Designer]`
  - **Location:** `paintCkViewer`
  - **Actionable fix:** Hold to compare (as in Looks) and ← → nudges.

---

## Summary

### What changed

- **Nothing written by the Assessor can replace another file:**
  - fixed copies take their name at once;
  - dropped files with one name are both kept;
  - reports in one minute each get their own name.
- **One verdict everywhere.** No "No problems found" above problem moments. A JPEG against its RAW is
  explained.
- **Housekeeping:**
  - Double-click a slider to go back to its suggested value.
  - The app's own copies of dropped files go to the Trash once taken out of the list.
  - The stray section numbers are gone.
- **The tab is called Assessor.**

Files: `clipcheck/fixes.py`, `studio/check.py`, `studio/web/check.js`, `studio/web/app.js`,
`studio/web/index.html`, `studio/web/app.css`, README, `AI.md`, tests.

### Test results

- `uv run pytest`: **248 passed**. New: two fixed copies made at once never share a name.
- `tests/ui/check_walk.py` (Chrome, a test copy, scratch copies, 1440 × 900 and 1280 × 800):
  **ALL OK**. It covers:
  - all 6 files checked (in 5 s);
  - a JPEG and its RAW fixed together give two files;
  - two dropped `same.JPG` stay two;
  - two reports in one minute stay two;
  - the list and **In short** agree on all 8 files;
  - JPEG vs RAW explained;
  - no "No problems found" above problem moments;
  - the tab reads Assessor;
  - no page errors at either size.

  The first run, before the fixes, failed the three overwrite checks: the proof.

### Checks to do yourself

1. Add a folder that has JPEG + RAW pairs. Fix both of one pair at once (turn on a fix on each and
   press **Make a fixed copy** on both). `Clip Analysis/Fixed` should hold two files.
2. Open a shaky or pumping clip. The list and **In short** should say the same thing, and **What's
   holding it back** should name the moments.
3. Drop a clip on the window, take it out of the list, quit and reopen the app. The app's copy should
   be in the Trash, and the original where it was.
4. Export a Word report twice in a row. You should get two files.
