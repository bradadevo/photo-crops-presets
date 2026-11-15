"""Artist techniques, applied to the whole picture (the players' faces too):
oil brushwork, graphite, charcoal, pen and ink, colored pencil, anime cel
shading and comic halftone.

They keep the picture's structure (every feature stays where it is, so a
face stays the child's) while every part of it, face included, becomes
painted or drawn in the one technique. All on this Mac, procedurally.
"""

import cv2
import numpy as np

from photo_presets.pipeline import Context, op
from photo_presets.procedural import fractal


def _lum(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def kuwahara(a: np.ndarray, r: int) -> np.ndarray:
    """Kuwahara filter: each pixel takes the mean of the calmest of its four
    neighboring quadrants, flattening detail into paint-like strokes while
    keeping edges sharp."""
    k = r + 1
    mean = cv2.boxFilter(a, -1, (k, k), normalize=True, borderType=cv2.BORDER_REFLECT)
    sq = cv2.boxFilter(a * a, -1, (k, k), normalize=True, borderType=cv2.BORDER_REFLECT)
    var = (sq - mean * mean).sum(axis=2)
    h, w = a.shape[:2]
    best = np.full((h, w), np.inf, np.float32)
    out = np.zeros_like(a)
    for dy, dx in ((-r // 2, -r // 2), (-r // 2, r // 2), (r // 2, -r // 2), (r // 2, r // 2)):
        m = np.roll(mean, (dy, dx), axis=(0, 1))
        v = np.roll(var, (dy, dx), axis=(0, 1))
        take = v < best
        best = np.where(take, v, best)
        out = np.where(take[..., None], m, out)
    return out


def _orientation(a: np.ndarray, sigma: float) -> np.ndarray:
    """The direction along the forms (radians), from the structure tensor."""
    g = cv2.GaussianBlur(_lum(a), (0, 0), 1.0)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), sigma)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), sigma)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), sigma)
    return 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2  # along the edges, not across


def strokes(rng: np.random.Generator, h: int, w: int, theta: np.ndarray, length: float, width: float) -> np.ndarray:
    """A field of brush strokes (0-1 height) following theta: noise smeared
    along the local direction (eight directions, each picked where it fits)."""
    noise = fractal(rng, h, w, max(1.5, width), 2)
    out = np.zeros((h, w), np.float32)
    best = np.full((h, w), np.inf, np.float32)
    n = max(3, int(length))
    for k in range(8):
        ang = k * np.pi / 8
        kern = np.zeros((n, n), np.float32)
        c = n // 2
        dx, dy = np.cos(ang) * c, np.sin(ang) * c
        cv2.line(kern, (int(c - dx), int(c - dy)), (int(c + dx), int(c + dy)), 1.0, 1, cv2.LINE_AA)
        kern /= max(kern.sum(), 1e-6)
        smear = cv2.filter2D(noise, -1, kern, borderType=cv2.BORDER_REFLECT)
        diff = np.abs(np.angle(np.exp(1j * 2 * (theta - ang)))) / 2  # how far this direction is from theta
        take = diff < best
        best = np.where(take, diff, best)
        out = np.where(take, smear, out)
    return out


def _paper(rng, h, w, tone=(0.97, 0.96, 0.93), tooth=0.05):
    t = fractal(rng, h, w, max(2.0, max(h, w) * 0.002), 3) - 0.5
    return (np.array(tone, np.float32)[None, None] * (1 - tooth * t)[..., None]).astype(np.float32)


def _hatch(h, w, angle: float, spacing: float, width: float, rng) -> np.ndarray:
    """Parallel hand-drawn lines (0-1 ink) at an angle, a little wavy."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.deg2rad(angle)
    wobble = (fractal(rng, h, w, spacing * 8, 2) - 0.5) * spacing * 0.8
    t = (xx * np.cos(a) + yy * np.sin(a) + wobble) / spacing
    d = np.abs(t - np.round(t)) * spacing
    return np.clip(1 - d / max(0.6, width), 0, 1)


def _ink_lines(a: np.ndarray, size: float, strength: float = 1.0) -> np.ndarray:
    """Drawn lines (0-1) at the picture's edges and folds."""
    g = cv2.bilateralFilter((np.clip(_lum(a), 0, 1) * 255).astype(np.uint8), 7, 30, 5).astype(np.float32) / 255
    s = max(0.8, size * 0.0012)
    dog = cv2.GaussianBlur(g, (0, 0), s) - cv2.GaussianBlur(g, (0, 0), s * 1.8)
    lines = np.clip((-dog - 0.004) * 60 * strength, 0, 1)
    return cv2.GaussianBlur(lines, (0, 0), 0.5)


