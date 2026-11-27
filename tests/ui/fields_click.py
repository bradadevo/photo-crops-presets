"""The field looks clicked through in Chrome on a separate test copy (3 real photos): the Field group
in the looks list, each look shown on the photo when pointed at, and one made for real.

    uv run --with playwright --with psutil --with requests python tests/ui/fields_click.py <out folder>
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
import scenarios as sc
import requests
from playwright.sync_api import sync_playwright

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
state = out / "state"; state.mkdir(exist_ok=True)
psg = Path("~/Movies/11U PSG LAKE NONA VS WPARK").expanduser()
photos = [psg / n for n in ("DSC03433.JPG", "DSC03375.JPG", "DSC03417.JPG")]
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
        groups = page.evaluate("[...document.querySelectorAll('#look-filters button')].map(b => b.textContent)")
        check("the looks list has a Field group", "Field" in groups, groups)
        page.click('#look-filters button[data-g="Field"]')
        page.wait_for_timeout(500)
        names = list(dict.fromkeys(page.evaluate("[...document.querySelectorAll('#look-grid .look')].map(b => b.dataset.name)")))
        check("Field shows the 11 field looks, and no Gray Day Stadium", len(names) == 11 and "Gray Day Stadium" not in names, names)
        page.screenshot(path=str(out / "1-field-group.png"))
        times = []
        for i, n in enumerate(names):
            page.mouse.move(700, 400)
            t = time.time()
            page.hover(f'#look-grid .look[data-name="{n}"]')
            page.wait_for_function(f"(() => {{ const o = document.querySelector('#frame .tryon.ready'); return !!o && o.textContent.includes({n!r}) }})()",
                                   timeout=180000, polling=100)
            times.append(round(time.time() - t, 2))
            page.wait_for_timeout(300)
            page.locator("#frame").screenshot(path=str(out / f"2-{i:02d}-{n.replace(' ', '_')}.png"))
        print("   shown after pointing (s):", times)
        check("each field look shows on the photo when pointed at", len(times) == len(names))
        check("after the first, each shows within 3 s", max(times[1:]) <= 3.0, f"first {times[0]} s")
        check("no page errors", not page.errors, page.errors[:3])
    # one made for real, at full size
    t = time.time()
    s = app.make(pids[1], "Center Circle")
    st = next(x for x in requests.get(app.base + "/api/state").json()["slots"] if x["id"] == s["id"])
    (out / "3-made-center-circle.jpg").write_bytes(requests.get(f"{app.base}/img/slot/{s['id']}/{st['ver']}/after.jpg", timeout=300).content)
    print(f"   Center Circle made in {time.time() - t:.1f} s; notes: {st.get('notes')}")
    check("a field look is made for real", (out / "3-made-center-circle.jpg").stat().st_size > 50000)
finally:
    app.stop()
print("ALL OK" if ok else "SOME FAILED")
