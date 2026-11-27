"""Reads the camera data Sony writes inside its video files: an XML block
(camera model, lens, picture profile) and a per-frame metadata track ("rtmd")
with the exposure, focus and lens settings of every frame. The per-frame
track follows the SMPTE RDD 18 lens and camera metadata layout."""

import re
import subprocess
from collections import Counter

# Every metadata set in a frame starts with this SMPTE label prefix; the next
# two bytes say which set it is (01 01 lens, 02 01 camera, 7f 01 Sony)
SET_LABEL = b"\x06\x0e\x2b\x34\x02\x53\x01\x01\x0c\x02\x01\x01"

EXPOSURE_MODES = {1: "Manual", 2: "Full auto", 3: "Gain priority", 4: "Aperture priority", 5: "Shutter priority"}
FOCUS_MODES = {0: "Manual focus", 1: "Autofocus (center)", 2: "Autofocus (wide area)",
               3: "Autofocus (multi-spot)", 4: "Autofocus (spot)"}
WHITE_BALANCE = {0: "Preset", 1: "Auto", 2: "Hold", 3: "One-push"}


def xml_block(path: str) -> str:
    """Sony's NonRealTimeMeta XML, or '' if the file has none."""
    with open(path, "rb") as f:
        data = f.read()
    start = data.find(b"<NonRealTimeMeta")
    end = data.find(b"</NonRealTimeMeta>", start)
    return data[start:end + 18].decode("utf-8", "replace") if start != -1 and end != -1 else ""


def xml_info(xml: str) -> dict:
    """Camera, lens and picture details from the XML block."""
    found = {}
    for key, pattern in [("camera", r'<Device[^>]*modelName="([^"]+)"'),
                         ("lens", r'<Lens[^>]*modelName="([^"]+)"'),
                         ("capture_fps", r'captureFps="([^"]+)"'),
                         ("picture_profile", r'CaptureGammaEquation" value="([^"]+)"'),
                         ("recording_mode", r'RecordingMode type="([^"]+)"')]:
        m = re.search(pattern, xml)
        if m:
            found[key] = m.group(1)
    return found


def metadata_sets(frame: bytes):
    """(tag, value) for every item in one frame's metadata."""
    i = frame.find(SET_LABEL)
    while i != -1:
        p = i + 16
        if p >= len(frame):
            return
        n = frame[p]
        p += 1
        if n & 0x80:  # long-form length
            k = n & 0x7F
            n = int.from_bytes(frame[p:p + k], "big")
            p += k
        end = min(p + n, len(frame))
        while p + 4 <= end:
            tag = frame[p:p + 2].hex()
            length = int.from_bytes(frame[p + 2:p + 4], "big")
            yield tag, frame[p + 4:p + 4 + length]
            p += 4 + length
        i = frame.find(SET_LABEL, end)


def _number(value: bytes) -> int:
    return int.from_bytes(value, "big")


def _metres(value: bytes) -> float:
    """RDD 18 distance: 4-bit signed power of ten, 12-bit mantissa, in metres."""
    x = _number(value)
    exponent = x >> 12
    exponent = exponent - 16 if exponent > 7 else exponent
    return (x & 0xFFF) * 10.0 ** exponent


def decode_frame(frame: bytes) -> dict:
    out = {}
    for tag, value in metadata_sets(frame):
        if not value:
            continue
        if tag == "8000":
            out["aperture"] = round(2 ** (8 * (1 - _number(value) / 0x10000)), 1)
        elif tag == "8001":
            out["focus_position"] = _number(value)  # unit varies by camera; only changes are used
        elif tag == "8004":
            out["focal_length_35mm"] = round(_metres(value) * 1000)
        elif tag == "8005":
            out["focal_length"] = round(_metres(value) * 1000)
        elif tag == "8100" and len(value) >= 14:
            out["exposure_mode"] = EXPOSURE_MODES.get(value[13], f"code {value[13]}")
        elif tag == "8101":
            out["focus_mode"] = FOCUS_MODES.get(value[0], f"code {value[0]}")
        elif tag == "8106" and len(value) == 8:
            out["capture_fps"] = round(_number(value[:4]) / max(1, _number(value[4:])), 2)
        elif tag == "8109" and len(value) == 8:
            num, den = _number(value[:4]), _number(value[4:])
            out["shutter"] = num / den if den else None
        elif tag == "810a":
            out["gain_db"] = _number(value) / 100
        elif tag == "810b":
            out["iso"] = _number(value)
        elif tag == "810c":
            out["digital_zoom"] = _number(value) / 100
        elif tag == "810d":
            out["white_balance"] = WHITE_BALANCE.get(value[0], f"code {value[0]}")
    return out


def per_frame(path: str, stream_index: int, frame_count: int, every: int = 2) -> list[dict]:
    """Decoded camera data for every `every`-th frame (empty if unreadable)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{stream_index}", "-c", "copy",
                          "-f", "data", "-"], capture_output=True).stdout
    if not raw or frame_count <= 0:
        return []
    size = len(raw) // frame_count
    if size < 32:
        return []
    return [decode_frame(raw[n * size:(n + 1) * size]) for n in range(0, frame_count, every)]


def summarize(frames: list[dict]) -> dict:
    """One value per setting (the most common), plus how it varied."""
    if not frames:
        return {}
    out = {"frames_sampled": len(frames)}
    for key in ["aperture", "shutter", "iso", "gain_db", "exposure_mode", "focus_mode", "white_balance",
                "focal_length", "focal_length_35mm", "digital_zoom", "capture_fps"]:
        values = [f[key] for f in frames if f.get(key) is not None]
        if not values:
            continue
        out[key] = Counter(values).most_common(1)[0][0]
        if key in ("iso", "aperture", "focal_length") and len(set(values)) > 1:
            out[f"{key}_range"] = (min(values), max(values))
    positions = [f.get("focus_position") for f in frames]
    out["focus_changes"] = sum(1 for a, b in zip(positions, positions[1:]) if a != b)
    out["iso_series"] = [f.get("iso") for f in frames]
    return out
