"""Fixes for a file you already have. Each problem found suggests a fix you can switch on and adjust;
the result is always a new file next to the original (the original is never changed). No AI: plain
image and video processing (OpenCV, ffmpeg)."""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from photo_presets.clipcheck import still

FIXED_FOLDER = ("Clip Analysis", "Fixed")
TARGET = 0.46  # the brightness a well exposed picture averages (0..1)
FINE = (0.36, 0.62)  # averages in this range look right (a sunny field is brighter than a gym)
PREVIEW_EDGE = 1600


@dataclass
class Fix:
    id: str
    label: str
    what: str  # what it does
    limit: str  # what it cannot do (said plainly)
    lo: float
    hi: float
    step: float
    unit: str = ""


CATALOG = {
    "exposure": Fix("exposure", "Brightness", "Brightens or darkens the picture, keeping the brightest and darkest parts.",
                    "Brightening a dark picture also shows more grain.", -1.5, 1.5, 0.05, "stops"),
    "highlights": Fix("highlights", "Recover bright areas", "Brings back detail in skies, white shirts and lights.",
                      "Pure white areas in a JPEG have no detail left to bring back; RAW files recover far more.",
                      0, 1, 0.05),
    "color": Fix("color", "Neutral color", "Takes away a color cast (too orange, too blue, too green).",
                 "Judged from the gray and white things in the picture; with none, it does little.", 0, 1, 0.05),
    "even": Fix("even", "Even out brightness", "Smooths quick brightness changes so the clip doesn't pump.",
                "Can't tell a real change in the light from a camera re-adjusting: it softens both.", 0, 1, 0.05),
    "grain": Fix("grain", "Reduce grain", "Cleans up the grain (noise) from high ISO or dark scenes.",
                 "Strong settings also smooth fine detail like grass and hair.", 0, 1, 0.05),
    "sharpen": Fix("sharpen", "Sharpen", "Makes edges crisper.",
                   "It can't fix missed focus or motion blur; too much adds halos and grain.", 0, 1, 0.05),
    "steady": Fix("steady", "Steady the camera", "Smooths out the jitter of a shaky hand; pans stay pans.",
                  "Zooms in a little to hide the moving edges; motion blur inside the frames stays.", 0, 1, 0.05),
}
VIDEO_FIXES = ("exposure", "color", "even", "grain", "sharpen", "steady")
PHOTO_FIXES = ("exposure", "highlights", "color", "grain", "sharpen")


# --- measuring the look -------------------------------------------------------------------------------

def _gray_world(rgb: np.ndarray) -> tuple[list[float], float]:
    """Gains that make the near-neutral parts (white shirts, lines, concrete, sky haze) neutral, and the
    share of the picture that is near-neutral (little of it: the gains can't be trusted)."""
    small = cv2.resize(rgb, (320, max(1, round(320 * rgb.shape[0] / rgb.shape[1]))), interpolation=cv2.INTER_AREA)
    f = small.reshape(-1, 3).astype(np.float32) / 255
    lum = f.mean(1)
    sat = (f.max(1) - f.min(1)) / np.maximum(f.max(1), 1e-4)
    neutral = (sat < 0.22) & (lum > 0.18) & (lum < 0.92)
    share = float(neutral.mean())
    if neutral.sum() < 50:
        return [1.0, 1.0, 1.0], share
    m = f[neutral].mean(0)
    gains = (m.mean() / np.maximum(m, 1e-4)).clip(0.7, 1.4)
    return [float(x) for x in gains], share


def measure_look(path: str, kind: str, duration: float = 0) -> dict:
    """Average brightness (0..1) and the color cast, from the photo or a dozen frames of the video."""
    if kind == "photo":
        frames = [load_rgb(path, 1200)]
    else:
        n = 12
        frames = [f for f in (frame_at(path, duration * (i + 0.5) / n, 480) for i in range(n)) if f is not None]
    if not frames:
        return {"brightness": TARGET, "gains": [1, 1, 1], "neutral": 0, "white": 0}
    stack = np.concatenate([f for f in frames if f.shape[1] == frames[0].shape[1]], axis=0)  # (one tall picture)
    gains, share = _gray_world(stack)
    lum = stack.astype(np.float32).mean(2) / 255
    return {"brightness": float(lum.mean()), "gains": gains, "neutral": share,
            "white": float((stack.max(2) >= 254).mean())}


