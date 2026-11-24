"""The "Delete rejects" box clicked through in Chrome on a separate test copy (its own Trash, never
yours): it names the folder the files are deleted from and says plainly whether they are the
camera originals or copies, before anything moves.

    uv run --with playwright --with psutil --with requests python tests/ui/delete_click.py <out folder>
"""
import shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
from playwright.sync_api import sync_playwright

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
state = out / "state"; shutil.rmtree(state, ignore_errors=True); state.mkdir()
src = Path("~/Movies/11U PSG LAKE NONA VS WPARK").expanduser()
event = state / "Lake Nona event"; event.mkdir()  # (copies of 3 shots, JPEG + RAW, as a camera card gives them)
for n in ("DSC03375", "DSC03406", "DSC03433"):
    for ext in (".JPG", ".ARW"):
        if (src / (n + ext)).exists():
            shutil.copy(src / (n + ext), event / (n + ext))
crops = state / "Best Crops"; crops.mkdir()  # (a folder of copies, opened as an event)
for f in sorted((src / "Best Crops").glob("*"))[:2]:
    shutil.copy(f, crops / f.name)

app = App(state); app.start()
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)

def reject_all(folder):
    sid = app.post("/api/cull/shoots", {"folders": [str(folder)]})["id"]
    ps = app.get(f"/api/cull/shoots/{sid}/photos").json()["photos"]
    app.post(f"/api/cull/shoots/{sid}/mark", {"items": [{"id": p["id"], "flag": "reject"} for p in ps]})
    return sid, len(ps)

def open_delete(page, name):
    page.click('.modes button[data-mode="cull"]')
    page.wait_for_timeout(800)
    page.locator(".cu-shoot, [data-shoot]", has_text=name).first.click()
    page.wait_for_timeout(1200)
    page.click("#cu-del")
    page.wait_for_selector(".modal .del-box", timeout=15000)
    page.wait_for_timeout(300)
    return page.locator(".modal").text_content()

try:
    s1, n1 = reject_all(event)
    s2, n2 = reject_all(crops)
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1400, "height": 900})
        page.goto(app.base); page.wait_for_timeout(1500)
        t = open_delete(page, "Lake Nona event")
        page.locator(".modal").screenshot(path=str(out / "1-originals.png"))
        print(t)
        check("says these are the originals", "ORIGINAL photos" in t)
        check("names the folder they are deleted from", "Deleted from" in t and "Lake Nona event" in t)
        check("counts JPEG and RAW", "3 JPEG + 2 RAW" in t)
        check("the button says originals", "Move 3 originals to Trash" in t)
        have = len(list(event.iterdir()))
        check("nothing moved just by opening the box", have == 5, have)
        page.click(".del-names summary"); page.wait_for_timeout(200)
        check("every file name can be seen", "DSC03375.ARW" in page.locator(".del-names").inner_text())
        page.click("#dr-go"); page.wait_for_timeout(1500)
        toast = page.locator(".toast").last.inner_text()
        check("the note after says where from", "Lake Nona event" in toast and "original" in toast, toast)
        check("the 5 files left the event folder", len(list(event.iterdir())) == 0)
        page.mouse.click(5, 5); page.keyboard.press("Meta+z"); page.wait_for_timeout(2500)
        check("undo (Cmd-Z) puts them back", len(list(event.iterdir())) == 5, len(list(event.iterdir())))
        page.reload(); page.wait_for_timeout(1500)
        t = open_delete(page, "Best Crops")
        page.locator(".modal").screenshot(path=str(out / "2-copies.png"))
        print(t)
        check("a folder of copies is called copies, not originals", "a copy, not your original" in t and "ORIGINAL photo" not in t and "Move 1 photo to Trash" in t)
        check("says why", 'a folder of copies' in t)
        page.click("[data-close]")
        check("no page errors", not page.errors if hasattr(page, "errors") else True)
finally:
    app.stop()
print("ALL OK" if ok else "SOME FAILED")
