"""Learns your taste from your own pass-2 decisions (keep or reject), on this Mac: a small
logistic model over pass 1's measurements (sharpness, face, size in frame, ball, light...).
Once it has seen enough of both, its guess is blended into pass 1's score, so each game's first
pass gets closer to what you would pick."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

NAMES = ["sharp", "face", "size", "ball", "players", "light", "focus", "eyes_open"]
MIN_EACH = 12  # decisions of each kind (kept, rejected) before it is used
MAX_ROWS = 6000
_lock = threading.Lock()


def vector(f: dict, m: dict | None = None) -> list[float]:
    v = [float(f.get(k, 0.0)) for k in NAMES]
    m = m or {}
    v += [1.0 if m.get("team_photo") else 0.0, min(1.0, float(m.get("subject_height", 0)) * 2)]
    return v


class Taste:
    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[str, tuple[list[float], int]] = {}  # photo key -> (features, kept 1 / rejected 0)
        self.w: np.ndarray | None = None
        try:
            data = json.loads(path.read_text())
            self.rows = {k: (v[0], v[1]) for k, v in data.get("rows", {}).items()}
        except (OSError, ValueError):
            pass
        self._fit()

    def counts(self) -> tuple[int, int]:
        kept = sum(1 for _, y in self.rows.values() if y)
        return kept, len(self.rows) - kept

    @property
    def ready(self) -> bool:
        k, r = self.counts()
        return k >= MIN_EACH and r >= MIN_EACH

    def learn(self, key: str, f: dict, m: dict, kept: bool | None) -> None:
        """Your decision on one photo (None: you took it back)."""
        with _lock:
            if kept is None:
                self.rows.pop(key, None)
            else:
                self.rows[key] = (vector(f, m), 1 if kept else 0)
                if len(self.rows) > MAX_ROWS:
                    for k in list(self.rows)[: len(self.rows) - MAX_ROWS]:
                        self.rows.pop(k)

    def save(self) -> None:
        with _lock:
            self._fit()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"rows": self.rows}))
            tmp.replace(self.path)

    def _fit(self) -> None:
        if not self.ready:
            self.w = None
            return
        X = np.array([r[0] for r in self.rows.values()], np.float64)
        y = np.array([r[1] for r in self.rows.values()], np.float64)
        X = np.hstack([X, np.ones((len(X), 1))])
        # balanced: as many keeps as rejects count, whatever the shares
        wt = np.where(y == 1, 0.5 / max(y.mean(), 1e-6), 0.5 / max(1 - y.mean(), 1e-6))
        w = np.zeros(X.shape[1])
        for _ in range(400):  # plain gradient steps with a little ridge: small and steady
            p = 1 / (1 + np.exp(-X @ w))
            grad = X.T @ ((p - y) * wt) / len(y) + 0.01 * np.r_[w[:-1], 0]
            w -= 1.5 * grad
        self.w = w

    def __call__(self, f: dict, m: dict) -> float | None:
        if self.w is None:
            return None
        x = np.r_[vector(f, m), 1.0]
        return float(1 / (1 + np.exp(-x @ self.w)))