def cast_name(gains: list[float]) -> str:
    """The cast, in words: the color there is too much of (its gain is the lowest) or too little of."""
    r, g, b = gains
    lo = min(gains)
    if lo == g and g < 0.97:
        return "a green"
    if lo == r:
        return "an orange" if g < 1 else "a red"
    if lo == b:
        return "a blue" if g >= 1 else "a cyan"
    return "a magenta" if g > 1.03 else "a slight"


def _cast(gains: list[float]) -> float:
    return max(gains) / min(gains) - 1


def suggest(kind: str, stats, look: dict, camera: dict | None = None, shaky_share: float = 0.0, path: str = "") -> list[dict]:
    """The fixes worth offering for this file, each with its suggested setting and whether it is on."""
    out = []
    b = look["brightness"]

    def add(fid, value, on, why):
        f = CATALOG[fid]
        out.append({"id": fid, "label": f.label, "what": f.what, "limit": f.limit, "lo": f.lo, "hi": f.hi,
                    "step": f.step, "unit": f.unit, "value": round(value, 2), "on": on, "why": why})

    ev = exposure_for(b)
    if not FINE[0] <= b <= FINE[1] and abs(ev) >= 0.2:
        add("exposure", ev, True, f"It averages {b * 255:.0f} of 255: {'dark' if b < FINE[0] else 'bright'} "
            f"(about {FINE[0] * 255:.0f}-{FINE[1] * 255:.0f} looks right).")
    else:
        add("exposure", 0.0, False, "The brightness looks right; adjust it if you like.")
    if kind == "photo" and stats.highlights_clipped > 0.005:
        raw = Path(path).suffix.lower() in still.RAW_EXTENSIONS
        add("highlights", 0.6, True, f"{stats.highlights_clipped:.1%} of it is pure white"
            + (" (a RAW file: there is detail to recover)." if raw else "."))
    cast = _cast(look["gains"])
    if cast >= 0.08 and look["neutral"] >= 0.02:
        add("color", 0.6, True, f"It has {cast_name(look['gains'])} cast ({cast:.0%} off neutral on its gray and "
            "white things).")
    else:
        add("color", 0.0, False, "The color looks neutral." if look["neutral"] >= 0.02
            else "Not enough gray or white in it to judge the color.")
    if kind == "video":
        swing = stats.brightness_swing
        pumping = (camera or {}).get("exposure_mode", "Manual") != "Manual"
        add("even", 0.6 if pumping else 0.4, swing >= 40 and pumping,
            f"The brightness swings by up to {swing:.0f} of 255 within 2 seconds"
            + (" as the camera re-adjusted." if pumping else " (from the scene itself; evening it is optional).")
            if swing >= 25 else "The brightness is steady.")
        add("steady", 0.6, shaky_share >= 0.2,
            f"The camera jitters in {shaky_share:.0%} of the clip." if shaky_share >= 0.05 else "The camera is steady.")
        grain = stats.grain_still or 0
    else:
        grain = stats.grain
    noisy = 1.4 if kind == "video" else 1.9  # (see advice.NOTICEABLE_GRAIN_PHOTO)
    add("grain", min(1.0, max(0.3, (grain - 1.0) * 1.2)), grain >= noisy,
        f"Grain measures {grain:.2f} (clean is about 1.0).")
    soft = (kind == "photo" and stats.focus_sharpness < (40 if Path(path).suffix.lower() in still.RAW_EXTENSIONS else 110)) or (kind == "video" and (stats.sharp_still or 999) < 150)
    add("sharpen", 0.35, soft, "It measures a little soft." if soft else "It is already sharp; a touch is optional.")
    order = VIDEO_FIXES if kind == "video" else PHOTO_FIXES
    return sorted(out, key=lambda f: order.index(f["id"]))


