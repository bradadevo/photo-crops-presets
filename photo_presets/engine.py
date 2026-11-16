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
from photo_presets import brand, deliver, edits, explore, match, pipeline, presets, reel, retouch
from photo_presets.assets import Library
from photo_presets.scene import Fix, Prepared, prepare, resized, segment

# Export file types: JPEG (web, Instagram, clients), 16-bit TIFF (print and further editing), or both
JPEG, TIFF, BOTH = "jpeg", "tiff", "both"
PREVIEW_EDGE = 1600
REEL_EDGE = 2400  # a landscape photo shows half its width across the reel's 1080 px
PREPARED_CACHE = 8
DRAWINGS_KEPT = 400  # AI drawings kept for reuse (about 1 MB each)
CUTOUT_TINT = np.array([0.18, 0.55, 1.0], np.float32)  # how the cut-out view marks the player
CROPS = {"none": "Whole photo", "wide": "Pro crop: no zoom (keeps the scene)",
         "crop": "Pro crop: zoomed in on the action", "face": "Face close-up"}


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
    frame: tuple[float, float, float, float] | None = None  # framed by its look: the box in the photo (shares)
    edits: dict = field(default_factory=dict)  # made on the picture after its look (see edits.py)

    @property
    def name(self) -> str:
        return self.recipe.get("name", "look")

    @property
    def title(self) -> str:
        return f"{self.source.stem} · {self.recipe.get('name', 'look')}"


@dataclass
class Job:
    """One look to make: a photo and the look's recipe."""
    path: Path
    recipe: dict
    seed: int

    @property
    def title(self) -> str:
        return f"{self.path.stem} · {self.recipe.get('name', 'look')}"


