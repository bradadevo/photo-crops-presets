"""A team photo's group: a half-hidden child is taken in, the grass between the players is not."""

import numpy as np
from PIL import Image

from photo_presets.scene import fill_group


def test_grass_between_the_players_stays_background_and_a_hidden_child_is_kept():
    h, w = 400, 600
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 120, 40)  # grass
    img[:120] = (30, 50, 30)  # trees above
    navy = (25, 30, 70)
    alpha = np.zeros((h, w), np.float32)
    # a row of players (solid), joined at the top so the gaps between their legs are enclosed
    alpha[120:160, 60:540] = 1
    for x0 in (60, 200, 340, 460):
        alpha[160:380, x0:x0 + 80] = 1
    alpha[380:395, 60:540] = 1  # their feet in a line: the gaps are closed in
    img[alpha > 0] = navy
    # a child the cut-out missed, between two players (navy, but not in the cut-out)
    img[200:330, 285:335] = navy
    people = alpha > 0
    people[200:330, 285:335] = True  # the detector found them
    out = fill_group(alpha, Image.fromarray(img), people)
    assert out[260:300, 150:190].max() < 0.2  # the grass between two players: background
    assert out[230:300, 295:325].mean() > 0.8  # the hidden child: part of the team
