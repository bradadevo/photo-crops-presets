from types import SimpleNamespace

from photo_presets.scene import ball_in_play

PLAYER = SimpleNamespace(box=(400, 100, 700, 1000), height=900)


def test_the_ball_at_the_players_feet_is_in_play():
    assert ball_in_play((650, 880, 780, 1000), [PLAYER])  # a seventh of the player's height


def test_a_ball_far_behind_the_player_is_not():
    assert not ball_in_play((900, 300, 946, 346), [PLAYER])  # a twentieth: another game behind


def test_a_ball_far_off_to_the_side_is_not():
    assert not ball_in_play((2200, 500, 2340, 640), [PLAYER])  # two player-heights away


def test_with_no_players_found_every_ball_counts():
    assert ball_in_play((0, 0, 10, 10), [])


def test_a_ball_beside_a_player_far_behind_is_not_in_the_play():
    # (DSC03406: the ball is at a background player's feet, the right size for them, 50 feet back)
    from types import SimpleNamespace
    near = SimpleNamespace(box=(385, 256, 920, 1868), height=1612)
    far = SimpleNamespace(box=(989, 369, 1240, 1097), height=728)
    assert not ball_in_play((1207, 872, 1308, 967), [near, far])
    assert ball_in_play((1000, 1700, 1230, 1930), [near, far])  # the main player's own ball still is


def test_a_blurred_ball_behind_is_out_and_a_sharp_one_counts():
    import numpy as np
    from PIL import Image, ImageFilter
    from photo_presets.scene import ball_sharpness
    rng = np.random.default_rng(1)
    img = Image.fromarray((rng.random((1000, 1000)) * 255).astype(np.uint8)).convert("RGB")
    soft = img.crop((600, 100, 700, 200)).filter(ImageFilter.GaussianBlur(4))
    img.paste(soft, (600, 100))
    player = SimpleNamespace(box=(100, 100, 400, 900), height=800)
    assert ball_sharpness(img, (600, 100, 700, 200), [player]) < 0.6  # out of focus: behind
    assert ball_sharpness(img, (450, 800, 550, 900), [player]) > 0.6  # as sharp as the player
