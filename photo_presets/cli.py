"""photo-presets-batch: looks on the command line, saved straight to full size.

    uv run photo-presets-batch ~/Movies/"Game day" --random 6
    uv run photo-presets-batch ~/Movies/"Game day" --preset "Grit & Glory" --crop crop
"""

import argparse
import sys
from pathlib import Path

from photo_presets import engine, presets
from photo_presets.app import DEFAULT_EXPORT
from photo_presets.engine import CROPS, Engine


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="photo-presets-batch", description="Creative looks for sports photos")
    p.add_argument("photos", nargs="*", help="photos and/or folders")
    how = p.add_mutually_exclusive_group(required=True)
    how.add_argument("--random", type=int, metavar="N", help="N random looks per photo")
    how.add_argument("--preset", help="run this saved preset (see --list)")
    how.add_argument("--list", action="store_true", help="list the presets and stop")
    p.add_argument("--crop", choices=list(CROPS), default="none", help="crop first the photo-crops way")
    p.add_argument("--seed", type=int, help="seed for random looks (same seed, same looks)")
    p.add_argument("--out", default=DEFAULT_EXPORT, help=f"export folder (default: {DEFAULT_EXPORT})")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    if a.list:
        print("\n".join(presets.load_all()))
        return 0
    paths = engine.collect(a.photos)
    if not a.photos:
        p.error("give photos or folders")
    if not paths:
        print("No photos found", file=sys.stderr)
        return 2
    if a.preset and a.preset not in presets.load_all():
        print(f"No preset named {a.preset!r}; --list shows them", file=sys.stderr)
        return 2

    def progress(done: int, total: int, title: str) -> None:
        print(f"[{done}/{total}] {title}", flush=True)

    e = Engine()
    results = (e.explore(paths, a.random, a.crop, a.seed, progress) if a.random
               else e.preset(paths, a.preset, a.crop, progress=progress))
    saved = e.export(results, Path(a.out).expanduser(), progress)
    print(f"Saved {len(saved)} photo(s) to {Path(a.out).expanduser()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
