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
