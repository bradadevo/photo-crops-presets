"""Turns settings and measurements into findings (what is wrong or worth
knowing), settings recommendations and shooting habits. The wording makes
no assumption about the subject (sport, people, wildlife...)."""

import math
from pathlib import Path
from dataclasses import dataclass, field

from photo_presets.clipcheck.still import RAW_EXTENSIONS, StillInfo, StillStats, safe_shutter, shutter_text
from photo_presets.clipcheck.video import PictureStats, VideoInfo

# Thresholds (see the README for how they were chosen)
HIGH_ISO_VIDEO = 1000
HIGH_GAIN_DB = 12
HIGH_ISO_PHOTO = 3200
NOTICEABLE_GRAIN = 1.4
# Photos: 24-33 MP Sony files (JPEG and RAW alike) measure about 1.5-1.8 at ISO 400-640, which looks clean
NOTICEABLE_GRAIN_PHOTO = 1.9
# RAW files have no in-camera sharpening, so they measure far softer than the camera's JPEG of the same
# shot (0.05-0.5 of it): only a clearly soft RAW is called soft
SOFT_FOCUS_RAW = 40
PANNING_OFTEN = 0.25  # share of the clip spent panning fast
PAN_SOFTENS = 0.5  # sharpness lost while panning fast
BRIGHTNESS_SWING = 40  # change in average brightness (0-255) within about 2 seconds
LOW_BITS_PER_PIXEL = {"h264": 0.1, "hevc": 0.06}
BLOWN_HIGHLIGHTS = 0.02
DARK_PHOTO = 50
# Sharpness of the sharpest area below which a photo is likely soft. Smooth
# subjects (plain clothing, skin, sky) score lower even when sharp, so this is
# set low and worded as "may be soft" (calibrated on 24-33 MP Sony JPEGs:
# a blurred 1/30 shot measured 99, a sharp shot of a white shirt 139)
SOFT_FOCUS = 110
SHUTTER_STEPS = [30, 50, 60, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 4000]


@dataclass
class Advice:
    findings: list[str] = field(default_factory=list)
    settings: list[tuple[str, str, str]] = field(default_factory=list)  # setting, recommendation, why
    habits: list[str] = field(default_factory=list)

    def setting(self, name: str, recommendation: str, why: str) -> None:
        if not any(s[0] == name for s in self.settings):
            self.settings.append((name, recommendation, why))

    def habit(self, text: str) -> None:
        if text not in self.habits:
            self.habits.append(text)


def shutter_step(denominator: float) -> int:
    return min(SHUTTER_STEPS, key=lambda s: abs(s - denominator))


def where(x: float, y: float) -> str:
    v = "top" if y < 0.34 else "bottom" if y > 0.66 else "middle"
    h = "left" if x < 0.34 else "right" if x > 0.66 else "center"
    return "center" if (v, h) == ("middle", "center") else f"{v} {h}" if v != "middle" else f"middle {h}"


