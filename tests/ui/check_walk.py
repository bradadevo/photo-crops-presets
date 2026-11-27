"""The Check tab walked through in Chrome on a separate test copy, on a scratch folder of COPIES (never
your own folders): what it writes (fixed copies, dropped files, reports) never writes over anything,
the list doesn't flicker, and screenshots at 1440 x 900 and 1280 x 800.

    uv run --with playwright --with psutil --with requests python tests/ui/check_walk.py <folder of copies> <out folder>
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
import requests
from playwright.sync_api import sync_playwright

src, out = Path(sys.argv[1]), Path(sys.argv[2])
assert "scratch" in str(src) or "tmp" in str(src), "only ever a scratch copy"
out.mkdir(parents=True, exist_ok=True)
state = out / "state"; state.mkdir(exist_ok=True)
app = App(state); app.start()
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)

def files():
    return app.get("/api/check/state").json()["files"]

def wait_done(timeout=300):
    t = time.time()
    while time.time() - t < timeout:
        fs = files()
        if fs and all(f["state"] in ("done", "failed") and (f.get("job") or {}).get("state") != "now" for f in fs):
            return fs
        time.sleep(1)
    return files()

try:
    t0 = time.time()
    app.post("/api/check/add", {"paths": [str(src)]})
    fs = wait_done()
    print(f"   checked {len(fs)} files in {time.time() - t0:.0f} s", flush=True)
    check("every file checked", all(f["state"] == "done" for f in fs), [(f["name"], f["state"], f.get("error")) for f in fs])
    byname = {f["name"]: f for f in fs}
    # 1. a JPEG and its RAW (one name) fixed at the same time: two fixed copies, neither written over
    pair = [byname[n]["id"] for n in ("DSC03375.JPG", "DSC03375.ARW") if n in byname]
    for fid in pair:
        requests.put(f"{app.base}/api/check/file/{fid}/fixes", json={"fixes": {"exposure": {"on": True, "value": 0.3}}})
    dests = [app.post(f"/api/check/file/{fid}/fix", {})["dest"] for fid in pair]
    wait_done()
    made = [Path(d) for d in dests]
    check("a JPEG and its RAW fixed together give two different files", len(set(dests)) == 2 and all(p.exists() for p in made), dests)
    # 2. two dropped files with one name (from two folders): two different files in the list
    a, b = out / "drop-a", out / "drop-b"
    a.mkdir(exist_ok=True); b.mkdir(exist_ok=True)
    (a / "same.JPG").write_bytes((src / "DSC03417.JPG").read_bytes())
    (b / "same.JPG").write_bytes((src / "DSC03433.JPG").read_bytes())
    r = requests.post(f"{app.base}/api/check/upload", files=[("files", ("same.JPG", open(a / "same.JPG", "rb"), "image/jpeg")),
                                                            ("files", ("same.JPG", open(b / "same.JPG", "rb"), "image/jpeg"))]).json()
    paths = [f["path"] for f in files() if f["id"] in r["added"]]
    check("two dropped files with one name stay two files", len(r["added"]) == 2 and len(set(paths)) == 2, paths)
    wait_done()
    # 3. two reports in the same minute: two files
    ids = [f["id"] for f in files() if f["state"] == "done"][:2]
    r1 = app.post("/api/check/export", {"ids": ids, "format": "docx"})["files"]
    r2 = app.post("/api/check/export", {"ids": ids, "format": "docx"})["files"]
    check("a second report never writes over the first", r1 != r2 and all(Path(p).exists() for p in r1 + r2), r1 + r2)
    # one verdict: the list says what "In short" says
    for f in files():
        if f["state"] == "done":
            d = app.get(f"/api/check/file/{f['id']}").json()
            check(f"{f['name']}: the list and In short agree", f.get("verdict") == d["recommend"]["verdict"], (f.get("verdict"), d["recommend"]["verdict"]))
    # a JPEG and its own RAW compared: said plainly
    c = app.post("/api/check/compare", {"ids": pair})
    check("JPEG vs its RAW: the note says it's the same photo", any("The same photo" in n for x in c["notes"] for n in x["notes"]))
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="chrome", headless=True)
        for W, H in ((1440, 900), (1280, 800)):
            page = br.new_page(viewport={"width": W, "height": H})
            errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
            page.add_init_script("localStorage.setItem('app.check.seenGuide', 'true')")
            page.goto(app.base); page.wait_for_timeout(1200)
            page.click('.modes button[data-mode="check"]'); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{W}-1-photo.png"))
            page.locator(".ck-row", has_text="clip1").click(); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{W}-2-video.png"))
            txt = page.locator("#ck-main").inner_text()
            moments = page.locator(".ck-mo").count()
            check(f"{W}: no 'No problems found' above problem moments", not (moments and "No problems found" in txt), moments)
            check(f"{W}: the tab is called Assessor", page.locator('.modes button[data-mode="check"]').inner_text().strip().lower() == "assessor")
            # the list while a file is being checked: are its thumbnails made again each refresh?
            app.post("/api/check/add", {"paths": [str(src / "DSC03417.JPG")]})
            page.evaluate("""window.__imgs = 0; new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) window.__imgs += n.tagName === 'IMG' ? 1 : n.querySelectorAll('img').length }))).observe(document.querySelector('#ck-list'), { childList: true, subtree: true })""")
            page.wait_for_timeout(5000)
            print(f"   {W}: list thumbnails made again in 5 s: {page.evaluate('window.__imgs')}", flush=True)
            # a fix's slider: the before picture must not blink
            page.locator(".ck-row", has_text="DSC03433").click(); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{W}-3-fixes.png"))
            for i, cb in enumerate(page.locator("[data-ck-pick]").all()[:3]):
                cb.check()
            page.click("#ck-compare"); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{W}-4-compare.png"))
            page.click("#ck-back"); page.wait_for_timeout(800)
            page.click("#ck-summary"); page.wait_for_timeout(2500)
            page.screenshot(path=str(out / f"{W}-5-summary.png"))
            page.click("#ck-sum-back"); page.wait_for_timeout(800)
            page.click("#ck-help"); page.wait_for_timeout(800)
            page.screenshot(path=str(out / f"{W}-6-guide.png"))
            check(f"{W}: no page errors", not errs, errs[:3])
            page.close()
finally:
    app.stop()
print("ALL OK" if ok else "SOME FAILED")
