"""Instagram reels from your looks: a vertical MP4 (1080 x 1920, 30 fps, H.264
and AAC) under a minute, ready to post.

It follows what worked in the video-reel generator's approved reels:
- Every photo on screen for the same time (2 s by default), shortened to fit
  the length (never under 1.5 s).
- Calm motion: a slow push-in on each photo, with short dissolves between them.
- One song with its cuts on the beat, and an opening title in the lower third
  (up to three lines).
- Vertical framing that keeps the play's context. A landscape photo shows about
  half its width, centered on the player, on a blurred copy of itself; a
  portrait photo fills the screen.
"""

import math
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
MAX_SEC = 59.0
PHOTO_SEC = 2.0
PHOTO_MIN_SEC = 1.5
FADE_SEC = 0.35
PUSH = 0.06  # how much each photo slowly zooms in over its time
TITLE_SEC = 3.0
CLOSING_SEC = 2.5
FONT = "/System/Library/Fonts/Avenir Next.ttc"  # index 0 is Bold
# Beats are counted between these lengths (a faster or slower beat is halved or doubled)
BEAT_RANGE = (0.35, 0.9)


@dataclass
class Shot:
    image: Image.Image
    focus: tuple[float, float] = (0.5, 0.5)  # the player: shares of the photo's width and height
    name: str = ""


@dataclass
class Plan:
    shots: list[Shot]
    seconds: float  # each photo's time on screen
    left_out: list[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return len(self.shots) * self.seconds


def fit(count: int, photo_sec: float = PHOTO_SEC, max_sec: float = MAX_SEC,
        beat: float | None = None) -> tuple[float, int]:
    """Each photo's time, and how many photos fit in max_sec.

    Photos get photo_sec, shortened so they all fit (but never under
    PHOTO_MIN_SEC; past that, the last ones are left out). With a beat, the
    time is the nearest whole number of beats, so every cut lands on one."""
    if count <= 0:
        return photo_sec, 0
    sec = max(PHOTO_MIN_SEC, min(photo_sec, max_sec / count))
    if beat:
        least = math.ceil(PHOTO_MIN_SEC / beat - 1e-9)
        beats = max(least, round(sec / beat))  # the whole number of beats nearest the time asked
        sec = beats * beat
    return sec, min(count, int(max_sec / sec + 1e-9))


def plan(shots: list[Shot], photo_sec: float = PHOTO_SEC, max_sec: float = MAX_SEC,
         beat: float | None = None) -> Plan:
    sec, keep = fit(len(shots), photo_sec, max_sec, beat)
    return Plan(shots[:keep], sec, [s.name for s in shots[keep:]])


def song_beat(path: str | Path) -> tuple[float, list[float]]:
    """The song's beat length (seconds) and its beat times."""
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True, duration=240)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    period = 60.0 / max(float(np.atleast_1d(tempo)[0]), 1.0)
    while period < BEAT_RANGE[0]:
        period *= 2
    while period > BEAT_RANGE[1]:
        period /= 2
    return period, [float(b) for b in beats]


def song_start(beats: list[float], wanted: float) -> float:
    """Where the song starts: the first beat at or after the wanted time, so
    the cuts fall on the beat."""
    later = [b for b in beats if b >= wanted - 1e-6]
    return later[0] if later else max(0.0, wanted)


# Pictures -------------------------------------------------------------------------

