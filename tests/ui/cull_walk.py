"""The Culling tab walked through in Chrome on a separate test copy, on a scratch folder of photo
COPIES (never your own folders): timings, flicker and screenshots at 1440 x 900 and 1280 x 800.

    uv run --with playwright --with psutil --with requests python tests/ui/cull_walk.py <event copy> <out folder>
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
from playwright.sync_api import sync_playwright

event, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
state = out / "state"; state.mkdir(exist_ok=True)
assert "scratch" in str(event) or "tmp" in str(event), "only ever a scratch copy"
app = App(state); app.start()
res = {}
def note(k, v):
    res[k] = v; print(f"{k}: {v}", flush=True)

try:
    t0 = time.time()
    sid = app.post("/api/cull/shoots", {"folders": [str(event)]})["id"]
    first = None
    while True:
        sh = next(s for s in app.get("/api/cull/state").json()["shoots"] if s["id"] == sid)
        if first is None and sh["thumbs"] > 0:
            first = time.time() - t0
        if sh["pass1"]:
            break
        time.sleep(1)
    note("first thumbnail (s)", round(first, 1))
    note("pass 1 done (s)", round(time.time() - t0, 1))
    note("shoot", {k: sh[k] for k in ("total", "keep", "reject", "measured")})
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        for W, H in ((1440, 900), (1280, 800)):
            tag = f"{W}"
            page = b.new_page(viewport={"width": W, "height": H})
            errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
            page.add_init_script("localStorage.setItem('app.cull.revealed', JSON.stringify({%d: 1}))" % sid)
            page.goto(app.base); page.wait_for_timeout(1200)
            page.click('.modes button[data-mode="cull"]'); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{tag}-1-grid.png"))
            # flicker: how many thumbnails are re-made in 6 s of doing nothing
            page.evaluate("""window.__imgs = 0; new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) window.__imgs += n.querySelectorAll ? n.querySelectorAll('img').length : 0 }))).observe(document.querySelector('#cu-space'), { childList: true, subtree: true })""")
            page.wait_for_timeout(6000)
            note(f"{tag} thumbnails re-made while idle 6 s", page.evaluate("window.__imgs"))
            # a mark: does the grid re-make every thumbnail?
            page.evaluate("window.__imgs = 0")
            page.keyboard.press("ArrowRight"); page.keyboard.press("p"); page.wait_for_timeout(600)
            note(f"{tag} thumbnails re-made by one mark", page.evaluate("window.__imgs"))
            page.wait_for_timeout(1500)
            sh = next(x for x in app.get("/api/cull/state").json()["shoots"] if x["id"] == sid)
            note(f"{tag} the mark reached the app (yours)", sh["yours"])
            note(f"{tag} bar height (one row < 56)", page.evaluate("document.querySelector('#cu-bar').offsetHeight"))
            # one big photo: hold the arrow through 20 frames
            page.keyboard.press("Space"); page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"{tag}-2-one.png"))
            ts = []
            for i in range(20):
                t = time.time(); page.keyboard.press("ArrowRight")
                page.wait_for_function("(() => { const i = document.querySelector('#cu-img'); return i && i.complete && i.naturalWidth > 0 })()", timeout=20000)
                ts.append(round(time.time() - t, 2))
            note(f"{tag} big photo, next (s) each", ts)
            page.click('#cu-side [data-show="unsure"]'); page.wait_for_timeout(500)
            note(f"{tag} unsure shown / unsure counted", page.evaluate("[cu.order.length, cuCounts()[0].unsure]"))
            for _ in range(3):
                page.keyboard.press("End"); page.keyboard.press("ArrowRight"); page.wait_for_timeout(150)
            note(f"{tag} notes showing after 3 end-of-list presses", page.evaluate("document.querySelectorAll('#toasts .toast').length"))
            page.click('#cu-side [data-show="all"]'); page.wait_for_timeout(500); page.keyboard.press("Space"); page.wait_for_timeout(800)
            page.keyboard.press("z"); t = time.time()
            page.wait_for_function("(() => { const i = document.querySelector('.cu-zoom img'); return i && i.complete && i.naturalWidth > 0 })()", timeout=30000)
            note(f"{tag} 100% zoom (s)", round(time.time() - t, 2))
            page.screenshot(path=str(out / f"{tag}-3-zoom.png"))
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
            page.keyboard.press("c"); page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"{tag}-4-compare.png"))
            page.keyboard.press("Escape"); page.wait_for_timeout(500)
            page.keyboard.press("Meta+z"); page.wait_for_timeout(500)
            page.evaluate("document.querySelectorAll('#toasts .toast').forEach((t) => t.remove())")
            page.click("#cu-pass1"); page.wait_for_timeout(500)
            page.screenshot(path=str(out / f"{tag}-5-pass1.png")); page.click("[data-close]")
            page.click("#cu-fin"); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{tag}-6-finish.png"), full_page=False)
            page.locator(".cu-fin").evaluate("e => e.scrollTop = 900"); page.wait_for_timeout(800)
            page.screenshot(path=str(out / f"{tag}-7-finish-crops.png"))
            page.click("#fin-back"); page.wait_for_timeout(500)
            page.evaluate("document.querySelectorAll('#toasts .toast').forEach((t) => t.remove())")
            page.click("#cu-del"); page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"{tag}-8-delete.png")); page.click("[data-close]")
            page.click("#cu-help"); page.wait_for_timeout(500)
            page.screenshot(path=str(out / f"{tag}-9-guide.png"))
            note(f"{tag} page errors", errs[:5])
            page.close()
finally:
    app.stop()
(out / "walk.json").write_text(json.dumps(res, indent=1))
