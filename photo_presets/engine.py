"""The two ways to use looks, and export.

- Random exploration: every photo gets `count` different random looks.
- Preset pipeline: every photo goes through each chosen preset.

Results are made at preview size for speed; export renders each one again
from the full-size photo, so the saved files are full resolution.

Each result keeps its look before the quick adjustments too, so changing
them (look strength, player and background brightness, warmth) is instant.
"""

import dataclasses
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photo_crops import images
from photo_presets import explore, pipeline, presets, reel
from photo_presets.assets import Library
from photo_presets.scene import Prepared, prepare, resized

PREVIEW_EDGE = 1600
REEL_EDGE = 2400  # a landscape photo shows half its width across the reel's 1080 px
PREPARED_CACHE = 4
CUTOUT_TINT = np.array([0.18, 0.55, 1.0], np.float32)  # how the cut-out view marks the player
CROPS = {"none": "Whole photo", "crop": "Pro crop (photo-crops)", "face": "Face close-up (photo-crops)"}


@dataclass
class Result:
    source: Path
    crop: str
    recipe: dict
    seed: int
    before: Image.Image
    after: Image.Image
    notes: list[str] = field(default_factory=list)
    exif: bytes | None = None  # the photo's camera data (date taken, camera, lens), for saved copies
    look: Image.Image | None = None  # the look before its quick adjustments

    @property
    def name(self) -> str:
        return self.recipe.get("name", "look")

    @property
    def title(self) -> str:
        return f"{self.source.stem} · {self.recipe.get('name', 'look')}"