def _layers(shot: Shot) -> tuple[np.ndarray, np.ndarray]:
    """The blurred background (W x H) and the photo at its largest size."""
    img = np.asarray(shot.image.convert("RGB"))
    h, w = img.shape[:2]
    cover = max(W / w, H / h)
    # fill the screen, unless that would show less than half the photo's width
    scale = min(cover, 2 * W / w)
    small = cv2.resize(img, (max(1, int(w * cover / 8)), max(1, int(h * cover / 8))), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 6)
    bg = cv2.resize(small, (int(w * cover) + 2, int(h * cover) + 2), interpolation=cv2.INTER_LINEAR)
    y0, x0 = (bg.shape[0] - H) // 2, (bg.shape[1] - W) // 2
    bg = (bg[y0:y0 + H, x0:x0 + W].astype(np.float32) * 0.55).astype(np.uint8)
    big = cv2.resize(img, (round(w * scale * (1 + PUSH)), round(h * scale * (1 + PUSH))), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(bg), big


def _place(size: float, screen: int, focus: float) -> float:
    """Where the photo's edge goes so the focus is centered, without showing past its edges."""
    if size <= screen:
        return (screen - size) / 2
    return min(0.0, max(screen - size, screen / 2 - focus * size))


def _frame(layers, focus, t: float) -> np.ndarray:
    """One frame of a shot, t from 0 to 1 through its time on screen."""
    bg, big = layers
    k = (1 + PUSH * min(max(t, 0.0), 1.0)) / (1 + PUSH)
    fw, fh = big.shape[1] * k, big.shape[0] * k
    m = np.float32([[k, 0, _place(fw, W, focus[0])], [0, k, _place(fh, H, focus[1])]])
    out = bg.copy()
    cv2.warpAffine(big, m, (W, H), dst=out, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
    return out


def _text_card(text: str, where: str) -> np.ndarray | None:
    """White bold text with a soft shadow, as an RGBA layer, wrapped onto up to
    three lines: "lower" (a lower third, at the left) or "center" (centered, low)."""
    text = " ".join((text or "").split())
    if not text:
        return None
    lines = textwrap.wrap(text, 18)[:3]
    size = 84 if len(lines) == 1 else 72
    try:
        font = ImageFont.truetype(FONT, size, index=0)
    except OSError:
        font = ImageFont.load_default(size)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    gap = int(size * 1.15)
    block = gap * len(lines)
    # the lower third sits above Instagram's caption area at the bottom
    # both sit low, under the players' faces and above Instagram's caption area
    top = int(H * 0.70) - block if where == "lower" else int(H * 0.80) - block
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        x = 80 if where == "lower" else (W - width) / 2
        y = top + i * gap
        sdraw.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
    if where == "lower":
        draw.rectangle((80, top - 28, 80 + 120, top - 18), fill=(255, 255, 255, 255))
    out = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)), layer)
    return np.asarray(out)


def _over(frame: np.ndarray, card: np.ndarray, alpha: float) -> np.ndarray:
    a = card[..., 3:4].astype(np.float32) / 255 * alpha
    return (frame * (1 - a) + card[..., :3] * a).astype(np.uint8)


def _fade(t: float, start: float, end: float, ramp: float = 0.3) -> float:
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / ramp, (end - t) / ramp)


# Making the reel --------------------------------------------------------------------

def render(p: Plan, out: Path, song: str | Path | None = None, start: float = 0.0, title: str = "",
           closing: str = "", progress=None) -> Path:
    """Writes the reel as an MP4. progress(done, total) is called as frames are made."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is needed to make reels (brew install ffmpeg)")
    if not p.shots:
        raise ValueError("No photos for the reel")
    out.parent.mkdir(parents=True, exist_ok=True)
    length = p.length
    frames = int(round(length * FPS))
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if song:
        cmd += ["-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", str(song), "-map", "0:v", "-map", "1:a",
                "-af", f"afade=t=out:st={max(0.0, length - 2):.3f}:d=2", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-movflags", "+faststart", str(out)]
    title_card, closing_card = _text_card(title, "lower"), _text_card(closing, "center")
    sec, half = p.seconds, FADE_SEC / 2
    cache: dict[int, tuple] = {}

    def layers(i):
        if i not in cache:
            for old in [k for k in cache if k < i - 1]:
                del cache[old]
            cache[i] = _layers(p.shots[i])
        return cache[i]

    def shot_frame(i, now):
        # each photo's push-in runs across its time on screen, dissolves included
        t = (now - (i * sec - half)) / (sec + FADE_SEC)
        return _frame(layers(i), p.shots[i].focus, t)

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in range(frames):
            now = f / FPS
            i = min(int(now / sec), len(p.shots) - 1)
            frame = shot_frame(i, now)
            # dissolve into the next photo around the cut
            into = (i + 1) * sec - now
            if into < half and i + 1 < len(p.shots):
                a = 0.5 - into / FADE_SEC
                frame = cv2.addWeighted(frame, 1 - a, shot_frame(i + 1, now), a, 0)
            elif now - i * sec < half and i > 0:
                a = 0.5 + (now - i * sec) / FADE_SEC
                frame = cv2.addWeighted(shot_frame(i - 1, now), 1 - a, frame, a, 0)
            if title_card is not None and (fa := _fade(now, 0.3, min(TITLE_SEC, length - 0.2))):
                frame = _over(frame, title_card, fa)
            if closing_card is not None and (fa := _fade(now, max(0.0, length - CLOSING_SEC), length + 1)):
                frame = _over(frame, closing_card, fa)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            if progress and f % FPS == 0:
                progress(f, frames)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg could not make the reel: {err.strip()[-400:]}")
    return out
