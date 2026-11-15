import numpy as np

from photo_presets.scene import Scene


def test_a_child_inside_the_cut_out_gets_a_real_face_and_hands():
    s = Scene(faces=[(0.5, 0.1, 0.1)], other_faces=[(0.2, 0.6, 0.05), (0.9, 0.5, 0.05)],
              other_hands=[(0.3, 0.7, 0.02), (0.95, 0.6, 0.02)])
    matte = np.zeros((100, 100), np.float32)
    matte[50:70, 10:30] = 1  # the child holding the main player's hand is in the cut-out
    s.take_in(matte)
    assert (0.2, 0.6, 0.05) in s.faces and (0.9, 0.5, 0.05) not in s.faces  # a bystander stays out
    assert s.hands == [(0.3, 0.7, 0.02)]
    assert s.other_faces == [(0.9, 0.5, 0.05)]