def for_video(v: VideoInfo, s: PictureStats) -> Advice:
    a = Advice()
    cam = v.camera
    iso, gain, shutter = cam.get("iso"), cam.get("gain_db"), cam.get("shutter")
    aperture = cam.get("aperture")
    # ISO decides; gain only when the camera did not record an ISO (gain is
    # relative to each camera's base ISO, so +15 dB can still be clean)
    low_light = iso >= HIGH_ISO_VIDEO if iso else (gain is not None and gain >= HIGH_GAIN_DB)

    if low_light:
        a.findings.append(f"High sensitivity (ISO {iso or '?'}" + (f", +{gain:g} dB gain" if gain else "") +
                          "): more grain, and the compression smooths away fine detail along with it.")
        if aperture and aperture > 2.0:
            a.setting("Aperture", "Open up toward the lens's widest aperture (e.g. f/2.8)",
                      f"Each stop wider than f/{aperture:g} halves the ISO needed or doubles the shutter speed")
        a.habit("Shoot where the light is best: light behind or beside you, or under the brightest lights.")
    if s.grain_still and s.grain_still >= NOTICEABLE_GRAIN:
        a.findings.append(f"Noticeable grain ({s.grain_still:.2f}; clean footage measures about 1.0).")

    pans_soft = s.fast_share >= PANNING_OFTEN and (s.pan_sharpness_loss or 0) >= PAN_SOFTENS
    if pans_soft:
        a.findings.append(f"Soft when panning: the camera moves fast {s.fast_share:.0%} of the time and loses "
                          f"{s.pan_sharpness_loss:.0%} of its sharpness while it does.")
        a.habit("Pan smoothly and early, leading the subject instead of chasing it.")
        a.habit("Frame a little wider so each pan sweeps less of the picture; crop in later if the resolution allows.")
        a.habit("Use a fluid-head tripod or a monopod for steadier pans.")
    elif s.fast_share >= PANNING_OFTEN:
        a.findings.append(f"Lots of fast panning ({s.fast_share:.0%} of the clip), but it holds up well.")
    if shutter and v.fps:
        target = shutter_step(4 * v.fps)
        if pans_soft and shutter > 1 / (3 * v.fps):
            a.setting("Shutter", f"1/{target}", f"{shutter_text(shutter)} blurs fast pans; 1/{target} keeps "
                      "pans, freeze frames and slow motion crisper (it needs one more stop of light)")
        elif shutter < 1 / (10 * v.fps):
            a.findings.append(f"Very fast shutter ({shutter_text(shutter)} at {v.fps:g} fps): motion can look "
                              "choppy or stuttery in playback.")
            a.setting("Shutter", f"About 1/{shutter_step(2 * v.fps)}", "Natural motion blur at this frame rate "
                      "(use an ND filter in bright light)")

    iso_values = [x for x in cam.get("iso_series", []) if x]
    iso_varies = len(set(iso_values)) > 1 and max(iso_values) >= 2 * min(iso_values)
    if s.brightness_swing >= BRIGHTNESS_SWING:
        if iso_varies or cam.get("exposure_mode", "Manual") != "Manual":
            reason = (f"ISO changed between {min(iso_values)} and {max(iso_values)}" if iso_varies
                      else f"exposure mode is {cam.get('exposure_mode')}")
            a.findings.append(f"Brightness pumps up and down (swings of {s.brightness_swing:.0f} on a 0-255 scale): "
                              f"the camera kept re-adjusting exposure ({reason}).")
            a.setting("Exposure", "Manual, with a fixed ISO (Auto ISO off)",
                      "Brightness stays steady when the camera moves between bright and dark areas")
            a.habit("Set exposure before you start recording and leave it alone during the take.")
        else:
            a.findings.append(f"Brightness changes noticeably (swings of {s.brightness_swing:.0f} on a 0-255 scale), "
                              "from the scene itself: the light changed, or the camera moved between light and shade.")
    if cam.get("white_balance") == "Auto":
        a.setting("White balance", "A fixed Kelvin value or preset",
                  "Auto can shift color mid-clip as the camera moves or the light changes")
    focus = cam.get("focus_mode")
    if focus:
        changes = cam.get("focus_changes", 0)
        a.findings.append(f"Focus: {focus}" + (f", adjusting {changes} times in the frames checked." if focus !=
                                               "Manual focus" else " (the lens did not refocus during the clip)."
                                               if not changes else f", focus was moved {changes} times by hand."))
    if cam.get("digital_zoom", 1) > 1.01:
        a.findings.append(f"Digital zoom was on ({cam['digital_zoom']:.1f}x): it enlarges pixels and lowers detail.")
        a.setting("Zoom", "Use the lens zoom (or crop later) instead of digital zoom", "Keeps full detail")
    bpp = v.bitrate * 1e6 / max(1, v.width * v.height * v.fps)
    if v.codec in LOW_BITS_PER_PIXEL and bpp < LOW_BITS_PER_PIXEL[v.codec]:
        a.findings.append(f"Heavily compressed ({v.bitrate:.0f} Mb/s for {v.width}x{v.height} at {v.fps:g} fps).")
        a.setting("Recording quality", "The highest bitrate the camera offers for this resolution",
                  "Less compression keeps detail in grass, hair, water and other fine texture")
    if v.fps >= 50:
        a.findings.append(f"{v.fps:g} fps: smooth motion and room for slow motion. For vertical social video, "
                          "30 fps exports compress best; for widescreen, keep the full frame rate.")
    if not a.findings:
        a.findings.append("No problems found: steady exposure, low grain and clean motion.")
    return a