def render(a: np.ndarray, kind: str, size: float, rng: np.random.Generator, detail: float = 1.0,
           portrait: bool = False) -> np.ndarray:
    """See _render; the result always within 0-1."""
    return np.clip(_render(a, kind, size, rng, detail, portrait), 0, 1).astype(np.float32)


def dodge_sketch(a: np.ndarray, size: float) -> np.ndarray:
    """The classic pencil sketch of a photo (gray divided by its blurred
    negative, a 'color dodge'): lines appear along every change of tone, so a
    face keeps every feature and every curl of hair; flat areas go to paper."""
    g = _lum(cv2.bilateralFilter((np.clip(a, 0, 1) * 255).astype(np.uint8), 5, 18, 3).astype(np.float32) / 255)
    blur = cv2.GaussianBlur(1 - g, (0, 0), max(1.0, size * 0.012))
    return np.clip(g / np.maximum(1 - blur, 0.02), 0, 1)


def portrait(a: np.ndarray, kind: str, size: float, rng: np.random.Generator) -> np.ndarray:
    """A face in the technique, keeping every tonal gradation (so strong side
    light on any skin tone keeps the features): only the surface is stylized."""
    g = _lum(a)
    if kind in ("graphite", "charcoal", "pen"):
        sketch = dodge_sketch(a, size)
        shade = cv2.GaussianBlur(g, (0, 0), max(1.0, size * 0.01))
        if kind == "pen":
            ink = np.clip((0.82 - sketch) / 0.25, 0, 1)
            deep = np.clip((0.22 - shade) / 0.15, 0, 1) * _hatch(*g.shape, 45, size * 0.012, size * 0.004, rng)
            ink = np.maximum(ink, deep)
            return _paper(rng, *g.shape, (0.985, 0.98, 0.965), 0.02) * (1 - ink[..., None] * 0.92)
        tone = sketch * (0.55 + 0.45 * np.clip(shade * 1.4, 0, 1))  # the sketch, shaded softly by the light
        if kind == "charcoal":
            tone = np.clip(tone * 0.92 - 0.04, 0, 1)
            paper_tone = (0.93, 0.91, 0.87)
        else:
            paper_tone = (0.97, 0.96, 0.93)
        deep = np.clip((0.2 - shade) / 0.15, 0, 1) * _hatch(*g.shape, 45, size * 0.012, size * 0.004, rng) * 0.35
        return _paper(rng, *g.shape, paper_tone, 0.04) * np.clip(tone - deep, 0, 1)[..., None]
    if kind in ("cel", "comic"):
        u8 = (np.clip(a, 0, 1) * 255).astype(np.uint8)
        u8 = cv2.bilateralFilter(cv2.bilateralFilter(u8, 7, 22, 3), 7, 18, 3)
        soft = u8.astype(np.float32) / 255
        lab = cv2.cvtColor(soft, cv2.COLOR_RGB2LAB)
        L = lab[..., 0] / 100
        lab[..., 0] = (L + (np.round(L * 6) / 6 - L) * 0.35) * 100  # leaning toward cel tones, gradients kept
        if kind == "comic":
            lab[..., 1:] *= 1.1
        out = np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)
        lines = np.clip((0.86 - dodge_sketch(a, size)) / 0.3, 0, 1) * 0.75  # fine ink at the features
        return out * (1 - lines[..., None])
    if kind in ("oil", "knife"):  # small, soft strokes; the face's modelling kept
        paint = kuwahara(a, max(1, int(size * 0.0035)))
        theta = _orientation(paint, max(1.0, size * 0.01))
        height = strokes(rng, *g.shape, theta, max(3.0, size * 0.03), max(1.0, size * 0.006))
        gy, gx = np.gradient(cv2.GaussianBlur(height, (0, 0), 1.0))
        light = np.clip(1 + (gx * -0.6 + gy * -0.8) * 5, 0.95, 1.05)
        return paint * light[..., None]
    return _render(a, kind, size, rng, 1.0, portrait=True)


