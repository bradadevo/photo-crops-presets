"""The asset library: LUTs, textures and overlays, found in your folders and
zip packs, fetched only when first used, and cached on disk.

Asset ids:
  lut:<name>        a .cube 3D LUT
  texture:<name>    a still texture image (paper, marker, film...)
  overlay:<name>    an effect with transparency (smoke, sparks, lightning...),
                    placed on the ball or the player's feet
  generated:<kind>  a texture generated on this Mac (see procedural.KINDS)

Zip packs are never unpacked whole: only the files a look uses are taken
out. Overlay packs made of transparent ProRes video clips (like Sports Impact
Essentials) are turned into a still by taking the clip's strongest frame
(the most visible effect) with ffmpeg.
"""

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from photo_presets import procedural

CONFIG_FILE = Path.home() / ".config" / "photo-crops-presets" / "assets.json"
CACHE_DIR = Path.home() / ".cache" / "photo-crops-presets" / "assets"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
# Overlay clips come in sizes and moving/still versions; this is the order of preference
OVERLAY_PREFERENCE = ("still l", "still m", "still s", "still", "moving l", "moving m", "moving s", "")
# Frames sampled to find a clip's strongest frame, at this size
PEAK_SAMPLE = 160


@dataclass
class Sources:
    lut_folders: list[str] = field(default_factory=lambda: ["~/Library/Application Support/ProApps/Custom LUTs"])
    lut_zips: list[str] = field(default_factory=lambda: ["~/Movies/Ultimate+Sports+Editing+Bundle.zip"])
    texture_folders: list[str] = field(default_factory=list)
    texture_zips: list[str] = field(default_factory=lambda: ["~/Movies/Textures.zip"])
    overlay_folders: list[str] = field(default_factory=list)
    overlay_zips: list[str] = field(default_factory=lambda: ["~/Movies/Sports_Impact_Essentials.zip"])

    @classmethod
    def load(cls) -> "Sources":
        try:
            saved = json.loads(CONFIG_FILE.read_text())
            return cls(**{k: v for k, v in saved.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=1))


@dataclass(frozen=True)
class Source:
    path: str  # a file, or a zip
    member: str = ""  # the file inside the zip


def _paths(items: list[str]) -> list[Path]:
    return [Path(p).expanduser() for p in items]


def _usable(name: str) -> bool:
    return "__MACOSX" not in name and not Path(name).name.startswith(".")


