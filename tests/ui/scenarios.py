"""What a photographer does, clicked through in a real browser (Chrome), each with its bar as a pass/fail
line. The bars are the plan's (docs/plans/instant-looks.md); they are not loosened to fit a result."""
from __future__ import annotations

import io
import statistics
import time
from pathlib import Path

import numpy as np
from PIL import Image

# (in the page) a photo or tile blurred: a blur filter on anything, or a frosted-glass layer bigger than a label
BLURRED = """[...document.querySelectorAll('#viewer, #viewer *')].filter(e => { const c = getComputedStyle(e),
  r = e.getBoundingClientRect(); return c.filter.includes('blur') || (c.backdropFilter.includes('blur') && r.width * r.height > 40000) })
  .map(e => e.className || e.tagName).join(', ')"""
SETTLED = """(() => { const f = document.querySelector('#frame'), i = f && f.querySelector('img.after');
  return !!i && i.complete && i.naturalWidth > 0 && !f.querySelector('.ready-note') })()"""


class Checks:
    def __init__(self, out: Path):
        self.out = out
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
        return ok

    def shot(self, page, name: str) -> None:
        page.screenshot(path=str(self.out / f"{name}.png"))


def open_photo(browser, app, sid: int):
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(app.base)
    page.wait_for_function("typeof st !== 'undefined' && st.slots.length > 0", timeout=120000)
    page.evaluate(f"select({sid})")
    page.wait_for_timeout(800)
    return page


def sliders(page, sid: int) -> list[float]:
    """Moves the background slider three times; seconds until each new picture is on screen."""
    times = []
    for v in (-0.4, 0.2, -0.1):
        ver0 = page.evaluate(f"slotById({sid}).ver")
        t = time.time()
        page.evaluate(f"sendAdjust({sid}, {{...slotById({sid}).adjust, background: {v}}})")
        for _ in range(400):
            page.wait_for_timeout(25)
            if page.evaluate(f"slotById({sid}).ver > {ver0}") and page.evaluate(SETTLED):
                break
        times.append(round(time.time() - t, 2))
    return times


# Phase 1: hover on the current photo ---------------------------------------------------------------