def exposure_for(brightness: float) -> float:
    """The Brightness setting (in stops) that brings this average brightness into the range that looks
    right (to its nearer end: a gentle change)."""
    b = min(0.97, max(0.03, brightness))
    goal = min(FINE[1] - 0.04, max(FINE[0] + 0.06, b))
    gamma = math.log(goal) / math.log(b)
    ev = -math.log2(gamma) / 0.55
    return round(max(-1.5, min(1.5, ev)) * 20) / 20


# --- photos -------------------------------------------------------------------------------------------

def load_rgb(path: str, edge: int | None = None, highlights: float = 0.0) -> np.ndarray:
    """The photo as 8-bit RGB (RAW files developed; with highlights, developed darker to keep the
    brightest detail, then brought back up in the mid tones)."""
    ext = Path(path).suffix.lower()
    if ext in still.RAW_EXTENSIONS:
        import rawpy
        # developed about as bright as the camera's own JPEG (1% allowed to clip); keeping highlights,
        # less is allowed to clip and the mid tones are lifted back
        thr = 0.01 * (1 - 0.85 * highlights)
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, auto_bright_thr=thr, output_bps=16,
                                  highlight_mode=rawpy.HighlightMode.Blend if highlights else rawpy.HighlightMode.Clip,
                                  half_size=bool(edge and edge <= 2000))
        img = rgb.astype(np.float32) / 65535
        if highlights:
            img = img ** (1 / (1 + 0.5 * highlights))
        out = (img.clip(0, 1) * 255 + 0.5).astype(np.uint8)
    elif ext in still.HEIF_EXTENSIONS:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        out = np.array(Image.open(path).convert("RGB"))
    else:
        bgr = cv2.imread(path, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("could not read the image")
        out = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if edge and max(out.shape[:2]) > edge:
        k = edge / max(out.shape[:2])
        out = cv2.resize(out, (round(out.shape[1] * k), round(out.shape[0] * k)), interpolation=cv2.INTER_AREA)
    return out


def _roll_off(x: np.ndarray, amount: float) -> np.ndarray:
    """Bright tones compressed toward white (amount 0..1) so near-white detail separates again."""
    if amount <= 0:
        return x
    knee = 1 - 0.35 * amount
    over = np.maximum(x - knee, 0)
    span = 1 - knee
    return np.where(x > knee, knee + span * (1 - np.exp(-over / span * 1.6)) / (1 - math.exp(-1.6)), x)


def apply_photo(rgb: np.ndarray, settings: dict, raw: bool = False) -> np.ndarray:
    """The photo with the fixes switched on (settings: {id: {on, value}})."""
    on = lambda k: settings.get(k, {}).get("on") and settings[k].get("value", 0)
    img = rgb.astype(np.float32) / 255
    if on("color"):
        gains, _ = _gray_world(rgb)
        a = settings["color"]["value"]
        img = img * np.array([1 + a * (g - 1) for g in gains], np.float32)
    if on("exposure"):
        img = img.clip(0, 1) ** (2 ** (-settings["exposure"]["value"] * 0.55))
    if on("highlights") and not raw:  # (a RAW file's are recovered as it is developed)
        img = _roll_off(img.clip(0, 1), settings["highlights"]["value"])
    out = (img.clip(0, 1) * 255 + 0.5).astype(np.uint8)
    if on("grain"):
        a = settings["grain"]["value"]
        scale = max(out.shape[:2]) / 6000
        h = (2 + 8 * a) * max(0.5, scale)
        out = cv2.fastNlMeansDenoisingColored(out, None, h, h, 5, 15)
    if on("sharpen"):
        a = settings["sharpen"]["value"]
        sigma = max(0.6, 1.2 * max(out.shape[:2]) / 6000)
        blur = cv2.GaussianBlur(out, (0, 0), sigma)
        out = cv2.addWeighted(out, 1 + 1.4 * a, blur, -1.4 * a, 0)
    return out


def photo_preview(path: str, settings: dict) -> np.ndarray:
    hl = settings.get("highlights", {})
    raw = Path(path).suffix.lower() in still.RAW_EXTENSIONS
    rgb = load_rgb(path, PREVIEW_EDGE, hl.get("value", 0) if hl.get("on") and raw else 0)
    return apply_photo(rgb, settings, raw)


def fix_photo(path: str, settings: dict, dest: Path) -> Path:
    hl = settings.get("highlights", {})
    raw = Path(path).suffix.lower() in still.RAW_EXTENSIONS
    out = apply_photo(load_rgb(path, None, hl.get("value", 0) if hl.get("on") and raw else 0), settings, raw)
    from PIL import Image
    img = Image.fromarray(out)
    exif = None
    try:
        exif = Image.open(path).info.get("exif") if not raw else None
    except Exception:
        pass
    img.save(dest, "JPEG", quality=95, **({"exif": exif} if exif else {}))
    return dest


def marks(path: str) -> np.ndarray:
    """The photo with its problem areas marked: pure white in red, pure black in blue."""
    rgb = load_rgb(path, PREVIEW_EDGE)
    gray = rgb.max(2)
    out = (rgb.astype(np.float32) * 0.55).astype(np.uint8)
    out[gray >= 254] = (255, 40, 40)
    out[rgb.min(2) <= 2] = (40, 110, 255)
    return out


# --- videos -------------------------------------------------------------------------------------------

def frame_at(path: str, t: float, width: int = 0, vf: str = "") -> np.ndarray | None:
    """One frame (RGB), optionally made smaller and passed through the fixes' filters."""
    chain = ",".join(x for x in [vf, f"scale={width}:-2" if width else ""] if x)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", path, "-frames:v", "1",
           *(["-vf", chain] if chain else []), "-f", "image2pipe", "-vcodec", "png", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    if not out:
        return None
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def video_filters(settings: dict, look: dict, fps: float) -> str:
    """The ffmpeg filters for the fixes switched on (steadying and evening are done frame by frame)."""
    on = lambda k: settings.get(k, {}).get("on") and settings[k].get("value", 0)
    f = []
    if on("color"):
        a = settings["color"]["value"]
        r, g, b = (1 + a * (x - 1) for x in look.get("gains", [1, 1, 1]))
        f.append(f"colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f}")
    if on("exposure"):
        gamma = 2 ** (-settings["exposure"]["value"] * 0.55)
        f.append(f"eq=gamma={1 / gamma:.3f}")
    if on("grain"):
        a = settings["grain"]["value"]
        f.append(f"hqdn3d={1 + 4 * a:.1f}:{1 + 3 * a:.1f}:{3 + 6 * a:.1f}:{3 + 4 * a:.1f}")
    if on("sharpen"):
        f.append(f"unsharp=5:5:{0.3 + 1.0 * settings['sharpen']['value']:.2f}:5:5:0")
    return ",".join(f)


def video_preview(path: str, t: float, settings: dict, look: dict, fps: float) -> np.ndarray | None:
    return frame_at(path, t, PREVIEW_EDGE, video_filters(settings, look, fps))


def _first_pass(path: str, width: int, height: int, fps: float, track: bool,
                progress: Callable[[float], None]) -> tuple[np.ndarray, list[float]]:
    """Read once on a small copy: how the camera moved from frame to frame (when steadying) and each
    frame's brightness (0..1)."""
    sw = 640
    sh = round(height * sw / width / 2) * 2
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-vf", f"scale={sw}:{sh},format=gray",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    total = max(1, round(duration_of(path) * fps))
    moves, bright, prev, pts = [], [], None, None
    while True:
        buf = proc.stdout.read(sw * sh)
        if len(buf) < sw * sh:
            break
        gray = np.frombuffer(buf, np.uint8).reshape(sh, sw)
        bright.append(float(gray.mean()) / 255)
        if track:
            dx = dy = da = 0.0
            if prev is not None and pts is not None and len(pts) >= 8:
                nxt, ok, _ = cv2.calcOpticalFlowPyrLK(prev, gray, pts, None)
                good = ok.reshape(-1) == 1
                if good.sum() >= 8:
                    m, _ = cv2.estimateAffinePartial2D(pts[good], nxt[good])
                    if m is not None:  # (how the frame's center moved, and the turn around it)
                        c = np.array([sw / 2, sh / 2, 1.0])
                        mx, my = m @ c
                        dx, dy = (mx - c[0]) * width / sw, (my - c[1]) * width / sw
                        da = math.atan2(m[1, 0], m[0, 0])
            moves.append((dx, dy, da))
            pts = cv2.goodFeaturesToTrack(gray, 200, 0.01, 20)
            prev = gray
        if len(bright) % 30 == 0:
            progress(0.3 * min(1.0, len(bright) / total))
    proc.wait()
    return np.array(moves, np.float64).reshape(-1, 3), bright


def _smooth(values: np.ndarray, radius: int) -> np.ndarray:
    k = np.ones(2 * radius + 1) / (2 * radius + 1)
    pad = np.pad(values, ((radius, radius),) + ((0, 0),) * (values.ndim - 1), mode="edge")
    if values.ndim == 1:
        return np.convolve(pad, k, mode="valid")
    return np.stack([np.convolve(pad[:, i], k, mode="valid") for i in range(values.shape[1])], 1)


def steadying(moves: np.ndarray, width: int, height: int, fps: float, amount: float) -> tuple[np.ndarray, float]:
    """Each frame's correction toward the smooth path the camera should have taken (a pan stays a pan),
    and the zoom that hides the moving edges."""
    path = np.cumsum(moves, 0)
    corr = _smooth(path, max(2, round(fps * (0.1 + 0.4 * amount)))) - path  # (short: it follows the action)
    limit = np.percentile(np.abs(corr[:, :2]), 98, axis=0) if len(corr) else np.zeros(2)
    zoom = float(min(1.08, 1 + 2 * max(limit[0] / width, limit[1] / height) + 0.01))
    margin = np.array([(zoom - 1) / 2 * width, (zoom - 1) / 2 * height])
    corr[:, :2] = np.clip(corr[:, :2], -margin, margin)  # (never shows the edge of the frame)
    return corr, zoom


def evening(bright: list[float], fps: float, amount: float) -> list[np.ndarray]:
    """Per frame, a tone curve that moves its brightness toward the smooth trend around it (the curve
    keeps black black and white white)."""
    b = np.clip(np.array(bright), 0.03, 0.97)
    trend = _smooth(b, max(2, round(fps * (0.5 + 2.5 * amount))))
    goal = b + (trend - b) * min(1.0, 0.4 + 0.6 * amount)
    x = np.arange(256) / 255
    luts = []
    for now, want in zip(b, goal):
        g = float(np.clip(math.log(want) / math.log(now), 0.6, 1.6))
        luts.append((x ** g * 255 + 0.5).astype(np.uint8))
    return luts


def duration_of(path: str) -> float:
    from photo_presets.clipcheck.video import duration_of as d
    return d(path)


def fix_video(path: str, settings: dict, look: dict, info, dest: Path, progress: Callable[[float], None]) -> Path:
    """The fixed copy: H.264 at the original's size and frame rate, sound kept."""
    w, h, fps = info.width, info.height, info.fps
    vf = video_filters(settings, look, fps)
    rate = max(20, min(100, round(info.bitrate or 50)))
    enc = ["-c:v", "h264_videotoolbox", "-b:v", f"{rate}M", "-pix_fmt", "yuv420p", "-tag:v", "avc1",
           "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]
    total = max(1, round(info.duration * fps))
    on = lambda k: settings.get(k, {}).get("on") and settings[k].get("value", 0)
    if not (on("steady") or on("even")):
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
               *(["-vf", vf] if vf else []), *enc, "-progress", "pipe:2", "-nostats", str(dest)]
        _run_with_progress(cmd, info.duration, progress, 0.0)
        return dest
    moves, bright = _first_pass(path, w, h, fps, bool(on("steady")), progress)
    corr, zoom = steadying(moves, w, h, fps, settings["steady"]["value"]) if on("steady") else (None, 1.0)
    luts = evening(bright, fps, settings["even"]["value"]) if on("even") else None
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
                           stdout=subprocess.PIPE)
    encp = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                             "-r", f"{fps}", "-i", "-", "-i", path, "-map", "0:v", "-map", "1:a:0?",
                             *(["-vf", vf] if vf else []), *enc, "-shortest", str(dest)], stdin=subprocess.PIPE)
    size, i = w * h * 3, 0
    try:
        while True:
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            if corr is not None:
                dx, dy, da = corr[min(i, len(corr) - 1)]
                m = cv2.getRotationMatrix2D((w / 2, h / 2), -math.degrees(da), zoom)  # (OpenCV turns the other way)
                m[0, 2] += dx * zoom
                m[1, 2] += dy * zoom
                frame = cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            if luts is not None:
                frame = cv2.LUT(frame, luts[min(i, len(luts) - 1)])
            encp.stdin.write(frame.tobytes())
            i += 1
            if i % 15 == 0:
                progress(0.3 + 0.7 * min(1.0, i / total))
    finally:
        encp.stdin.close()
        encp.wait()
        dec.wait()
    if encp.returncode:
        raise RuntimeError("the video encoder stopped")
    return dest


