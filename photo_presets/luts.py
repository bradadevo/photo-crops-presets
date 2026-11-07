"""3D LUTs (.cube): reading and applying them.

Copied from match-cull (fc-sport-culling); the two apps change separately.
Applied with Pillow's built-in 3D LUT filter (trilinear, in C), with a numpy
fallback for the rare LUT whose domain is not 0-1.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# Pixels processed per slice by the numpy fallback, to bound memory
_CHUNK_PIXELS = 1_000_000


@dataclass
class Lut:
    name: str
    table: np.ndarray  # (N, N, N, 3) indexed [blue, green, red]
    domain_min: np.ndarray
    domain_max: np.ndarray

    @property
    def size(self) -> int:
        return self.table.shape[0]


def parse_cube(path: str) -> Lut:
    """Reads an Adobe/Resolve .cube 3D LUT (red varies fastest in the data)."""
    size = None
    domain_min = np.zeros(3, dtype=np.float32)
    domain_max = np.ones(3, dtype=np.float32)
    rows = []
    for line in Path(path).read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split()[0].upper()
        if key == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif key == "DOMAIN_MIN":
            domain_min = np.array(line.split()[1:4], dtype=np.float32)
        elif key == "DOMAIN_MAX":
            domain_max = np.array(line.split()[1:4], dtype=np.float32)
        elif key in ("TITLE", "LUT_1D_SIZE", "LUT_1D_INPUT_RANGE", "LUT_3D_INPUT_RANGE"):
            if key == "LUT_1D_SIZE":
                raise ValueError(f"{path} is a 1D LUT; only 3D LUTs are supported")
        else:
            try:
                rows.append([float(v) for v in line.split()[:3]])
            except ValueError:
                continue
    if not size or len(rows) != size ** 3:
        raise ValueError(f"{path} is not a valid 3D .cube LUT")
    table = np.array(rows, dtype=np.float32).reshape(size, size, size, 3)
    return Lut(Path(path).stem, table, domain_min, domain_max)


@lru_cache(maxsize=32)
def load(path: str) -> Lut:
    return parse_cube(path)


def apply_lut(img: Image.Image, lut: Lut) -> Image.Image:
    """.cube data and Pillow both list red fastest, so the table passes straight through."""
    if not (np.allclose(lut.domain_min, 0) and np.allclose(lut.domain_max, 1)):
        return _apply_lut_any_domain(img, lut)
    table = ImageFilter.Color3DLUT(lut.size, lut.table.reshape(-1).tolist())
    return img.convert("RGB").filter(table)


def _apply_lut_any_domain(img: Image.Image, lut: Lut) -> Image.Image:
    src = np.asarray(img.convert("RGB"))
    h, w, _ = src.shape
    flat = src.reshape(-1, 3)
    out = np.empty_like(flat)
    n = lut.size
    scale = (n - 1) / (lut.domain_max - lut.domain_min)
    t = lut.table
    for start in range(0, flat.shape[0], _CHUNK_PIXELS):
        x = flat[start:start + _CHUNK_PIXELS].astype(np.float32) / 255.0
        idx = np.clip((x - lut.domain_min) * scale, 0, n - 1)
        i0 = np.minimum(idx.astype(np.int32), n - 2)
        f = idx - i0
        r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
        fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
        c00 = t[b0, g0, r0] + (t[b0, g0, r0 + 1] - t[b0, g0, r0]) * fr
        c01 = t[b0, g0 + 1, r0] + (t[b0, g0 + 1, r0 + 1] - t[b0, g0 + 1, r0]) * fr
        c10 = t[b0 + 1, g0, r0] + (t[b0 + 1, g0, r0 + 1] - t[b0 + 1, g0, r0]) * fr
        c11 = t[b0 + 1, g0 + 1, r0] + (t[b0 + 1, g0 + 1, r0 + 1] - t[b0 + 1, g0 + 1, r0]) * fr
        c0 = c00 + (c01 - c00) * fg
        c1 = c10 + (c11 - c10) * fg
        res = c0 + (c1 - c0) * fb
        out[start:start + _CHUNK_PIXELS] = np.clip(res * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out.reshape(h, w, 3))
