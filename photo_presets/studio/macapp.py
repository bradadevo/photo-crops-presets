"""Installs VS Digital Pro as a Mac app: ~/Applications/VS Digital Pro.app, with its
icon, that opens the app in its own window (no Terminal, no browser). Drag it
to the Dock to keep it there. Run it again after updating Python or the
project's environment.

    uv run vsdigitalpro-install-app
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from photo_presets.studio.server import WEB

PROJECT = Path(__file__).resolve().parents[2]
APP = Path("~/Applications/VS Digital Pro.app").expanduser()
LOG = Path("~/Library/Logs/VS Digital Pro.log").expanduser()


def icon(size: int = 1024) -> Image.Image:
    """The app's icon: VS, heavy and italic like a jersey, on a deep navy-to-blue Mac-style tile with a
    light speed stripe across it (the same mark as the page's corner)."""
    from PIL import ImageFont
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pad, r = int(s * 0.09), int(s * 0.2)
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + s * 0.015, s - pad, s - pad + s * 0.015), r, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(s * 0.02)))
    tile = Image.new("RGBA", (s, s))
    a, b = (12, 24, 56), (47, 107, 255)  # navy at the top left, the app's blue at the bottom right
    px = tile.load()
    for y in range(s):
        for x in range(0, s, 4):
            t = min(1.0, max(0.0, (x + y) / (2 * s) * 1.25 - 0.1))
            c = tuple(int(p + (q - p) * t) for p, q in zip(a, b)) + (255,)
            for k in range(4):
                if x + k < s:
                    px[x + k, y] = c
    over = Image.new("RGBA", (s, s), (0, 0, 0, 0))  # a light speed stripe behind the letters
    ImageDraw.Draw(over).polygon([(s * 0.08, s * 0.71), (s * 0.92, s * 0.43), (s * 0.92, s * 0.48), (s * 0.08, s * 0.76)],
                                 fill=(140, 180, 255, 70))
    tile.alpha_composite(over)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Avenir Next Condensed.ttc", int(s * 0.46), index=9)  # Heavy Italic
    except OSError:
        font = ImageFont.load_default()
    sh = Image.new("RGBA", (s, s), (0, 0, 0, 0))  # a soft shadow under the letters
    ImageDraw.Draw(sh).text((s * 0.5, s * 0.515), "VS", font=font, fill=(0, 8, 30, 150), anchor="mm")
    tile.alpha_composite(sh.filter(ImageFilter.GaussianBlur(s * 0.018)))
    ink = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ink).text((s * 0.49, s * 0.5), "VS", font=font, fill=(255, 255, 255, 255), anchor="mm")
    tile.alpha_composite(ink)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, s - pad, s - pad), r, fill=255)
    img.paste(tile, (0, 0), mask)
    return img


def icns(dest: Path) -> None:
    base = icon(1024)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "AppIcon.iconset"
        folder.mkdir()
        for px in (16, 32, 128, 256, 512):
            base.resize((px, px), Image.LANCZOS).save(folder / f"icon_{px}x{px}.png")
            base.resize((px * 2, px * 2), Image.LANCZOS).save(folder / f"icon_{px}x{px}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(folder), "-o", str(dest)], check=True)


def main() -> int:
    uv = shutil.which("uv") or str(Path("~/.local/bin/uv").expanduser())
    if APP.exists():
        shutil.rmtree(APP)
    (APP / "Contents" / "MacOS").mkdir(parents=True)
    (APP / "Contents" / "Resources").mkdir()
    icns(APP / "Contents" / "Resources" / "AppIcon.icns")
    icon(512).save(WEB / "icon.png")  # the Dock icon while it runs
    with open(APP / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleName": "VS Digital Pro", "CFBundleDisplayName": "VS Digital Pro",
            "CFBundleIdentifier": "com.vsdigitalpro.studio", "CFBundleVersion": "1.0", "CFBundleShortVersionString": "1.0",
            "CFBundleExecutable": "launch", "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
            "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.photography",
        }, f)
    # Python itself, copied into the app, so the Dock and the menu bar say VS Digital Pro
    # (not "python"); it runs the project's environment
    engine = APP / "Contents" / "MacOS" / "VS Digital Pro"
    shutil.copy2(Path(sys.executable).resolve(), engine)
    site_packages = next((PROJECT / ".venv" / "lib").glob("python3*/site-packages"))
    launcher = APP / "Contents" / "MacOS" / "launch"
    launcher.write_text(f"""#!/bin/bash
# VS Digital Pro: opens the app in its own window (the looks engine lives in {PROJECT})
export PATH="{Path(uv).parent}:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONHOME="{sys.base_prefix}"
cd "{PROJECT}" || exit 1
mkdir -p "{LOG.parent}"
exec "{engine}" -c "import site, sys; site.addsitedir('{site_packages}'); sys.argv = ['vsdigitalpro', '--window']; \\
from photo_presets.studio.server import main; sys.exit(main())" >> "{LOG}" 2>&1
""")
    launcher.chmod(0o755)
    subprocess.run(["touch", str(APP)])  # so Finder shows the new icon
    print(f"Installed {APP}\nOpen it from Finder (Applications in your home folder) or Spotlight: VS Digital Pro. "
          "Drag it to the Dock to keep it there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