def _run_with_progress(cmd: list[str], duration: float, progress: Callable[[float], None], base: float) -> None:
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    errors = []
    for line in p.stderr:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                t = int(line.split("=")[1]) / 1e6
                progress(base + (1 - base) * min(1.0, t / max(0.1, duration)))
            except ValueError:
                pass
        elif "=" not in line:
            errors.append(line.strip())
    if p.wait():
        raise RuntimeError(" ".join(errors)[-300:] or "ffmpeg stopped")


def moment_clip(path: str, start: float, end: float, dest: Path) -> Path:
    """A short, small copy of a moment (a second either side), for playing in the app."""
    a = max(0.0, start - 1.0)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.2f}", "-t", f"{min(8.0, end + 1.0 - a):.2f}", "-i", path,
                    "-vf", "scale=1280:-2", "-c:v", "h264_videotoolbox", "-b:v", "6M", "-pix_fmt", "yuv420p",
                    "-tag:v", "avc1", "-an", "-movflags", "+faststart", str(dest)], check=True)
    return dest


def fixed_path(original: str, fallback: Path, ext: str) -> Path:
    """Where the fixed copy goes: a Clip Analysis/Fixed folder next to the original (or the fallback
    folder when the original's folder can't be written), never over an existing file."""
    folder = Path(original).parent.joinpath(*FIXED_FOLDER)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.touch()
        probe.unlink()
    except OSError:
        folder = fallback
        folder.mkdir(parents=True, exist_ok=True)
    stem = Path(original).stem + " fixed"
    dest = folder / f"{stem}{ext}"
    n = 2
    while dest.exists():
        dest = folder / f"{stem} {n}{ext}"
        n += 1
    return dest


def estimate_seconds(kind: str, settings: dict, info=None) -> float:
    """About how long making the fixed copy takes on this Mac."""
    if kind == "photo":
        mp = (getattr(info, "width", 6000) * getattr(info, "height", 4000)) / 1e6
        return 1 + (mp * 0.15 if settings.get("grain", {}).get("on") else 0) + mp * 0.05
    d = getattr(info, "duration", 10)
    px = getattr(info, "width", 3840) * getattr(info, "height", 2160) * getattr(info, "fps", 60) / (3840 * 2160 * 60)
    base = d * 1.3 * px  # (measured on an M5: 7 s of 4K 60 fps)
    if settings.get("grain", {}).get("on"):
        base += d * 1.8 * px
    if settings.get("steady", {}).get("on"):
        base += d * 1.3 * px
    return max(3, base)



def jitter(path: str, info) -> float:
    """How much the camera's movement changes from frame to frame (lower is steadier), measured the way
    steadying tracks it: used to check that steadying helped."""
    moves, _ = _first_pass(path, info.width, info.height, info.fps, True, lambda f: None)
    return float(np.abs(np.diff(moves[:, :2], axis=0)).mean()) if len(moves) > 2 else 0.0
