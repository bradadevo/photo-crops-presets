"""The tone curve clicked through in Chrome on a separate test copy (2 real photos): a situation curve,
   dragging, adding and taking out points, undo, the players/background parts, double-click.

    uv run --with playwright --with psutil --with requests python tests/ui/curves_click.py <out folder>
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App
import scenarios as sc
from playwright.sync_api import sync_playwright

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
state = out / "state"; state.mkdir(exist_ok=True)
photos = sorted(Path("~/Movies/PSG U13 Halloween/PSG U13 vc OC").expanduser().glob("*.[Jj][Pp][Gg]"))[:2]
app = App(state); app.start()
errs = []; ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)
try:
    pids = app.add_photos(photos)
    sid = app.make(pids[0], "Original")["id"]
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = sc.open_photo(b, app, sid)
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.set_viewport_size({"width": 1440, "height": 900})
        page.evaluate(f"""st.tab = 'edit'; renderTabs(); st.openGroups.advanced = true; st.openGroups['adv-curve'] = true;
            st.openGroups.light = false; st.openGroups.color = false; st.openGroups.look = false; editSig = ''; renderEdit(slotById({sid}))""")
        page.wait_for_selector(".curve-svg", timeout=60000)
        page.wait_for_timeout(1500)
        page.locator(".curve-box").scroll_into_view_if_needed()
        page.screenshot(path=str(out / "1-open.png"))
        sits = page.locator(".curve-sit").count()
        check("six situation curves listed", sits == 6, sits)
        sug = page.evaluate("[...document.querySelectorAll('.curve-sit')].filter(b => !b.querySelector('.curve-sug').hidden).map(b => b.dataset.sit)")
        print("   suggested here:", sug)
        ver = page.evaluate(f"slotById({sid}).ver")
        t = time.time()
        page.click('.curve-sit[data-sit="flat"]')
        page.wait_for_function(f"slotById({sid}).ver > {ver} && slotById({sid}).adjust.curve_all_rgb", timeout=60000)
        print(f"   flat curve shown in {time.time() - t:.2f} s")
        check("Flat light sets the whole photo's RGB curve", page.evaluate(f"slotById({sid}).adjust.curve_all_rgb") == "0,0;64,52;192,206;255,255")
        page.wait_for_timeout(800)
        check("its button shows on, and the RGB tab shows it's set", page.locator('.curve-sit.on[data-sit="flat"]').count() == 1 and page.locator('[data-cch="rgb"].set').count() == 1)
        page.screenshot(path=str(out / "2-flat.png"))
        # drag the 192 point up
        box = page.locator(".curve-svg").bounding_box()
        px = lambda x, y: (box["x"] + (x + 6) / 267 * box["width"], box["y"] + (255 - y + 6) / 267 * box["height"])
        ver = page.evaluate(f"slotById({sid}).ver")
        page.mouse.move(*px(192, 206)); page.mouse.down(); page.mouse.move(*px(192, 230), steps=6); page.mouse.up()
        page.wait_for_function(f"slotById({sid}).ver > {ver}", timeout=60000); page.wait_for_timeout(600)
        c = page.evaluate(f"slotById({sid}).adjust.curve_all_rgb")
        check("dragging a point moves it", "192,2" in c and "192,206" not in c, c)
        # add a point by clicking
        page.mouse.move(*px(128, 135)); page.mouse.down(); page.mouse.move(*px(128, 150), steps=4); page.mouse.up(); page.wait_for_timeout(1500)
        c2 = page.evaluate(f"slotById({sid}).adjust.curve_all_rgb")
        check("clicking the line and dragging adds a point", len(c2.split(";")) == 5, c2)
        # drag it off
        page.mouse.move(*px(128, 150)); page.mouse.down(); page.mouse.move(*px(128, 330), steps=6); page.mouse.up(); page.wait_for_timeout(1500)
        c3 = page.evaluate(f"slotById({sid}).adjust.curve_all_rgb")
        check("dragging it off takes it out", len(c3.split(";")) == 4, c3)
        page.keyboard.press("Meta+z"); page.wait_for_timeout(2000)
        c4 = page.evaluate(f"slotById({sid}).adjust.curve_all_rgb")
        check("⌘Z puts it back", c4 == c2, c4)
        # players / background
        t = time.time()
        page.click('.curve-sit[data-sit="night"]'); page.wait_for_timeout(1200)
        note = page.locator(".toast").all_inner_texts()
        print("   while the players are found:", note)
        page.wait_for_function(f"slotById({sid}).adjust.curve_bg_rgb", timeout=90000); page.wait_for_timeout(800)
        print(f"   night curve shown after {time.time() - t:.1f} s")
        a = page.evaluate(f"slotById({sid}).adjust")
        check("Night game goes on the background only", a["curve_bg_rgb"] and not a["curve_player_rgb"], a["curve_bg_rgb"])
        check("the Background tab is shown, with its dot", page.locator('[data-cpart="bg"].on .curve-dot').count() == 1)
        page.screenshot(path=str(out / "3-night.png"))
        page.click('[data-cch="b"]'); page.wait_for_timeout(500)
        page.mouse.click(*px(100, 130)); page.wait_for_timeout(1000)
        check("a click alone on the graph changes nothing", page.evaluate(f"slotById({sid}).adjust.curve_bg_b") == "")
        page.click('[data-cch="rgb"]'); page.wait_for_timeout(300)
        page.mouse.dblclick(*px(60, 34)); page.wait_for_timeout(2500)
        check("double-clicking a point takes it out", page.evaluate(f"slotById({sid}).adjust.curve_bg_rgb") == "0,0;140,120;255,255", page.evaluate(f"slotById({sid}).adjust.curve_bg_rgb"))
        page.mouse.dblclick(*px(200, 60)); page.wait_for_timeout(2500)
        print("   after double-click:", {k: v for k, v in page.evaluate(f"slotById({sid}).adjust").items() if k.startswith("curve_bg")})
        check("double-clicking the empty graph straightens the curve", page.evaluate(f"slotById({sid}).adjust.curve_bg_rgb") == "")
        check("the whole photo's curve is untouched by all that", page.evaluate(f"slotById({sid}).adjust.curve_all_rgb") == c2)
        page.click('.curve-sit[data-sit="night"]'); page.wait_for_function(f"slotById({sid}).adjust.curve_bg_rgb", timeout=30000); page.wait_for_timeout(800)
        page.click('.curve-sit[data-sit="night"]'); page.wait_for_function(f"!slotById({sid}).adjust.curve_bg_rgb", timeout=30000)
        check("clicking Night game again takes it off", True)
        b.close()
finally:
    app.stop()
check("no page errors", not errs, errs)
print("ALL OK" if ok else "SOME FAILED")
