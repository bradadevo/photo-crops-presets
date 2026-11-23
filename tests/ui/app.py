"""A separate test copy of VS Digital Pro for the browser tests: its own folder (never your photos,
looks or settings), started and stopped like the real app, with its memory watched the whole time."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import psutil
import requests

REPO = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class App:
    def __init__(self, state: Path):
        self.state = state
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.peak = 0.0  # GB: the most memory the app has used since `mark()`
        self._watching = False

    # starting and stopping -----------------------------------------------------------------------

    def start(self, log_name: str = "server.log") -> None:
        env = dict(os.environ, ALLPROPHOTO_STATE=str(self.state))
        self.proc = subprocess.Popen(["uv", "run", "vsdigitalpro", "--port", str(self.port), "--no-browser"],
                                     cwd=REPO, env=env, stdout=open(self.state / log_name, "w"),
                                     stderr=subprocess.STDOUT)
        for _ in range(240):
            try:
                requests.get(self.base + "/api/version", timeout=1)
                break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            raise RuntimeError("the test app did not start (see server.log)")
        self._watching = True
        threading.Thread(target=self._watch, daemon=True).start()

    def stop(self) -> None:
        """Quits as the real app is quit, and waits until it has really gone (as before reopening it)."""
        self._watching = False
        if self.proc is None:
            return
        procs = self._procs()
        self.proc.terminate()
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        psutil.wait_procs(procs, timeout=20)
        self.proc = None

    def restart(self) -> None:
        self.stop()
        self.start("server-restarted.log")

    # memory -------------------------------------------------------------------------------------

    def _procs(self) -> list[psutil.Process]:
        try:
            root = psutil.Process(self.proc.pid)
            return [root] + root.children(recursive=True)
        except (psutil.Error, AttributeError):
            return []

    def memory(self) -> float:
        total = 0
        for p in self._procs():
            try:
                total += p.memory_info().rss
            except psutil.Error:
                pass
        return total / 1e9

    def _watch(self) -> None:
        while self._watching:
            self.peak = max(self.peak, self.memory())
            time.sleep(0.2)

    def mark(self) -> None:
        """Starts measuring the peak afresh (for one part of a test)."""
        self.peak = self.memory()

    # the app's own API --------------------------------------------------------------------------

    def get(self, path: str, **kw):
        r = requests.get(self.base + path, timeout=60, **kw)
        r.raise_for_status()
        return r

    def post(self, path: str, body=None, **kw):
        r = requests.post(self.base + path, json=body, timeout=600, **kw)
        r.raise_for_status()
        return r.json()

    def state_now(self) -> dict:
        return self.get("/api/state").json()

    def add_photos(self, files: list[Path]) -> list[int]:
        added = []
        for i in range(0, len(files), 8):
            batch = [("files", (f.name, f.read_bytes(), "image/jpeg")) for f in files[i:i + 8]]
            added += self.post("/api/photos/upload", files=batch)["added"]
        return added

    def make(self, pid: int, look: str) -> dict:
        """Makes a look of a photo (as the Make button does) and waits until it's done."""
        out = self.post("/api/run", {"photos": [pid], "looks": [look]})["slots"]
        sid = out[0] if isinstance(out[0], int) else out[0]["id"]
        for _ in range(1200):
            s = next(x for x in self.state_now()["slots"] if x["id"] == sid)
            if s["state"] in ("done", "failed"):
                return s
            time.sleep(0.5)
        raise TimeoutError(f"{look} not made in 10 minutes")


def many_looks(target: int = 120) -> dict[str, dict]:
    """Extra looks (variations of the built-in non-AI ones) so the app has 100+ to make ahead, as a
    photographer with a big collection would."""
    import sys
    sys.path.insert(0, str(REPO))
    from photo_presets import presets, timing
    base = {n: r for n, r in presets.load_all().items() if not timing.uses_ai(r) and not r.get("design")}
    out: dict[str, dict] = {}
    k = 0
    while len(base) + len(out) < target:
        for name, recipe in base.items():
            if len(base) + len(out) >= target:
                break
            r = json.loads(json.dumps(recipe))
            r.setdefault("adjust", {})["exposure"] = round(0.1 * (k % 5 + 1) * (-1 if k % 2 else 1), 2)
            out[f"{name} · test {k}"] = r
            k += 1
    return out