def for_still(info: StillInfo, s: StillStats) -> Advice:
    a = Advice()
    cam = info.camera
    shutter, iso = cam.get("shutter"), cam.get("iso")
    f35 = cam.get("focal_length_35mm") or cam.get("focal_length")
    stabilized = (cam.get("stabilization") or "").lower().startswith("on")
    safe = safe_shutter(f35, stabilized)
    raw = Path(info.path).suffix.lower() in RAW_EXTENSIONS
    soft = s.focus_sharpness < (SOFT_FOCUS_RAW if raw else SOFT_FOCUS)
    problems = 0

    if soft and shutter and shutter > 1 / 500:  # motion advice outranks the camera-shake minimum
        a.setting("Shutter", "1/500 for walking pace, 1/1000-1/2000 for fast action", "Freezes movement")
    if shutter and safe and shutter > safe:
        problems += 1
        a.findings.append(f"Slow shutter for handheld at {f35} mm ({shutter_text(shutter)}; about "
                          f"{shutter_text(safe)} or faster avoids camera shake" +
                          (" with stabilization on)." if stabilized else ")."))
        a.setting("Shutter", f"{shutter_text(safe)} or faster", "Avoids blur from camera shake at this focal length")
    if soft:
        problems += 1
        if shutter and shutter > 1 / 500:
            a.findings.append(f"The photo may be soft (sharpest detail {s.focus_sharpness:.0f}) and the shutter was "
                              f"{shutter_text(shutter)}: likely motion blur, from the subject or the camera.")
        else:
            a.findings.append(f"The photo may be soft (sharpest detail {s.focus_sharpness:.0f}) even at "
                              f"{shutter_text(shutter)}: focus may have missed the subject (smooth subjects "
                              "also score low, so check it).")
            a.habit("Check where the focus point sits before pressing the shutter; use a smaller focus area on "
                    "busy scenes.")
    a.findings.append(f"The sharpest detail is in the {where(*s.focus_spot)} of the frame; if that is not your "
                      "subject, focus may have landed elsewhere (busy texture like grass can also win here).")
    if (iso and iso >= HIGH_ISO_PHOTO) or s.grain >= NOTICEABLE_GRAIN_PHOTO:
        problems += 1
        a.findings.append(f"Noticeable grain (ISO {iso or '?'}, grain {s.grain:.2f}).")
        if cam.get("aperture") and cam["aperture"] > 2.8:
            a.setting("Aperture", "Open up toward the lens's widest aperture",
                      f"More light than f/{cam['aperture']:g}, so the ISO can come down")
    if s.highlights_clipped > BLOWN_HIGHLIGHTS:
        problems += 1
        a.findings.append(f"{s.highlights_clipped:.1%} of the photo is pure white (blown highlights, no detail).")
        a.setting("Exposure", "About -0.7 to -1 stop, or expose for the brightest important area",
                  "Recovers detail in skies, white clothing and lights")
    if s.brightness < DARK_PHOTO:
        problems += 1
        a.findings.append(f"Dark photo (average brightness {s.brightness:.0f} of 255"
                          + (f", {s.shadows_crushed:.0%} pure black" if s.shadows_crushed > 0.02 else "") + ").")
        a.setting("Exposure", "Brighter: slower shutter (if it still freezes motion), wider aperture or higher ISO",
                  "Lifting a dark photo later adds much more grain")
    focus = cam.get("focus_mode")
    if focus:
        area = f", {cam['focus_area']} area" if cam.get("focus_area") else ""
        a.findings.append(f"Focus mode: {focus}{area}.")
        if focus == "AF-S" and (cam.get("drive_mode") or "").startswith("Continuous"):
            a.setting("Focus mode", "AF-C for moving subjects", "AF-S locks once; AF-C keeps tracking through a burst")
    if cam.get("white_balance") == "Auto":
        a.setting("White balance", "A preset or Kelvin value for a series",
                  "Keeps color consistent from photo to photo")
    if not problems:
        a.findings.insert(0, "No problems found: sharp, clean and well exposed.")
    return a


def stop_difference(a: float | None, b: float | None) -> float | None:
    """Stops between two ISO or shutter values (each stop doubles the light)."""
    return abs(math.log2(a / b)) if a and b else None


def aperture_stops(a: float | None, b: float | None) -> float | None:
    """Stops between two f-numbers (each stop is the f-number times about 1.4)."""
    return abs(2 * math.log2(a / b)) if a and b else None
