"""photo-crops on the command line. The questionnaire lives in the UI
(photo-crops-ui); here every answer is a flag, defaulting to the last run's."""

import argparse
import sys

from photo_crops import run, settings
from photo_crops.settings import Settings


def parse(argv: list[str]) -> tuple[Settings, argparse.Namespace]:
    s = Settings.load()
    p = argparse.ArgumentParser(prog="photo-crops", description="Pro crops and face close-ups of every photo in a folder")
    p.add_argument("folder", help="the photo folder")
    p.add_argument("--sources", help="extra folder to search for screenshot sources, such as the SD card's DCIM folder")
    p.add_argument("--out", help=f"output folder name inside the photo folder (now: {s.out_name})")
    p.add_argument("--versions", help="any of O,crop,face (now: " + ",".join(s.versions) + ")")
    p.add_argument("--shape", choices=list(settings.SHAPES))
    p.add_argument("--faces", choices=list(settings.FACES))
    p.add_argument("--edit", choices=list(settings.EDITS))
    p.add_argument("--screenshots", choices=list(settings.SCREENSHOTS))
    p.add_argument("--no-match", choices=list(settings.NO_MATCH))
    p.add_argument("--team-name")
    p.add_argument("--team-color", help="team jersey color, like #1f2a44")
    p.add_argument("--goalie-color")
    p.add_argument("--opponent-color")
    p.add_argument("--team-first", action="store_true", help="put the team's players ahead of the goalie")
    p.add_argument("--estimate", action="store_true", help="show what would be done and stop")
    p.add_argument("--yes", action="store_true", help="start without asking")
    a = p.parse_args(argv)
    s.folder = a.folder
    for key, value in (("sources", a.sources), ("out_name", a.out), ("shape", a.shape), ("faces", a.faces),
                       ("edit", a.edit), ("screenshots", a.screenshots), ("no_match", a.no_match),
                       ("team_name", a.team_name), ("team_color", a.team_color),
                       ("goalie_color", a.goalie_color), ("opponent_color", a.opponent_color)):
        if value is not None:
            setattr(s, key, value)
    if a.versions:
        s.versions = [v.strip() for v in a.versions.split(",") if v.strip()]
    if a.team_first:
        s.goalie_first = False
    return s, a


def main(argv: list[str] | None = None) -> int:
    s, a = parse(sys.argv[1:] if argv is None else argv)
    problems = s.problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    job = run.prepare(s)
    print(s.instructions().split("\n\nCommand:")[0])
    print()
    print(job.summary())
    if a.estimate:
        return 0
    if not a.yes and input("Start? [Y/n]: ").strip().lower() not in ("", "y", "yes"):
        return 1
    s.save()

    def progress(done: int, total: int, message: str) -> None:
        print(f"[{done}/{total}] {message}", flush=True)

    run.run(s, progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
