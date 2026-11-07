"""The questionnaire: a page on this Mac, opened in the browser.

It asks every question, picks folders with the Mac's own folder dialog, shows
the estimate, runs the job with live progress, and can copy the answers as
instructions to paste to Claude. It listens only on this computer
(127.0.0.1), and every action needs the page's own random token.
"""

import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from photo_crops import images, run, settings
from photo_crops.settings import Settings

PORT = 8765
PAGE = Path(__file__).with_name("ui.html")
LOG_LINES = 400


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.status = {"state": "idle", "done": 0, "total": 0, "log": [], "out": ""}

    def update(self, **kw):
        with self.lock:
            log = kw.pop("line", None)
            self.status.update(kw)
            if log:
                self.status["log"] = (self.status["log"] + [log])[-LOG_LINES:]

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.status))


STATE = State()
TOKEN = secrets.token_urlsafe(16)


def recent_folders(limit: int = 12) -> list[str]:
    """Folders in ~/Movies and ~/Pictures that hold photos, newest first."""
    found = []
    for root in (Path.home() / "Movies", Path.home() / "Pictures"):
        if not root.is_dir():
            continue
        for d in root.iterdir():
            try:
                if d.is_dir() and not d.name.startswith(".") and any(images.is_image(f) for f in d.iterdir()):
                    found.append((d.stat().st_mtime, str(d)))
            except OSError:
                continue
    return [p for _, p in sorted(found, reverse=True)[:limit]]


def card_folders() -> list[str]:
    """Photo folders on memory cards (DCIM) currently plugged in."""
    out = []
    for dcim in Path("/Volumes").glob("*/DCIM"):
        try:
            out += [str(d) for d in sorted(dcim.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        except OSError:
            continue
    return out


def choose_folder(prompt: str, start: str) -> str:
    """The Mac's own folder dialog; '' when cancelled."""
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    script = f"POSIX path of (choose folder with prompt {q(prompt)}"
    if start and Path(start).expanduser().is_dir():
        script += f" default location (POSIX file {q(str(Path(start).expanduser()))})"
    script += ")"
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip().rstrip("/") if r.returncode == 0 else ""


def start_run(s: Settings) -> str | None:
    with STATE.lock:
        if STATE.thread and STATE.thread.is_alive():
            return "A run is already going"
    problems = s.problems()
    if problems:
        return "; ".join(problems)
    s.save()
    STATE.stop.clear()
    STATE.update(state="running", done=0, total=0, log=[], out=str(s.out_path))

    def progress(done: int, total: int, message: str) -> None:
        STATE.update(done=done, total=total, line=message)

    def work():
        try:
            run.run(s, progress, STATE.stop)
            STATE.update(state="stopped" if STATE.stop.is_set() else "done")
        except Exception as e:
            STATE.update(state="error", line=f"Error: {e}")

    STATE.thread = threading.Thread(target=work, daemon=True)
    STATE.thread.start()
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, kind: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE.read_text().replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(STATE.snapshot())
        else:
            self._send(404, b"{}")

    def do_POST(self):
        if self.headers.get("X-Token") != TOKEN:
            return self._json({"error": "bad token"}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/setup":
            self._json({"settings": asdict(Settings.load()), "recent": recent_folders(), "cards": card_folders(),
                        "options": {"versions": settings.VERSIONS, "shape": settings.SHAPES,
                                    "faces": settings.FACES, "edit": settings.EDITS,
                                    "screenshots": settings.SCREENSHOTS, "no_match": settings.NO_MATCH}})
        elif self.path == "/api/choose":
            self._json({"path": choose_folder(body.get("prompt", "Choose a folder"), body.get("start", ""))})
        elif self.path == "/api/check":
            s = Settings.from_dict(body)
            problems = s.problems()
            summary = "" if problems else run.prepare(s).summary()
            self._json({"problems": problems, "summary": summary, "instructions": s.instructions()})
        elif self.path == "/api/run":
            error = start_run(Settings.from_dict(body))
            self._json({"error": error} if error else {"ok": True})
        elif self.path == "/api/stop":
            STATE.stop.set()
            self._json({"ok": True})
        elif self.path == "/api/open":
            target = Path(STATE.snapshot()["out"])
            if target.is_dir():
                subprocess.run(["open", str(target)])
            self._json({"ok": target.is_dir()})
        else:
            self._json({"error": "unknown"}, 404)


def main() -> int:
    server = None
    for port in range(PORT, PORT + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        print("No free port found", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"photo-crops is open at {url}  (press Ctrl+C here to quit)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        STATE.stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
