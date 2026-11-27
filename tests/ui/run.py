"""The browser tests: VS Digital Pro clicked through in real Chrome, on a separate test copy, with real
photos, before a change reaches the app. Every bar from docs/plans/instant-looks.md is a pass/fail line.

    uv run --with playwright --with psutil --with requests python tests/ui/run.py --photos "<folder of event photos>"

About 10 minutes for 40 photos. Screenshots and the app's log go in the test folder it prints.
It never touches your own photos, looks or settings (the test copy has its own folder).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import App, many_looks  # noqa: E402
import scenarios as sc  # noqa: E402

PHOTO_TYPES = {".jpg", ".jpeg"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", required=True, help="a folder of real event photos (JPEG)")
    ap.add_argument("--count", type=int, default=40, help="how many of them (default 40, a typical event)")
    ap.add_argument("--looks", type=int, default=120, help="looks in the app, made ahead (default 120)")
    ap.add_argument("--out", help="the test folder (default: a new one in the system's temporary folder)")
    args = ap.parse_args()

    every = sorted(f for f in Path(args.photos).expanduser().iterdir() if f.suffix.lower() in PHOTO_TYPES)
    files, extra = every[:args.count], every[args.count:args.count + 1]  # (one more, added later)
    if len(files) < 2:
        print(f"Need at least 2 JPEG photos in {args.photos}")
        return 2
    state = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="vsdigitalpro-ui-"))
    state.mkdir(parents=True, exist_ok=True)
    (state / "presets.json").write_text(json.dumps(many_looks(args.looks)))
    print(f"Test copy: {state}\n{len(files)} photos from {args.photos}\n")

    from playwright.sync_api import sync_playwright
    c = sc.Checks(state)
    app = App(state)
    t0 = time.time()
    try:
        app.start()
        pids = app.add_photos(files)
        pid = pids[0]
        sid = app.make(pid, "Original")["id"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)

            print("== Hover on the current photo (nothing made yet)")
            app.mark()
            sc.hover(c, browser, app, pid, sid)
            editing_peak = app.peak  # (making every look includes the full player cut-out: normal editing)
            print(f"   memory: peak {editing_peak:.1f} GB while editing and making looks ahead")

            print("== The whole event (nothing made yet)")
            app.mark()
            sc.event(c, browser, app, pid, sid)
            c.check("the whole-event work never needs more memory than normal editing (+0.3 GB)",
                    app.peak <= editing_peak + 0.3, f"peak {app.peak:.1f} GB vs editing {editing_peak:.1f} GB")
            print("== A photo opened a while after it was added")
            later = pids[3]
            sc.opened_later(c, browser, app, later, app.make(later, "Original")["id"])
            print("== The page at every common window size")
            sc.layout(c, browser, app)
            browser.close()

        print("== Quit and reopen the app")
        name = next(x["name"] for x in app.state_now()["photos"] if x["id"] == pid)
        app.restart()
        now = app.state_now()  # (reopened, the app numbers photos and looks afresh: found again by name)
        pid = next(x["id"] for x in now["photos"] if x["name"] == name)
        sid = next(x["id"] for x in now["slots"] if x["photo"] == pid and x["look"] == "Original")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            print("== The whole event, after the restart")
            sc.event(c, browser, app, pid, sid, after_restart=True)
            print("== The looks list")
            sc.looks_list(c, browser, app, pid, sid)
            if extra:
                print("== A photo added later")
                sc.event_photo_added(c, browser, app, sid, extra[0])
            browser.close()
    except Exception as e:  # (a test that can't go on is a failure, said plainly)
        c.check("the tests ran to the end", False, f"{type(e).__name__}: {e}")
    finally:
        app.stop()

    failed = [r for r in c.results if not r[1]]
    print(f"\n{len(c.results) - len(failed)} of {len(c.results)} passed in {(time.time() - t0) / 60:.0f} min. Test copy: {state}")
    for name, _, detail in failed:
        print(f"  FAIL {name}  [{detail}]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
