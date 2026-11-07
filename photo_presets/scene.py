"""What is in a photo, for placing effects and keeping faces clean: faces,
the ball and the main player's feet, as shares of the image's width and
height so one scene serves the preview and the full-size export.

Found with photo-crops' free YOLO models (people, ball, heads) and its
subject rules (goalie first, then your team, then whoever is in focus).
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from photo_crops import focus, framing, images
from photo_crops.people import GOALIE, OPPONENT, TEAM, Detector, Person

Box = tuple[int, int, int, int]

# A face is drawn this many head-sizes wide when keeping it clean
FACE_REACH = 1.6


@dataclass
class Scene:
    faces: list[tuple[float, float, float]] = field(default_factory=list)  # x, y, radius (shares of width)
    balls: list[tuple[float, float, float]] = field(default_factory=list)
    feet: tuple[float, float] | None = None
    subject_height: float = 0.5  # share of the image's height

    def in_crop(self, box: Box, size: tuple[int, int]) -> "Scene":
        """The same scene inside a crop of the image it was found in."""
        w, h = size
        x0, y0, x1, y1 = box
        cw, ch = x1 - x0, y1 - y0

        def move(x, y):
            return (x * w - x0) / cw, (y * h - y0) / ch

        def keep(items):
            out = []
            for x, y, r in items:
                nx, ny = move(x, y)
                if -0.1 <= nx <= 1.1 and -0.1 <= ny <= 1.1:
                    out.append((nx, ny, r * w / cw))
            return out

        feet = move(*self.feet) if self.feet else None
        return Scene(keep(self.faces), keep(self.balls), feet, min(1.0, self.subject_height * h / ch))


@dataclass
class Prepared:
    """A photo ready for looks: the image (cropped if asked) and its scene."""
    path: Path
    image: Image.Image
    scene: Scene
    exif: bytes | None


_detector: Detector | None = None


def detector() -> Detector:
    global _detector
    if _detector is None:
        _detector = Detector()
    return _detector


def find(img: Image.Image, people: list[Person], balls: list[Box], plan: framing.Plan) -> Scene:
    w, h = img.size
    faces = []
    for p in people:
        if p.head and p.height > 0.08 * h:
            x, y, spread = p.head
            radius = max(spread * 1.4, p.height * 0.12) * FACE_REACH / 2
            faces.append((x / w, y / h, radius / w))
    ball_list = [((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h, (b[2] - b[0]) / 2 / w) for b in balls]
    subject = plan.subject
    feet = ((subject.box[0] + subject.box[2]) / 2 / w, subject.box[3] / h) if subject else None
    height = (subject.height / h) if subject else 0.5
    return Scene(faces, ball_list, feet, height)


def prepare(path: Path, crop: str = "none", colors: dict[str, str] | None = None,
            goalie_first: bool = True, shape: str = "best") -> Prepared:
    """Loads a photo (RAW in the camera's look), finds its scene and, if
    asked, crops it the photo-crops way: "crop" (pro crop) or "face"."""
    colors = colors or {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}
    photo = images.load(path)
    img = photo.image
    people, balls = detector().find(img, focus.focus_point(path, img.size), colors)
    plan = framing.choose(people, balls, img.size, goalie_first)
    scene = find(img, people, balls, plan)
    box = None
    if crop == "crop":
        box = framing.crop_box(plan, img.size, shape)
    elif crop == "face" and plan.face_person:
        box = framing.face_box(plan.face_person, img.size, "sharp", framing.crop_box(plan, img.size, shape))
    if box:
        return Prepared(path, img.crop(box), scene.in_crop(box, img.size), photo.exif)
    return Prepared(path, img, scene, photo.exif)