class Engine:
    def __init__(self, library: Library | None = None):
        self.library = library or Library()
        self._prepared: OrderedDict[tuple[str, str], Prepared] = OrderedDict()
        # each photo's player cut-out at preview size (small, so all of a game's fit)
        self._cutouts: dict[tuple, np.ndarray | None] = {}
        # your clicks fixing each photo's cut-out, kept for every look and export of it
        self.fixes: dict[tuple[str, str], list[Fix]] = {}
        # AI drawings, kept so a look's export (and reel) reuse its preview's drawing
        self.drawings: OrderedDict = OrderedDict()
        self.brand_dir = Path("~/.config/photo-crops-presets").expanduser()  # where the brand kit's logos are
        # distractions removed from each photo: a list of removals, each a list of brush strokes
        self.removals: dict[str, list[list[dict]]] = {}
        self._cleaned: OrderedDict = OrderedDict()  # (photo, removals): its cleaned image and 16-bit copy
        self._parts: OrderedDict = OrderedDict()  # traced parts of pictures, for adjusting them on their own
        self._people: OrderedDict = OrderedDict()  # each picture's people (outlines), for removing them
        self._gone: OrderedDict = OrderedDict()  # what each removal takes, and pictures with it removed

    def prepared(self, path: Path, crop: str) -> Prepared:
        key = (str(path), crop)
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        p = prepare(path, crop, retouch=self._retouched) if self.removals.get(str(path)) else prepare(path, crop)
        if self.fixes.get(key):
            p.set_fixes(self.fixes[key])
        self._prepared[key] = p
        while len(self._prepared) > PREPARED_CACHE:
            self._prepared.popitem(last=False)
        return p

    # Removing distractions ------------------------------------------------------------------

    def _retouched(self, photo):
        """The loaded photo with its removals filled in (kept, so each is done once)."""
        removals = self.removals.get(str(photo.path))
        if not removals:
            return photo
        key = (str(photo.path), json.dumps(removals))
        if key not in self._cleaned:
            done = retouch.apply(photo, removals)
            self._cleaned[key] = (done.image, done.fine)
            while len(self._cleaned) > 3:
                self._cleaned.popitem(last=False)
        photo.image, photo.fine = self._cleaned[key]
        return photo

    def set_removals(self, path: Path, removals: list[list[dict]]) -> None:
        """These removals on the photo; everything made from it is made again."""
        key = str(path)
        if removals:
            self.removals[key] = [list(r) for r in removals]
        else:
            self.removals.pop(key, None)
        for k in [k for k in self._prepared if k[0] == key]:
            del self._prepared[k]
        for k in [k for k in self._cutouts if k[0] == key]:
            del self._cutouts[k]
        for k in [k for k in self._parts if k[0] == key]:
            del self._parts[k]

    def to_photo(self, r: "Result", x: float, y: float) -> tuple[float, float]:
        """A point on the result's picture (shares) as shares of the whole photo."""
        x, y = from_frame(r.frame, x, y)
        box = self.prepared(r.source, r.crop).box
        if box:
            x, y = box[0] + x * (box[2] - box[0]), box[1] + y * (box[3] - box[1])
        return x, y

    def from_photo(self, r: "Result", x: float, y: float) -> tuple[float, float]:
        """A point on the whole photo (shares) as shares of the result's picture."""
        box = self.prepared(r.source, r.crop).box
        if box:
            x, y = (x - box[0]) / (box[2] - box[0]), (y - box[1]) / (box[3] - box[1])
        return to_frame(r.frame, x, y)

    def photo_scale(self, r: "Result") -> float:
        """The result's picture width as a share of the photo's width."""
        w = 1.0 if not r.frame else r.frame[2] - r.frame[0]
        box = self.prepared(r.source, r.crop).box
        return w * (1.0 if not box else box[2] - box[0])

    # Edits after the look --------------------------------------------------------------------

    def part(self, r: "Result", x: float, y: float, h: int, w: int) -> np.ndarray:
        """The part of the result's picture at x, y (a face, the player, the sky), traced (0-1, h x w)."""
        p = self.ready(r.source, r.crop, r.recipe)
        key = (str(r.source), r.crop, r.frame, json.dumps(self.removals.get(str(r.source), [])), round(x, 4), round(y, 4))
        if key not in self._parts:
            scale = min(1.0, edits.AREA_EDGE / max(p.image.size))
            size = (max(1, round(p.image.height * scale)), max(1, round(p.image.width * scale)))
            self._parts[key] = segment(p.image, x, y, size)
            while len(self._parts) > 64:
                self._parts.popitem(last=False)
        m = self._parts[key]
        return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR) if m.shape != (h, w) else m

    # Removing distractions from a picture --------------------------------------------------------

    REMOVE_EDGE = 1600  # px: what a removal takes is worked out at this size, then scaled to any picture

    def _picture(self, r: "Result"):
        """The result's picture region of the photo (before its look), at REMOVE_EDGE."""
        p = self.ready(r.source, r.crop, r.recipe)
        img = p.image.copy()
        img.thumbnail((self.REMOVE_EDGE, self.REMOVE_EDGE))
        return img

    def people_in(self, r: "Result") -> list[np.ndarray]:
        key = (str(r.source), r.crop, r.frame)
        if key not in self._people:
            self._people[key] = retouch.people(self._picture(r))
            while len(self._people) > 24:
                self._people.popitem(last=False)
        return self._people[key]

    def removal_mask(self, r: "Result", removal: dict, h: int, w: int) -> np.ndarray:
        """What one removal takes from the result's picture (bool, h x w): what was brushed,
        and the whole person or object clicked, with its edge and shadow; never the players
        kept in the look, unless brushed over directly."""
        key = ("mask", str(r.source), r.crop, r.frame, json.dumps(removal, sort_keys=True))
        if key not in self._gone:
            img = self._picture(r)
            matte = self.cutout(r)
            protect = None if matte is None else cv2.resize(matte, img.size, interpolation=cv2.INTER_LINEAR)
            self._gone[key] = retouch.what_to_remove(img, removal.get("strokes", []), removal.get("points", []),
                                                     protect, self.people_in(r))
            self._trim()
        m = self._gone[key]
        if m.shape != (h, w):
            m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR) > 0
        return m

    def _trim(self) -> None:
        while len(self._gone) > 48:
            self._gone.popitem(last=False)

    def removed(self, r: "Result", arr: np.ndarray) -> np.ndarray:
        """The picture (floats 0-1, any size) with the result's removals filled in."""
        removals = (r.edits or {}).get("removals") or []
        if not removals:
            return arr
        h, w = arr.shape[:2]
        sample = arr[:: max(1, h // 64), :: max(1, w // 64)].tobytes()
        key = ("fill", hash(sample), h, w, json.dumps(removals, sort_keys=True), str(r.source), r.crop, r.frame)
        if key not in self._gone:
            mask = np.zeros((h, w), bool)
            for rm in removals:
                mask |= self.removal_mask(r, rm, h, w)
            u8 = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
            filled, weight = retouch.fill(u8, mask)
            wgt = weight[..., None]
            self._gone[key] = (arr * (1 - wgt) + filled.astype(np.float32) / 255 * wgt).astype(np.float32)
            self._trim()
        return self._gone[key]

    def base_after(self, r: "Result") -> np.ndarray:
        """The result's preview (floats 0-1) with its removals: they are filled in the look and
        the photo under it (kept, so the sliders stay instant), then its sliders applied."""
        removals = (r.edits or {}).get("removals")
        if not removals:
            return pipeline.to_array(r.after)
        look = self.removed(r, pipeline.to_array(r.look or r.after))
        if not pipeline.adjusted(r.recipe):
            return look
        before = self.removed(r, pipeline.matched(pipeline.to_array(r.before), r.recipe))
        alpha = self.cutout(r) if pipeline.needs_cutout({"adjust": r.recipe.get("adjust")}) else None
        done, _ = pipeline.finish(before, look, r.recipe, alpha)
        return done

    def finalize(self, r: "Result", arr: np.ndarray, areas: bool = True, geometry: bool = True,
                 texts: bool = True, removals: bool = True) -> np.ndarray:
        """The result's picture (floats 0-1, any size) with its edits: parts
        adjusted, straightened and cropped, and its text."""
        e = r.edits or {}
        if not edits.edited(e):
            return arr
        out = self.removed(r, arr) if removals else arr
        if areas:
            for a in e.get("areas", []):
                out = edits.adjust_part(out, self.part(r, a["x"], a["y"], *out.shape[:2]), a)
        if geometry:
            out = edits.geometry(out, e)
        if texts:  # (and logos: drawn on top like text)
            out = edits.draw_texts(out, e.get("texts"))
            out = brand.draw(out, e.get("logos"), self.brand_dir)
        return out

    def finished(self, r: "Result", texts: bool = True) -> Image.Image:
        """The result's preview with its edits."""
        if not edits.edited(r.edits):
            return r.after
        return pipeline.to_image(self.finalize(r, self.base_after(r), texts=texts, removals=False))

    def ready(self, path: Path, crop: str, recipe: dict) -> Prepared:
        """The photo ready for this look: cut out if the look needs it, and
        framed around the players if the look frames itself ("frame")."""
        p = self.prepared(path, crop)
        if pipeline.needs_cutout(recipe):
            p.ensure_matte()
        spec = recipe.get("frame")
        if not spec:
            return p
        box = frame_box(p.scene, p.image.width, p.image.height, float(spec.get("aspect", 0.8)),
                        float(spec.get("fill", 0.8)))
        if box is None:
            return p
        w, h = p.image.size
        fine = None if p.fine is None else p.fine[box[1]:box[3], box[0]:box[2]]
        q = Prepared(p.path, p.image.crop(box), p.scene.in_crop(box, (w, h)), p.exif, fine)
        q.scene.matte = whole_figures(q.scene.matte, q.scene.subject_box)
        q.scene.subject_mask = whole_figures(q.scene.subject_mask, q.scene.subject_box)
        q._auto = (q.scene.matte, q.scene.subject_mask)  # already traced (and fixed) on the whole photo
        q.frame = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
        return q

    def memo_key(self, path: Path, crop: str, recipe: dict, frame) -> tuple:
        """What a look of a photo is, for reusing its AI drawings: the photo, crop,
        framing, cut-out fixes and the look (its quick adjustments aside)."""
        look = json.dumps({k: v for k, v in recipe.items() if k != "adjust"}, sort_keys=True, default=str)
        fixes = tuple((f.x, f.y, f.add) for f in self.fixes.get((str(path), crop), []))
        while len(self.drawings) > DRAWINGS_KEPT:
            self.drawings.popitem(last=False)
        cleaned = json.dumps(self.removals.get(str(path), []))
        return str(path), crop, frame, look, fixes, cleaned

    def _one(self, path: Path, crop: str, recipe: dict, seed: int) -> Result:
        p = self.ready(path, crop, recipe)
        small = p.image.copy()
        small.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
        after, look, notes = pipeline.render_parts(small, recipe, self.library, p.scene, seed, self.drawings,
                                                   self.memo_key(path, crop, recipe, p.frame))
        if p.scene.matte is not None:
            self._keep_cutout((str(path), crop, p.frame), p, small.size)
        return Result(path, crop, recipe, seed, small, after, notes, p.exif, look, p.frame)

    def _keep_cutout(self, key: tuple, p: Prepared, size: tuple[int, int]) -> None:
        m = resized(p.scene.matte, size[1], size[0])
        self._cutouts[key] = None if m is None else (np.clip(m, 0, 1) * 255).astype(np.uint8)

    def cutout(self, r: Result) -> np.ndarray | None:
        """The result's player cut-out (0-1) at its size, traced if needed."""
        key = (str(r.source), r.crop, r.frame)
        if key not in self._cutouts:
            p = self.ready(r.source, r.crop, dict(r.recipe, adjust={"subject": 1}))  # (so it is traced)
            self._keep_cutout(key, p, r.before.size)
        m = self._cutouts[key]
        return None if m is None else m.astype(np.float32) / 255

    def adjust(self, r: Result, adj: dict) -> Result:
        """The result with new quick adjustments: instant, the look is not made again."""
        recipe = pipeline.with_adjust(r.recipe, adj)
        alpha = self.cutout(r) if pipeline.needs_cutout({"adjust": recipe.get("adjust")}) else None
        look = r.look or r.after
        before = pipeline.matched(pipeline.to_array(r.before), recipe)
        done, notes = pipeline.finish(before, pipeline.to_array(look), recipe, alpha)
        kept = [n for n in r.notes if not n.startswith(("fill light", "no player cut-out here, so the player/"))]
        return dataclasses.replace(r, recipe=recipe, after=pipeline.to_image(done), notes=kept + notes, look=look)

    # Fixing the cut-out ------------------------------------------------------------

    def set_fixes(self, r: Result, fixes: list[Fix]) -> None:
        """Uses these clicks on the result's photo (all its looks)."""
        key = (str(r.source), r.crop)
        self.fixes[key] = list(fixes)
        p = self.prepared(r.source, r.crop)
        p.set_fixes(self.fixes[key])
        p.ensure_matte()
        for k in [k for k in self._cutouts if k[:2] == key]:  # every framing of this photo
            del self._cutouts[k]
        self.cutout(r)

    def fixes_for(self, r: Result) -> list[Fix]:
        return list(self.fixes.get((str(r.source), r.crop), []))

    def fix_view(self, r: Result) -> Image.Image:
        """The original photo with the cut-out tinted blue and your clicks
        marked (green: added, red: taken out), for fixing it."""
        before = pipeline.to_array(r.before)
        m = self.cutout(r)
        out = before.copy()
        if m is not None:
            a = m[..., None]
            out = before * (1 - 0.5 * a) + CUTOUT_TINT * 0.5 * a
            edge = cv2.morphologyEx((m > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT,
                                    np.ones((3, 3), np.uint8)).astype(bool)
            out[edge] = CUTOUT_TINT
        img = (np.clip(out, 0, 1) * 255).astype(np.uint8)
        h, w = img.shape[:2]
        size = max(6, int(max(h, w) * 0.007))
        for f in self.fixes_for(r):
            x, y = to_frame(r.frame, f.x, f.y)
            if not (0 <= x <= 1 and 0 <= y <= 1):
                continue
            c = (int(x * w), int(y * h))
            color = (40, 220, 90) if f.add else (240, 50, 60)
            cv2.circle(img, c, size + 2, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(img, c, size, color, -1, cv2.LINE_AA)
            cv2.line(img, (c[0] - size // 2, c[1]), (c[0] + size // 2, c[1]), (255, 255, 255), 2, cv2.LINE_AA)
            if f.add:
                cv2.line(img, (c[0], c[1] - size // 2), (c[0], c[1] + size // 2), (255, 255, 255), 2, cv2.LINE_AA)
        return Image.fromarray(img)

    def remake(self, r: Result) -> Result:
        """The look made again (after its photo's cut-out was fixed or cleaned), keeping its fine-tuning and edits."""
        return dataclasses.replace(self._one(r.source, r.crop, r.recipe, r.seed), edits=r.edits)

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

    def explore_jobs(self, paths: list[Path], count: int, seed: int | None = None) -> list[Job]:
        """The random looks to make: (photo, recipe, seed), photo by photo."""
        base = int(time.time()) % 100000 if seed is None else seed
        return [Job(path, explore.recipe(base + i * count + k, self.library), base + i * count + k)
                for i, path in enumerate(paths) for k in range(count)]

    def preset_jobs(self, paths: list[Path], names: list[str]) -> list[Job]:
        """Every photo through each of the named presets (photo by photo, so each
        photo is prepared once)."""
        saved = presets.load_all()
        return [Job(path, dict(saved[name], name=name), 0) for path in paths for name in names]

    def look(self, job: Job, crop: str = "none") -> Result:
        """One look of one photo, at preview size."""
        return self._one(job.path, crop, job.recipe, job.seed)

    def is_prepared(self, path: Path, crop: str) -> bool:
        return (str(path), crop) in self._prepared

    def is_cut_out(self, path: Path, crop: str) -> bool:
        p = self._prepared.get((str(path), crop))
        return p is not None and p._auto is not None

    def explore(self, paths: list[Path], count: int, crop: str = "none", seed: int | None = None,
                progress=None) -> list[Result]:
        return self._run(self.explore_jobs(paths, count, seed), crop, progress)

    def _run(self, jobs: list[Job], crop: str, progress=None) -> list[Result]:
        out = []
        for job in jobs:
            out.append(self.look(job, crop))
            if progress:
                progress(len(out), len(jobs), out[-1].title)
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
        return self._run(self.preset_jobs(paths, names), crop, progress)

    def _kit_logo(self, logo: dict | None, arr: np.ndarray) -> list[dict]:
        """The export's logo ({"id", "corner", "size", "color", "opacity"}) placed in its corner
        of this picture (each size has its own shape)."""
        if not logo or not logo.get("id"):
            return []
        art = brand.load(self.brand_dir, logo["id"])
        if art is None:
            return []
        h, w = arr.shape[:2]
        size = float(logo.get("size", 0.16))
        x, y = brand.corner_place(logo.get("corner", "br"), size, art.width / art.height, w, h)
        return [{"id": logo["id"], "x": x, "y": y, "size": size, "color": logo.get("color", "auto"),
                 "opacity": float(logo.get("opacity", 1.0))}]

    def reel_shots(self, results: list[Result], progress=None) -> list[reel.Shot]:
        """The looks again at REEL_EDGE px (sharper than the previews on a
        phone screen), each with where its player is."""
        shots = []
        for i, r in enumerate(results):
            p = self.ready(r.source, r.crop, r.recipe)
            img = p.image.copy()
            img.thumbnail((REEL_EDGE, REEL_EDGE))
            look, _ = pipeline.render(img, r.recipe, self.library, p.scene, r.seed, self.drawings,
                                      self.memo_key(r.source, r.crop, r.recipe, p.frame))
            where = focus(p.scene)
            if edits.edited(r.edits):
                where = edits.map_point(*where, look.width, look.height, r.edits)
                look = pipeline.to_image(self.finalize(r, pipeline.to_array(look)))
            shots.append(reel.Shot(look, where, r.title))
            if progress:
                progress(i + 1, len(results), r.title)
        return shots

    # Matching a game --------------------------------------------------------------

    def match_game(self, results: list[Result], reference: Result, progress=None) -> tuple[list[Result], int]:
        """Every photo's exposure and white balance evened out to the reference
        photo's (see match.py), and its looks made again. Returns the results and
        how many photos were corrected."""
        ref = match.measure(reference.before)
        by_photo: dict[tuple[str, str], dict | None] = {}
        for r in results:
            key = (str(r.source), r.crop)
            if key not in by_photo:
                same = key == (str(reference.source), reference.crop)
                by_photo[key] = None if same else match.correction(ref, match.measure(r.before))
        out = []
        for i, r in enumerate(results):
            m = by_photo[(str(r.source), r.crop)]
            recipe = {k: v for k, v in r.recipe.items() if k != "match"}
            if m:
                recipe["match"] = m
            out.append(r if recipe == r.recipe
                       else dataclasses.replace(self._one(r.source, r.crop, recipe, r.seed), edits=r.edits))
            if progress:
                progress(i + 1, len(results), r.title)
        return out, sum(1 for m in by_photo.values() if m)

    def clear_match(self, results: list[Result], progress=None) -> list[Result]:
        out = []
        for i, r in enumerate(results):
            if "match" in r.recipe:
                r = dataclasses.replace(self._one(r.source, r.crop, {k: v for k, v in r.recipe.items() if k != "match"},
                                                  r.seed), edits=r.edits)
            out.append(r)
            if progress:
                progress(i + 1, len(results), r.title)
        return out

    # Export ---------------------------------------------------------------------------

    def export(self, results: list[Result], folder: Path, progress=None, kind: str = JPEG,
               sizes: list[str] | None = None, credit: deliver.Credit | None = None,
               mark: deliver.Watermark | None = None, logo: dict | None = None) -> tuple[list[Path], list[str]]:
        """Each result in each size (full size, Instagram, prints), with its
        recipe beside it as JSON. Returns the files saved and notes (such as a
        print size enlarged past the photo's own pixels).

        The look is made from the photo's 16-bit copy when it has one (RAW,
        16-bit TIFF) and kept in floats to the end: a JPEG is rounded to 8 bits
        once, dithered (no bands in glows and skies); a TIFF keeps 16 bits.
        Every file carries the sRGB profile, the photo's date and camera, and
        your name and copyright when given."""
        folder.mkdir(parents=True, exist_ok=True)
        sizes = sizes or [deliver.FULL]
        credit = credit or deliver.Credit()
        saved, notes_out = [], []
        for i, r in enumerate(results):
            p = self.ready(r.source, r.crop, r.recipe)
            full, notes = pipeline.render_fine(p.fine if p.fine is not None else p.image, r.recipe,
                                               self.library, p.scene, r.seed, self.drawings,
                                               self.memo_key(r.source, r.crop, r.recipe, p.frame))
            fh, fw = full.shape[:2]
            where, players = focus(p.scene), players_box(p.scene)
            if edits.edited(r.edits):
                where = edits.map_point(*where, fw, fh, r.edits)
                players = edits.map_box(players, fw, fh, r.edits)
                full = self.finalize(r, full, texts=False)  # text is drawn on each size
            taken = images.taken_at(p.exif)
            exif = deliver.credited_exif(p.exif, credit, taken.year if taken else None)
            xmp = deliver.xmp(credit, taken.year if taken else None)
            stem = f"{r.source.stem}_{slug(r.recipe.get('name', 'look'))}" + (f"_{r.crop}" if r.crop != "none" else "")
            for key in sizes:
                arr, name = full, stem
                if key != deliver.FULL:
                    size = deliver.SIZES[key]
                    arr, grow = deliver.sized(full, size, where, players)
                    name = f"{stem}_{deliver.SHORT[key]}"
                    if grow > 1.05:
                        notes_out.append(f"{r.source.name} {size.label.split(' (')[0]}: enlarged {grow:.1f}x "
                                         "(the photo has fewer pixels than this print size)")
                arr = edits.draw_texts(arr, (r.edits or {}).get("texts"))
                arr = brand.draw(arr, (r.edits or {}).get("logos") or self._kit_logo(logo, arr), self.brand_dir)
                if mark is not None:
                    arr = deliver.watermark(arr, mark)
                dest = _unique(folder / f"{name}.jpg")
                if kind == TIFF:
                    dest = _unique(folder / f"{name}.tif")
                elif kind == BOTH:  # the JPEG and the TIFF share a name
                    while dest.with_suffix(".tif").exists():
                        dest = _unique(dest.with_name(dest.stem + "-2.jpg"))
                if kind in (JPEG, BOTH):
                    images.save_jpeg(pipeline.to_image(arr), dest, exif, xmp)
                if kind in (TIFF, BOTH):
                    images.save_tiff16(arr, dest.with_suffix(".tif"), exif, xmp)
                dest.with_suffix(".json").write_text(json.dumps(
                    {"source": str(r.source), "crop": r.crop, "seed": r.seed, "size": key, "recipe": r.recipe,
                     "edits": r.edits, "removed": self.removals.get(str(r.source), []),
                     "notes": notes, "cutout_fixes": [[f.x, f.y, f.add] for f in self.fixes_for(r)]},
                    indent=1))
                saved.append(dest)
            if progress:
                progress(i + 1, len(results), r.title)
        return saved, notes_out

def frame_box(scene, w: int, h: int, aspect: float, fill: float) -> tuple[int, int, int, int] | None:
    """A box of this shape (width / height) around the players in the play,
    sized so they fill `fill` of its height (and fit its width), inside the
    photo: how an illustrator would frame them."""
    pb = scene.subject_box or players_box(scene)  # framed on the main player
    if pb is None:
        return None
    bx0, by0, bx1, by1 = pb[0] * w, pb[1] * h, pb[2] * w, pb[3] * h
    def gap(x, y):  # how far a ball is outside the player's box, in pixels
        dx = max(bx0 - x * w, 0, x * w - bx1)
        dy = max(by0 - y * h, 0, y * h - by1)
        return (dx * dx + dy * dy) ** 0.5
    near = [b for b in scene.balls if gap(b[0], b[1]) <= 0.5 * (by1 - by0)]
    if near:  # the ball in play (the nearest, if it is close) stays in the picture
        x, y, r = min(near, key=lambda b: gap(b[0], b[1]))
        bx0, bx1 = min(bx0, (x - r * 1.3) * w), max(bx1, (x + r * 1.3) * w)
        by0, by1 = min(by0, y * h - r * 1.3 * w), max(by1, y * h + r * 1.3 * w)
    ch = (by1 - by0) / fill
    cw = ch * aspect
    if cw < (bx1 - bx0) / 0.92:
        cw = (bx1 - bx0) / 0.92
        ch = cw / aspect
    if cw > w:
        cw, ch = w, w / aspect
    if ch > h:
        cw, ch = h * aspect, h
    x0 = min(max((bx0 + bx1) / 2 - cw / 2, 0), w - cw)
    y0 = min(max((by0 + by1) / 2 - ch * 0.53, 0), h - ch)  # a little more room above the head
    return int(x0), int(y0), int(x0 + cw), int(y0 + ch)


def whole_figures(mask: np.ndarray | None, keep_box) -> np.ndarray | None:
    """A framed cut-out without the figures the frame slices through (a
    teammate half out of the picture), so they become background instead of
    half a person; the main player always stays."""
    if mask is None:
        return None
    m = mask.astype(np.float32) / (255.0 if mask.dtype == np.uint8 else 1.0)
    h, w = m.shape
    n, lab = cv2.connectedComponents((m > 0.5).astype(np.uint8))
    if n <= 1:
        return mask
    keep_lab = set()
    if keep_box:
        x0, y0, x1, y1 = (int(np.clip(keep_box[0] * w, 0, w - 1)), int(np.clip(keep_box[1] * h, 0, h - 1)),
                          int(np.clip(keep_box[2] * w, 1, w)), int(np.clip(keep_box[3] * h, 1, h)))
        keep_lab = set(np.unique(lab[y0:y1, x0:x1]).tolist()) - {0}
    edge = 2
    cut = set(np.unique(np.concatenate([lab[:, :edge].ravel(), lab[:, -edge:].ravel(), lab[:edge].ravel()])).tolist())
    drop = (cut - keep_lab) - {0}
    if not drop:
        return mask
    gone = np.isin(lab, list(drop))
    gone = cv2.dilate(gone.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)  # their soft edges too
    out = mask.copy()
    out[gone] = 0
    return out


def to_frame(frame, x: float, y: float) -> tuple[float, float]:
    """A point on the photo (shares) as shares of a framed look's picture."""
    if not frame:
        return x, y
    return (x - frame[0]) / (frame[2] - frame[0]), (y - frame[1]) / (frame[3] - frame[1])


def from_frame(frame, x: float, y: float) -> tuple[float, float]:
    """A point on a framed look's picture as shares of the whole photo."""
    if not frame:
        return x, y
    return frame[0] + x * (frame[2] - frame[0]), frame[1] + y * (frame[3] - frame[1])


def players_box(scene) -> tuple[float, float, float, float] | None:
    """The box around the players in the play (shares of the image), to keep whole when cropping."""
    m = scene.subject_mask
    if m is None or not m.any():
        return None
    ys, xs = np.nonzero(m)
    h, w = m.shape[:2]
    return xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h


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
