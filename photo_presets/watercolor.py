"""Watercolor, painted on this Mac: paper, washes, blooms, wet edges, granulation, splatter and drips.

Watercolor is transparent paint on white paper: each wash darkens what is
under it (layers multiply), pigment pools at the edge of a wash as it dries
(a darker "wet edge"), settles into the paper's grain (granulation), and
blooms where wet paint meets wet paint. Splatter is flicked drops, in
clusters, bigger near where they were flicked from. These are drawn here,
procedurally (no AI), the same for the same seed.
"""

import cv2
import numpy as np

from photo_presets.pipeline import Context, MissingAsset, op
from photo_presets.procedural import fractal

PAPER = np.array([0.985, 0.978, 0.962], np.float32)  # warm white cold-press paper
RAINBOW = "#6a4fb3,#e0a52b,#2c7a4b,#3fb6a8,#e8577a,#2b3a8c,#f2c94c,#c2185b,#8bc34a"


def _palette(colors: str) -> np.ndarray:
    out = []
    for c in colors.split(","):
        c = c.strip().lstrip("#")
        if len(c) == 6:
            out.append([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    return np.array(out or [[0.2, 0.4, 0.8]], np.float32)


def paper(rng: np.random.Generator, h: int, w: int, mottle: float = 0.5) -> np.ndarray:
    """Cold-press paper: warm white, a fine tooth, and faint gray clouds (a light wash)."""
    s = max(h, w)
    tooth = fractal(rng, h, w, max(3.0, s * 0.004), 3) - 0.5
    clouds = fractal(rng, h, w, s * 0.09, 6)
    shade = 1 - 0.035 * tooth - mottle * 0.09 * np.clip(clouds - 0.42, 0, 1) * 2
    return (PAPER[None, None] * shade[..., None]).astype(np.float32)


def grain(rng: np.random.Generator, h: int, w: int) -> np.ndarray:
    """The paper's grain, where pigment settles (0-1, mostly near 0.5)."""
    return fractal(rng, h, w, max(2.0, max(h, w) * 0.002), 3)


def ragged(rng: np.random.Generator, mask: np.ndarray, rough: float, scale: float) -> np.ndarray:
    """A soft mask's edge made irregular, as paint spreads on wet paper."""
    h, w = mask.shape
    n = fractal(rng, h, w, max(2.0, scale), 4) - 0.5
    return np.clip((mask - 0.5 + rough * n) * 6 + 0.5, 0, 1).astype(np.float32)


def wash(rng: np.random.Generator, shape: np.ndarray, strength: float = 0.7, wet_edge: float = 0.6,
         granulation: float = 0.35, flow: float = 0.5, grain_map: np.ndarray | None = None) -> np.ndarray:
    """How much pigment a wash of this shape (0-1) leaves at each pixel: uneven
    inside (flow), pooled darker at its edge (wet edge), and settled into the
    grain."""
    h, w = shape.shape
    s = max(h, w)
    inner = 1 - flow * 0.6 * fractal(rng, h, w, s * 0.05, 4)
    soft = cv2.GaussianBlur(shape, (0, 0), max(1.0, s * 0.006))
    edge = np.clip(shape - soft, 0, 1) * 2.2  # pigment pooled just inside the edge
    density = shape * inner * strength + edge * wet_edge * strength
    if granulation > 0:
        g = grain_map if grain_map is not None else grain(rng, h, w)
        density *= 1 + granulation * (g - 0.5) * 1.6
    return np.clip(density, 0, 1).astype(np.float32)


def glaze(base: np.ndarray, color: np.ndarray, density: np.ndarray) -> np.ndarray:
    """Transparent paint over what is there: it darkens toward its color."""
    return base * (1 - density[..., None] * (1 - color[None, None]))


def blob(rng: np.random.Generator, h: int, w: int, cx: float, cy: float, r: float, rough: float = 0.35,
         stretch: float = 1.0, angle: float = 0.0) -> tuple[np.ndarray, tuple[slice, slice]] | None:
    """An irregular wash shape (0-1) around cx, cy (pixels), about r across,
    drawn only in the box around it: (shape, (rows, columns)), or None off the picture."""
    reach = int(r * max(stretch, 1 / stretch) * 1.8) + 4
    x0, y0, x1, y1 = max(0, int(cx) - reach), max(0, int(cy) - reach), min(w, int(cx) + reach), min(h, int(cy) + reach)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    axes = (max(1, int(r * stretch)), max(1, int(r / stretch)))
    cv2.ellipse(m, (int(cx) - x0, int(cy) - y0), axes, angle, 0, 360, 1.0, -1, cv2.LINE_AA)
    m = cv2.GaussianBlur(m, (0, 0), max(1.0, r * 0.35))
    return ragged(rng, m, rough, max(2.0, r * 0.5)), (slice(y0, y1), slice(x0, x1))


def splatter(rng: np.random.Generator, h: int, w: int, center: tuple[float, float], reach: float, count: int,
             size: float) -> list[tuple[float, float, float]]:
    """Flicked drops (x, y, radius in pixels): in clusters along a few
    directions, bigger nearer where they came from."""
    drops = []
    cx, cy = center
    for _ in range(max(1, count // 25)):
        ang = rng.uniform(0, 2 * np.pi)
        for _ in range(25):
            d = reach * rng.uniform(0.15, 1.0) ** 0.7
            a = ang + rng.normal(0, 0.35)
            x, y = cx + np.cos(a) * d, cy + np.sin(a) * d
            r = size * (1.15 - d / reach) * rng.pareto(2.2) * 0.6 + size * 0.15
            if 0 <= x < w and 0 <= y < h:
                drops.append((x, y, min(r, size * 3)))
    return drops


def drops_layer(rng: np.random.Generator, h: int, w: int, drops, colors: np.ndarray,
                base: np.ndarray) -> np.ndarray:
    """Drops painted as tiny washes with wet edges."""
    out = base
    if not drops:
        return out
    by_color = rng.integers(0, len(colors), len(drops))
    for k, color in enumerate(colors):
        m = np.zeros((h, w), np.float32)
        for (x, y, r), c in zip(drops, by_color):
            if c == k:
                cv2.circle(m, (int(x * 4), int(y * 4)), max(1, int(r * 4)), 1.0, -1, cv2.LINE_AA, shift=2)
        if m.any():
            d = wash(rng, m, strength=0.85, wet_edge=0.8, granulation=0.15, flow=0.25)
            out = glaze(out, color, d)
    return out


def defringe(img: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """The players' edge pixels (hair, arms) with the old background's color
    taken out, so no light or dark halo shows over a new background.

    An edge pixel is a mix of player and background: it is solved for the
    player's color, with the background estimated from nearby background
    pixels; where the player is faint (wisps of hair), the color comes from
    the nearest solid player pixels instead."""
    h, w = alpha.shape
    band = (alpha > 0.01) & (alpha < 0.98)
    if not band.any():
        return img
    s = max(2.0, 0.006 * max(h, w))
    def spread(mask):
        m = mask.astype(np.float32)
        num = cv2.GaussianBlur(img * m[..., None], (0, 0), s)
        den = cv2.GaussianBlur(m, (0, 0), s)[..., None]
        return num / np.maximum(den, 1e-4), den[..., 0]
    bg, _ = spread(alpha < 0.05)
    solid, _ = spread(alpha > 0.95)
    a = np.clip(alpha, 0.05, 1)[..., None]
    solved = np.clip((img - (1 - a) * bg) / a, 0, 1)
    t = np.clip((alpha - 0.15) / 0.5, 0, 1)[..., None]  # faint: the solid color; firmer: the solved one
    fixed = solid * (1 - t) + solved * t
    return np.where(band[..., None], fixed, img).astype(np.float32)


def _mask(ctx: Context) -> np.ndarray:
    if ctx.alpha is None or float(ctx.alpha.max()) < 0.5:
        raise MissingAsset("no player cut-out in this photo")
    return np.clip(ctx.alpha, 0, 1).astype(np.float32)


def splat(rng: np.random.Generator, h: int, w: int, cx: float, cy: float, r: float, lobes: float = 1.0):
    """An ink-blot splat: a cluster of uneven lobes with ragged edges (see blob for what it returns)."""
    reach = int(r * 2.2) + 4
    x0, y0, x1, y1 = max(0, int(cx) - reach), max(0, int(cy) - reach), min(w, int(cx) + reach), min(h, int(cy) + reach)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    c = np.array([cx - x0, cy - y0])
    cv2.circle(m, tuple(int(v) for v in c), max(1, int(r * 0.7)), 1.0, -1, cv2.LINE_AA)
    for _ in range(int(rng.integers(3, 8) * lobes)):
        a, d = rng.uniform(0, 2 * np.pi), r * rng.uniform(0.4, 1.1)
        q = c + d * np.array([np.cos(a), np.sin(a)])
        cv2.circle(m, (int(q[0]), int(q[1])), max(1, int(r * rng.uniform(0.2, 0.55))), 1.0, -1, cv2.LINE_AA)
    m = cv2.GaussianBlur(m, (0, 0), max(0.8, r * 0.18))
    return ragged(rng, m, 0.35, max(2.0, r * 0.3)), (slice(y0, y1), slice(x0, x1))


def paint(fill: np.ndarray, color: np.ndarray, density: np.ndarray, shape: np.ndarray, pool: float = 0.35) -> np.ndarray:
    """Pigment laid over pigment (staying vivid, as layered watercolor does
    where it dries between washes), with its edge pooled darker."""
    out = fill * (1 - density[..., None]) + color[None, None] * density[..., None]
    soft = cv2.GaussianBlur(shape, (0, 0), max(0.8, 0.02 * max(shape.shape)))
    edge = np.clip(shape - soft, 0, 1) * 2.0
    return out * (1 - (edge * pool)[..., None] * (1 - color[None, None] * 0.4))


def _saturate(rgb: np.ndarray, amount: float) -> np.ndarray:
    gray = rgb.mean(axis=2, keepdims=True)
    return np.clip(gray + (rgb - gray) * amount, 0, 1)


def _contours(src: np.ndarray, inside: np.ndarray, ph: float) -> tuple[np.ndarray, np.ndarray]:
    """Dark and pale lines along the photo's folds and edges, inside the figure (0-1 each)."""
    g = cv2.GaussianBlur(src.mean(axis=2).astype(np.float32), (0, 0), max(0.8, ph * 0.002))
    dog = cv2.GaussianBlur(g, (0, 0), max(0.8, ph * 0.0015)) - cv2.GaussianBlur(g, (0, 0), max(2.0, ph * 0.006))
    core = cv2.erode(inside, np.ones((5, 5), np.uint8))
    dark = np.clip((-dog - 0.035) * 30, 0, 1) * core
    pale = np.clip((dog - 0.04) * 20, 0, 1) * core
    # only lines long enough to be folds or outlines, not the kit's printed pattern
    keep = []
    for m in (dark, pale):
        n, lab, st, _ = cv2.connectedComponentsWithStats((m > 0.3).astype(np.uint8), connectivity=8)
        longest = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT])
        ok = (longest >= ph * 0.05) & (st[:, cv2.CC_STAT_AREA] < longest * max(3.0, ph * 0.004) * 3)
        ok[0] = False
        keep.append(m * ok[lab])
    return keep[0], keep[1]


def _edge_points(alpha: np.ndarray, lower: float = 0.7) -> np.ndarray:
    """Points on the figure's outline (x, y), weighted toward its lower part."""
    ring = cv2.morphologyEx((alpha > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(ring)
    if not len(xs):
        return np.zeros((0, 2))
    keep = ys >= np.percentile(ys, 100 * lower * 0.6)
    return np.stack([xs[keep], ys[keep]], 1)


def flicks(rng: np.random.Generator, alpha: np.ndarray, ph: float, count: int, size: float) -> list:
    """Splatter flicked off the figure: clusters starting at its outline (mostly
    limbs and feet), flying outward, big drops near, fine ones far."""
    h, w = alpha.shape
    pts = _edge_points(alpha)
    if not len(pts):
        return []
    ys, xs = np.nonzero(alpha > 0.5)
    center = np.array([xs.mean(), ys.mean()])
    drops = []
    for _ in range(max(1, count // 18)):
        sx, sy = pts[rng.integers(len(pts))]
        out = np.array([sx, sy]) - center
        ang = np.arctan2(out[1], out[0]) + rng.normal(0, 0.5)
        for _ in range(18):
            d = ph * 0.32 * rng.uniform(0.0, 1.0) ** 1.3
            a = ang + rng.normal(0, 0.28)
            x, y = sx + np.cos(a) * d, sy + np.sin(a) * d
            r = size * (1.3 - d / (ph * 0.32)) * (0.3 + rng.pareto(2.5) * 0.5)
            if 0 <= x < w and 0 <= y < h and alpha[int(y), int(x)] < 0.3:
                drops.append((x, y, float(np.clip(r, size * 0.2, size * 3.5))))
    return drops


@op("wc_silhouette", cutout=True, label="Watercolor silhouette (rainbow blooms)", colors=RAINBOW, blooms=1.0,
    shading=0.45, lines=0.6, splatter=1.0, mottle=1.0, vivid=1.1, granulation=0.6)
def wc_silhouette(a, p, ctx: Context):
    """The players as a silhouette filled with bright, layered watercolor
    blooms and splats, traced with fine lines from the photo, with splatter
    flicked off them, on mottled paper (the classic wall-print look)."""
    alpha = _mask(ctx)
    h, w = alpha.shape
    rng = np.random.default_rng(ctx.seed + 11)
    colors = _palette(p["colors"])
    g = grain(rng, h, w)
    out = paper(rng, h, w, float(p["mottle"]))
    inside = cv2.GaussianBlur((alpha > 0.5).astype(np.float32), (0, 0), 0.7)
    ys, xs = np.nonzero(alpha > 0.5)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    ph = float(max(y1 - y0, x1 - x0))
    pick = lambda: colors[rng.integers(len(colors))]  # noqa: E731
    t = np.clip((np.arange(h, dtype=np.float32)[:, None] - y0) / max(ph, 1), 0, 1)[..., None]
    fill = np.ones((h, w, 3), np.float32) * (pick() * (1 - t) + pick() * t) * 0.8 + 0.2
    blooms = float(p["blooms"])
    layers = [(int(30 * blooms), 0.05, 0.12, (0.6, 0.85)),  # washes in several colors: no paper left
              (int(55 * blooms), 0.035, 0.11, (0.55, 0.9)),  # blooms
              (int(140 * blooms), 0.008, 0.035, (0.7, 0.95))]  # small splats
    for n, lo, hi, (dlo, dhi) in layers:
        for k in range(n):
            cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
            if alpha[int(cy), int(cx)] < 0.5:
                continue
            r = ph * rng.uniform(lo, hi)
            b = (splat(rng, h, w, cx, cy, r) if hi < 0.05 and rng.random() < 0.6
                 else blob(rng, h, w, cx, cy, r, rough=0.5, stretch=rng.uniform(0.6, 1.7), angle=rng.uniform(0, 180)))
            if b is None:
                continue
            shape, at = b
            d = wash(rng, shape, rng.uniform(dlo, dhi), 0.0, float(p["granulation"]), 0.55, g[at])
            fill[at] = paint(fill[at], pick(), d, shape)
    for k in range(int(420 * blooms)):  # tiny speckles of pigment through the figure
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if alpha[int(cy), int(cx)] < 0.5:
            continue
        r = ph * rng.uniform(0.002, 0.007)
        b = blob(rng, h, w, cx, cy, r, rough=0.15)
        if b is not None:
            shape, at = b
            fill[at] = paint(fill[at], pick(), shape * rng.uniform(0.6, 0.95), shape, 0.2)
    fill = _saturate(fill, float(p["vivid"]))
    if float(p["shading"]) > 0:  # the body's form, faintly, from the photo
        src = ctx.original if ctx.original is not None else a
        lum = cv2.GaussianBlur(src.mean(axis=2), (0, 0), max(1.0, ph * 0.006))
        lum = (lum - lum[alpha > 0.5].mean()) / max(float(lum[alpha > 0.5].std()), 1e-3)
        fill = fill * (1 + float(p["shading"]) * 0.12 * np.clip(lum, -2, 2))[..., None]
    if float(p["lines"]) > 0:
        dark, pale = _contours(ctx.original if ctx.original is not None else a, inside, ph)
        k = float(p["lines"])
        fill = fill * (1 - (dark * k * 0.5)[..., None])
        fill = fill + (1 - fill) * (pale * k * 0.5)[..., None]
    fill = np.clip(fill, 0, 1)
    out = out * (1 - inside[..., None]) + fill * (out / PAPER[None, None]) * inside[..., None]
    if float(p["splatter"]) > 0:
        drops = flicks(rng, alpha, ph, int(800 * float(p["splatter"])), ph * 0.005)
        for x, y, r in drops:
            b = splat(rng, h, w, x, y, r, 0.6) if r > ph * 0.009 else blob(rng, h, w, x, y, r, rough=0.2)
            if b is None:
                continue
            shape, at = b
            d = wash(rng, shape, rng.uniform(0.6, 0.9), 0.0, 0.15, 0.2, g[at])
            out[at] = paint(out[at], pick(), d, shape, 0.5)
    return np.clip(out, 0, 1).astype(np.float32)


# Backgrounds, scenes, ink and paper for the painted-player looks ------------------------------

def shades(colors: str, n: int = 6) -> np.ndarray:
    """A family of washes from the given colors: each as given, lighter and deeper."""
    base = _palette(colors)
    out = []
    for c in base:
        for k in (0.0, 0.35, -0.25):
            out.append(np.clip(c + (1 - c) * k if k > 0 else c * (1 + k), 0, 1))
    return np.array(out[: max(n, len(base))], np.float32)


def _figure(alpha: np.ndarray) -> tuple[float, float, float, float, float]:
    ys, xs = np.nonzero(alpha > 0.5)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    return x0, y0, x1, y1, float(max(x1 - x0, y1 - y0))


@op("wc_backdrop", cutout=True, label="Watercolor background (splash or full sheet)", colors="#2f6db3,#8fc1e8",
    style="splash", amount=1.0, splatter=1.0, mottle=0.4)
def wc_backdrop(a, p, ctx: Context):
    """A painted background behind the players, in their colors: "splash"
    (clouds of paint around them, fading into white paper, with flicked
    drops) or "full" (the whole sheet washed, in two or three colors)."""
    alpha = _mask(ctx)
    h, w = alpha.shape
    rng = np.random.default_rng(ctx.seed + 23)
    pal = shades(p["colors"], 9)
    g = grain(rng, h, w)
    out = paper(rng, h, w, float(p["mottle"]))
    x0, y0, x1, y1, ph = _figure(alpha)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    amount = float(p["amount"])
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if p["style"] == "full":
        # the whole sheet: big wet washes in the team colors, dragged diagonally, pooled at their
        # edges, with lights lifted out and runs of paint
        base = _palette(p["colors"])
        side = (xx / w + (fractal(rng, h, w, max(h, w) * 0.35, 3) - 0.5) * 0.8) > 0.5
        for _ in range(int(26 * amount)):
            r = max(h, w) * rng.uniform(0.12, 0.3)
            bx, by = rng.uniform(-0.1, 1.1) * w, rng.uniform(-0.1, 1.1) * h
            b = blob(rng, h, w, bx, by, r, rough=0.7, stretch=rng.uniform(1.0, 2.4), angle=rng.uniform(-60, -20))
            if b is None:
                continue
            shape, at = b
            col = base[0] if not side[int(np.clip(by, 0, h - 1)), int(np.clip(bx, 0, w - 1))] else base[-1]
            col = np.clip(col + (1 - col) * rng.uniform(-0.15, 0.45), 0, 1)
            out[at] = glaze(out[at], col, wash(rng, shape, rng.uniform(0.25, 0.55), 1.1, 0.6, 0.8, g[at]))
        for _ in range(int(30 * amount)):  # smaller, darker accents
            r = max(h, w) * rng.uniform(0.02, 0.07)
            b = blob(rng, h, w, rng.uniform(0, w), rng.uniform(0, h), r, rough=0.6, stretch=rng.uniform(0.8, 2.0),
                     angle=rng.uniform(-60, -20))
            if b is not None:
                shape, at = b
                out[at] = glaze(out[at], pal[rng.integers(len(pal))], wash(rng, shape, rng.uniform(0.3, 0.65), 1.0,
                                                                         0.6, 0.6, g[at]))
        for _ in range(int(10 * amount)):  # lifted lights: paper showing through where the painter blotted
            r = max(h, w) * rng.uniform(0.03, 0.09)
            b = blob(rng, h, w, rng.uniform(0, w), rng.uniform(0, h), r, rough=0.6, stretch=rng.uniform(1, 2.2),
                     angle=rng.uniform(-60, -20))
            if b is None:
                continue
            shape, at = b
            out[at] = out[at] + (PAPER[None, None] - out[at]) * (shape * 0.6)[..., None]
    else:
        # clouds of paint around the players, heavier low and behind them, fading out into the paper
        for _ in range(int(55 * amount)):
            ang = rng.uniform(0, 2 * np.pi)
            dist = ph * rng.uniform(0.0, 0.62) ** 0.8
            bx, by = cx + np.cos(ang) * dist * 1.1, cy + np.sin(ang) * dist * 0.8 + ph * 0.12
            r = ph * rng.uniform(0.06, 0.2)
            b = blob(rng, h, w, bx, by, r, rough=0.6, stretch=rng.uniform(0.7, 1.9), angle=rng.uniform(-30, 30))
            if b is None:
                continue
            shape, at = b
            fade = np.exp(-((xx[at] - cx) ** 2 / (ph * 0.75) ** 2 + (yy[at] - cy - ph * 0.1) ** 2 / (ph * 0.7) ** 2))
            d = wash(rng, shape, rng.uniform(0.2, 0.6), 1.0, 0.55, 0.7, g[at]) * (0.35 + 0.65 * fade)
            out[at] = glaze(out[at], pal[rng.integers(len(pal))], d)
        for _ in range(int(8 * amount)):  # a ground wash, dragged sideways under the feet
            r = ph * rng.uniform(0.08, 0.16)
            b = blob(rng, h, w, cx + rng.normal(0, ph * 0.3), y1 + rng.normal(0, ph * 0.03), r, rough=0.6,
                     stretch=rng.uniform(2.0, 3.5), angle=rng.uniform(-6, 6))
            if b is not None:
                shape, at = b
                out[at] = glaze(out[at], pal[rng.integers(len(pal))], wash(rng, shape, rng.uniform(0.3, 0.6), 1.0,
                                                                         0.55, 0.7, g[at]))
    if float(p["splatter"]) > 0:
        drops = flicks(rng, alpha, ph, int(420 * float(p["splatter"])), ph * 0.006)
        for x, y, r in drops:
            b = splat(rng, h, w, x, y, r, 0.6) if r > ph * 0.009 else blob(rng, h, w, x, y, r, rough=0.2)
            if b is None:
                continue
            shape, at = b
            out[at] = paint(out[at], pal[rng.integers(len(pal))],
                            wash(rng, shape, rng.uniform(0.55, 0.9), 0.0, 0.15, 0.2, g[at]), shape, 0.5)
    keep = alpha[..., None]
    return np.clip(out * (1 - keep) + defringe(a, alpha) * keep, 0, 1).astype(np.float32)


def _loosen(rgb: np.ndarray, rng: np.random.Generator, scale: float) -> np.ndarray:
    """A picture made loose and painterly: flattened into soft color areas,
    with their edges wandering as wet paint does."""
    h, w = rgb.shape[:2]
    small_edge = 700
    k = min(1.0, small_edge / max(h, w))
    small = cv2.resize(rgb, (max(8, int(w * k)), max(8, int(h * k))), interpolation=cv2.INTER_AREA)
    u8 = (np.clip(small, 0, 1) * 255).astype(np.uint8)
    flat = cv2.pyrMeanShiftFiltering(u8, sp=int(10 * scale), sr=int(28 * scale)).astype(np.float32) / 255
    sh, sw = flat.shape[:2]
    dx = (fractal(rng, sh, sw, sw * 0.04, 3) - 0.5) * sw * 0.012
    dy = (fractal(rng, sh, sw, sw * 0.04, 3) - 0.5) * sw * 0.012
    gx, gy = np.meshgrid(np.arange(sw, dtype=np.float32), np.arange(sh, dtype=np.float32))
    flat = cv2.remap(flat, gx + dx, gy + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.resize(flat, (w, h), interpolation=cv2.INTER_CUBIC)


@op("wc_scene", cutout=True, label="Watercolor scene (the real background, painted loose)",
    colors="#f6c56b,#f4a259,#ee7b6f,#f7dc8a,#7fb8d8", light=0.5, bloom=1.0, dissolve=1.0, drips=1.0, splatter=1.0,
    warm="#f6d7a0")
def wc_scene(a, p, ctx: Context):
    """The photo's own background painted loosely in watercolor (flattened,
    bleeding, pooled at the edges of its color areas, settled into the grain),
    with warm washes blooming through it, dissolving into white paper around
    the edges, with drips along the bottom and splatter."""
    alpha = _mask(ctx)
    h, w = alpha.shape
    rng = np.random.default_rng(ctx.seed + 31)
    pal = _palette(p["colors"])
    g = grain(rng, h, w)
    base = paper(rng, h, w, 0.3)
    src = ctx.original if ctx.original is not None else a
    # the players taken out of the scene first (filled from around them), so no ghost of them is painted in
    k = max(1.0, 700 / max(h, w))
    small = cv2.resize((np.clip(src, 0, 1) * 255).astype(np.uint8), (max(8, int(w * min(1, k))), max(8, int(h * min(1, k)))),
                       interpolation=cv2.INTER_AREA)
    hole = cv2.resize((alpha > 0.05).astype(np.uint8), small.shape[1::-1], interpolation=cv2.INTER_NEAREST)
    hole = cv2.dilate(hole, np.ones((7, 7), np.uint8))
    filled = cv2.inpaint(small, hole, 9, cv2.INPAINT_TELEA)
    src = cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255
    loose = _loosen(src, rng, 1.0)
    loose = 1 - (1 - loose) * (1 - float(p["light"]))  # watercolor is lighter and more transparent
    edges = cv2.Laplacian(cv2.GaussianBlur(loose.mean(axis=2), (0, 0), 1.5), cv2.CV_32F, ksize=3)
    loose = loose * (1 - np.clip(np.abs(edges) * 3, 0, 0.25))[..., None]  # pooled edges between areas
    loose = loose * (1 + 0.5 * (g - 0.5) * 0.4)[..., None]
    x0, y0, x1, y1, ph = _figure(alpha)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    gray = loose.mean(axis=2, keepdims=True)
    loose = gray + (loose - gray) * 0.75  # calmer colors, so the washes lead
    out = base * loose / PAPER[None, None]
    if p["warm"]:
        out = glaze(out, _palette(p["warm"])[0], np.full((h, w), 0.35, np.float32))
    for _ in range(int(24 * float(p["bloom"]))):  # warm washes blooming through the scene, mostly above and behind
        r = max(h, w) * rng.uniform(0.08, 0.2)
        bx, by = rng.uniform(0, w), rng.uniform(0, h * 0.7)
        b = blob(rng, h, w, bx, by, r, rough=0.65, stretch=rng.uniform(0.8, 1.6))
        if b is None:
            continue
        shape, at = b
        out[at] = glaze(out[at], pal[rng.integers(len(pal))], wash(rng, shape, rng.uniform(0.3, 0.55), 1.0, 0.5,
                                                                  0.7, g[at]))
    # dissolving into the paper: a ragged vignette around the players, open at the edges
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rx, ry = max(w * 0.48, (x1 - x0) * 0.75), max(h * 0.46, (y1 - y0) * 0.65)
    dist = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy + ph * 0.05) / ry) ** 2)
    keep = np.clip((1.0 - dist) * 3 + (fractal(rng, h, w, max(h, w) * 0.06, 5) - 0.5) * 1.6, 0, 1)
    keep = keep ** (0.7 + 0.6 * float(p["dissolve"]))
    if float(p["drips"]) > 0:  # paint running down from the bottom of the painted area
        bottom = np.zeros((h, w), np.float32)
        for _ in range(int(26 * float(p["drips"]))):
            x = int(rng.uniform(x0 - ph * 0.4, x1 + ph * 0.4))
            if not 0 <= x < w:
                continue
            col = keep[:, x]
            rows = np.nonzero(col > 0.5)[0]
            if not len(rows):
                continue
            start = rows.max()
            length = int(ph * rng.uniform(0.04, 0.22))
            width = max(1, int(ph * rng.uniform(0.003, 0.009)))
            cv2.line(bottom, (x, start), (x, min(h - 1, start + length)), 1.0, width, cv2.LINE_AA)
            cv2.circle(bottom, (x, min(h - 1, start + length)), int(width * 1.3), 1.0, -1, cv2.LINE_AA)
        keep = np.maximum(keep, cv2.GaussianBlur(bottom, (0, 0), 0.8) * 0.85)
    out = base * (1 - keep[..., None]) + out * keep[..., None]
    if float(p["splatter"]) > 0:
        drops = flicks(rng, alpha, ph, int(320 * float(p["splatter"])), ph * 0.006)
        for x, y, r in drops:
            b = splat(rng, h, w, x, y, r, 0.6) if r > ph * 0.009 else blob(rng, h, w, x, y, r, rough=0.2)
            if b is None:
                continue
            shape, at = b
            out[at] = paint(out[at], pal[rng.integers(len(pal))],
                            wash(rng, shape, rng.uniform(0.5, 0.85), 0.0, 0.15, 0.2, g[at]), shape, 0.5)
    m = alpha[..., None]
    return np.clip(out * (1 - m) + defringe(a, alpha) * m, 0, 1).astype(np.float32)


@op("wc_ink", cutout=True, label="Pen and ink lines over the players", color="#2a2320", amount=0.7, sketch=1.0,
    detail=0.6)
def wc_ink(a, p, ctx: Context):
    """Sketchy pen-and-ink lines over the players, traced from the photo: the
    outline and main folds, drawn twice, a little apart, as a quick hand does."""
    alpha = _mask(ctx)
    from photo_presets.comic import line_art
    src = ctx.original if ctx.original is not None else a
    x0, y0, x1, y1, ph = _figure(alpha)
    lines = line_art(src, None, float(p["detail"])).astype(np.float32) / 255
    h, w = alpha.shape
    inner = cv2.erode((alpha > 0.5).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
    ring = cv2.morphologyEx((alpha > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    rng0 = np.random.default_rng(ctx.seed + 43)
    broken = (fractal(rng0, h, w, ph * 0.04, 3) > 0.55).astype(np.float32)  # the hand lifts off now and then
    lines = np.maximum(lines * inner, ring * broken * 0.8)
    n, lab, st, _ = cv2.connectedComponentsWithStats((lines > 0.3).astype(np.uint8), connectivity=8)
    longest = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT])
    ok = longest >= ph * 0.02
    ok[0] = False
    lines = lines * ok[lab]
    rng = np.random.default_rng(ctx.seed + 41)
    ink = lines.copy()
    if float(p["sketch"]) > 0:  # a second pass, slightly off, fainter
        off = max(1.0, ph * 0.0025)
        m = np.float32([[1, 0, rng.uniform(-off, off)], [0, 1, rng.uniform(-off, off)]])
        ink = np.maximum(ink, cv2.warpAffine(lines, m, (w, h)) * 0.55 * float(p["sketch"]))
    ink = cv2.GaussianBlur(ink, (0, 0), 0.5) * (0.75 + 0.5 * fractal(rng, h, w, ph * 0.05, 3))
    color = _palette(p["color"])[0]
    return glaze(a, color, np.clip(ink * float(p["amount"]), 0, 1))


@op("wc_finish", label="Watercolor paper (grain across the whole picture)", grain=0.6)
def wc_finish(a, p, ctx: Context):
    """One paper's grain across the whole picture, so painted, drawn and AI
    parts read as one sheet."""
    h, w = a.shape[:2]
    rng = np.random.default_rng(ctx.seed + 51)
    tooth = fractal(rng, h, w, max(2.0, max(h, w) * 0.0025), 3) - 0.5
    return np.clip(a * (1 - float(p["grain"]) * 0.07 * tooth)[..., None], 0, 1).astype(np.float32)


@op("wc_integrate", cutout=True, label="Watercolor: blend the players into the painting", colors="#2f6db3,#8fc1e8",
    lost=1.0, cross=1.0, splatter=0.6)
def wc_integrate(a, p, ctx: Context):
    """The painted players made part of the painting, as a watercolorist leaves
    them: some outer edges lost into the paper (ragged, never on the face),
    washes of the background colors crossing the outline, and drops flicked over
    them."""
    alpha = _mask(ctx)
    h, w = alpha.shape
    rng = np.random.default_rng(ctx.seed + 71)
    pal = shades(p["colors"], 9)
    g = grain(rng, h, w)
    x0, y0, x1, y1, ph = _figure(alpha)
    out = a.copy()
    inside = (alpha > 0.5).astype(np.float32)
    faces = np.zeros((h, w), np.float32)
    for fx, fy, fr in ctx.scene.faces:  # faces stay untouched
        cv2.circle(faces, (int(fx * w), int(fy * h - fr * w * 0.1)), int(fr * w * 1.3), 1.0, -1)
    faces = cv2.GaussianBlur(faces, (0, 0), max(2.0, ph * 0.02))
    if float(p["lost"]) > 0:
        # how far inside the outline each pixel is; edges are lost where noise says so, more at the bottom
        depth = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5) / ph
        noise = fractal(rng, h, w, ph * 0.12, 4)
        low = np.clip((np.arange(h, dtype=np.float32)[:, None] - y0) / max(ph, 1), 0, 1)  # 0 top, 1 feet
        # only in patches (where the noise is high), more toward the feet; never a rim all round
        reach = 0.06 * np.clip(noise - 0.58, 0, 1) * 2.4 * (0.3 + low) * float(p["lost"])
        lost = np.clip((reach - depth) / np.maximum(reach, 1e-4), 0, 1) * inside * (reach > 0.004)
        lost = ragged(rng, lost, 0.35, max(2.0, ph * 0.01)) * lost.astype(bool) * (1 - faces)
        # lost into what is around them (the painted background), not into a white outline
        bg = (alpha < 0.05).astype(np.float32)
        sigma = max(3.0, ph * 0.03)
        around = cv2.GaussianBlur(a * bg[..., None], (0, 0), sigma) / np.maximum(cv2.GaussianBlur(bg, (0, 0), sigma),
                                                                                 1e-3)[..., None]
        out = out * (1 - lost[..., None] * 0.85) + around * (lost[..., None] * 0.85)
    if float(p["cross"]) > 0:
        ring = cv2.morphologyEx(inside.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        ys, xs = np.nonzero(ring)
        for _ in range(int(14 * float(p["cross"]))) if len(xs) else []:
            k = rng.integers(len(xs))
            r = ph * rng.uniform(0.04, 0.1)
            b = blob(rng, h, w, xs[k], ys[k], r, rough=0.6, stretch=rng.uniform(0.8, 2.0), angle=rng.uniform(0, 180))
            if b is None:
                continue
            shape, at = b
            d = wash(rng, shape, rng.uniform(0.15, 0.35), 1.0, 0.5, 0.7, g[at]) * (1 - faces[at])
            out[at] = glaze(out[at], pal[rng.integers(len(pal))], d)
    if float(p["splatter"]) > 0:
        for _ in range(int(90 * float(p["splatter"]))):
            x, y = rng.uniform(x0, x1), rng.uniform(y0 + ph * 0.25, y1)
            if inside[int(y), int(x)] < 0.5 or faces[int(y), int(x)] > 0.2:
                continue
            r = ph * rng.uniform(0.002, 0.008) * (1 + rng.pareto(3.0))
            b = blob(rng, h, w, x, y, r, rough=0.2)
            if b is None:
                continue
            shape, at = b
            out[at] = paint(out[at], pal[rng.integers(len(pal))], wash(rng, shape, rng.uniform(0.5, 0.85), 0.0, 0.1, 0.2,
                                                                     g[at]), shape, 0.4)
    return np.clip(out, 0, 1).astype(np.float32)
