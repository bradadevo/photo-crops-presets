"""Field sets: the player put on a real-looking field at night (or dusk, or a gray day), the way a
sideline portrait is lit and shot. Not floating lights or poles: the ground is the set.

Everything is built in the field's own measurements (meters) and seen through a camera that matches
the photo, so it lines up with the player:
- the camera: the horizon is where the photo's own field ended (or low, at the knees, for a
  ground-level look), and the player's height in the frame gives the scale (pixels per meter);
- the ground: turf sampled at its true size at every distance (fine near the feet, smooth far
  away), lit in a pool around the player and falling off into the dark;
- the lines: soccer and football markings at their real widths (12 cm soccer, 10 cm football),
  drawn on the ground in perspective, so a line toward the camera narrows into the distance;
- the focus: sharp at the player's distance, softer in front and behind, like a fast lens;
- the feet: a contact shadow, a darker hollow right under the shoes and a few blades of grass in
  front of the soles, so they stand in the turf instead of on top of it;
- behind the field: a dark stadium shape (press box, stands, a wall or a tree line) against the sky,
  out of focus. No lamps, no poles.

Made at most MAKE_EDGE pixels on the long side (it is soft and dark), then scaled up, with fine turf
grain added at full size."""
from __future__ import annotations

import math

import cv2
import numpy as np

MAKE_EDGE = 2048


