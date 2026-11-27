"""The smoke looks (and a lens-blur look) clicked through in Chrome on a separate test copy: shown on
the photo when pointed at, then made for real at full size, with how long each took. The photos are
uploaded, so the app works on its own copies.

    uv run --with playwright --with psutil --with requests python tests/ui/smoke_click.py <folder of copies> <out folder>
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
import scenarios as sc
import requests
from playwright.sync_api import sync_playwright

src, out = Path(sys.argv[1]), Path(sys.argv[2])
assert "scratch" in str(src) or "tmp" in str(src), "only ever a scratch copy"
out.mkdir(parents=True, exist_ok=True)
state = out / "state"; state.mkdir(exist_ok=True)
photos = [src / n for n in ("DSC03433.JPG", "DSC03406.JPG")]
looks = ["Color Smoke", "Stadium Smoke", "Shallow Focus"]
app = App(state); app.start()
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)
try:
    pids = app.add_photos(photos)
    sid = app.make(pids[0], "Original")["id"]
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = sc.open_photo(b, app, sid)
        page.click('#look-filters button[data-g="All"]') if page.locator('#look-filters button[data-g="All"]').count() else None
        for i, n in enumerate(looks):
            page.mouse.move(700, 400)
            t = time.time()
            page.locator(f'#look-grid .look[data-name="{n}"]').first.scroll_into_view_if_needed()
            page.hover(f'#look-grid .look[data-name="{n}"]')
            page.wait_for_function(f"(() => {{ const o = document.querySelector('#frame .tryon.ready'); return !!o && o.textContent.includes({n!r}) }})()",
                                   timeout=180000, polling=100)
            print(f"   {n} shown after pointing: {time.time() - t:.1f} s", flush=True)
            page.wait_for_timeout(300)
            page.locator("#frame").screenshot(path=str(out / f"1-{i}-{n.replace(' ', '_')}.png"))
        check("no page errors", not page.errors, page.errors[:3])
    for pid, name in zip(pids, ("DSC03433", "DSC03406")):
        for n in looks[:2]:
            t = time.time()
            s = app.make(pid, n)
            st = next(x for x in requests.get(app.base + "/api/state").json()["slots"] if x["id"] == s["id"])
            f = out / f"2-{name}-{n.replace(' ', '_')}.jpg"
            f.write_bytes(requests.get(f"{app.base}/img/slot/{s['id']}/{st['ver']}/after.jpg", timeout=300).content)
            print(f"   {name} {n} made in {time.time() - t:.1f} s; notes: {st.get('notes')}", flush=True)
            check(f"{name} {n} made for real", st["state"] == "done" and f.stat().st_size > 50000)
finally:
    app.stop()
print("ALL OK" if ok else "SOME FAILED")
