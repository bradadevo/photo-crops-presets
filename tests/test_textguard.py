import cv2
import numpy as np
import pytest

from photo_presets import textguard

pytest.importorskip("Vision")


def _shirt(text: str | None) -> np.ndarray:
    img = np.full((400, 300, 3), (40, 50, 120), np.uint8)
    if text:
        cv2.putText(img, text, (60, 230), cv2.FONT_HERSHEY_DUPLEX, 2.0, (255, 255, 255), 6)
    return img.astype(np.float32) / 255


def test_a_number_the_drawing_invents_is_painted_out():
    drawn, photo = _shirt("48"), _shirt(None)
    assert textguard.find_text(drawn)
    out, invented, real = textguard.honest_text(drawn, photo, np.ones((400, 300), np.float32))
    assert invented >= 1 and real == 0
    assert not textguard.find_text(out)


def test_the_photos_own_text_is_put_back():
    drawn, photo = _shirt(None), _shirt("48")
    out, invented, real = textguard.honest_text(drawn, photo, np.ones((400, 300), np.float32))
    assert real >= 1 and invented == 0
    assert textguard.find_text(out)
