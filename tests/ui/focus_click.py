"""The Assessor's focus check and taking files out of the list, clicked through in Chrome on a separate
test copy, on a scratch folder of COPIES (never your own folders).

    uv run --with playwright --with psutil --with requests python tests/ui/focus_click.py <folder of copies> <out folder>

The folder needs a clip with a person the camera follows (C0418.MP4: a runner coming toward the camera
with the focus left behind him) and a couple of other files.
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
app = App(state); app.start()
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)

def files():
    return app.get("/api/check/state").json()["files"]

def wait_done(timeout=600):
    t = time.time()
    while time.time() - t < timeout:
        fs = files()
        if fs and all(f["state"] in ("done", "failed") for f in fs):
            return fs
        time.sleep(1)
    return files()

try:
    t0 = time.time()
    app.post("/api/check/add", {"paths": [str(src)]})
    app.post("/api/check/assess", {"ids": []})  # (adding never starts it: Assess does)
    fs = wait_done()
    print(f"   checked {len(fs)} files in {time.time() - t0:.0f} s", flush=True)
    clip = next(f for f in fs if f["name"] == "C0418.MP4")
    d = app.get(f"/api/check/file/{clip['id']}").json()
    fo = d.get("focus")
    check("the focus check found the subject", fo and fo["points"], d.get("error"))
    print("   ", fo["finding"])
    check("it says the focus sat behind him and didn't follow", "behind them" in fo["finding"] and "came closer" in fo["finding"])
    check("it says when (a moment on the timeline)", any(m["kind"] == "focus" for m in d["moments"]),
          [(m["clock"], m["label"]) for m in d["moments"]])
    check("the advice starts with focus settings", d["advice"] and d["advice"][0][0] in ("Focus mode", "Focus area"), d["advice"][:2])
    check("In short says it needs attention", d["recommend"]["level"] == "attention", d["recommend"]["verdict"])
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script("localStorage.setItem('app.check.seenGuide', 'true')")
        page.goto(app.base); page.wait_for_timeout(1200)
        page.click('.modes button[data-mode="check"]'); page.wait_for_timeout(2000)
        page.click(f'.ck-row[data-ck="{clip["id"]}"]'); page.wait_for_timeout(2000)
        check("the focus card shows", page.locator(".ck-focus").count() == 1)
        check("the timeline has the focus moment", page.locator('#ck-timeline .mo[style*="#2ad4c4"]').count() >= 1)
        page.locator(".ck-focus").screenshot(path=str(out / "1-focus-card.png"))
        # a focus moment: the picture shows the subject's box (red) and the sharpest part
        i = next(k for k, m in enumerate(d["moments"]) if m["kind"] == "focus")
        page.click(f'.ck-moments .ck-mo[data-mo="{i}"]'); page.wait_for_timeout(2500)
        check("clicking it shows the subject out of focus on the picture", page.locator("#ck-fover .fb.subject.soft").count() == 1,
              page.locator("#ck-fover").inner_text() if page.locator("#ck-fover").count() else "no overlay")
        check("and where the picture is sharp", page.locator("#ck-fover .fb.sharpest").count() >= 1)
        page.locator("#ck-viewer").screenshot(path=str(out / "2-focus-view.png"))
        # the chart: click a moment where he's sharpest
        sh = fo["sharpest"]
        box = page.locator("#ck-fchart").bounding_box()
        page.mouse.click(box["x"] + box["width"] * ((sh[0] + sh[1]) / 2) / d["duration"], box["y"] + 30); page.wait_for_timeout(2000)
        lab = page.locator("#ck-fover .fb.subject span").inner_text() if page.locator("#ck-fover .fb.subject").count() else ""
        check("clicking the chart moves the picture there", "Your subject" in lab, lab)
        # picking someone else: a time with another person in the picture
        other_t = None
        for p in fo["points"]:
            ppl = app.get(f"/api/check/file/{clip['id']}/people?t={p['t']}").json()["people"]
            if any(not x["subject"] for x in ppl):
                other_t = p["t"]; break
        if other_t is not None:
            box = page.locator("#ck-fchart").bounding_box()
            page.mouse.click(box["x"] + box["width"] * other_t / d["duration"], box["y"] + 30); page.wait_for_timeout(1500)
            page.click("#ck-pick"); page.wait_for_timeout(2500)
            check("picking: the other people can be clicked", page.locator("#ck-fover.picking .fb.other").count() >= 1)
            page.locator("#ck-viewer").screenshot(path=str(out / "3-picking.png"))
            page.locator("#ck-fover .fb.other").first.click(); page.wait_for_timeout(3000)
            d2 = app.get(f"/api/check/file/{clip['id']}").json()
            check("the picked person is now the subject", d2["focus"]["picked"] and d2["focus"]["points"] != fo["points"])
            check("the card says so", "the person you picked" in page.locator(".ck-focus h3").inner_text())
            page.click("#ck-auto"); page.wait_for_timeout(2500)
            d3 = app.get(f"/api/check/file/{clip['id']}").json()
            check("Automatic goes back to the runner", not d3["focus"]["picked"] and d3["focus"]["finding"] == fo["finding"])
        # taking files out of the list, from the list
        n = len(files())
        other = next(f for f in files() if f["id"] != clip["id"])
        page.hover(f'.ck-row[data-ck="{other["id"]}"]')
        page.click(f'.ck-row[data-ck="{other["id"]}"] .ck-x'); page.wait_for_timeout(1500)
        check("the x on a row takes it out", len(files()) == n - 1 and page.locator(".ck-row").count() == n - 1)
        page.locator(".toast button", has_text="Undo").first.click(); page.wait_for_timeout(1500)
        check("Undo puts it back", len(files()) == n)
        ids = [f["id"] for f in files()][:2]
        for fid in ids:
            page.check(f'[data-ck-pick="{fid}"]')
        page.wait_for_timeout(300)
        check("ticked files show Remove (2)", "Remove (2)" in page.locator("#ck-foot").inner_text())
        page.keyboard.press("Delete"); page.wait_for_timeout(2000)
        check("Delete takes the ticked files out", len(files()) == n - 2 and all(f["id"] not in ids for f in files()))
        page.screenshot(path=str(out / "4-list-after-delete.png"))
        page.locator(".toast button", has_text="Undo").first.click(); page.wait_for_timeout(2000)
        check("one Undo puts both back", len(files()) == n)
        check("no page errors", not errors, errors[:3])
        b.close()
    after = {p.name: p.stat().st_size for p in src.iterdir()}
    check("the folder of copies is untouched", before == after)
finally:
    app.stop()
print("ALL OK" if ok else "SOME FAILED")
