"""The Assessor assesses only when asked: adding a file shows it (picture, quick facts, how long assessing
would take) but starts nothing; Assess, Assess (n), Assess all and Stop do what they say; and after a
restart, files not assessed stay that way while assessed ones come back from their results.
Clicked through in Chrome on a separate test copy, on a scratch folder of COPIES (never your own folders).

    uv run --with playwright --with psutil --with requests python tests/ui/assess_click.py <folder of copies> <out folder>

The folder needs one video and three photos.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
from playwright.sync_api import sync_playwright

src, out = Path(sys.argv[1]), Path(sys.argv[2])
assert "scratch" in str(src) or "tmp" in str(src), "only ever a scratch copy"
out.mkdir(parents=True, exist_ok=True)
state = out / "state"; state.mkdir(exist_ok=True)
before = {p.name: p.stat().st_size for p in src.iterdir()}
vids = sorted(p for p in src.iterdir() if p.suffix.lower() in (".mp4", ".mov"))
pics = sorted(p for p in src.iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
assert len(vids) == 1 and len(pics) >= 3
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)

app = App(state); app.start()
def files():
    return {f["name"]: f for f in app.get("/api/check/state").json()["files"]}
def wait(cond, timeout=300):
    t = time.time()
    while time.time() - t < timeout:
        if cond(files()):
            return True
        time.sleep(1)
    return False
def row(name):
    return f'.ck-row[data-ck="{files()[name]["id"]}"]'

try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script("localStorage.setItem('app.check.seenGuide', 'true')")
        page.goto(app.base); page.wait_for_timeout(1200)
        page.click('.modes button[data-mode="check"]'); page.wait_for_timeout(1500)
        # 1. adding only adds
        app.post("/api/check/add", {"paths": [str(vids[0]), *map(str, pics[:2])]})
        page.wait_for_timeout(4000)
        fs = files()
        check("adding starts nothing", all(f["state"] == "new" for f in fs.values()), {n: f["state"] for n, f in fs.items()})
        page.evaluate("ckRefresh()"); page.wait_for_timeout(800)
        page.click(row(vids[0].name)); page.wait_for_timeout(2500)
        txt = page.locator(f"{row(vids[0].name)} small").inner_text()
        check("the row says Not assessed and how long", "Not assessed" in txt and "about" in txt and "about about" not in txt, txt)
        check("the clip's picture shows before assessing",
              page.evaluate("(() => { const i = document.querySelector('.ck-pending-pic img'); return !!i && i.naturalWidth > 0 })()"))
        facts = page.locator(".ck-facts").inner_text() if page.locator(".ck-facts").count() else ""
        check("and its quick facts (size, frame rate, length)", "3840" in facts and "fps" in facts and " s" in facts, facts)
        btn = page.locator("#ck-assess-one").inner_text().lower()
        check("an Assess this clip button with the time", "assess this clip" in btn and "about" in btn and "about about" not in btn, btn)
        check("and Assess all 3", "assess all 3" in page.locator("#ck-assess-all").inner_text().lower())
        thumbs = page.evaluate("[...document.querySelectorAll('#ck-list .ck-thumb img')].filter(i => i.naturalWidth > 0).length")
        check("thumbnails in the list before assessing", thumbs == 3, thumbs)
        check("the footer offers Assess all (3)", "assess all (3)" in page.locator("#ck-foot").inner_text().lower())
        page.screenshot(path=str(out / "1-added-not-assessed.png"))
        # 2. Assess all, then Stop: the waiting photos go back, the clip under way finishes
        page.click("#ck-assess"); page.wait_for_timeout(2500)
        fs = files()
        check("Assess all starts them", fs[vids[0].name]["state"] == "now" and all(fs[p.name]["state"] == "wait" for p in pics[:2]),
              {n: f["state"] for n, f in fs.items()})
        page.screenshot(path=str(out / "2-assessing.png"))
        page.click("#ck-stop"); page.wait_for_timeout(1500)
        fs = files()
        check("Stop takes the waiting ones back", all(fs[p.name]["state"] == "new" for p in pics[:2]) and fs[vids[0].name]["state"] == "now",
              {n: f["state"] for n, f in fs.items()})
        check("and says the one under way finishes", "finishes" in page.locator(".toast").last.inner_text())
        # 3. one photo: Assess this photo, Don't assess it, then Assess again
        page.click(row(pics[0].name)); page.wait_for_timeout(1500)
        check("a photo says Assess this photo", "assess this photo" in page.locator("#ck-assess-one").inner_text().lower())
        page.click("#ck-assess-one"); page.wait_for_timeout(1500)
        check("it waits its turn", "Waiting its turn" in page.locator(".ck-pending").inner_text())
        page.click("#ck-stop-one"); page.wait_for_timeout(1500)
        check("Don't assess it takes it back", files()[pics[0].name]["state"] == "new")
        page.click("#ck-assess-one"); page.wait_for_timeout(1000)
        check("the clip and that photo finish", wait(lambda fs: fs[vids[0].name]["state"] == "done" and fs[pics[0].name]["state"] == "done"))
        page.wait_for_timeout(2500)
        check("its assessment shows when done", page.locator(".ck-pending").count() == 0 and page.locator("#ck-main").inner_text().strip() != "")
        check("the other photo was not assessed", files()[pics[1].name]["state"] == "new")
        # 4. a ticked photo: Assess (1)
        page.check(f'[data-ck-pick="{files()[pics[1].name]["id"]}"]'); page.wait_for_timeout(400)
        check("ticked: Assess (1)", "assess (1)" in page.locator("#ck-foot").inner_text().lower())
        page.click("#ck-assess")
        check("the ticked photo is assessed", wait(lambda fs: fs[pics[1].name]["state"] == "done", 60))
        # 5. one more, left not assessed; then restart the app
        app.post("/api/check/add", {"paths": [str(pics[2])]})
        b.close()
    app.stop()
    app = App(state); app.start()
    time.sleep(4)
    fs = files()
    check("after a restart: assessed files are back from their results", all(fs[p.name]["state"] == "done" for p in [vids[0], *pics[:2]]),
          {n: f["state"] for n, f in fs.items()})
    check("and the one not assessed is still not assessed", fs[pics[2].name]["state"] == "new")
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script("localStorage.setItem('app.check.seenGuide', 'true')")
        page.goto(app.base); page.wait_for_timeout(1200)
        page.click('.modes button[data-mode="check"]'); page.wait_for_timeout(2000)
        page.click(row(pics[2].name)); page.wait_for_timeout(2000)
        page.screenshot(path=str(out / "3-after-restart.png"))
        check("no page errors", not errors, errors[:3])
        b.close()
    after = {p.name: p.stat().st_size for p in src.iterdir()}
    check("the folder of copies is untouched", before == after)
finally:
    app.stop()
print("ALL OK" if ok else "SOME FAILED")
