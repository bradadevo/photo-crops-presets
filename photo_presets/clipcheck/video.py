"""Video clips: file and camera details, then measurements taken from the
picture itself (panning, sharpness, grain and brightness over time)."""

import json
import math
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from photo_presets.clipcheck import sony

# Size of the region measured, taken at full resolution from the frame center
# (scaling would hide grain and blur)
CROP_W, CROP_H = 1280, 720
# At most this many frames are measured per clip; long clips skip more frames
MAX_SAMPLES = 1500
# Panning speed in percent of the frame width per second
STILL_BELOW = 3.0
FAST_FROM = 12.0


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    codec: str
    profile: str
    bit_depth: str
    bitrate: float  # megabits per second
    recorded: str
    audio: str
    color: str
    camera: dict = field(default_factory=dict)  # settings from the camera's own data

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def frame_count(self) -> int:
        return round(self.duration * self.fps)


def duration_of(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def probe(path: str, every: int = 2) -> VideoInfo:
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
                                     capture_output=True, text=True, check=True).stdout)
    fmt = info["format"]
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
    video = next(s for s in info["streams"] if s.get("codec_type") == "video")
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    fps = float(Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30"))
    if not fps or math.isnan(fps):
        fps = float(Fraction(video.get("r_frame_rate", "30/1")))
    v = VideoInfo(
        path=str(path), width=int(video["width"]), height=int(video["height"]), fps=round(fps, 3),
        duration=float(fmt.get("duration") or video.get("duration") or 0), codec=video.get("codec_name", ""),
        profile=video.get("profile", ""), bit_depth=video.get("bits_per_raw_sample") or video.get("pix_fmt", ""),
        bitrate=int(fmt.get("bit_rate") or 0) / 1e6, recorded=tags.get("creation_time", ""),
        audio=f"{audio.get('codec_name')} {audio.get('sample_rate')} Hz, {audio.get('channels')} ch" if audio else "none",
        color="/".join(x for x in [video.get("color_primaries"), video.get("color_transfer")] if x) or "unknown",
    )
    camera = {}
    for key in ("com.apple.quicktime.make", "make"):
        if key in tags:
            camera["make"] = tags[key]
    for key in ("com.apple.quicktime.model", "model"):
        if key in tags:
            camera["camera"] = tags[key]
    xml = sony.xml_block(path) if tags.get("major_brand", "").startswith("XAVC") or camera.get("make") == "SONY" \
        else ""
    if xml:
        camera.update(sony.xml_info(xml))
        camera["make"] = "Sony"
    rtmd = next((s["index"] for s in info["streams"] if s.get("codec_tag_string") == "rtmd"), None)
    if rtmd is not None:
        camera.update(sony.summarize(sony.per_frame(path, rtmd, v.frame_count, every)))
        camera["series_every_s"] = every / fps if fps else None
    v.camera = camera
    return v


@dataclass
class PictureStats:
    samples: int
    every: int
    still_share: float
    slow_share: float
    fast_share: float
    fastest_pan: float  # percent of frame width per second
    sharp_still: float | None
    sharp_slow: float | None
    sharp_fast: float | None
    grain_still: float | None
    pan_sharpness_loss: float | None  # 0..1
    brightness: list[float]  # average brightness per sample, 0..255
    brightness_swing: float  # largest change within about 2 seconds, 0..255
    # Per measured frame (the same order as brightness), for finding the moments where problems happen
    times: list[float] = field(default_factory=list)  # seconds into the clip
    sharpness: list[float] = field(default_factory=list)
    speed: list[float] = field(default_factory=list)  # panning, % of frame width per second
    shake: list[float] = field(default_factory=list)  # jitter around the smooth camera path, same units


def sample_step(v: VideoInfo, every: int) -> int:
    return max(every, math.ceil(v.frame_count / MAX_SAMPLES))


def grain_of(gray: np.ndarray) -> float:
    """Grain (noise) level in the flat parts of the picture."""
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    residue = np.abs(cv2.filter2D(gray.astype(np.float32), -1, kernel))
    edges = cv2.Sobel(gray, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(gray, cv2.CV_32F, 0, 1) ** 2
    flat = edges < 400
    return float(residue[flat].mean() * math.sqrt(math.pi / 2) / 6) if flat.any() else float("nan")


def measure(v: VideoInfo, every: int = 2) -> PictureStats:
    step = sample_step(v, every)
    w, h = min(CROP_W, v.width), min(CROP_H, v.height)
    cmd = ["ffmpeg", "-v", "error", "-i", v.path, "-vf", f"select=not(mod(n\\,{step})),crop={w}:{h},format=gray",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    window = cv2.createHanningWindow((w // 4, h // 4), cv2.CV_32F)
    previous, sharp, grain, speed, bright, moves = None, [], [], [], [], []
    while True:
        buf = proc.stdout.read(w * h)
        if len(buf) < w * h:
            break
        gray = np.frombuffer(buf, np.uint8).reshape(h, w)
        sharp.append(cv2.Laplacian(gray, cv2.CV_64F).var())
        grain.append(grain_of(gray))
        bright.append(float(gray.mean()))
        small = cv2.resize(gray, (w // 4, h // 4)).astype(np.float32)
        if previous is None:
            speed.append(0.0)
            moves.append((0.0, 0.0))
        else:
            (dx, dy), _ = cv2.phaseCorrelate(previous, small, window)
            px_per_frame = math.hypot(dx, dy) * 4 / step
            speed.append(px_per_frame * v.fps / v.width * 100)
            moves.append((dx * 4 / step * v.fps / v.width * 100, dy * 4 / step * v.fps / v.width * 100))
        previous = small
    proc.wait()
    if len(sharp) < 2:
        raise ValueError("could not read enough frames")
    sharp_a, grain_a, speed_a = np.array(sharp[1:]), np.array(grain[1:]), np.array(speed[1:])
    still = speed_a < STILL_BELOW
    fast = speed_a >= FAST_FROM
    slow = ~still & ~fast

    def median(values, mask):
        return float(np.nanmedian(values[mask])) if mask.sum() >= 5 else None

    s_still, s_fast = median(sharp_a, still), median(sharp_a, fast)
    window_n = max(1, round(2 * v.fps / step))
    swing = max((max(bright[i:i + window_n]) - min(bright[i:i + window_n]) for i in range(len(bright))), default=0)
    return PictureStats(
        samples=len(sharp), every=step, still_share=float(still.mean()), slow_share=float(slow.mean()),
        fast_share=float(fast.mean()), fastest_pan=float(np.percentile(speed_a, 99)), sharp_still=s_still,
        sharp_slow=median(sharp_a, slow), sharp_fast=s_fast, grain_still=median(grain_a, still) or
        float(np.nanmedian(grain_a)), pan_sharpness_loss=(1 - s_fast / s_still) if s_still and s_fast else None,
        brightness=bright, brightness_swing=float(swing),
        times=[i * step / v.fps for i in range(len(sharp))], sharpness=[float(x) for x in sharp],
        speed=[float(x) for x in speed], shake=shake_of(moves, max(3, round(0.5 * v.fps / step))))


def shake_of(moves: list[tuple[float, float]], span: int) -> list[float]:
    """How far each frame's movement strays from the smooth camera path around it (a pan is smooth;
    a shaky hand jitters back and forth)."""
    if not moves:
        return []
    m = np.array(moves, np.float64)
    k = np.ones(span) / span
    smooth = np.stack([np.convolve(m[:, i], k, mode="same") for i in (0, 1)], 1)
    return [float(x) for x in np.hypot(*(m - smooth).T)]