class Engine:
    def __init__(self, library: Library | None = None):
        self.library = library or Library()
        self._prepared: OrderedDict[tuple[str, str], Prepared] = OrderedDict()
        # each photo's player cut-out at preview size (small, so all of a game's fit)
        self._cutouts: dict[tuple[str, str], np.ndarray | None] = {}

    def prepared(self, path: Path, crop: str) -> Prepared:
        key = (str(path), crop)
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        p = prepare(path, crop)
        self._prepared[key] = p
        while len(self._prepared) > PREPARED_CACHE:
            self._prepared.popitem(last=False)
        return p

    def _one(self, path: Path, crop: str, recipe: dict, seed: int) -> Result:
        p = self.prepared(path, crop)
        if pipeline.needs_cutout(recipe):
            p.ensure_matte()
        small = p.image.copy()
        small.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
        after, look, notes = pipeline.render_parts(small, recipe, self.library, p.scene, seed)
        if p.scene.matte is not None:
            self._keep_cutout(path, crop, p, small.size)
        return Result(path, crop, recipe, seed, small, after, notes, p.exif, look)

    def _keep_cutout(self, path: Path, crop: str, p: Prepared, size: tuple[int, int]) -> None:
        m = resized(p.scene.matte, size[1], size[0])
        self._cutouts[(str(path), crop)] = None if m is None else (np.clip(m, 0, 1) * 255).astype(np.uint8)

    def cutout(self, r: Result) -> np.ndarray | None:
        """The result's player cut-out (0-1) at its size, traced if needed."""
        key = (str(r.source), r.crop)
        if key not in self._cutouts:
            p = self.prepared(r.source, r.crop)
            p.ensure_matte()
            self._keep_cutout(r.source, r.crop, p, r.before.size)
        m = self._cutouts[key]
        return None if m is None else m.astype(np.float32) / 255

    def adjust(self, r: Result, adj: dict) -> Result:
        """The result with new quick adjustments: instant, the look is not made again."""
        recipe = pipeline.with_adjust(r.recipe, adj)
        alpha = self.cutout(r) if pipeline.needs_cutout({"adjust": recipe.get("adjust")}) else None
        look = r.look or r.after
        done, notes = pipeline.finish(pipeline.to_array(r.before), pipeline.to_array(look), recipe, alpha)
        kept = [n for n in r.notes if not n.startswith(("fill light", "no player cut-out here, so the player/"))]
        return dataclasses.replace(r, recipe=recipe, after=pipeline.to_image(done), notes=kept + notes, look=look)

    def cutout_view(self, r: Result) -> Image.Image:
        """The result with the player tinted blue and outlined: what the app
        treats as the player (brightened, kept clear of effects)."""
        after = pipeline.to_array(r.after)
        m = self.cutout(r)
        if m is None:
            return r.after
        a = m[..., None]
        tinted = after * (1 - 0.45 * a) + CUTOUT_TINT * 0.45 * a
        edge = cv2.morphologyEx((m > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT,
                                np.ones((3, 3), np.uint8)).astype(bool)
        tinted[edge] = CUTOUT_TINT
        return pipeline.to_image(tinted)

    def explore(self, paths: list[Path], count: int, crop: str = "none", seed: int | None = None,
                progress=None) -> list[Result]:
        base = int(time.time()) % 100000 if seed is None else seed
        out = []
        total = len(paths) * count
        for i, path in enumerate(paths):
            for k in range(count):
                s = base + i * count + k
                out.append(self._one(path, crop, explore.recipe(s, self.library), s))
                if progress:
                    progress(len(out), total, out[-1].title)
        return out

    def preset(self, paths: list[Path], name: str, crop: str = "none", recipe: dict | None = None,
               progress=None) -> list[Result]:
        recipe = dict(recipe or presets.load_all()[name], name=name)
        out = []
        for i, path in enumerate(paths):
            out.append(self._one(path, crop, recipe, i))
            if progress:
                progress(len(out), len(paths), out[-1].title)
        return out

    def presets(self, paths: list[Path], names: list[str], crop: str = "none", progress=None) -> list[Result]:
        """Every photo through each of the named presets (photo by photo, so each
        photo is prepared once)."""
        saved = presets.load_all()
        out = []
        total = len(paths) * len(names)
        for path in paths:
            for name in names:
                out.append(self._one(path, crop, dict(saved[name], name=name), 0))
                if progress:
                    progress(len(out), total, out[-1].title)
        return out

    def reel_shots(self, results: list[Result], progress=None) -> list[reel.Shot]:
        """The looks again at REEL_EDGE px (sharper than the previews on a
        phone screen), each with where its player is."""
        shots = []
        for i, r in enumerate(results):
            p = self.prepared(r.source, r.crop)
            if pipeline.needs_cutout(r.recipe):
                p.ensure_matte()
            img = p.image.copy()
            img.thumbnail((REEL_EDGE, REEL_EDGE))
            look, _ = pipeline.render(img, r.recipe, self.library, p.scene, r.seed)
            shots.append(reel.Shot(look, focus(p.scene), r.title))
            if progress:
                progress(i + 1, len(results), r.title)
        return shots

    def export(self, results: list[Result], folder: Path, progress=None) -> list[Path]:
        """Full-resolution JPEGs, each with its recipe beside it as JSON."""
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, r in enumerate(results):
            p = self.prepared(r.source, r.crop)
            if pipeline.needs_cutout(r.recipe):
                p.ensure_matte()
            full, notes = pipeline.render(p.image, r.recipe, self.library, p.scene, r.seed)
            stem = f"{r.source.stem}_{slug(r.recipe.get('name', 'look'))}" + (f"_{r.crop}" if r.crop != "none" else "")
            dest = _unique(folder / f"{stem}.jpg")
            images.save_jpeg(full, dest, p.exif)
            dest.with_suffix(".json").write_text(json.dumps(
                {"source": str(r.source), "crop": r.crop, "seed": r.seed, "recipe": r.recipe, "notes": notes},
                indent=1))
            saved.append(dest)
            if progress:
                progress(i + 1, len(results), dest.name)
        return saved


def focus(scene) -> tuple[float, float]:
    """Where to center a reel on (shares of the image): the middle of the
    players in the play (so a pair stays together), else of the main player,
    else the center."""
    m = scene.subject_mask
    if m is not None and m.any():
        ys, xs = np.nonzero(m)
        h, w = m.shape[:2]
        return (xs.min() + xs.max()) / 2 / w, (ys.min() + ys.max()) / 2 / h
    if scene.feet:
        x, y = scene.feet
        return x, max(0.0, y - scene.subject_height / 2)
    return 0.5, 0.5


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "look"


def _unique(path: Path) -> Path:
    n, out = 2, path
    while out.exists():
        out = path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1
    return out


def collect(paths: list[str]) -> list[Path]:
    """Photos from files and folders (directly inside); screenshots included."""
    out = []
    for item in paths:
        p = Path(item).expanduser()
        if p.is_dir():
            photos, shots = images.collect(p)
            out += photos + shots
        elif p.is_file() and images.is_image(p):
            out.append(p)
    return out
