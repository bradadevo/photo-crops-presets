"""Installs AllProPhoto as a Mac app: ~/Applications/AllProPhoto.app, with its
icon, that opens the app in its own window (no Terminal, no browser). Drag it
to the Dock to keep it there. Run it again after updating Python or the
project's environment.

    uv run allprophoto-install-app
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
APP = Path("~/Applications/AllProPhoto.app").expanduser()
LOG = Path("~/Library/Logs/AllProPhoto.log").expanduser()


def icon(size: int = 1024) -> Image.Image:
    """The app's icon: the mark from the page's corner on a dark Mac-style tile."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pad, r = int(s * 0.09), int(s * 0.2)
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + s * 0.015, s - pad, s - pad + s * 0.015), r, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(s * 0.02)))
    tile = Image.new("RGBA", (s, s))
    top, bottom = (79, 139, 255), (138, 92, 255)
    grad = ImageDraw.Draw(tile)
    for y in range(s):
        t = y / s
        grad.line([(0, y), (s, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, s - pad, s - pad), r, fill=255)
    img.paste(tile, (0, 0), mask)
    # the mark: an A cut like a peak, in white
    cx, w, h, y0 = s / 2, s * 0.46, s * 0.46, s * 0.27
    a = [(cx, y0), (cx + w / 2, y0 + h), (cx + w * 0.2, y0 + h), (cx, y0 + h * 0.5), (cx - w * 0.2, y0 + h),
         (cx - w / 2, y0 + h)]
    ImageDraw.Draw(img).polygon(a, fill=(255, 255, 255, 255))
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
            "CFBundleName": "AllProPhoto", "CFBundleDisplayName": "AllProPhoto",
            "CFBundleIdentifier": "com.allprophoto.studio", "CFBundleVersion": "1.0", "CFBundleShortVersionString": "1.0",
            "CFBundleExecutable": "launch", "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
            "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.photography",
        }, f)
    # Python itself, copied into the app, so the Dock and the menu bar say AllProPhoto
    # (not "python"); it runs the project's environment
    engine = APP / "Contents" / "MacOS" / "AllProPhoto"
    shutil.copy2(Path(sys.executable).resolve(), engine)
    site_packages = next((PROJECT / ".venv" / "lib").glob("python3*/site-packages"))
    launcher = APP / "Contents" / "MacOS" / "launch"
    launcher.write_text(f"""#!/bin/bash
# AllProPhoto: opens the app in its own window (the looks engine lives in {PROJECT})
export PATH="{Path(uv).parent}:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONHOME="{sys.base_prefix}"
cd "{PROJECT}" || exit 1
mkdir -p "{LOG.parent}"
exec "{engine}" -c "import site, sys; site.addsitedir('{site_packages}'); sys.argv = ['allprophoto', '--window']; \\
from photo_presets.studio.server import main; sys.exit(main())" >> "{LOG}" 2>&1
""")
    launcher.chmod(0o755)
    subprocess.run(["touch", str(APP)])  # so Finder shows the new icon
    print(f"Installed {APP}\nOpen it from Finder (Applications in your home folder) or Spotlight: AllProPhoto. "
          "Drag it to the Dock to keep it there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
