import struct

import numpy as np
from PIL import Image

from photo_crops import edit, focus, framing, images, settings
from photo_crops.people import GOALIE, OPPONENT, OTHER, TEAM, Person, jersey_kind
from photo_crops.settings import Settings

SIZE = (7008, 4672)
COLORS = {TEAM: "#1f2a44", GOALIE: "#86d0d8", OPPONENT: "#f0f0f0"}


def person(x0, y0, x1, y1, kind=TEAM, sharp=1000.0, focus_hit=False, head=None):
    return Person((x0, y0, x1, y1), kind, sharp, head, focus_hit)


def test_sharp_goalie_leads_but_a_blurry_one_does_not():
    player = person(3500, 900, 4300, 3000, TEAM, 2700, focus_hit=True)
    sharp_goalie = person(1100, 900, 1900, 2900, GOALIE, 2500)
    assert framing.choose([player, sharp_goalie], [], SIZE).reason == "goalie"
    blurry_goalie = person(1100, 900, 1900, 2900, GOALIE, 400)
    plan = framing.choose([player, blurry_goalie], [], SIZE)
    assert plan.subject is player and plan.reason == "team player in focus"
    assert framing.choose([player, sharp_goalie], [], SIZE, goalie_first=False).subject is player


def test_small_distant_goalie_does_not_lead():
    player = person(3200, 1900, 3840, 3520, TEAM, 2000, focus_hit=True)
    far_goalie = person(4777, 1943, 5083, 2822, GOALIE, 300)
    assert framing.choose([player, far_goalie], [], SIZE).subject is player


def test_team_player_beats_a_focused_opponent():
    opponent = person(1000, 1000, 2000, 3500, OPPONENT, 3000, focus_hit=True)
    ours = person(4000, 1000, 5000, 3400, TEAM, 2000)
    assert framing.choose([opponent, ours], [], SIZE).subject is ours


def test_duel_and_ball_join_the_crop_but_blurry_foreground_does_not():
    ours = person(3000, 1000, 3800, 3000, TEAM, 2000, focus_hit=True)
    duel = person(3900, 1100, 4600, 3000, OPPONENT, 1500)
    blurry = person(1700, 500, 2900, 3700, TEAM, 200)
    ball = (2600, 2800, 2800, 3000)
    plan = framing.choose([ours, duel, blurry], [ball], SIZE)
    assert plan.group == (2600, 1000, 4600, 3000)


def test_team_photo_is_framed_whole_with_the_goalie_as_face():
    row = [person(500 + 600 * i, 1400, 1050 + 600 * i, 3900, TEAM, 3000) for i in range(9)]
    row[0].kind = GOALIE
    plan = framing.choose(row, [], SIZE)
    assert plan.team_photo and plan.face_person is row[0]
    box = framing.crop_box(plan, SIZE, "best")
    assert box[0] <= 500 and box[2] >= 1050 + 600 * 8
    assert abs((box[2] - box[0]) / (box[3] - box[1]) - 1.5) < 0.01


def test_best_crop_shapes():
    single = framing.Plan(person(3000, 1000, 3800, 3000), (3000, 1000, 3800, 3000), "x")
    box = framing.crop_box(single, SIZE, "best")
    assert abs((box[2] - box[0]) / (box[3] - box[1]) - 0.8) < 0.01
    duel = framing.Plan(person(2000, 1500, 3000, 3000), (2000, 1500, 4500, 3000), "x")
    box = framing.crop_box(duel, SIZE, "best")
    assert abs((box[2] - box[0]) / (box[3] - box[1]) - 1.5) < 0.01
    # a crop that would be nearly the whole frame becomes a real 4:5 crop
    wide = framing.Plan(person(1300, 300, 5300, 4600), (1300, 300, 5300, 4600), "x")
    box = framing.crop_box(wide, SIZE, "best")
    assert box[2] - box[0] < 0.6 * SIZE[0]


def test_crops_stay_inside_the_photo():
    plan = framing.Plan(person(0, 0, 400, 900), (0, 0, 400, 900), "x")
    for shape in settings.SHAPES:
        x0, y0, x1, y1 = framing.crop_box(plan, SIZE, shape)
        assert 0 <= x0 < x1 <= SIZE[0] and 0 <= y0 < y1 <= SIZE[1]


def test_face_box_is_head_and_shoulders_and_never_too_small():
    p = person(3000, 1000, 3800, 3500, head=(3400, 1200, 150))
    box = framing.face_box(p, SIZE, "sharp")
    assert box[2] - box[0] >= framing.FACE_MIN_WIDTH["sharp"]
    assert box[1] < 1200 < box[3] and box[0] < 3400 < box[2]
    tiny = person(3000, 2000, 3100, 2300, head=(3050, 2020, 10))
    assert framing.face_box(tiny, SIZE, "skip-small") is None
    assert framing.face_box(tiny, SIZE, "sharp") is not None


