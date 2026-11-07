"""Every answer the questionnaire asks for, with today's choices as defaults.

The same settings drive the command line and the UI, are remembered between
runs, and can be written out as plain instructions to paste to Claude.
"""

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SETTINGS_FILE = Path.home() / ".config" / "photo-crops" / "settings.json"

VERSIONS = {"O": "Original copy", "crop": "Pro crop", "face": "Face close-up"}
SHAPES = {"best": "Best crop (4:5 for one player, 3:2 for a duel or group)", "4:5": "Instagram post (4:5)",
          "9:16": "Story (9:16)", "1:1": "Square (1:1)", "3:2": "Landscape (3:2)", "16:9": "YouTube (16:9)"}
FACES = {"sharp": "Zoom as far as it stays sharp", "tight": "Always tight on the face",
         "skip-small": "Skip the face version when the face is too small"}
EDITS = {"none": "No edit (as the camera made it)", "light": "Light clean edit",
         "full": "Full clean edit (deep blacks, punchier)"}
SCREENSHOTS = {"rebuild": "Rebuild from the original photo", "copy": "Copy as is", "skip": "Leave out"}
NO_MATCH = {"copy": "Copy as is and flag it", "skip": "Leave it out"}


@dataclass
class Settings:
    folder: str = ""
    # Extra folder to search for screenshot sources, such as the camera's SD card
    sources: str = ""
    out_name: str = "Best Crops"
    team_name: str = "PSG"
    team_color: str = "#1f2a44"
    goalie_color: str = "#86d0d8"
    opponent_color: str = "#f0f0f0"
    goalie_first: bool = True
    versions: list[str] = field(default_factory=lambda: ["O", "crop", "face"])
    shape: str = "best"
    faces: str = "sharp"
    edit: str = "light"
    screenshots: str = "rebuild"
    no_match: str = "copy"

    def problems(self) -> list[str]:
        out = []
        if not self.folder or not Path(self.folder).expanduser().is_dir():
            out.append(f"Photo folder not found: {self.folder or '(none chosen)'}")
        if self.sources and not Path(self.sources).expanduser().is_dir():
            out.append(f"Screenshot source folder not found: {self.sources}")
        if not self.versions:
            out.append("Choose at least one version")
        for name, value, allowed in (("shape", self.shape, SHAPES), ("faces", self.faces, FACES),
                                     ("edit", self.edit, EDITS), ("screenshots", self.screenshots, SCREENSHOTS),
                                     ("no_match", self.no_match, NO_MATCH)):
            if value not in allowed:
                out.append(f"Unknown {name}: {value}")
        if any(v not in VERSIONS for v in self.versions):
            out.append(f"Unknown version in {self.versions}")
        if not self.out_name.strip() or "/" in self.out_name:
            out.append("The output folder name must be a plain name, like Best Crops")
        return out

    @property
    def folder_path(self) -> Path:
        return Path(self.folder).expanduser()

    @property
    def out_path(self) -> Path:
        return self.folder_path / self.out_name

    @property
    def sources_path(self) -> Path | None:
        return Path(self.sources).expanduser() if self.sources else None

    def instructions(self) -> str:
        """The answers as plain instructions, to paste to Claude."""
        versions = ", ".join(VERSIONS[v] for v in self.versions)
        lines = [
            f"Crop the photos in {self.folder}.",
            f"Put everything in a new folder inside it named \"{self.out_name}\"; leave my originals where they are.",
            "Keep every photo (no ranking).",
            f"Make these versions of each photo: {versions}.",
            f"Crop shape: {SHAPES[self.shape]}.",
            f"Face close-ups: {FACES[self.faces]}.",
            f"Edit: {EDITS[self.edit]}.",
            f"My team is {self.team_name} in {self.team_color} jerseys; the goalie wears {self.goalie_color}; "
            f"opponents wear {self.opponent_color}.",
            ("Priority: the goalie first, then my team's player, then whoever is in focus."
             if self.goalie_first else "Priority: my team's player first, then whoever is in focus."),
            f"Screenshots: {SCREENSHOTS[self.screenshots]}"
            + (f"; if there is no matching photo: {NO_MATCH[self.no_match]}." if self.screenshots == "rebuild" else "."),
        ]
        if self.sources:
            lines.append(f"Also look for screenshot source photos in {self.sources}.")
        lines += ["", "Command:", "  " + self.command()]
        return "\n".join(lines)

    def command(self) -> str:
        def q(s: str) -> str:
            return "'" + s.replace("'", "'\\''") + "'"
        parts = ["uv run photo-crops", q(self.folder), "--yes",
                 "--out", q(self.out_name), "--versions", ",".join(self.versions), "--shape", self.shape,
                 "--faces", self.faces, "--edit", self.edit, "--screenshots", self.screenshots,
                 "--no-match", self.no_match, "--team-name", q(self.team_name), "--team-color", self.team_color,
                 "--goalie-color", self.goalie_color, "--opponent-color", self.opponent_color]
        if self.sources:
            parts += ["--sources", q(self.sources)]
        if not self.goalie_first:
            parts.append("--team-first")
        return " ".join(parts)

    def save(self) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls) -> "Settings":
        try:
            saved = json.loads(SETTINGS_FILE.read_text())
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(saved)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
