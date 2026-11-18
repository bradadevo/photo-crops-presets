"""The optional Gemini parts, only when you ask: rating a shortlist (score, reason, its best crop)
and the D edit's suggested adjustments. Nothing is redrawn: Gemini only judges and suggests."""

from __future__ import annotations

import os
import re
from pathlib import Path

from photo_presets.cull import adjust, analysis, gemini

COST_PER_CALL = (0.001, 0.002)  # dollars: Gemini Flash with one image, low and high


def key_ready() -> bool:
    """GEMINI_API_KEY in the environment, or read from ~/.zshrc (the app is opened from the Dock,
    which does not read it)."""
    if os.environ.get("GEMINI_API_KEY"):
        return True
    try:
        text = Path("~/.zshrc").expanduser().read_text()
    except OSError:
        return False
    m = re.search(r'^\s*export\s+GEMINI_API_KEY\s*=\s*["\']?([^"\'\s]+)', text, re.M)
    if m:
        os.environ["GEMINI_API_KEY"] = m.group(1)
        return True
    return False


def cost(calls: int) -> str:
    lo, hi = (calls * c for c in COST_PER_CALL)
    if hi < 0.01:
        return "under 1¢"
    return f"about ${lo:.2f}–${hi:.2f}"


_client = None


def client():
    global _client
    if _client is None:
        if not key_ready():
            raise RuntimeError("No Gemini key: add export GEMINI_API_KEY=... to ~/.zshrc")
        _client = gemini.create_client()
    return _client


def rate(img, usage: list | None = None) -> analysis.PhotoAssessment:
    return analysis.analyze(client(), img, {}, gemini.DEFAULT_MODEL, usage=usage)


def adjustments(img, usage: list | None = None) -> adjust.Adjustments:
    return adjust.suggest(client(), img, gemini.DEFAULT_MODEL, "", usage)
