"""Runs the checks on one file and lays the results out as rows for the
report, the spreadsheet and side-by-side comparisons."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from photo_presets.clipcheck import advice, still, video
from photo_presets.clipcheck.advice import Advice

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".mts", ".mxf", ".avi", ".mkv")
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", *still.HEIF_EXTENSIONS, *still.RAW_EXTENSIONS)


@dataclass
class Result:
    path: str
    kind: str  # "video" or "photo"
    info: object
    stats: object
    advice: Advice
    error: str | None = None

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def camera(self) -> dict:
        return getattr(self.info, "camera", {}) or {}


@dataclass
class Failed:
    path: str
    error: str
    kind: str = "unreadable"
    advice: Advice = field(default_factory=Advice)

    @property
    def name(self) -> str:
        return Path(self.path).name


def kind_of(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    return "video" if ext in VIDEO_EXTENSIONS else "photo" if ext in PHOTO_EXTENSIONS else None


def find_files(paths: list[str]) -> list[str]:
    """Videos and photos among the given files and folders (folders are not
    searched below their first level), in name order."""
    found = []
    for p in map(Path, paths):
        if p.is_dir():
            found += sorted(str(f) for f in p.iterdir() if f.is_file() and not f.name.startswith(".") and kind_of(str(f)))
        elif p.is_file() and kind_of(str(p)):
            found.append(str(p))
    return list(dict.fromkeys(found))


def analyze(path: str, every: int = 2) -> Result | Failed:
    try:
        if kind_of(path) == "video":
            info = video.probe(path, every)
            stats = video.measure(info, every)
            return Result(path, "video", info, stats, advice.for_video(info, stats))
        info, stats = still.measure(path)
        return Result(path, "photo", info, stats, advice.for_still(info, stats))
    except Exception as e:  # one bad file never stops the run
        return Failed(path, f"{type(e).__name__}: {e}"[:200])


def _when(text: str) -> str:
    """Readable local time. Video files store UTC (ending in Z), which is
    converted to this Mac's time zone; photo times are already local."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y:%m:%d %H:%M:%S"):
        try:
            when = datetime.strptime(text, fmt)
        except (ValueError, TypeError):
            continue
        if fmt.endswith("Z"):
            when = when.replace(tzinfo=timezone.utc).astimezone()
        return when.strftime("%b %-d %Y, %-I:%M %p")
    return text or "-"


def _fmt(value, suffix: str = "") -> str:
    return "-" if value in (None, "") else f"{value:g}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def settings_rows(r: Result) -> list[tuple[str, str]]:
    """Camera and file details, as (label, value)."""
    c = r.camera
    rows = [("Camera", " ".join(x for x in [c.get("make"), c.get("camera")] if x) or "-"),
            ("Lens", c.get("lens", "-"))]
    if r.kind == "video":
        v = r.info
        rows += [("Recorded", _when(v.recorded)), ("Resolution", f"{v.width}x{v.height}"),
                 ("Frame rate", f"{v.fps:g} fps"), ("Length", f"{v.duration:.1f} s"),
                 ("Format", f"{v.codec} {v.profile}".strip()), ("Bitrate", f"{v.bitrate:.0f} Mb/s"),
                 ("Color", c.get("picture_profile") or v.color), ("Audio", v.audio)]
        iso = _fmt(c.get("iso"))
        if c.get("iso_range"):
            iso = f"{c['iso_range'][0]}-{c['iso_range'][1]} (mostly {c.get('iso')})"
        rows += [("Exposure mode", _fmt(c.get("exposure_mode"))),
                 ("Aperture", f"f/{c['aperture']:g}" if c.get("aperture") else "-"),
                 ("Shutter", still.shutter_text(c.get("shutter"))), ("ISO", iso),
                 ("Gain", _fmt(c.get("gain_db"), " dB")), ("White balance", _fmt(c.get("white_balance"))),
                 ("Focus mode", _fmt(c.get("focus_mode"))),
                 ("Focal length", f"{c['focal_length']} mm" + (f" ({c['focal_length_35mm']} mm equivalent)"
                                                              if c.get("focal_length_35mm") else "")
                  if c.get("focal_length") else "-")]
    else:
        rows += [("Recorded", _when(c.get("recorded", ""))), ("Resolution", f"{r.info.width}x{r.info.height}"),
                 ("Exposure mode", _fmt(c.get("exposure_mode"))),
                 ("Aperture", f"f/{c['aperture']:g}" if c.get("aperture") else "-"),
                 ("Shutter", still.shutter_text(c.get("shutter"))), ("ISO", _fmt(c.get("iso"))),
                 ("Exposure compensation", _fmt(c.get("exposure_compensation"), " EV")),
                 ("Focal length", f"{c['focal_length']} mm" + (f" ({c['focal_length_35mm']} mm equivalent)"
                                                              if c.get("focal_length_35mm") else "")
                  if c.get("focal_length") else "-"),
                 ("Focus mode", " / ".join(x for x in [c.get("focus_mode"), c.get("focus_area")] if x) or "-"),
                 ("Stabilization", _fmt(c.get("stabilization"))), ("Drive mode", _fmt(c.get("drive_mode"))),
                 ("Metering", _fmt(c.get("metering"))), ("White balance", _fmt(c.get("white_balance"))),
                 ("Picture style", _fmt(c.get("picture_style")))]
    return rows