def _render(a: np.ndarray, kind: str, size: float, rng: np.random.Generator, detail: float = 1.0,
            portrait: bool = False) -> np.ndarray:
    """The picture in a technique, its marks sized for `size` pixels. portrait:
    the gentler rules painters use on faces (more, softer tones; no black
    shadow shapes; hatching only in the darker tones; small strokes)."""
    h, w = a.shape[:2]
    if kind in ("oil", "knife"):
        r = max(1 if portrait else 2, int(size * (0.004 if kind == "oil" else 0.007) / detail))
        paint = kuwahara(a, r)
        if not portrait:
            paint = kuwahara(paint, max(2, r // 2))
        theta = _orientation(paint, size * 0.01)
        height = strokes(rng, h, w, theta, size * (0.05 if kind == "oil" else 0.07), size * 0.007)
        gy, gx = np.gradient(cv2.GaussianBlur(height, (0, 0), 1.5))
        relief = (8 if portrait else 14) if kind == "oil" else (10 if portrait else 22)
        busy = cv2.GaussianBlur(np.abs(cv2.Laplacian(cv2.GaussianBlur(_lum(a), (0, 0), 2.0), cv2.CV_32F)), (0, 0),
                                size * 0.02)
        busy = 0.12 + 0.88 * np.clip(busy / max(float(np.percentile(busy, 90)), 1e-4), 0, 1)  # calm on flat areas
        light = np.clip(1 + (gx * -0.6 + gy * -0.8) * relief * busy, 0.9, 1.1)  # raised paint, lit from the top left
        out = paint * light[..., None]
        if kind == "knife":
            gray = out.mean(axis=2, keepdims=True)
            out = gray + (out - gray) * 1.25
        return out
    if kind in ("graphite", "charcoal", "pen"):
        lum = _lum(cv2.bilateralFilter((np.clip(a, 0, 1) * 255).astype(np.uint8), 7, 30, 5).astype(np.float32) / 255)
        tone = np.clip((lum - 0.05) / 0.9, 0, 1)
        if portrait:  # a face is drawn lighter and evened: hatching only in its real darks
            broad = cv2.GaussianBlur(tone, (0, 0), max(2.0, size * 0.08))
            tone = np.clip(tone - broad * 0.5 + float(broad.mean()) * 0.5, 0, 1)
            tone = 0.4 + tone * 0.6
        sp = size * (0.0045 if kind != "pen" else 0.004)
        layers = [(0.85, 45), (0.6, -45), (0.38, 0), (0.18, 90)] if not portrait else [(0.62, 45), (0.45, -45)]
        ink = np.zeros((h, w), np.float32)
        for level, ang in layers:  # darker tones get more layers of hatching
            dark = np.clip((level - tone) / 0.12, 0, 1)
            ink = np.maximum(ink, _hatch(h, w, ang + rng.normal(0, 4), sp, sp * (0.22 if kind == "pen" else 0.35), rng)
                             * dark)
        lines = _ink_lines(a, size, 1.2 if kind == "pen" else 0.9)
        if kind == "pen":
            ink = (np.maximum(ink, lines) > 0.45).astype(np.float32)
            return _paper(rng, h, w, (0.985, 0.98, 0.965), 0.02) * (1 - ink[..., None] * 0.92)
        if kind == "charcoal":
            smudge = cv2.GaussianBlur(1 - tone, (0, 0), max(1.0, size * 0.004)) * 0.75
            ink = np.clip(np.maximum(ink * 0.7, smudge) + lines * 0.8, 0, 1)
            grain = fractal(rng, h, w, max(1.5, size * 0.0015), 2)
            ink = np.clip(ink * (0.7 + 0.6 * grain), 0, 1)
            return _paper(rng, h, w, (0.93, 0.91, 0.87), 0.08) * (1 - ink[..., None] * 0.9)
        soft = (1 - tone) * 0.35
        ink = np.clip(np.maximum(ink * 0.75, soft) + lines * 0.7, 0, 1)
        grain = fractal(rng, h, w, max(1.5, size * 0.0012), 2)
        ink = ink * (0.75 + 0.5 * grain)
        return _paper(rng, h, w) * (1 - ink[..., None] * 0.85)
    if kind == "colored_pencil":
        base = cv2.bilateralFilter((np.clip(a, 0, 1) * 255).astype(np.uint8), 7, 30, 5).astype(np.float32) / 255
        sp = size * 0.004
        strokes_a = _hatch(h, w, 35, sp, sp * 0.45, rng) * 0.6 + _hatch(h, w, -30, sp * 1.3, sp * 0.4, rng) * 0.4
        pigment = (1 - base) * ((0.75 if portrait else 0.55) + (0.35 if portrait else 0.6) * strokes_a)[..., None]
        out = _paper(rng, h, w, (0.97, 0.95, 0.9)) * (1 - np.clip(pigment, 0, 1))
        return out * (1 - _ink_lines(a, size, 0.7)[..., None] * 0.5)
    if kind in ("cel", "comic"):
        u8 = (np.clip(a, 0, 1) * 255).astype(np.uint8)
        for _ in range(1 if portrait else 3):
            u8 = cv2.bilateralFilter(u8, 9 if not portrait else 5, 40 if not portrait else 25, 7 if not portrait else 3)
        lab = cv2.cvtColor(u8.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
        L = lab[..., 0] / 100
        if portrait:  # light evened out, darks lifted, soft tones: the face's shapes, no black shadow shapes
            broad = cv2.GaussianBlur(L, (0, 0), max(2.0, size * 0.08))
            L = np.clip(L - broad * 0.6 + float(broad.mean()) * 0.6, 0, 1)
            L = 0.28 + L * 0.72
            Lq = np.round(L * 6) / 6
            lab[..., 0] = (Lq * 0.45 + L * 0.55) * 100
        else:
            steps = 4 if kind == "cel" else 3
            lab[..., 0] = (np.round(L * steps) / steps * 0.85 + L * 0.15) * 100
        if kind == "comic":
            lab[..., 1:] *= 1.25 if not portrait else 1.1
        flat = np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)
        lines = _ink_lines(a, size, (1.3 if kind == "comic" else 1.0) * (0.7 if portrait else 1.0))
        out = flat * (1 - lines[..., None] * 0.9)
        if kind == "comic" and not portrait:  # halftone dots in the shadows
            step = max(4, int(size / 160))
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            gy, gx = (yy % step) - step / 2, ((xx + (yy // step % 2) * step / 2) % step) - step / 2
            shade = np.clip((0.55 - L) / 0.4, 0, 1)
            dots = np.clip(shade * step * 0.55 - np.sqrt(gx ** 2 + gy ** 2), 0, 1)
            out = out * (1 - dots[..., None] * 0.5)
        return out
    return a


def _heads(ctx: Context, h: int, w: int) -> list[tuple[float, float, float]]:
    return [(fx * w, fy * h, fr * w) for fx, fy, fr in ctx.scene.faces if fr * w >= 4]


@op("technique", label="Artist technique (oil, pencil, charcoal, ink, cel, comic)", kind="oil", amount=1.0,
    detail=1.0, where="all")
def technique(a, p, ctx: Context):
    """The technique over the picture ("all") or only the players ("players",
    for flat backgrounds that should stay smooth, like an anime sky); each face
    drawn again at its own scale with portrait rules, so it stays the child's."""
    h, w = a.shape[:2]
    size = float(max(h, w))
    rng = np.random.default_rng(ctx.seed + 81)
    kind, amount = p["kind"], float(p["amount"])
    out = render(a, kind, size, rng, float(p["detail"]))
    if p["where"] == "players" and ctx.alpha is not None:
        m = np.clip(ctx.alpha, 0, 1)[..., None]
        out = a * (1 - m) + out * m
    for cx, cy, r in _heads(ctx, h, w):
        reach = r * 1.9
        x0, y0 = int(max(0, cx - reach)), int(max(0, cy - reach * 1.1))
        x1, y1 = int(min(w, cx + reach)), int(min(h, cy + r * 1.3))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        # marks sized for the face (r is about half a head): fine brushwork and hatching
        face = np.clip(portrait(a[y0:y1, x0:x1], kind, r * 4, np.random.default_rng(ctx.seed + 83)), 0, 1)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        d = np.sqrt(((xx - cx) / (r * 1.25)) ** 2 + ((yy - cy) / (r * 1.4)) ** 2)
        m = np.clip((1.0 - d) / 0.35, 0, 1)
        if ctx.alpha is not None:
            m = m * np.clip(cv2.GaussianBlur(ctx.alpha[y0:y1, x0:x1], (0, 0), 1.0) * 1.3, 0, 1)
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - m[..., None]) + face * m[..., None]
    return np.clip(a + (out - a) * amount, 0, 1).astype(np.float32)