class Library:
    def __init__(self, sources: Sources | None = None):
        self.sources = sources or Sources.load()
        self.luts: dict[str, Source] = {}
        self.textures: dict[str, Source] = {}
        self.overlays: dict[str, Source] = {}
        self.scan()

    def scan(self) -> None:
        s = self.sources
        self.luts, self.textures, self.overlays = {}, {}, {}
        for folder in _paths(s.lut_folders):
            if folder.is_dir():
                for p in sorted(folder.rglob("*.cube")):
                    if _usable(str(p)):
                        self.luts.setdefault(p.stem, Source(str(p)))
        for z, member in self._zip_members(s.lut_zips):
            if member.lower().endswith(".cube"):
                self.luts.setdefault(Path(member).stem, Source(str(z), member))
        for folder in _paths(s.texture_folders):
            if folder.is_dir():
                for p in sorted(folder.rglob("*")):
                    if p.suffix.lower() in IMAGE_EXTS and _usable(str(p)):
                        self.textures.setdefault(p.stem, Source(str(p)))
        for z, member in self._zip_members(s.texture_zips):
            if Path(member).suffix.lower() in IMAGE_EXTS:
                self.textures.setdefault(Path(member).stem, Source(str(z), member))
        for folder in _paths(s.overlay_folders):
            if folder.is_dir():
                for p in sorted(folder.rglob("*.png")):
                    if _usable(str(p)):
                        self.overlays.setdefault(p.stem, Source(str(p)))
        clips: dict[str, list[tuple[int, Source]]] = {}
        for z, member in self._zip_members(s.overlay_zips):
            if Path(member).suffix.lower() in VIDEO_EXTS | {".png"}:
                parent = Path(member).parent.name or Path(member).stem
                stem = Path(member).stem.lower().replace("_", " ")
                rank = next(i for i, key in enumerate(OVERLAY_PREFERENCE) if key in stem)
                clips.setdefault(parent, []).append((rank, Source(str(z), member)))
        for name, options in sorted(clips.items()):
            self.overlays.setdefault(name, min(options, key=lambda t: t[0])[1])

    @staticmethod
    def _zip_members(zips: list[str]):
        for z in _paths(zips):
            if not z.is_file():
                continue
            try:
                with zipfile.ZipFile(z) as f:
                    for member in f.namelist():
                        if not member.endswith("/") and _usable(member):
                            yield z, member
            except zipfile.BadZipFile:
                continue

    def ids(self) -> dict[str, list[str]]:
        return {
            "lut": [f"lut:{n}" for n in sorted(self.luts)],
            "texture": [f"texture:{n}" for n in sorted(self.textures)]
                       + [f"generated:{k}" for k in procedural.KINDS],
            "overlay": [f"overlay:{n}" for n in sorted(self.overlays)],
        }

    def has(self, asset_id: str) -> bool:
        kind, _, name = asset_id.partition(":")
        return {"lut": name in self.luts, "texture": name in self.textures, "overlay": name in self.overlays,
                "generated": name in procedural.KINDS}.get(kind, False)

    # Fetching -----------------------------------------------------------------

    def lut_path(self, name: str) -> str:
        return str(_local(self.luts[name], ".cube"))

    def texture(self, asset_id: str, h: int, w: int, seed: int = 0) -> np.ndarray:
        """The texture as floats (H, W, 3) in 0-1, covering h x w."""
        kind, _, name = asset_id.partition(":")
        if kind == "generated":
            t = procedural.make(name, h, w, seed)
            return np.repeat(t[..., None], 3, axis=2)
        img = _image(str(_local(self.textures[name], Path(self.textures[name].member or self.textures[name].path).suffix)))
        return _cover(img.convert("RGB"), h, w)

    def overlay(self, name: str) -> Image.Image:
        """The overlay as RGBA."""
        src = self.overlays[name]
        suffix = Path(src.member or src.path).suffix.lower()
        if suffix in VIDEO_EXTS:
            return _image(str(_clip_still(src)))
        return _image(str(_local(src, suffix)))


def _key(src: Source) -> str:
    p = Path(src.path)
    stat = p.stat()
    return hashlib.sha1(f"{p}|{src.member}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:16]


def _local(src: Source, suffix: str) -> Path:
    """The asset as a local file: itself, or taken out of its zip once."""
    if not src.member:
        return Path(src.path)
    dest = CACHE_DIR / f"{_key(src)}{suffix}"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src.path) as z, z.open(src.member) as f, open(dest, "wb") as out:
            shutil.copyfileobj(f, out)
    return dest


def _clip_still(src: Source) -> Path:
    """The clip's strongest frame (most visible effect) as a transparent PNG."""
    dest = CACHE_DIR / f"{_key(src)}.png"
    if dest.exists():
        return dest
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is needed to use video overlays (brew install ffmpeg)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / f"clip{Path(src.member or src.path).suffix}"
        if src.member:
            with zipfile.ZipFile(src.path) as z, z.open(src.member) as f, open(clip, "wb") as out:
                shutil.copyfileobj(f, out)
        else:
            clip = Path(src.path)
        raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(clip), "-vf", f"scale={PEAK_SAMPLE}:{PEAK_SAMPLE}",
                              "-pix_fmt", "rgba", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        frames = np.frombuffer(raw, np.uint8).reshape(-1, PEAK_SAMPLE, PEAK_SAMPLE, 4)
        peak = int(np.argmax(frames[..., 3].reshape(len(frames), -1).mean(axis=1)))
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(clip), "-vf", f"select=eq(n\\,{peak})",
                        "-frames:v", "1", "-pix_fmt", "rgba", str(dest)], check=True)
    return dest


@lru_cache(maxsize=24)
def _image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img


def _cover(img: Image.Image, h: int, w: int) -> np.ndarray:
    """Scales and center-crops img to fill h x w."""
    s = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.Resampling.BILINEAR)
    left, top = (r.width - w) // 2, (r.height - h) // 2
    return np.asarray(r.crop((left, top, left + w, top + h)), np.float32) / 255.0
