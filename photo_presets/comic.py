"""Comic illustration of the players, drawn by AI on this Mac (free, no paid service).

The players (from their cut-out) are redrawn as a comic illustration by
Stable Diffusion 1.5 with a ControlNet line-art model: it starts from the
look so far (its colors), and follows the photo's own outlines (traced here),
so the pose, the kit and the face stay the photo's while the shading, ink and
highlights become drawn. The drawing is made at 768 px and enlarged with
Real-ESRGAN's illustration model (crisp lines at full size), then laid back in
along the cut-out. Faces can keep some of the look underneath ("face"), so
the player stays recognizable.

The models (about 3 GB, CreativeML OpenRAIL-M and Apache / BSD licenses, free
for commercial use) download once on first use. It takes about 15 s per
photo. Without them, or without a cut-out, the step is skipped with a note.
"""

import cv2
import numpy as np
from PIL import Image

from photo_presets.pipeline import Context, MissingAsset, op, face_mask

BASE = "stable-diffusion-v1-5/stable-diffusion-v1-5"
LINEART = "lllyasviel/control_v11p_sd15_lineart"
UPSCALER = "RealESRGAN_x4plus_anime_6B.pth"
UPSCALER_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/" + UPSCALER
EDGE = 768  # the drawing's long edge
DETAIL_EDGE = 512  # the face, ball and hand passes
PAD = 0.08  # room around the players, as a share of their size
PROMPT = ("highly detailed neon comic illustration of a young athlete, bold black ink outlines, cel shading, "
          "glowing neon rim light, vivid cyan, hot pink, orange and yellow, airbrushed highlights, graphic novel "
          "art, digital painting, black background")
NEGATIVE = ("photo, photorealistic, blurry, noisy, text, letters, writing, watermark, signature, artist name, "
            "deformed, extra limbs, extra ball, bad anatomy, bad hands, extra fingers, ugly face, distorted face, "
            "different person, blood, red marks on face")
FACE_REACH = 3.4  # a face pass covers this many face radii across (hair to chin)

_pipes: dict = {}
_upscaler = None


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _pipeline(base: str = BASE):
    if base not in _pipes:
        import torch
        from diffusers import ControlNetModel, StableDiffusionControlNetImg2ImgPipeline, UniPCMultistepScheduler
        from diffusers.utils import logging
        logging.set_verbosity_error()
        dtype = torch.float16 if _device() == "mps" else torch.float32
        cn = ControlNetModel.from_pretrained(LINEART, torch_dtype=dtype)
        try:
            pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
                base, controlnet=cn, torch_dtype=dtype, variant="fp16", safety_checker=None,
                requires_safety_checker=False)
        except (OSError, ValueError):  # a model published without half-size weights
            pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
                base, controlnet=cn, torch_dtype=dtype, safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
        pipe = pipe.to(_device())
        pipe.enable_attention_slicing()
        pipe.set_progress_bar_config(disable=True)
        _pipes[base] = pipe
    return _pipes[base]


def _upscale_model():
    global _upscaler
    if _upscaler is None:
        import spandrel
        from photo_crops.people import CACHE_DIR
        path = CACHE_DIR / UPSCALER
        if not path.exists():
            import urllib.request
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(UPSCALER_URL, path)
        _upscaler = spandrel.ModelLoader().load_from_file(str(path)).to(_device()).eval()
    return _upscaler