def hover(c: Checks, browser, app, pid: int, sid: int) -> None:
    page = open_photo(browser, app, sid)
    names = list(dict.fromkeys(page.evaluate("[...document.querySelectorAll('#look-grid .look:not(.own)')].map(b => b.dataset.name)")))
    ai = set(page.evaluate("st.looks.filter(l => l.ai || l.design).map(l => l.name)"))
    plain = [n for n in names if n not in ai]
    print(f"   {len(names)} looks in the list: {len(plain)} made ahead, {len(names) - len(plain)} AI or designs")
    t0 = time.time()
    first = plain[len(plain) // 2]
    page.hover(f'#look-grid .look[data-name="{first}"]')
    page.wait_for_timeout(100)
    note = page.locator("#frame .tryon .tag").inner_text() if page.locator("#frame .tryon .tag").count() else ""
    blur = page.evaluate(BLURRED)
    c.check("hover before it's made: the photo stays, a note says so in words, nothing blurred",
            ("Making" in note or "Finding the players" in note) and not blur, f"note: {note!r}; blurred: {blur or 'none'}")
    page.wait_for_function("!!document.querySelector('#frame .tryon.ready img')", timeout=60000, polling=50)
    c.check("that look appears as soon as it's made (the one under the pointer first)", True, f"{time.time() - t0:.1f} s")
    page.mouse.move(700, 400)
    page.wait_for_timeout(200)
    players = page.evaluate("ahead.cut && ahead.cut.this")
    watch = page.evaluate_handle("""(() => { const seen = []; const o = new MutationObserver(() => {
      document.querySelectorAll('.toast').forEach(t => { if (!seen.includes(t.textContent)) seen.push(t.textContent) }) });
      o.observe(document.body, {childList: true, subtree: true}); return seen })()""")
    times = sliders(page, sid)
    said = watch.json_value()
    c.check("sliders stay quick while looks are made ahead (≤ 0.15 s; 0.3 s on an M2)", max(times) <= 0.15,
            f"{times} s; this photo's players: {players}")
    if max(times) > 0.5:
        c.check("a slider waiting for the players says so in words", any("Finding the players" in x for x in said),
                f"said: {said[:2]}")
    page.wait_for_function("ahead.total > 0 && ahead.imgs.size >= ahead.total", timeout=900000, polling=250)
    warm = time.time() - t0
    each = warm * 2 / len(plain)  # (M2 estimate)
    c.check(f"all {len(plain)} looks made ahead, ≤ 1.5 s a look on an M2 (estimate: this Mac × 2)", each <= 1.5,
            f"{warm:.0f} s here; {each:.2f} s a look on an M2")
    c.check("the status line says they're all ready", "All" in page.locator("#ahead-status").inner_text(),
            page.locator("#ahead-status").inner_text())
    status = page.evaluate("[document.querySelector('#ahead-status').textContent, document.querySelector('#ahead-status').scrollWidth <= document.querySelector('#ahead-status').clientWidth + 1]")
    c.check("the status line says how far the players' cut-outs are (or nothing once all are)",
            "players ready in" in status[0] or page.evaluate("ahead.cut.done >= ahead.cut.total"), status[0])
    lat = []
    for n in plain:
        page.mouse.move(700, 400)
        t = time.time()
        page.hover(f'#look-grid .look[data-name="{n}"]')
        page.wait_for_function(f"(() => {{ const o = document.querySelector('#frame .tryon.ready'); return !!o && o.textContent.includes({n!r}) }})()", timeout=5000)
        lat.append((time.time() - t) * 1000)
    c.check("pointer on a look → that look on the big photo (≤ 120 ms incl. moving the pointer)", max(lat) <= 120,
            f"median {statistics.median(lat):.0f} ms, max {max(lat):.0f} ms over {len(lat)} looks")
    disp = [page.evaluate(f"(() => {{ const t = performance.now(); tryOn({n!r}); return performance.now() - t }})()") for n in plain[:20]]
    c.check("showing a made-ahead look (≤ 50 ms)", max(disp) <= 50, f"max {max(disp):.1f} ms")
    c.shot(page, "hover")
    page.evaluate("tryOff()")
    c.check("no page errors (hover)", not page.errors, "; ".join(page.errors[:2]))
    page.close()
    # the preview is exactly what Make makes
    name = plain[0]
    made = app.make(pid, name)
    after = np.asarray(Image.open(io.BytesIO(app.get(f"/img/slot/{made['id']}/{made['ver']}/after.jpg").content)).convert("RGB"), np.float32)
    for _ in range(600):
        r = app.post(f"/api/ahead/{pid}", {"order": [name]})
        if name in r["ready"]:
            break
        time.sleep(0.2)
    pre = np.asarray(Image.open(io.BytesIO(app.get(f"/img/ahead/{pid}/{name}.jpg?e={r['token']}").content)).convert("RGB"), np.float32)
    diff = float(np.abs(after - pre).mean()) if after.shape == pre.shape else -1
    c.check("the hover preview is the very picture Make makes (mean difference < 2/255)", 0 <= diff < 2,
            f"{name}: sizes {after.shape[:2]} and {pre.shape[:2]}, difference {diff:.2f}/255")
    app.post("/api/slots/remove", {"ids": [made["id"]]})


def opened_later(c: Checks, browser, app, pid: int, sid: int) -> None:
    """A photo opened a while after it was added: its players were cut out in the background meanwhile,
    so the looks built on them come at the speed of any other look."""
    left = app.post(f"/api/ahead/{pid}", {"order": []})["cutting"]
    page = open_photo(browser, app, sid)
    ai = set(page.evaluate("st.looks.filter(l => l.ai || l.design).map(l => l.name)"))
    on_players = set(page.evaluate("st.looks.filter(l => l.cutout).map(l => l.name)"))
    names = list(dict.fromkeys(page.evaluate("[...document.querySelectorAll('#look-grid .look:not(.own)')].map(b => b.dataset.name)")))
    plain = [n for n in names if n not in ai]
    first = next(n for n in plain[len(plain) // 2:] if n in on_players)
    t0 = time.time()
    page.hover(f'#look-grid .look[data-name="{first}"]')
    page.wait_for_function("!!document.querySelector('#frame .tryon.ready img')", timeout=60000, polling=50)
    dt = time.time() - t0
    c.check("a photo opened later: a look on its players shows within 1.5 s on an M2 (cut out ahead)", dt * 2 <= 1.5,
            f"{first}: {dt:.2f} s here ({dt * 2:.2f} s M2 estimate); {left} photos still to cut out")
    page.mouse.move(700, 400)
    page.wait_for_timeout(200)
    times = sliders(page, sid)
    c.check("a photo opened later: sliders quick while its looks are made (≤ 0.15 s)", max(times) <= 0.15, f"{times} s")
    page.wait_for_function("ahead.total > 0 && ahead.imgs.size >= ahead.total", timeout=900000, polling=250)
    warm = time.time() - t0
    each = warm * 2 / len(plain)
    c.check(f"a photo opened later: all {len(plain)} looks made ahead, ≤ 1.5 s a look on an M2", each <= 1.5,
            f"{warm:.0f} s here; {each:.2f} s a look on an M2")
    c.check("no page errors (opened later)", not page.errors, "; ".join(page.errors[:2]))
    page.close()


# Phase 2: the looks list ---------------------------------------------------------------------------

def looks_list(c: Checks, browser, app, pid: int, sid: int) -> None:
    page = open_photo(browser, app, sid)
    n = page.evaluate("document.querySelectorAll('#look-grid .look').length")
    t = page.evaluate("(() => { const t = performance.now(); renderLooks(true); return performance.now() - t })()")
    c.check(f"the list of {n} looks draws in ≤ 60 ms (100+ looks)", n >= 100 and t <= 60, f"{t:.0f} ms")
    page.wait_for_function("ahead.total > 0 && ahead.imgs.size >= ahead.total", timeout=900000)
    fr = page.evaluate("""() => new Promise((done) => { const g = document.querySelector('#look-grid'); g.scrollTop = 0;
      const ts = []; let last = performance.now(); const end = last + 2500;
      const tick = (now) => { ts.push(now - last); last = now; g.scrollTop += 40; if (now < end) requestAnimationFrame(tick); else done(ts.slice(2)); };
      requestAnimationFrame(tick); })""")
    fps, slow = 1000 / statistics.mean(fr), sum(1 for x in fr if x > 25)
    c.check("scrolling the list stays smooth (≥ 55 fps, ≤ 3 slow frames)", fps >= 55 and slow <= 3, f"{fps:.0f} fps, {slow} slow of {len(fr)}")
    st_ = [page.evaluate(f"(() => {{ st.query = {q!r}; const t = performance.now(); renderLooks(true); return performance.now() - t }})()")
           for q in ("night", "mono", "warm", "stadium", "")]
    page.evaluate("st.query = ''; renderLooks(true)")
    c.check("search (≤ 30 ms a keystroke)", max(st_) <= 30, f"max {max(st_):.0f} ms")
    page.click("#look-search")
    page.wait_for_timeout(100)
    shown = []
    for _ in range(6):
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(30)
        kb = page.evaluate("document.querySelector('#look-grid .look.kb')?.dataset.name || ''")
        ov = page.evaluate("document.querySelector('#frame .tryon.ready')?.textContent || ''")
        shown.append(bool(kb) and (kb in ov or kb == "Original" or page.evaluate(f"!!lookByName({kb!r})?.ai")))
    c.check("↓ steps through the looks, each shown on the photo at once", all(shown), str(shown))
    page.keyboard.press("ArrowUp")
    page.wait_for_timeout(50)
    kb = page.evaluate("document.querySelector('#look-grid .look.kb').dataset.name")
    before = page.evaluate(f"st.picked.has({kb!r})")
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    c.check("Return picks the look for Make", page.evaluate(f"st.picked.has({kb!r})") != before, kb)
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    c.check("Esc puts the photo back", not page.evaluate("!!document.querySelector('#frame .tryon')"))
    name = page.evaluate("[...document.querySelectorAll('#look-grid .look.row:not(.own)')].map(r => r.dataset.name).find(n => !lookByName(n).ai)")
    row = page.locator(f'#look-grid .look[data-name="{name}"]').first
    row.hover()
    row.locator("[data-fav]").click()
    page.wait_for_timeout(200)
    head = page.evaluate("document.querySelector('#look-grid .group-title')?.textContent")
    top = page.evaluate("document.querySelector('#look-grid .look.row:not(.own)')?.dataset.name")
    c.check("a starred look goes to Favorites at the top", head == "Favorites" and top == name, f"{head}: {top}")
    page.reload()
    page.wait_for_function("typeof st !== 'undefined' && st.slots.length > 0")
    page.evaluate(f"select({sid})")
    page.wait_for_timeout(800)
    c.check("favorites are remembered", page.evaluate("document.querySelector('#look-grid .group-title')?.textContent") == "Favorites")
    page.locator(f'#look-grid .look[data-name="{name}"] [data-fav]').first.click()  # (back as it was)
    page.wait_for_timeout(1500)
    chips = page.evaluate("[...document.querySelectorAll('#look-grid .look.row:not(.own)')].filter(r => !lookByName(r.dataset.name).ai && !lookByName(r.dataset.name).design).map(r => r.querySelector('.chip img').src.includes('/img/ahead/'))")
    c.check("each row's picture is that look on your photo", all(chips), f"{sum(chips)} of {len(chips)}")
    c.shot(page, "looks-list")
    c.check("no page errors (list)", not page.errors, "; ".join(page.errors[:2]))
    page.close()


# Phase 3: the whole event --------------------------------------------------------------------------

ALL_DRAWN = """(() => { const o = document.querySelector('#viewer .event-try'); if (!o) return false;
  const imgs = [...o.querySelectorAll('.event-grid img')];
  return imgs.length > 0 && imgs.every(i => i.complete && i.naturalWidth && i.src.includes('/img/event/')) })()"""


def event(c: Checks, browser, app, pid: int, sid: int, after_restart: bool = False) -> None:
    when = "after a restart" if after_restart else "first time"
    page = open_photo(browser, app, sid)
    page.click('#ahead-scope button[data-v="event"]')
    page.wait_for_timeout(300)
    n = page.evaluate("st.photos.length")
    names = page.evaluate("[...document.querySelectorAll('#look-grid .look.row:not(.own)')].map(r => r.dataset.name).filter(n => !lookByName(n).ai && !lookByName(n).design)")
    row_top = f"document.querySelector('#look-grid .look[data-name=\"{names[0]}\"]').getBoundingClientRect().top"
    top0 = page.evaluate(row_top)
    t0 = time.time()
    page.hover(f'#look-grid .look[data-name="{names[0]}"]')
    page.wait_for_timeout(300)
    tiles = page.evaluate("document.querySelectorAll('#viewer .event-try figure').length")
    drawn = page.evaluate("[...document.querySelectorAll('#viewer .event-try img')].filter(i => i.complete && i.naturalWidth).length")
    blur = page.evaluate(BLURRED)
    if not c.check(f"{when}: pointing at a look shows all {n} photos at once, none blank, none blurred",
                   tiles == n and drawn == n and not blur, f"{drawn} of {tiles} drawn after 0.3 s; blurred: {blur or 'none'}"):
        print("   page:", page.evaluate("JSON.stringify({look: " + repr(names[0]) + ", tryName, scope: st.aheadScope, active: st.activePhoto, "
                                        "current: st.current, mode: st.mode, view: st.view, rows: document.querySelectorAll('#look-grid .look').length, "
                                        "hovered: document.querySelector('#look-grid .look:hover')?.dataset.name})"))
        c.shot(page, f"event-{'restart' if after_restart else 'first'}-failed")
    page.wait_for_function(ALL_DRAWN, timeout=120000 if after_restart else 900000, polling=250)
    top1 = page.evaluate(row_top)
    c.check(f"{when}: the list never moves under the pointer while looks get ready", top0 == top1, f"row moved {top1 - top0:+.0f} px")
    c.check(f"{when}: the look reaches every photo", True, f"{time.time() - t0:.0f} s on this Mac ({(time.time() - t0) * 2:.0f} s M2 estimate)")
    page.mouse.move(700, 900)
    page.wait_for_timeout(300)
    page.evaluate("tryOff()")
    times = sliders(page, sid)
    c.check(f"{when}: sliders stay quick while the event is made (≤ 0.15 s; 0.3 s on an M2)", max(times) <= 0.15, f"{times} s")
    page.wait_for_function("evAhead.total > 0 && evAhead.complete.size >= evAhead.total", timeout=1200000, polling=1000)
    total = page.evaluate("evAhead.total")
    took = time.time() - t0
    if after_restart:
        c.check(f"after a restart: all {total} looks on all {n} photos come back from disk (≤ 10 s, nothing made again)",
                took <= 10, f"{took:.0f} s")
    else:
        c.check(f"all {total} looks on all {n} photos made in the background", True, f"{took:.0f} s ({took * 2 / 60:.1f} min M2 estimate)")
    page.evaluate("""() => { window._ev = []; document.querySelector('#look-grid').addEventListener('mouseover', (e) => {
        const b = e.target.closest('.look'); if (!b) return; const t0 = e.timeStamp, name = b.dataset.name;
        const check = () => { const o = document.querySelector('#viewer .event-try');
          const imgs = o ? [...o.querySelectorAll('.event-grid img')] : [];
          if (o && o.dataset.name === name && imgs.length && imgs.every(i => i.complete && i.naturalWidth && i.src.includes('/img/event/'))) {
            requestAnimationFrame(() => _ev.push(performance.now() - t0)); } else if (performance.now() - t0 < 3000) requestAnimationFrame(check); };
        requestAnimationFrame(check); }, true); }""")
    seq = names[:25]
    for nm in seq:
        box = page.locator(f'#look-grid .look[data-name="{nm}"]').first
        box.scroll_into_view_if_needed()
        bb = box.bounding_box()
        page.mouse.move(bb["x"] + 40, bb["y"] + bb["height"] / 2)
        page.wait_for_timeout(350)
    lat = page.evaluate("_ev")
    c.check(f"{when}: every one of the {n} photos swaps to the look under the pointer (≤ 300 ms)",
            len(lat) >= len(seq) - 1 and max(lat) <= 300,
            f"median {statistics.median(lat):.0f} ms, max {max(lat):.0f} ms over {len(lat)} looks")
    c.shot(page, f"event-{'restart' if after_restart else 'first'}")
    page.mouse.move(700, 900)
    page.wait_for_timeout(200)
    c.check(f"{when}: moving off puts the photo back", not page.evaluate("!!document.querySelector('#viewer .event-try')"))
    page.click('#ahead-scope button[data-v="photo"]')
    page.wait_for_timeout(300)
    page.hover(f'#look-grid .look[data-name="{names[3]}"]')
    page.wait_for_timeout(300)
    c.check(f"{when}: 'This photo' shows the look on the big photo again",
            page.evaluate("!!document.querySelector('#frame .tryon')") and not page.evaluate("!!document.querySelector('#viewer .event-try')"))
    c.check(f"no page errors (event, {when})", not page.errors, "; ".join(page.errors[:2]))
    page.close()


def event_photo_added(c: Checks, browser, app, sid: int, extra: Path) -> None:
    """A photo added after the event's previews were all made: it gets them too (no broken tiles)."""
    page = open_photo(browser, app, sid)
    page.click('#ahead-scope button[data-v="event"]')
    page.wait_for_function("evAhead.total > 0 && evAhead.complete.size >= evAhead.total", timeout=120000)
    app.add_photos([extra])
    page.wait_for_function(f"st.photos.length === {page.evaluate('st.photos.length') + 1}", timeout=30000)
    name = page.evaluate("[...document.querySelectorAll('#look-grid .look.row:not(.own)')].map(r => r.dataset.name).find(n => !lookByName(n).ai && !lookByName(n).design)")
    page.hover(f'#look-grid .look[data-name="{name}"]')
    page.wait_for_timeout(300)
    broken = page.evaluate("[...document.querySelectorAll('#viewer .event-try img')].filter(i => i.complete && !i.naturalWidth).length")
    c.check("a photo added later: no broken tiles while its previews are made", broken == 0, f"{broken} broken")
    page.wait_for_function(ALL_DRAWN, timeout=120000, polling=250)
    n = page.evaluate("document.querySelectorAll('#viewer .event-try figure').length")
    c.check("a photo added later gets the look too", n == page.evaluate("st.photos.length"), f"{n} photos shown")
    c.check("no page errors (photo added)", not page.errors, "; ".join(page.errors[:2]))
    page.close()
