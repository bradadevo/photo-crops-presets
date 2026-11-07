"""The clean, neutral edit, applied at a chosen strength.

From ai-versions (fc-sport-culling-solo-ai): gentle noise reduction for
grainy photos, a neutral color balance, a tone curve that sets true black and
clean white while keeping the midtones where they were, exposure safety, a
soft lift on dark players, light clarity and a small saturation lift.

At full strength it darkened darker skin in bright sun on the camera's own
JPEGs, which are already well processed, so the default "light" strength
applies half of it on top of the camera's look.
"""

import cv2
import numpy as np
from PIL import Image

STRENGTH = {"none": 0.0, "light": 0.5, "full": 1.0}

CLARITY = 0.2
CLARITY_SIGMA_S = 10
CLARITY_SIGMA_R = 0.15
# Clarity may not darken tones below this brightness (0-255)
CLARITY_SHADOW_END = 100
SATURATION = 1.12
# Grain level (0-255 scale) above which a photo gets gentle noise reduction
NOISE_THRESHOLD = 2.0
DENOISE_MAX_PIXELS = 8_000_000
# The color balance moves at most this far (Lab units), so grass is not pushed magenta
MAX_COLOR_SHIFT = 8.0
NEUTRAL_STRENGTH = 0.8
# The darkest 1% / brightest 0.5% of tones are set to these levels
BLACK_TARGET = 5.0
WHITE_TARGET = 232.0
CURVE_STRENGTH = 0.8
# Photos already spanning this range get no curve
FULL_RANGE = (8.0, 230.0)
# Exposure: a median brightness inside this range is left as shot
EXPOSURE_OK_RANGE = (0.28, 0.66)
GAMMA_LIMITS = (0.7, 1.5)
HIGHLIGHT_START = 100
# Players darker than SUBJECT_TARGET get a feathered lift of at most SUBJECT_MAX_LIFT
SUBJECT_TARGET = 105
SUBJECT_MAX_LIFT = 30
SUBJECT_LIFT_END = 150
SUBJECT_FEATHER = 0.25

Box = tuple[int, int, int, int]


def _luma(arr: np.ndarray) -> np.ndarray:
    return 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]


def _u8(arr: np.ndarray) -> np.ndarray:
    return np.clip(arr + 0.5, 0, 255).astype(np.uint8)


def noise_level(arr: np.ndarray) -> float:
    """Median fine detail in the flattest parts of the photo, where detail can only be noise."""
    gray = cv2.cvtColor(_u8(arr), cv2.COLOR_RGB2GRAY).astype(np.float32)
    residual = np.abs(gray - cv2.GaussianBlur(gray, (0, 0), 1.0))
    texture = cv2.GaussianBlur(residual, (0, 0), 4)
    flat = texture <= np.percentile(texture, 30)
    return float(np.median(residual[flat]) * 1.4826)


def denoise(arr: np.ndarray) -> np.ndarray:
    if arr.shape[0] * arr.shape[1] > DENOISE_MAX_PIXELS:
        return arr
    level = noise_level(arr)
    if level < NOISE_THRESHOLD:
        return arr
    h = float(min(8.0, 1.5 * level))
    return cv2.fastNlMeansDenoisingColored(_u8(arr), None, h, h, 5, 15).astype(np.float32)


def neutral_color(arr: np.ndarray) -> np.ndarray:
    """Moves the least colorful 40% of the photo (whites, grays, lines) toward neutral, capped."""
    lab = cv2.cvtColor(_u8(arr), cv2.COLOR_RGB2LAB).astype(np.float32)
    a, b = lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.hypot(a, b)
    grayish = chroma <= np.percentile(chroma, 40)
    shift = np.array([np.median(a[grayish]), np.median(b[grayish])]) * NEUTRAL_STRENGTH
    norm = float(np.hypot(*shift))
    if norm > MAX_COLOR_SHIFT:
        shift *= MAX_COLOR_SHIFT / norm
    lab[..., 1] -= shift[0]
    lab[..., 2] -= shift[1]
    out = cv2.cvtColor(_u8(lab), cv2.COLOR_LAB2RGB).astype(np.float32)
    return out * ((_luma(arr) + 1) / (_luma(out) + 1))[..., None]  # change color only