def test_jersey_colors_tell_sunlit_teal_from_white():
    def lab(rgb, n=200):
        import cv2
        px = np.array([[rgb] * n], np.uint8)
        return cv2.cvtColor(px, cv2.COLOR_RGB2LAB).astype(np.float32)[0]
    # colors measured on real shirts in sun and shade
    assert jersey_kind(lab((0x1d, 0x28, 0x43)), COLORS) == TEAM
    for teal in ((0xaf, 0xe2, 0xe5), (0x99, 0xd6, 0xdb), (0x69, 0x9c, 0xae), (0x35, 0x66, 0x79)):
        assert jersey_kind(lab(teal), COLORS) == GOALIE, teal
    assert jersey_kind(lab((0xec, 0xe6, 0xe3)), COLORS) == OPPONENT
    assert jersey_kind(lab((0xc3, 0xcc, 0xd6)), COLORS) == OPPONENT  # white in shade, not navy
    assert jersey_kind(lab((200, 40, 40)), COLORS) == OTHER


def test_match_tones_follows_the_reference():
    rng = np.random.default_rng(0)
    raw16 = (rng.random((60, 80, 3)) ** 2 * 65535).astype(np.uint16)  # dark, like a plain RAW render
    reference = (np.clip(rng.normal(150, 40, (60, 80, 3)), 0, 255)).astype(np.uint8)
    out = images.match_tones(raw16, reference)
    assert abs(float(np.median(out)) - float(np.median(reference))) < 8
    order = np.argsort(raw16[..., 0].ravel())
    assert np.all(np.diff(out[..., 0].ravel()[order].astype(int)) >= 0)  # tones keep their order


def test_edit_strength_none_changes_nothing_and_light_is_between():
    rng = np.random.default_rng(1)
    img = Image.fromarray(rng.uniform(40, 150, (60, 60, 3)).astype(np.uint8))
    assert edit.apply(img, None, "none") is img
    base = np.asarray(img, np.float32)
    light = np.asarray(edit.apply(img, None, "light"), np.float32)
    full = np.asarray(edit.apply(img, None, "full"), np.float32)
    assert np.abs(light - (base + full) / 2).max() <= 1.5


def test_collect_prefers_camera_jpeg_and_finds_screenshots(tmp_path):
    for name in ("DSC1.JPG", "DSC1.ARW", "DSC2.ARW", "Screenshot 2026-11-07 at 12.00.00 PM.heic", "notes.txt", ".hidden.jpg"):
        (tmp_path / name).write_bytes(b"x")
    photos, shots = images.collect(tmp_path)
    assert [p.name for p in photos] == ["DSC1.JPG", "DSC2.ARW"]
    assert [p.name for p in shots] == ["Screenshot 2026-11-07 at 12.00.00 PM.heic"]


def test_sony_focus_point_from_jpeg_and_arw_maker_notes(tmp_path):
    def tiff(sony_header: bool) -> bytes:
        e = "<"
        maker = (b"SONY DSC \0\0\0" if sony_header else b"")
        # maker note: one entry, FocusLocation (4 x uint16, stored after the IFD)
        mn_ifd_len = 2 + 12 + 4
        exif_ifd_at, maker_at = 26, 26 + 18
        value_at = maker_at + len(maker) + mn_ifd_len
        mn = maker + struct.pack(e + "H", 1) + struct.pack(e + "HHII", 0x2027, 3, 4, value_at) + b"\0\0\0\0"
        mn += struct.pack(e + "4H", 7008, 4672, 3504, 1168)
        header = b"II*\0" + struct.pack(e + "I", 8)
        ifd0 = struct.pack(e + "H", 1) + struct.pack(e + "HHII", 0x8769, 4, 1, exif_ifd_at) + b"\0\0\0\0"
        exif = struct.pack(e + "H", 1) + struct.pack(e + "HHII", 0x927C, 7, len(mn), maker_at) + b"\0\0\0\0"
        return header + ifd0 + exif + mn
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe1\0\0Exif\0\0" + tiff(True))
    arw = tmp_path / "a.arw"
    arw.write_bytes(tiff(False))
    assert focus.focus_point(jpg, (7008, 4672)) == (3504, 1168)
    assert focus.focus_point(arw, (3504, 2336)) == (1752, 584)
    (tmp_path / "b.jpg").write_bytes(b"\xff\xd8 nothing")
    assert focus.focus_point(tmp_path / "b.jpg", (100, 100)) is None


def test_settings_problems_and_instructions(tmp_path):
    s = Settings(folder=str(tmp_path))
    assert s.problems() == []
    assert "Best Crops" in s.instructions() and "--edit light" in s.command()
    assert Settings(folder=str(tmp_path / "missing")).problems()
    assert Settings(folder=str(tmp_path), versions=[]).problems()
    assert Settings(folder=str(tmp_path), out_name="a/b").problems()
    restored = Settings.from_dict({"folder": "x", "edit": "full", "unknown": 1})
    assert restored.edit == "full"


def test_focus_goes_to_the_one_person_in_front():
    from photo_crops.people import focused_person
    back = np.zeros((100, 100), bool)
    back[10:90, 40:60] = True       # partly hidden player behind
    front = np.zeros((100, 100), bool)
    front[5:95, 30:80] = True       # bigger player in front, overlapping
    assert focused_person((50, 50), [back, front], 3) == 1
    assert focused_person((83, 50), [back, front], 5) == 1   # just outside the front player's outline
    assert focused_person((99, 2), [back, front], 3) is None


def test_goalie_hidden_behind_a_player_does_not_lead():
    player = person(2693, 1560, 3653, 4235, TEAM, 1982)
    peeking_goalie = person(2675, 1736, 2963, 3635, GOALIE, 900, focus_hit=True)
    assert framing.choose([player, peeking_goalie], [], SIZE).subject is player
