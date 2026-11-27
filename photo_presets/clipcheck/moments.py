"""The moments in a video where a problem shows: soft pans, shaky stretches, brightness jumps, and
stretches that are too dark or too bright. Found from the per-frame measurements (video.measure)."""

from dataclasses import dataclass

import numpy as np

from photo_presets.clipcheck.video import FAST_FROM, PictureStats

SOFT_PAN = 0.5  # sharpness below this share of the still shots' sharpness, while panning fast
SHAKY = 20.0  # jitter around the smooth camera path (% of frame width per second), held for a moment
WHIP_PAN = 60.0  # faster than this the jitter is part of a whip pan, not a shaky hand
JUMP = 30  # brightness change (0-255) within about a second
DARK, BRIGHT = 45, 215
MIN_LENGTH = 0.4  # seconds: shorter than this is not a moment anyone sees
MOST = 8  # moments shown per clip, the worst first


@dataclass
class Moment:
    kind: str  # soft_pan, shaky, jump, dark, bright
    start: float  # seconds
    end: float
    label: str
    detail: str
    severity: float  # for ordering (higher is worse)

    @property
    def middle(self) -> float:
        return (self.start + self.end) / 2


def _runs(mask: np.ndarray, times: np.ndarray, gap: float = 0.3):
    """(start index, end index) of each stretch where mask holds, joining stretches less than gap apart."""
    out = []
    idx = np.flatnonzero(mask)
    if not len(idx):
        return out
    start = prev = idx[0]
    for i in idx[1:]:
        if times[i] - times[prev] > gap:
            out.append((start, prev))
            start = i
        prev = i
    out.append((start, prev))
    return out


def _rolling(values: np.ndarray, n: int) -> np.ndarray:
    n = max(1, n)
    pad = np.pad(values, (n // 2, n - 1 - n // 2), mode="edge")
    return np.array([np.median(pad[i:i + n]) for i in range(len(values))])


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def find(s: PictureStats, fps: float, duration: float) -> list[Moment]:
    if len(s.times) < 5:
        return []
    t = np.array(s.times)
    per_second = max(1, round(1 / max(1e-6, t[1] - t[0])))
    speed, sharp = np.array(s.speed), np.array(s.sharpness)
    bright = np.array(s.brightness)
    shake = _rolling(np.array(s.shake), per_second // 2) if s.shake else np.zeros(len(t))
    end_of = lambda j: min(duration, t[j] + (t[1] - t[0]))
    found: list[Moment] = []

    def add(kind, a, b, label, detail, severity):
        if end_of(b) - t[a] >= MIN_LENGTH:
            found.append(Moment(kind, round(float(t[a]), 2), round(float(end_of(b)), 2), label, detail, severity))

    if s.sharp_still:
        soft = (speed >= FAST_FROM) & (sharp < SOFT_PAN * s.sharp_still)
        for a, b in _runs(soft, t):
            loss = 1 - float(np.median(sharp[a:b + 1])) / s.sharp_still
            add("soft_pan", a, b, "Soft while panning",
                f"The picture loses {loss:.0%} of its sharpness as the camera swings "
                f"({float(np.median(speed[a:b + 1])):.0f}% of the frame width per second).", loss * (end_of(b) - t[a]))
    shaky = (shake >= SHAKY) & (_rolling(speed, per_second) < WHIP_PAN)
    for a, b in _runs(shaky, t, gap=0.5):
        add("shaky", a, b, "Shaky camera",
            "The frame jitters back and forth instead of moving smoothly.",
            float(np.median(shake[a:b + 1])) / SHAKY * (end_of(b) - t[a]))
    w = per_second
    change = np.zeros(len(t))
    change[w:] = np.abs(bright[w:] - bright[:-w])
    for a, b in _runs(change >= JUMP, t, gap=0.6):
        a0 = max(0, a - w)
        lo, hi = float(bright[a0:b + 1].min()), float(bright[a0:b + 1].max())
        first, last = float(bright[a0]), float(bright[b])
        how = (f"gets {'brighter' if last > first else 'darker'} quickly ({first:.0f} to {last:.0f}"
               if abs(last - first) >= JUMP else f"flickers between {lo:.0f} and {hi:.0f}")
        add("jump", a0, b, "Brightness jumps",
            f"The picture {how} on a 0-255 scale): "
            "the light changed, the camera swung between light and shade, or the exposure re-adjusted.",
            (hi - lo) / JUMP * 0.8)
    for kind, mask, label, why in (
            ("dark", _rolling(bright, w) < DARK, "Too dark", "Shadows and faces lose detail here."),
            ("bright", _rolling(bright, w) > BRIGHT, "Too bright", "Bright areas turn pure white here.")):
        for a, b in _runs(mask, t, gap=0.6):
            add(kind, a, b, label, f"{why} (average brightness {float(np.median(bright[a:b + 1])):.0f} of 255.)",
                (end_of(b) - t[a]) * 0.6)
    found.sort(key=lambda m: -m.severity)
    return sorted(found[:MOST], key=lambda m: m.start)


def clock(t: float) -> str:
    return _clock(t)