def tone_curve(arr: np.ndarray) -> np.ndarray:
    """Restores a full tonal range to faded photos with a gamma curve through
    black, the unchanged middle tone and clean white."""
    lum = _luma(arr)
    low, mid, high = (float(v) for v in np.percentile(lum, (1.0, 50.0, 99.5)))
    if low <= FULL_RANGE[0] and high >= FULL_RANGE[1]:
        return arr
    black, white = min(low, BLACK_TARGET), max(high, WHITE_TARGET)
    x = np.clip((lum - low) / max(high - low, 1.0), 0, 1)
    x_mid = min(max((mid - low) / max(high - low, 1.0), 1e-3), 0.999)
    y_mid = min(max((mid - black) / (white - black), 1e-3), 0.999)
    target = black + (white - black) * x ** (np.log(y_mid) / np.log(x_mid))
    target = lum + (target - lum) * CURVE_STRENGTH
    return arr * ((target + 1) / (lum + 1))[..., None]


def auto_exposure(arr: np.ndarray) -> np.ndarray:
    """Brightens dark photos; tames bright ones by pulling down only bright tones."""
    median = np.median(_luma(np.clip(arr, 0, 255))) / 255.0
    low, high = EXPOSURE_OK_RANGE
    if median <= 0.01 or median >= 0.99 or low <= median <= high:
        return arr
    gamma = np.log(low if median < low else high) / np.log(median)
    gamma = min(max(gamma, GAMMA_LIMITS[0]), GAMMA_LIMITS[1])
    base = np.clip(arr, 0, 255)
    curved = 255.0 * (base / 255.0) ** gamma
    if gamma <= 1:
        return curved
    weight = np.clip((_luma(base) - HIGHLIGHT_START) / (255 - HIGHLIGHT_START), 0, 1)[..., None]
    return base * (1 - weight) + curved * weight


def lift_subject(arr: np.ndarray, box: Box | None) -> np.ndarray:
    """A soft local lift on dark players (dark skin, navy kits), like a Lightroom subject mask."""
    if box is None:
        return arr
    h, w = arr.shape[:2]
    left, top, right, bottom = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
    if right - left < 8 or bottom - top < 8:
        return arr
    median = float(np.median(_luma(np.clip(arr[top:bottom, left:right], 0, 255))))
    if median >= SUBJECT_TARGET:
        return arr
    amount = SUBJECT_MAX_LIFT * min(1.0, (SUBJECT_TARGET - median) / SUBJECT_TARGET * 2)
    lum = np.clip(_luma(arr), 0, 255)
    lifted = lum + amount * np.clip(1 - lum / SUBJECT_LIFT_END, 0, 1) ** 1.5
    mask = np.zeros((h, w), np.float32)
    mask[top:bottom, left:right] = 1
    mask = cv2.GaussianBlur(mask, (0, 0), max(2.0, SUBJECT_FEATHER * min(right - left, bottom - top)))
    return arr * (1 + ((lifted + 1) / (lum + 1) - 1) * mask)[..., None]


def clarity(arr: np.ndarray, amount: float = CLARITY) -> np.ndarray:
    detail = cv2.detailEnhance(np.ascontiguousarray(_u8(arr)[..., ::-1]), sigma_s=CLARITY_SIGMA_S,
                               sigma_r=CLARITY_SIGMA_R)[..., ::-1].astype(np.float32)
    out = arr + (detail - arr) * amount
    lum_in, lum_out = _luma(arr), _luma(out)
    guard = np.clip(1 - lum_in / CLARITY_SHADOW_END, 0, 1) ** 0.5
    return out + (arr - out) * np.where(lum_out < lum_in, guard, 0.0)[..., None]


def saturate(arr: np.ndarray, amount: float = SATURATION) -> np.ndarray:
    hsv = cv2.cvtColor(_u8(arr), cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * amount, 0, 255)
    return cv2.cvtColor(hsv.round().astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)


def clean(arr: np.ndarray, subject: Box | None) -> np.ndarray:
    """The full clean edit of an image at its final size."""
    arr = denoise(arr)
    arr = neutral_color(arr)
    arr = tone_curve(arr)
    arr = auto_exposure(arr)
    arr = lift_subject(arr, subject)
    arr = clarity(arr)
    return saturate(arr)


def apply(img: Image.Image, subject: Box | None, strength: str) -> Image.Image:
    """The clean edit blended over the image at the chosen strength."""
    amount = STRENGTH[strength]
    if amount == 0:
        return img
    base = np.asarray(img.convert("RGB"), np.float32)
    out = base + amount * (clean(base, subject) - base)
    return Image.fromarray(_u8(out))


def crop_and_edit(img: Image.Image, box: Box, subject: Box | None, strength: str) -> Image.Image:
    """Crops at full resolution, then edits; subject is in the full image's pixels."""
    crop = img.crop(box)
    sub = None
    if subject:
        sub = (max(0, round(subject[0] - box[0])), max(0, round(subject[1] - box[1])),
               min(crop.width, round(subject[2] - box[0])), min(crop.height, round(subject[3] - box[1])))
    return apply(crop, sub, strength)