def upscale(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """A drawing (floats 0-1) at size (w, h): enlarged 4x by the illustration
    model when it grows, then fitted with plain resizing."""
    h, w = img.shape[:2]
    if size[0] > w * 1.3:
        try:
            import torch
            with torch.no_grad():
                x = torch.from_numpy(np.ascontiguousarray(img)).permute(2, 0, 1)[None].to(_device())
                img = _upscale_model()(x)[0].permute(1, 2, 0).clamp(0, 1).float().cpu().numpy()
        except Exception:  # without the upscaler, plain enlarging still works
            pass
    interp = cv2.INTER_AREA if img.shape[1] > size[0] else cv2.INTER_LANCZOS4
    return np.clip(cv2.resize(img, size, interpolation=interp), 0, 1).astype(np.float32)


def line_art(photo: np.ndarray, alpha: np.ndarray | None = None, detail: float = 1.0) -> np.ndarray:
    """The photo's outlines as white lines on black (what the line-art model
    follows): around and inside the players when their cut-out is given.
    Lower detail keeps only the main shapes (folds, limbs, face), so the model
    draws them in its style instead of copying the photo's texture."""
    g = cv2.cvtColor((np.clip(photo, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    calm = 1 + 2 * (1 - detail)
    g = cv2.bilateralFilter(g, int(7 * calm) | 1, 40 * calm, 7 * calm)
    edges = cv2.Canny(g, 40 + 50 * (1 - detail), 110 + 90 * (1 - detail))
    dog = cv2.GaussianBlur(g, (0, 0), 1.0).astype(np.float32) - cv2.GaussianBlur(g, (0, 0), 2.2)
    lines = np.maximum(edges, ((dog < -3 - 6 * (1 - detail)) * 255).astype(np.uint8))
    if alpha is None:
        return lines
    inside = (alpha > 0.5).astype(np.uint8)
    ring = cv2.morphologyEx(inside, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) * 255
    near = cv2.dilate((alpha > 0.3).astype(np.uint8), np.ones((9, 9), np.uint8))
    return np.maximum(lines, ring) * near


def players_box(alpha: np.ndarray, pad: float = PAD) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(alpha > 0.5)
    if not len(xs):
        return None
    h, w = alpha.shape
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    m = int(pad * max(x1 - x0, y1 - y0))
    return max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m)


def _draw(pipe, look: np.ndarray, photo: np.ndarray, alpha: np.ndarray | None, p: dict,
          strength: float | None = None, edge: int = EDGE, steps: int | None = None) -> np.ndarray:
    """One part of the picture (floats 0-1) drawn: starting from the look,
    following the photo's outlines; returned at the part's own size."""
    import torch
    ch, cw = look.shape[:2]
    s = edge / max(cw, ch)
    tw, th = max(64, int(cw * s) // 8 * 8), max(64, int(ch * s) // 8 * 8)
    small = lambda arr: cv2.resize(arr, (tw, th), interpolation=cv2.INTER_AREA)  # noqa: E731
    init = Image.fromarray((np.clip(small(look), 0, 1) * 255).astype(np.uint8))
    lines = line_art(small(photo), None if alpha is None else small(alpha), float(p["detail"]))
    gen = torch.Generator("cpu").manual_seed(int(p["seed"]))  # the same drawing every time
    drawn = pipe(p["prompt"] or PROMPT, image=init, control_image=Image.fromarray(np.stack([lines] * 3, -1)),
                 strength=float(p["strength"] if strength is None else strength),
                 num_inference_steps=int(steps or p["steps"]), guidance_scale=7.0,
                 controlnet_conditioning_scale=float(p["lines"]), negative_prompt=NEGATIVE,
                 generator=gen).images[0]
    return upscale(np.asarray(drawn, np.float32) / 255, (cw, ch))


@op("comic_redraw", cutout=True, label="AI illustration of the players (drawn on this Mac)", strength=0.7,
    lines=0.9, face=0.0, steps=25, prompt="", seed=7, spill=0.0, face_pass=0.45, detail=1.0, model=BASE,
    real_face=0.0, face_style="paint", inset=0.003)
def comic_redraw(a, p, ctx: Context):
    """Redraws the players in the prompt's style (see the module notes).
    spill lets the drawing reach past their outline (a share of their size),
    for painted or sketched edges on a plain background."""
    box = players_box(ctx.alpha) if ctx.alpha is not None else None
    if box is None:
        raise MissingAsset("no player cut-out in this photo")
    try:
        pipe = _pipeline(p["model"] or BASE)
    except Exception as e:  # not installed, offline on first use...
        raise MissingAsset(f"the drawing model could not load ({type(e).__name__})") from e
    original = ctx.original if ctx.original is not None else a
    x0, y0, x1, y1 = box
    alpha = ctx.alpha[y0:y1, x0:x1]
    drawn = _match_background(_draw(pipe, a[y0:y1, x0:x1], original[y0:y1, x0:x1], alpha, p), a[y0:y1, x0:x1], alpha)
    # the drawing stops just inside the outline: models draw their own pale contour there (a halo);
    # the outermost pixels come from the look underneath, whose edge colors are already clean
    inset = max(1, int(round(float(p["inset"]) * max(alpha.shape))))
    keep = cv2.erode(alpha, np.ones((2 * inset + 1, 2 * inset + 1), np.uint8))
    keep = cv2.GaussianBlur(keep, (0, 0), max(0.7, inset * 0.5))
    spill = float(p["spill"]) * max(alpha.shape)
    if spill >= 1:
        k = int(spill) * 2 + 1
        grown = cv2.dilate(alpha, np.ones((k, k), np.uint8))
        reach = cv2.GaussianBlur(grown, (0, 0), spill / 2) * (grown > 0.5)  # no stray marks beyond it
        keep = np.maximum(keep, reach)
    keep = keep[..., None]
    out = a.copy()
    out[y0:y1, x0:x1] = a[y0:y1, x0:x1] * (1 - keep) + drawn * keep
    if float(p["face_pass"]) > 0:
        out = _faces(pipe, out, a, original, ctx, p)
    if float(p["real_face"]) > 0:
        out = _real_faces(out, original, ctx, float(p["real_face"]), p["face_style"])
    face = float(p["face"])  # keep some of the look underneath on faces
    if face > 0:
        f = face_mask(ctx.scene, *a.shape[:2])
        if f is not None:
            out = out + (a - out) * (face * f)[..., None]
    return out


def _match_background(drawn: np.ndarray, look: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """The drawing's background toned to the look's own (the model paints its
    own paper or backdrop, a little off), so painted edges past the players'
    outline show only real paint marks, not a halo."""
    bg = (alpha < 0.05).astype(np.float32)
    if bg.mean() < 0.02:
        return drawn
    sigma = max(4.0, 0.06 * max(alpha.shape))
    num = cv2.GaussianBlur(look * bg[..., None], (0, 0), sigma)
    den = cv2.GaussianBlur(drawn * bg[..., None], (0, 0), sigma)
    ratio = np.clip((num + 1e-3) / (den + 1e-3), 0.5, 2.0)
    soft = cv2.GaussianBlur(alpha, (0, 0), 1.5)[..., None]
    return np.clip(drawn * soft + drawn * ratio * (1 - soft), 0, 1).astype(np.float32)


def _face_lines(photo: np.ndarray, strength: float = 6.0) -> np.ndarray:
    g = photo.mean(axis=2)
    return np.clip((g - cv2.GaussianBlur(g, (0, 0), 2.0)) * -strength, 0, 1)


def cel_face(photo: np.ndarray) -> np.ndarray:
    """The real face cel-shaded, as anime and comics draw it: a few flat
    tones per color (light, mid, shadow), smooth, with its darkest lines inked."""
    u8 = (np.clip(photo, 0, 1) * 255).astype(np.uint8)
    soft = cv2.bilateralFilter(cv2.bilateralFilter(u8, 9, 40, 7), 9, 30, 5).astype(np.float32) / 255
    lab = cv2.cvtColor(soft, cv2.COLOR_RGB2LAB)
    lab[..., 0] = np.round(lab[..., 0] / 100 * 4) / 4 * 100 * 0.85 + lab[..., 0] * 0.15  # four tones of light
    flat = np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)
    flat = cv2.GaussianBlur(flat, (0, 0), 0.6)
    return np.clip(flat * (1 - _face_lines(photo, 9.0)[..., None] * 0.85), 0, 1).astype(np.float32)


def graphite_face(photo: np.ndarray) -> np.ndarray:
    """The real face in pencil: gray tones on white paper, with drawn lines."""
    g = cv2.bilateralFilter((np.clip(photo.mean(axis=2), 0, 1) * 255).astype(np.uint8), 7, 25, 5).astype(np.float32) / 255
    tone = 1 - (1 - g) * 0.8
    out = tone * (1 - _face_lines(photo, 8.0) * 0.8)
    return np.repeat(np.clip(out, 0, 1)[..., None], 3, axis=2).astype(np.float32)


FACE_STYLES = {}


def painted_face(photo: np.ndarray) -> np.ndarray:
    """The real face in a painter's tone: a touch lighter and more transparent,
    gently evened, with every feature, eyelash, skin tone and hair strand kept
    (its fine detail is put back after the evening)."""
    u8 = (np.clip(photo, 0, 1) * 255).astype(np.uint8)
    soft = cv2.bilateralFilter(u8, 5, 14, 3).astype(np.float32) / 255
    detail = photo - cv2.GaussianBlur(photo, (0, 0), 1.2)
    lit = 1 - (1 - soft) * 0.92
    return np.clip(lit + detail * 0.95, 0, 1).astype(np.float32)


FACE_STYLES.update(paint=painted_face, cel=cel_face, graphite=graphite_face)


def _real_faces(out: np.ndarray, photo: np.ndarray, ctx: Context, amount: float, style: str = "paint") -> np.ndarray:
    """Each head of the players in the play (face, hair, ears, jaw) from the
    photo itself, rendered in the look's technique and laid over the drawing,
    following the head's own outline: the face is the child's, exactly."""
    h, w = out.shape[:2]
    render = FACE_STYLES.get(style, painted_face)
    for fx, fy, fr in ctx.scene.faces:
        r = fr * w * 1.05  # the whole head, not just the face
        if r < 4:
            continue
        cx, cy = fx * w, fy * h - r * 0.12  # a little up, for the hair
        x0, y0 = int(max(0, cx - r * 1.5)), int(max(0, cy - r * 1.6))
        x1, y1 = int(min(w, cx + r * 1.5)), int(min(h, cy + r * 1.6))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.sqrt(((xx - cx) / r) ** 2 + ((yy - cy) / (r * 1.2)) ** 2)
        reach = np.clip((1.15 - d) / 0.3, 0, 1)  # full over the head, fading out at the neck and shoulders
        alpha = ctx.alpha[y0:y1, x0:x1] if ctx.alpha is not None else np.ones((y1 - y0, x1 - x0), np.float32)
        m = (reach * np.clip(alpha, 0, 1) * amount)[..., None]
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - m) + render(photo[y0:y1, x0:x1]) * m
    return out


def _faces(pipe, out: np.ndarray, look: np.ndarray, photo: np.ndarray, ctx: Context, p: dict) -> np.ndarray:
    """Each face, and the ball, drawn again up close and more gently, from the
    real one: in the style, but still the player (the "detail" pass)."""
    h, w = out.shape[:2]
    real = float(p.get("real_face", 0)) >= 0.5
    spots = [] if real else [(fx, fy, fr * FACE_REACH / 2) for fx, fy, fr in ctx.scene.faces]
    spots += [(bx, by, br * 1.6) for bx, by, br in ctx.scene.balls]
    gentle = len(spots)  # hands keep their real shape best with an even lighter touch
    spots += [(hx, hy, hr * 1.4) for hx, hy, hr in ctx.scene.hands]
    for i, (fx, fy, fr) in enumerate(spots):
        strength = float(p["face_pass"]) * (0.75 if i >= gentle else 1.0)
        r = fr * w
        if r < 6:
            continue
        cx, cy = fx * w, fy * h
        x0, y0 = int(max(0, cx - r)), int(max(0, cy - r))
        x1, y1 = int(min(w, cx + r)), int(min(h, cy + r))
        if x1 - x0 < 16 or y1 - y0 < 16:
            continue
        alpha = ctx.alpha[y0:y1, x0:x1]
        # small areas: a smaller, quicker drawing is as sharp as they need
        drawn = _draw(pipe, look[y0:y1, x0:x1], photo[y0:y1, x0:x1], alpha, p, strength, DETAIL_EDGE,
                      max(12, int(int(p["steps"]) * 0.6)))
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        ring = np.clip((1 - d) / 0.35, 0, 1)  # full in the middle, fading out toward the edge
        m = (ring * np.clip(cv2.GaussianBlur(alpha, (0, 0), 1.0) * 1.5, 0, 1))[..., None]
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - m) + drawn * m
    return out
