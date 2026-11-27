"""Apple's own outline of the people in a photo (macOS Vision, on the Neural Engine): about 1-2 s and
1 GB. Used only to trim the hair pass of the players' cut-out tighter around each head, so no halo of
background is left around the hair; it never decides who is in the picture (see scene.refine_heads).

Checked once, at start: on a Mac without it (macOS before 14, or Vision not there) the cut-out is
made as before, and nothing fails later.
"""
from __future__ import annotations

import io
import logging
import platform
import sys

import numpy as np
from PIL import Image

log = logging.getLogger("vsdigitalpro")
_available: bool | None = None


def available() -> bool:
    """Apple's person outline can be used on this Mac (macOS 14 or later, with Vision)."""
    global _available
    if _available is None:
        _available = False
        try:
            if sys.platform == "darwin" and int(platform.mac_ver()[0].split(".")[0] or 0) >= 14:
                import Quartz  # noqa: F401
                import Vision
                _available = hasattr(Vision, "VNGeneratePersonSegmentationRequest")
        except Exception:
            _available = False
    return _available


def outline(img: Image.Image) -> np.ndarray | None:
    """The people's outline (floats 0-1, the image's size), at Apple's best quality; None when it
    can't be had (the cut-out is then made as before)."""
    if not available():
        return None
    try:
        import Quartz
        import Vision
        from Foundation import NSData
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
        req = Vision.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
        req.setQualityLevel_(Vision.VNGeneratePersonSegmentationRequestQualityLevelAccurate)
        req.setOutputPixelFormat_(Quartz.kCVPixelFormatType_OneComponent32Float)
        ok, _ = handler.performRequests_error_([req], None)
        res = req.results() if ok else None
        if not res:
            return None
        pb = res[0].pixelBuffer()
        Quartz.CVPixelBufferLockBaseAddress(pb, 1)
        try:
            w, h = Quartz.CVPixelBufferGetWidth(pb), Quartz.CVPixelBufferGetHeight(pb)
            row = Quartz.CVPixelBufferGetBytesPerRow(pb)
            raw = bytes(Quartz.CVPixelBufferGetBaseAddress(pb).as_buffer(row * h))
        finally:
            Quartz.CVPixelBufferUnlockBaseAddress(pb, 1)
        m = np.frombuffer(raw, np.float32).reshape(h, row // 4)[:, :w]
        m = np.clip(m, 0, 1).astype(np.float32)
        if m.shape != (img.height, img.width):
            import cv2
            m = cv2.resize(m, img.size, interpolation=cv2.INTER_LINEAR)
        return m
    except Exception:
        log.exception("Apple's person outline failed: the cut-out is made as before")
        return None