def measurement_rows(r: Result) -> list[tuple[str, str]]:
    s = r.stats
    if r.kind == "video":
        pct = lambda x: f"{x:.0%}"
        num = lambda x: "-" if x is None else f"{x:.0f}"
        return [("Frames measured", f"{s.samples} (every {s.every}{'nd' if s.every == 2 else 'th'} frame)"),
                ("Time still / slow pan / fast pan", f"{pct(s.still_share)} / {pct(s.slow_share)} / {pct(s.fast_share)}"),
                ("Fastest pan", f"{s.fastest_pan:.0f}% of the frame width per second"),
                ("Sharpness: still / slow pan / fast pan", f"{num(s.sharp_still)} / {num(s.sharp_slow)} / {num(s.sharp_fast)}"),
                ("Sharpness lost in fast pans", "-" if s.pan_sharpness_loss is None else pct(s.pan_sharpness_loss)),
                ("Grain", "-" if s.grain_still is None else f"{s.grain_still:.2f}"),
                ("Biggest brightness swing (2 s)", f"{s.brightness_swing:.0f} of 255"),
                ("Focus adjustments", _fmt(r.camera.get("focus_changes")))]
    return [("Sharpest detail", f"{s.focus_sharpness:.0f} (in the {advice.where(*s.focus_spot)})"),
            ("Overall sharpness", f"{s.overall_sharpness:.0f}"), ("Grain", f"{s.grain:.2f}"),
            ("Average brightness", f"{s.brightness:.0f} of 255"),
            ("Pure white / pure black", f"{s.highlights_clipped:.1%} / {s.shadows_crushed:.1%}")]


def comparison(results: list[Result]) -> tuple[list[str], list[list[str]], list[str]]:
    """(header, rows, differences) for files of the same kind, side by side."""
    header = [""] + [r.name for r in results]
    labels = list(dict.fromkeys(label for r in results for label, _ in settings_rows(r) + measurement_rows(r)))
    tables = [dict(settings_rows(r) + measurement_rows(r)) for r in results]
    rows = [[label] + [t.get(label, "-") for t in tables] for label in labels
            if len({t.get(label, "-") for t in tables}) > 1 or label in ("Camera", "Lens")]
    return header, rows, differences(results)


def differences(results: list[Result]) -> list[tuple[str, list[str]]]:
    """Plain-language notes on what differs most: every file against the
    first one (the reference), as (heading, notes)."""
    if len(results) < 2:
        return []
    ref = results[0]
    return [(f"{other.name} vs {ref.name}", pair_differences(other, ref))
            for other in results[1:] if other.kind == ref.kind]


def pair_differences(a: Result, b: Result) -> list[str]:
    ca, cb = a.camera, b.camera
    notes = []
    when_a = _when(a.info.recorded if a.kind == "video" else ca.get("recorded", ""))
    when_b = _when(b.info.recorded if b.kind == "video" else cb.get("recorded", ""))
    if when_a != "-" and when_b != "-":
        notes.append(f"Recorded {when_a} vs {when_b} (camera clock; time of day often explains a difference in light).")
    stops = advice.stop_difference(ca.get("iso"), cb.get("iso"))
    if stops and stops >= 1:
        hi, lo = (a, b) if ca["iso"] > cb["iso"] else (b, a)
        why = "a faster shutter" if hi.camera.get("shutter") and lo.camera.get("shutter") and \
            hi.camera["shutter"] < lo.camera["shutter"] / 1.9 else "less light"
        notes.append(f"{hi.name} used {stops:.1f} stops more ISO ({hi.camera['iso']} vs {lo.camera['iso']}), "
                     f"likely for {why}: expect more grain and softer fine detail.")
    stops = advice.aperture_stops(ca.get("aperture"), cb.get("aperture"))
    if stops and stops >= 0.5:
        notes.append(f"Aperture differs by {stops:.1f} stops (f/{ca['aperture']:g} vs f/{cb['aperture']:g}).")
    if ca.get("shutter") and cb.get("shutter") and ca["shutter"] != cb["shutter"]:
        notes.append(f"Shutter: {still.shutter_text(ca['shutter'])} vs {still.shutter_text(cb['shutter'])}.")
    elif ca.get("shutter") and cb.get("shutter"):
        notes.append(f"Same shutter in both ({still.shutter_text(ca['shutter'])}), so motion blur per movement "
                     "is the same.")
    if a.kind == "video":
        sa, sb = a.stats, b.stats
        if abs(sa.fast_share - sb.fast_share) >= 0.15:
            more, less = (a, b) if sa.fast_share > sb.fast_share else (b, a)
            notes.append(f"{more.name} pans fast far more ({more.stats.fast_share:.0%} vs "
                         f"{less.stats.fast_share:.0%} of the time), and fast pans blur.")
        if sa.sharp_still and sb.sharp_still:
            ratio = sa.sharp_still / sb.sharp_still
            if ratio < 0.8 or ratio > 1.25:
                soft, crisp = (a, b) if ratio < 1 else (b, a)
                notes.append(f"Even when the camera is still, {soft.name} is "
                             f"{1 - soft.stats.sharp_still / crisp.stats.sharp_still:.0%} less sharp.")
        if sa.grain_still and sb.grain_still and max(sa.grain_still, sb.grain_still) / min(sa.grain_still, sb.grain_still) > 1.2:
            grainy, clean = (a, b) if sa.grain_still > sb.grain_still else (b, a)
            notes.append(f"{grainy.name} has {grainy.stats.grain_still / clean.stats.grain_still - 1:.0%} more grain.")
    else:
        sa, sb = a.stats, b.stats
        if max(sa.focus_sharpness, sb.focus_sharpness) / max(1, min(sa.focus_sharpness, sb.focus_sharpness)) > 1.3:
            crisp, soft = (a, b) if sa.focus_sharpness > sb.focus_sharpness else (b, a)
            notes.append(f"{crisp.name}'s sharpest detail is {crisp.stats.focus_sharpness / soft.stats.focus_sharpness:.1f}x "
                         f"crisper than {soft.name}'s (smooth subjects score lower, so check by eye).")
    return notes