def _hex(c: str) -> np.ndarray:
    c = (c or "#000000").lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / np.maximum(np.asarray(e1) - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


# Field markings, in meters on the ground: X across the frame (0 under the player), D away from the
# camera (0 at the player's feet). Each is (kind, numbers..., width).
def _line(x0, d0, x1, d1, wd=0.12):
    return ("seg", x0, d0, x1, d1, wd)


def _arc(cx, cd, r, a0=0.0, a1=360.0, wd=0.12):
    return ("arc", cx, cd, r, a0, a1, wd)


MARKINGS = {
    "none": [],
    # a line running toward the camera right under the player, the far sideline across behind them
    "yard_line": [_line(0, -60, 0, 9.5, 0.10), _line(-80, 9.5, 80, 9.5, 0.10)],
    # a goal line across just behind the player, the field's end beyond
    "goal_line": [_line(-80, 1.2, 80, 1.2, 0.12)],
    # soccer's halfway line across behind the player, the center circle around them
    "center_circle": [_line(-80, 0.6, 80, 0.6, 0.12), _arc(0, 0.6, 9.15), _arc(0, 0.6, 0.11, wd=0.22)],
    # the corner of the penalty box: the 18-yard line across behind, its side line toward the camera
    "box_corner": [_line(-80, 3.0, 2.5, 3.0, 0.12), _line(2.5, -60, 2.5, 3.0, 0.12), _line(-80, 19.5, 80, 19.5, 0.12)],
    # football: a yard line toward the camera and the hash marks either side of it every yard
    "hash_marks": [_line(0, -60, 0, 60, 0.10)]
    + [("hash", -5.6, 0.6, 1.0, 0.10), ("hash", 5.6, 0.6, 1.0, 0.10)]
    + [_line(-80, d, 80, d, 0.10) for d in (-9.14, 9.14, 4.57, -4.57)],
    # the end zone: the goal line across in front, the end line behind
    "end_zone": [_line(-80, -1.5, 80, -1.5, 0.20), _line(-80, 9.1, 80, 9.1, 0.10), _line(0, -60, 0, -1.5, 0.10)],
    # soccer's corner: the corner arc around the player, the touchline and goal line meeting there
    "corner_arc": [_arc(-1.0, 1.0, 1.0, 270, 360), _line(-1.0, 1.0, 80, 1.0, 0.12), _line(-1.0, -60, -1.0, 1.0, 0.12)],
}

# Behind the field: what stands against the sky (drawn as dark shapes, always out of focus)
STANDS = ("press_box", "bleachers", "wall", "trees", "none")


def _wrap_blur(g: np.ndarray, s: float) -> np.ndarray:
    """A Gaussian blur that wraps around the edges (so the texture tiles), done in frequency."""
    n0, n1 = g.shape
    fy = np.fft.fftfreq(n0)[:, None]
    fx = np.fft.rfftfreq(n1)[None, :]
    k = np.exp(-2 * (math.pi * s) ** 2 * (fx ** 2 + fy ** 2))
    return np.fft.irfft2(np.fft.rfft2(g) * k, s=g.shape).astype(np.float32)


def _texture(seed: int, n: int = 512) -> list[np.ndarray]:
    """Turf: a tiling grain at 1 cm a texel (5 m across), and smaller copies for further away."""
    rng = np.random.default_rng(seed)
    t = np.zeros((n, n), np.float32)
    for s, amp in ((0.7, 1.0), (1.6, 0.7), (4.0, 0.45), (12.0, 0.3), (40.0, 0.25)):
        g = rng.standard_normal((n, n)).astype(np.float32)
        g = _wrap_blur(g, s)
        t += g / max(float(g.std()), 1e-6) * amp
    t = t / float(t.std())
    levels = [t]
    while levels[-1].shape[0] > 8:
        levels.append(cv2.resize(_wrap_blur(levels[-1], 1.0),
                                 (levels[-1].shape[1] // 2, levels[-1].shape[0] // 2), interpolation=cv2.INTER_AREA))
    return levels


def _sample(levels: list[np.ndarray], u: np.ndarray, v: np.ndarray, foot: np.ndarray) -> np.ndarray:
    """The turf grain at ground points (u, v in texels of the finest level), filtered for a pixel
    that covers foot texels (no shimmer far away)."""
    lod = np.clip(np.log2(np.maximum(foot, 1.0)), 0, len(levels) - 1.001)
    out = np.zeros(u.shape, np.float32)
    lo = np.floor(lod).astype(np.int32)
    fr = (lod - lo).astype(np.float32)
    for k in range(len(levels)):
        wk = np.where(lo == k, 1 - fr, 0) + np.where(lo == k - 1, fr, 0)
        if not wk.any():
            continue
        n = levels[k].shape[0]
        su = (np.mod(u / 2 ** k, n)).astype(np.float32)
        sv = (np.mod(v / 2 ** k, n)).astype(np.float32)
        out += cv2.remap(levels[k], su, sv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP) * wk
    return out


def _markings(marks, X, D, fx, fd, min_px: float = 0.0) -> np.ndarray:
    """How much of each pixel is painted line (0-1), antialiased for the pixel's size on the ground
    (fx meters across, fd meters in depth)."""
    cov = np.zeros(X.shape, np.float32)
    for m in marks:
        if m[0] == "hash":  # short marks across, every step meters along the field (one pattern, not 80 lines)
            _, xc, length, step, wd = m
            off = np.abs(np.mod(D + step / 2, step) - step / 2)
            dist = np.where(np.abs(X - xc) <= length / 2, off, 1e9)
            nx, nd = 0.0, 1.0
            foot = np.sqrt((nx * fx) ** 2 + (nd * fd) ** 2) + 1e-6
            wide = np.maximum(wd, min_px * foot)
            c = np.clip((wide / 2 - dist) / foot + 0.5, 0, 1) * np.minimum(1.0, wide / foot) * (wd / wide) ** 0.3
            # (far off the marks crowd together: there they fade rather than fill the turf)
            c = c * np.clip(step / (8 * fd), 0, 1)
            cov = np.maximum(cov, c.astype(np.float32))
            continue
        if m[0] == "seg":
            _, x0, d0, x1, d1, wd = m
            vx, vd = x1 - x0, d1 - d0
            L = math.hypot(vx, vd)
            ux, ud = vx / L, vd / L
            t = np.clip((X - x0) * ux + (D - d0) * ud, 0, L)
            dist = np.hypot(X - (x0 + t * ux), D - (d0 + t * ud))
            nx, nd = -ud, ux  # the normal: the line's width is measured along it
        else:
            _, cx, cd, r, a0, a1, wd = m
            ang = (np.degrees(np.arctan2(D - cd, X - cx)) + 360) % 360
            inside = ((ang >= a0) & (ang <= a1)) if a1 - a0 < 360 else np.ones(X.shape, bool)
            rr = np.hypot(X - cx, D - cd)
            dist = np.where(inside, np.abs(rr - r), 1e9)
            nx, nd = (X - cx) / np.maximum(rr, 1e-6), (D - cd) / np.maximum(rr, 1e-6)
        foot = np.sqrt((nx * fx) ** 2 + (nd * fd) ** 2) + 1e-6
        # far away a line is thinner than a pixel: it is kept at least min_px wide (dimmer), as the
        # sheen on a far line makes it read in a real photo
        wide = np.maximum(wd, min_px * foot)
        c = np.clip((wide / 2 - dist) / foot + 0.5, 0, 1) * np.minimum(1.0, wide / foot) * (wd / wide) ** 0.3
        cov = np.maximum(cov, c.astype(np.float32))
    return cov


def _stands(h, w, top_row, kind, color, seed) -> np.ndarray:
    """How much each pixel is the dark stadium shape (0 sky, 1 structure), above top_row (the field's
    far edge), sized to the room there is. Big, simple shapes: they are seen dark and out of focus."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    S = max(1.0, float(top_row))  # the rows above the field
    edge = float(top_row)
    if kind == "none":
        return np.ones((h, w), np.float32)
    if kind == "press_box":
        # stands rising behind the field (higher in the middle), a press box on top with a roof
        # overhanging and columns under it; the sky shows above and at the sides
        rng = np.random.default_rng(seed)
        cx = 0.5 + rng.uniform(-0.08, 0.08)
        stand_top = edge - (0.30 + 0.12 * np.clip(1 - np.abs(x / w - cx) / 0.6, 0, 1)) * S
        s = (y >= stand_top).astype(np.float32)
        x0, x1 = (cx - 0.30) * w, (cx + 0.30) * w
        box_top, box_bot = edge - 0.74 * S, edge - 0.50 * S
        s = np.maximum(s, ((y >= box_top) & (y <= box_bot) & (x >= x0) & (x <= x1)).astype(np.float32))
        roof = (y >= box_top - 0.035 * S) & (y < box_top) & (x >= x0 - 0.025 * w) & (x <= x1 + 0.025 * w)
        # under the box: its supports in front of a dim back wall (only a little sky shows through)
        under = ((y > box_bot) & (x >= x0) & (x <= x1)).astype(np.float32) * 0.82
        cols = (y > box_bot) & (np.mod(x - x0, (x1 - x0) / 6) < 0.012 * w) & (x >= x0) & (x <= x1 + 0.012 * w)
        return np.clip(np.maximum(np.maximum(s, under), roof.astype(np.float32)) + cols, 0, 1).astype(np.float32)
    if kind == "bleachers":
        # stands with a top sloping down to the sides, a rail along the top
        slope = edge - (0.55 - 0.25 * np.abs(x / w - 0.5) * 2) * S
        s = (y >= slope).astype(np.float32)
        rail = np.abs(y - (slope - 0.07 * S)) < max(1.0, 0.008 * S)
        posts = (np.mod(x, 0.06 * w) < max(1.0, 0.004 * w)) & (y > slope - 0.07 * S) & (y < slope)
        return np.clip(s + rail + posts, 0, 1).astype(np.float32)
    if kind == "wall":
        return (y >= edge - 0.30 * S).astype(np.float32)
    if kind == "trees":
        from photo_presets.backgrounds import noise
        crown = noise(1, w, seed, 6, 6)[0] * 0.25 + noise(1, w, seed + 1, 3, 40)[0] * 0.08
        return (y >= edge - (0.35 + crown[None, :]) * S).astype(np.float32)
    return np.zeros((h, w), np.float32)


def _depth_blur(img: np.ndarray, amount: np.ndarray, top: float) -> np.ndarray:
    """Out of focus by amount (0-1 per pixel, 1 = top pixels of blur): a few blurred copies,
    blended (a lens blur's look for soft, dark scenes)."""
    stops = [0.0, 0.12, 0.3, 0.6, 1.0]
    copies = [img if s == 0 else cv2.GaussianBlur(img, (0, 0), max(0.3, s * top)) for s in stops]
    a = np.clip(amount, 0, 1)
    out = np.zeros_like(img)
    for i in range(len(stops) - 1):
        lo, hi = stops[i], stops[i + 1]
        t = np.clip((a - lo) / (hi - lo), 0, 1)
        inside = ((a >= lo) & (a <= hi)) if i else (a <= hi)
        wt = np.where(inside, 1.0, 0.0).astype(np.float32)[..., None]
        out += (copies[i] * (1 - t[..., None]) + copies[i + 1] * t[..., None]) * wt
    # (pixels exactly on a stop are counted twice; normalize)
    count = np.zeros(a.shape, np.float32)
    for i in range(len(stops) - 1):
        lo, hi = stops[i], stops[i + 1]
        count += (((a >= lo) & (a <= hi)) if i else (a <= hi)).astype(np.float32)
    return out / np.maximum(count, 1)[..., None]


def feet_of(alpha: np.ndarray, scene) -> tuple[float, float, float]:
    """The main player's feet (x, y) and height, in pixels: the lowest solid part of the cut-out
    under the player the scene found (feet, a knee or a shin on the ground)."""
    h, w = alpha.shape
    if scene is not None and getattr(scene, "feet", None):
        fx, fy, ph = scene.feet[0] * w, scene.feet[1] * h, scene.subject_height * h
    else:
        fx, fy, ph = w / 2, h * 0.95, h * 0.7
    # the cut-out's lowest row near that point is the truth (the box can stop short)
    x0, x1 = int(max(0, fx - 0.4 * ph)), int(min(w, fx + 0.4 * ph))
    rows = np.nonzero((alpha[:, x0:x1] > 0.5).any(1))[0]
    if len(rows):
        fy = float(rows.max())
        cols = np.nonzero(alpha[max(0, int(fy) - int(0.05 * ph)):int(fy) + 1, x0:x1] > 0.5)[1]
        if len(cols):
            fx = x0 + float(np.median(cols))
    return fx, fy, max(ph, 0.05 * h)


def _camera(h, w, fy, ph, V, st):
    """The camera that matches the photo: focal length (pixels), the player's distance and the camera's
    height (meters), from the horizon row V and the player's height in the frame."""
    q = ph / st["player_m"]  # pixels per meter at the player
    f = w / (2 * math.tan(math.radians(st["fov"]) / 2))
    return f, f / q, max(0.05, (fy - V) / q)


def _ground_coords(yy, xx, w, fx, V, f, Zp, Hc):
    """Ground meters for pixels below the horizon: X across (0 under the player), D away from the
    camera (0 at the player), and the meters one pixel covers across and in depth."""
    below = yy > V + 0.5
    Z = np.where(below, f * Hc / np.maximum(yy - V, 0.5), 1e6).astype(np.float32)
    X = (xx - w / 2) * Z / f - (fx - w / 2) * Zp / f
    return below, Z, X, Z - Zp, Z / f, Z * Z / (f * Hc)


def _behind(hs, ws, k, h, edge, st, seed) -> np.ndarray:
    """Sky and the stadium's dark shape over the field's far edge (edge: full-size row per column)."""
    yy = (np.arange(hs, dtype=np.float32)[:, None] + 0.5) / k
    top = float(np.min(edge))
    t = np.clip(yy / max(top, 1), 0, 1)
    sky = _hex(st["sky_top"]) + (_hex(st["sky_low"]) - _hex(st["sky_top"])) * (t ** st["sky_curve"])[..., None]
    sky = np.broadcast_to(sky, (hs, ws, 3)).copy()
    shape = _stands(hs, ws, float(np.median(edge)) * k, st["stands"], st["stand_color"], seed)
    # the structure is not flat black: faint rows of seats and a lighter top edge where the sky lights it
    yk = np.arange(hs, dtype=np.float32)[:, None]
    rows = 0.5 + 0.5 * np.cos(yk / max(2.0, 0.011 * hs) * 2 * math.pi)
    spill = np.clip(1 - (float(np.median(edge)) * k - yk) / max(1.0, 0.5 * float(np.median(edge)) * k), 0, 1) ** 2
    stand = _hex(st["stand_color"]) * (1 + 0.5 * rows[..., None] * st["seat_rows"]) + _hex(st["sky_low"]) * (0.10 * spill)[..., None]
    top_edge = np.clip(shape - cv2.GaussianBlur(shape, (0, 0), max(1.0, 0.006 * hs)), 0, 1)
    out = sky * (1 - shape[..., None]) + stand * shape[..., None] + _hex(st["sky_low"]) * (top_edge * 0.35)[..., None]
    if st["windows"] and st["stands"] == "press_box":
        e = float(np.median(edge)) * k
        band = ((yk > e - 0.56 * hs) & (yk < e - 0.51 * hs)).astype(np.float32)
        xs = np.arange(ws, dtype=np.float32)[None, :]
        band = band * ((xs > 0.22 * ws) & (xs < 0.78 * ws)) * (0.6 + 0.4 * (np.mod(xs, 0.05 * ws) > 0.006 * ws))
        out = out + _hex(st["window_color"]) * (band * st["windows"])[..., None]
    return cv2.GaussianBlur(out.astype(np.float32), (0, 0), max(1.0, st["blur"] * ws))


def _grass_below(img: np.ndarray, a: np.ndarray) -> bool:
    """Whether the photo stands on grass (most of the bottom of the background is green)."""
    small = cv2.resize(img, (160, max(8, round(160 * img.shape[0] / img.shape[1]))), interpolation=cv2.INTER_AREA)
    sa = cv2.resize(a, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor((np.clip(small, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    low = slice(int(small.shape[0] * 0.75), None)
    green = (hsv[low][..., 0] >= 28) & (hsv[low][..., 0] <= 92) & (hsv[low][..., 1] >= 40)
    bg = sa[low] < 0.3
    return bool(bg.sum() > 20 and (green & bg).sum() / bg.sum() > 0.5)


def others(img: np.ndarray, alpha: np.ndarray, scene) -> np.ndarray | None:
    """Everyone who isn't in the cut-out (and the shadow at their feet), to take off the field."""
    pm = getattr(scene, "people_mask", None)
    if pm is None:
        return None
    h, w = alpha.shape
    m = cv2.resize(pm.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
    m &= cv2.dilate((alpha > 0.3).astype(np.uint8), np.ones((5, 5), np.uint8)) == 0
    if m.sum() < 0.0005 * h * w:
        return None
    r = max(3, int(0.012 * max(h, w)))
    grown = cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    # their shadows lie at their feet: reach a little further down and sideways there
    down = cv2.dilate(grown, np.ones((r * 2, r * 4), np.uint8), anchor=(r * 2, 0))
    keep_off = cv2.dilate((alpha > 0.05).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return ((grown | down) > 0) & ~keep_off


def build(img: np.ndarray, alpha: np.ndarray, scene, style: dict, seed: int = 7,
          horizon: np.ndarray | None = None, clean: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """The set behind the player, at the photo's size: (picture, geometry). horizon: the row where the
    photo's own field ends, for each column (None: no far edge in the photo)."""
    st = {**DEFAULT, **style}
    h, w = img.shape[:2]
    fx, fy, ph = feet_of(alpha, scene)
    real = st["ground"] == "photo" and _grass_below(img, alpha)
    if real and horizon is not None:
        xs_ = np.arange(len(horizon), dtype=np.float32)
        slope, icpt = np.polyfit(xs_, horizon.astype(np.float64), 1)
        slope = float(np.clip(slope, -st["max_tilt"], st["max_tilt"]))
        mid = float(np.median(horizon))
        edge = (mid + slope * (xs_ - len(xs_) / 2)).astype(np.float32)
        edge = np.minimum(edge, fy - 0.02 * ph)
        V = float(np.median(edge)) - 0.01 * h
    elif real:  # the field fills the frame: the camera looks down on it
        edge, V = None, fy - st["high_horizon"] * ph
    else:  # no field in the photo: a field made here, seen from low down
        V = fy - st["low_horizon"] * ph
        edge = None
    f, Zp, Hc = _camera(h, w, fy, ph, V, st)
    if not real:
        edge = np.full((w,), V + f * Hc / (Zp + st["field_depth"]), np.float32)

    k = min(1.0, MAKE_EDGE / max(h, w))
    hs, ws = max(8, round(h * k)), max(8, round(w * k))
    ys, xs = np.mgrid[0:hs, 0:ws].astype(np.float32)
    yy, xx = (ys + 0.5) / k, (xs + 0.5) / k
    below, Z, X, D, fxm, fdm = _ground_coords(yy, xx, w, fx, V, f, Zp, Hc)
    fxm, fdm = fxm / k, fdm / k

    # the light on the ground: a pool around the player, falling off into the dark
    rx, rd = st["pool"]
    pool = np.exp(-((X / rx) ** 2) - (((D + 0.2 * rd) / rd) ** 2)).astype(np.float32)
    light = np.where(below, st["ambient"] + (1 - st["ambient"]) * pool, st["ambient"]).astype(np.float32)
    # markings are laid out for a frame about 10 m across at the player; a tight telephoto frame shows
    # less field, so they move in with it (the viewer judges lines by the frame, not by meters)
    span = np.clip((w / (f / Zp)) / 10.0, 0.35, 2.5)
    # depth is squeezed by a long lens seen from low down: 10 m behind the player is laid halfway
    # (in the picture) from the feet to the field's far edge, so lines behind them show
    far_row = float(np.median(edge)) if edge is not None else V + 0.25 * (fy - V)
    mid = (fy + far_row) / 2
    span_d = float(np.clip((f * Hc / max(mid - V, 1.0) - Zp) / 10.0, span, 8.0))
    paint = _markings(MARKINGS.get(st["lines"], []), X / span, D / span_d, fxm / span, fdm / span_d,
                      min_px=st["line_min_px"] * k) * below
    if edge is not None:
        e = cv2.resize(edge[None, :].astype(np.float32), (ws, 1), interpolation=cv2.INTER_LINEAR)[0][None, :]
        field = _smooth(e - 0.003 * h, e + 0.003 * h, yy)  # 1 on the field, 0 behind it
        haze = np.exp(-((yy - e) / max(2.0, st["haze_width"] * h)) ** 2).astype(np.float32) * st["haze"]
    else:
        e, field, haze = None, np.ones((hs, ws), np.float32), np.zeros((hs, ws), np.float32)
    # grazing back light: the turf lifts toward the far edge, the lines most (they shine)
    back = (np.exp(-((yy - (e if e is not None else 0)) / max(2.0, 0.06 * h)) ** 2) * (yy > (e if e is not None else 0))
            ).astype(np.float32) * st["backlight"] if e is not None else np.zeros((hs, ws), np.float32)

    if real:
        small = cv2.resize(img, (ws, hs), interpolation=cv2.INTER_AREA)
        ground = None  # (the photo's own grass, at full size, below)
    else:
        levels = _texture(seed)
        grain = _sample(levels, X / 0.01, D / 0.01, np.maximum(fxm, fdm * 0.35) / 0.01)
        turf = _hex(st["turf"]) * (1 + st["grain"] * 0.16 * grain[..., None])
        ground = turf * (1 - paint[..., None] * 0.92) + _hex(st["line_color"]) * (paint[..., None] * 0.92)
        ground = ground * light[..., None]
    behind = _behind(hs, ws, k, h, edge if edge is not None else np.full((w,), -1.0, np.float32), st, seed)

    up = (lambda m: cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)) if k < 1 else (lambda m: m)
    field_f, haze_f, back_f, light_f, paint_f = up(field), up(haze), up(back), up(light), up(paint)
    behind_f = up(behind)
    if real:
        g = (clean if clean is not None else img) * _hex(st["ground_tint"])
        lum = g[..., 0] * 0.299 + g[..., 1] * 0.587 + g[..., 2] * 0.114
        g = lum[..., None] + (g - lum[..., None]) * st["ground_sat"]
        # added lines are painted onto this grass: white, carrying the grass's own texture
        tex = np.clip(lum / max(float(np.median(lum)), 1e-3), 0.6, 1.4)[..., None]
        g = g * (1 - paint_f[..., None] * 0.9) + _hex(st["line_color"]) * tex * 0.8 * (paint_f[..., None] * 0.9)
        # painted lines catch more of the light than the grass around them (they read further out)
        g = g * (light_f * (1 - paint_f) + np.sqrt(light_f) * paint_f)[..., None]
    else:
        g = up(ground)
    g = g + _hex(st["back_color"]) * (back_f * (0.06 + 0.5 * paint_f))[..., None]
    pic = behind_f * (1 - field_f[..., None]) + g * field_f[..., None]
    pic = pic + _hex(st["back_color"]) * haze_f[..., None] * 0.4
    if st["fog"]:  # haze in the air: more with distance, all of it over the stands
        Dm = np.where(below, D, 1e3).astype(np.float32)
        deep = np.clip((Dm + 4) / st["fog_depth"], 0, 1)
        deep = up(np.where(field > 0.5, deep, 1.0).astype(np.float32))
        pic = pic + (_hex(st["fog_color"]) - pic) * (st["fog"] * deep)[..., None]
    geo = {"fx": fx, "fy": fy, "ph": ph, "V": V, "f": f, "Hc": Hc, "Zp": Zp, "real": real}
    return np.clip(pic, 0, 1).astype(np.float32), geo


DEFAULT = {
    "camera": "photo",      # "photo": the horizon where the photo's field ended; "low": at the knees
    "low_horizon": 0.04,    # for "low": the horizon this share of the player's height above the feet
    "player_m": 1.75,       # a player's height (m): sets the scale
    "fov": 14.0,            # the lens's angle across the frame (degrees): a sideline telephoto
    "field_depth": 12.0,    # meters of field behind the player before the dark
    "turf": "#2f6a2c", "grain": 1.0, "stripes": 0.0, "stripe_amount": 0.12,
    "lines": "yard_line", "line_color": "#eef2f3", "line_min_px": 2.2,
    "pool": (7.0, 7.0),     # the light pool on the ground (m across, m deep)
    "ambient": 0.12,        # light on the ground outside the pool (0-1)
    "backlight": 0.6, "back_color": "#bcd7ff",
    "sky_top": "#0a1a33", "sky_low": "#2b5f9c", "sky_curve": 1.4,
    "stands": "press_box", "stand_color": "#070b14", "windows": 0.0, "window_color": "#8fb4e8", "seat_rows": 0.5,
    "max_tilt": 0.03,       # the far edge's most tilt (a detected edge steeper than this is a mistake)
    "ground": "photo",      # "photo": the photo's own grass, relit; "made": turf made here
    "ground_tint": "#e6f0ff", "ground_sat": 0.85,
    "high_horizon": 1.1,    # a field filling the frame: the horizon this many player heights above the feet
    "haze": 0.5, "haze_width": 0.012,
    "fog": 0.0, "fog_color": "#4a5668", "fog_depth": 30.0,
    "dof": 1.6,             # how quickly the ground goes soft in front and behind
    "blur": 0.011,          # how out of focus the stadium is (share of the width)
}


def place(img: np.ndarray, alpha: np.ndarray, scene, style: dict, seed: int = 7,
          horizon: np.ndarray | None = None, clean: np.ndarray | None = None) -> np.ndarray:
    """The player (img where alpha is 1) on the field set: standing in the turf, lit from behind."""
    from photo_presets import backgrounds
    from photo_presets.effects import _ground_shadow
    st = {**DEFAULT, **style}
    h, w = img.shape[:2]
    a = np.clip(alpha, 0, 1).astype(np.float32)
    bg, geo = build(img, a, scene, st, seed, horizon, clean)
    fx, fy, ph = geo["fx"], geo["fy"], geo["ph"]
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    # the shadows: a soft one spread along the ground, and a dark hollow right where they touch it
    sh = _ground_shadow(a, h, w)
    if sh is not None:
        bg = bg * (1 - st["shadow"] * 0.85 * sh)[..., None]
    if fy < h * 0.985:
        low = (a > 0.5) & (yy > fy - 0.03 * ph)
        touch = cv2.GaussianBlur(low.astype(np.float32), (0, 0), max(1.0, 0.012 * ph), sigmaY=max(0.7, 0.004 * ph))
        touch = np.clip(touch * 2.5, 0, 1) * (yy >= fy - 0.01 * ph) * (1 - a)
        bg = bg * (1 - 0.75 * st["shadow"] * touch)[..., None]
    out = backgrounds.compose(img * (2 ** st["player_stops"]), a, bg, match=st["match"], wrap=st["wrap"], shadow=0.0)
    # light from behind on the player's edges (the rim a back light gives), most on the top and sides
    if st["rim"]:
        inner = cv2.GaussianBlur(a, (0, 0), max(1.0, 0.006 * ph))
        rim = np.clip((a - inner) * 3.0, 0, 1) * a
        up = np.clip(1.15 - (yy - (fy - ph)) / max(ph, 1) * 0.6, 0.35, 1)
        out = out + _hex(st["back_color"]) * (rim * up * st["rim"])[..., None] * 0.55
    # blades of turf in front of the soles (only where they meet the ground, and only near the focus)
    if fy < h * 0.985 and st["blades"]:
        rng = np.random.default_rng(seed + 11)
        tall = rng.random(w).astype(np.float32) ** 3 * (0.022 * ph) * st["blades"]
        tall = np.minimum(tall, cv2.GaussianBlur(tall[None, :], (0, 0), 0.6)[0] * 1.8)
        lowest = np.where((a > 0.5).any(0), h - 1 - np.argmax((a > 0.5)[::-1], axis=0), -1).astype(np.float32)
        on = (lowest > fy - 0.04 * ph) & (lowest >= 0)
        cover = ((yy > lowest[None, :] - tall[None, :]) & on[None, :] & (yy <= lowest[None, :] + 1)).astype(np.float32)
        cover = cv2.GaussianBlur(cover, (0, 0), 0.6) * a
        out = out * (1 - cover[..., None]) + bg * cover[..., None]
    return np.clip(out, 0, 1).astype(np.float32)


DEFAULT.update({"player_stops": 0.0, "match": 0.2, "wrap": 0.25, "rim": 0.5, "shadow": 1.0, "blades": 1.0})

# The field looks: a one-line description, then the set (anything not given is DEFAULT's).
# Lines work for both soccer and football unless the name says otherwise.
BLUE_HOUR = {"sky_top": "#071630", "sky_low": "#2d63a3"}
NIGHT = {"sky_top": "#020408", "sky_low": "#16233a", "back_color": "#a9c4f0", "ambient": 0.08}
LOOKS: dict[str, tuple[str, dict]] = {
    "Kneel Line": ("Blue-hour sky over a dark press box, a white line running out from under the player",
                   {**BLUE_HOUR, "lines": "yard_line"}),
    "Goal Line Night": ("Night: a goal line across the turf just behind the player, the stands lost in the dark",
                        {**NIGHT, "lines": "goal_line", "stands": "wall"}),
    "Center Circle": ("Soccer's halfway line and center circle around the player, stands at dusk",
                      {**BLUE_HOUR, "lines": "center_circle", "stands": "bleachers", "pool": (9.0, 8.0)}),
    "Box Corner": ("The corner of the penalty box behind the player, a press box against a sunset",
                   {"sky_top": "#1b1f3d", "sky_low": "#c9744a", "back_color": "#ffd2a8", "lines": "box_corner",
                    "ground_tint": "#fff0e0"}),
    "Hash Marks": ("Football: a yard line under the player with the hash marks, a lit press box at night",
                   {**NIGHT, "lines": "hash_marks", "pool": (8.0, 8.0)}),
    "End Zone": ("Football: the goal line in front, the end line behind, steel-gray night",
                 {"sky_top": "#0b0d10", "sky_low": "#3b4450", "back_color": "#d8dee6", "lines": "end_zone",
                  "stands": "wall", "ground_sat": 0.7}),
    "Corner Arc": ("Soccer's corner arc around the player, the touchline meeting the goal line, trees at twilight",
                   {"sky_top": "#0c1a2e", "sky_low": "#4f6f93", "lines": "corner_arc", "stands": "trees"}),
    "Sideline Haze": ("Night with haze in the air: the stands fade into it, a line running out from the player",
                      {**NIGHT, "lines": "yard_line", "fog": 0.35, "fog_color": "#56657c", "haze": 0.8}),
    "Golden Field": ("Golden hour: a warm sky low behind a tree line, the pitch in late sun",
                     {"sky_top": "#33527a", "sky_low": "#f0b26a", "back_color": "#ffcf96", "stands": "trees",
                      "lines": "none", "ambient": 0.55, "ground_tint": "#fff1dc", "ground_sat": 1.0, "haze": 0.35}),
    "Blackout": ("Pure black around the player: only the turf at their feet and one line are lit",
                 {"sky_top": "#000000", "sky_low": "#040506", "stands": "none", "lines": "yard_line",
                  "ambient": 0.02, "pool": (4.5, 4.0), "haze": 0.0, "backlight": 0.2}),
    "Midfield Night": ("Night: the halfway line across under the player's feet, the center spot, stands above",
                       {**NIGHT, "lines": "center_circle", "stands": "press_box", "pool": (6.0, 5.0)}),
}


def clutter(img: np.ndarray, alpha: np.ndarray, horizon: np.ndarray | None, fy: float) -> np.ndarray | None:
    """Things lying on the field between its far edge and the player (a goal's wheels, bags, cones):
    blobs that are neither grass nor a white line."""
    if horizon is None:
        return None
    h, w = alpha.shape
    hsv = cv2.cvtColor((np.clip(img, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    H, Sat, Val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (H >= 25) & (H <= 95) & (Sat >= 35)
    white = (Sat < 50) & (Val > 170)
    yy = np.arange(h)[:, None]
    band = (yy > horizon[None, :] - 0.01 * h) & (yy < max(float(np.median(horizon)) + 0.02 * h, fy - 0.02 * h))
    m = (~green & ~white & band & (alpha < 0.05)).astype(np.uint8)
    r = max(1, int(0.003 * max(h, w)))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2 * r + 1, 2 * r + 1), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros((h, w), bool)
    for i in range(1, n):
        if stats[i, 4] >= (0.004 * max(h, w)) ** 2:
            keep |= lab == i
    if not keep.any():
        return None
    g = max(3, int(0.012 * max(h, w)))
    return cv2.dilate(keep.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1))) > 0


def cleaned(img: np.ndarray, alpha: np.ndarray, scene, horizon: np.ndarray | None = None) -> np.ndarray | None:
    """The empty field: the photo with everyone taken out (LaMa, on this Mac). The players in the
    cut-out go back on top; the ground filled in behind them is for their edges."""
    m = others(img, alpha, scene)
    h, w = alpha.shape
    r = max(2, int(0.004 * max(h, w)))
    body = cv2.dilate((alpha > 0.05).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    m = body if m is None else (m | body)  # (the players too: the ground behind them, for their edges)
    c = clutter(img, alpha, horizon, feet_of(alpha, scene)[1])
    if c is not None:
        m = m | c
    from photo_presets import retouch
    u8 = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    out, _ = retouch.fill(u8, m)
    return out.astype(np.float32) / 255


_KEPT: "OrderedDict[str, np.ndarray | None]" = None  # type: ignore[assignment]
_KEPT_BYTES = 600 * 2 ** 20
_lock = None


def cleaned_kept(img: np.ndarray, alpha: np.ndarray, scene, horizon: np.ndarray | None = None) -> np.ndarray | None:
    """cleaned(), remembered by the picture itself (a small copy of it and of the cut-out, and its size):
    every field look of a photo starts from the same picture, so LaMa runs once a photo and size, also
    for the looks made ahead. Kept in memory, the newest 600 MB (8 bits)."""
    global _KEPT, _lock
    import hashlib
    import threading
    from collections import OrderedDict
    if _KEPT is None:
        _KEPT, _lock = OrderedDict(), threading.Lock()
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA) * 255).astype(np.uint8).tobytes())
    h.update(np.ascontiguousarray(cv2.resize(alpha, (64, 64), interpolation=cv2.INTER_AREA) * 255).astype(np.uint8).tobytes())
    h.update(repr((img.shape, None if horizon is None else round(float(np.median(horizon)), 1))).encode())
    key = h.hexdigest()
    with _lock:
        if key in _KEPT:
            _KEPT.move_to_end(key)
            kept = _KEPT[key]
            return None if kept is None else kept.astype(np.float32) / 255
    clean = cleaned(img, alpha, scene, horizon)
    kept = None if clean is None else (np.clip(clean, 0, 1) * 255 + 0.5).astype(np.uint8)
    with _lock:
        _KEPT[key] = kept
        while len(_KEPT) > 1 and sum(v.nbytes for v in _KEPT.values() if v is not None) > _KEPT_BYTES:
            _KEPT.popitem(last=False)
    return clean
