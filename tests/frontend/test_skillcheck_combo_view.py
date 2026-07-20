import importlib.util
import logging
from unittest.mock import MagicMock, call

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.aim_view import AimController
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.combo_view import (
    ComboController, COMBO_RESULT_HOLD_MS, COMBO_BRILLIANT_TEXT, COMBO_CLEAN_TEXT,
    COMBO_FAIL_TEXT)
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.combo import ComboChallenge, COMBO_MAX_WRONGS
from chessshootout.skillcheck.types import SkillCheckKind


_pygame_init = pygame_display(700, 700)

_PROMPTS = ("up", "down", "left", "right", "up")
_ARROW_KEYS = {"up": pg.K_UP, "down": pg.K_DOWN, "left": pg.K_LEFT, "right": pg.K_RIGHT}
_WASD_KEYS = {"up": pg.K_w, "down": pg.K_s, "left": pg.K_a, "right": pg.K_d}


def _key(direction):
    return pg.event.Event(pg.KEYDOWN, {"key": _ARROW_KEYS[direction], "mod": 0})


def _wasd(direction):
    return pg.event.Event(pg.KEYDOWN, {"key": _WASD_KEYS[direction], "mod": 0})


def _click(pos):
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": pos})


def _combo(prompts=_PROMPTS, **kw):
    return ComboController(
        ComboChallenge(prompts=tuple(prompts), deadline_ms=5000.0),
        pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000, **kw)


def _combo_scene(prompts, cell):
    center = 350
    rect = pg.Rect(center - cell // 2, center - cell // 2, cell, cell)
    return ComboController(
        ComboChallenge(prompts=tuple(prompts), deadline_ms=5000.0),
        rect, now_ms=0, deadline_ms=5000,
        board_rect=pg.Rect(0, 0, 700, 700), geom=lambda sq: (350, 350),
        victim_surface=pg.Surface((cell, cell), pg.SRCALPHA),
        attacker_surface=pg.Surface((cell, cell), pg.SRCALPHA),
        from_sq=Square(4, 4), victim_sq=Square(3, 3), audio=MagicMock())


def _run_correct(ctrl, prompts=_PROMPTS, key=_key, step=150):
    for i, direction in enumerate(prompts):
        ctrl.update(step * (i + 1))
        ctrl.handle_event(key(direction))


def _region_brightness(surf, rect):
    total = 0
    n = 0
    for x in range(rect.left, rect.right, 2):
        for y in range(rect.top, rect.bottom, 2):
            col = surf.get_at((x, y))
            total += col.r + col.g + col.b
            n += 1
    return total / max(n, 1)


def test_local_correct_run_commits_win():
    audio = MagicMock()
    ctrl = _combo(audio=audio)
    _run_correct(ctrl)
    assert ctrl.progress == 5
    assert ctrl.landed is True
    assert ctrl.done is False
    ctrl.update(750 + COMBO_RESULT_HOLD_MS)
    assert ctrl.done is True
    audio.play_combo_complete.assert_called_once()
    assert audio.play_combo_hit.call_count == 5


def test_wrong_press_locks_and_lockout_press_is_ignored():
    ctrl = _combo()
    ctrl.update(150)
    ctrl.handle_event(_key("down"))
    assert ctrl.progress == 0
    assert ctrl.wrong_count == 1
    assert ctrl._lockout_until > ctrl._now
    ctrl.update(200)
    ctrl.handle_event(_key("up"))
    assert ctrl.progress == 0, "a press inside the lockout does not advance"
    assert ctrl.wrong_count == 1, "a lockout-swallowed press is not counted as a wrong"
    ctrl.update(400)
    ctrl.handle_event(_key("up"))
    assert ctrl.progress == 1, "after the lockout the correct press lands"


def test_third_wrong_commits_fail():
    ctrl = _combo()
    t = 0
    for _ in range(COMBO_MAX_WRONGS):
        t += 300
        ctrl.update(t)
        ctrl.handle_event(_key("down"))
    assert ctrl.wrong_count == COMBO_MAX_WRONGS
    assert ctrl.landed is False
    assert ctrl._judgement == COMBO_FAIL_TEXT
    ctrl.update(t + COMBO_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_deadline_commits_fail():
    ctrl = _combo()
    ctrl.update(4999)
    assert ctrl.landed is None
    ctrl.update(5000)
    assert ctrl.landed is False
    ctrl.update(5000 + COMBO_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_wasd_matches_arrows():
    ctrl = _combo()
    _run_correct(ctrl, key=_wasd)
    assert ctrl.landed is True


def test_mouse_click_on_receptor_advances():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    ctrl.update(150)
    ctrl.handle_event(_click(ctrl._receptors["up"].center))
    assert ctrl.progress == 1
    ctrl.handle_event(_click((5, 5)))
    assert ctrl.progress == 1, "a click off every receptor is ignored"


def test_judgement_tiers_track_driven_latency():
    brilliant = _combo()
    brilliant.update(300)
    brilliant.handle_event(_key("up"))
    assert brilliant._judgement == COMBO_BRILLIANT_TEXT
    clean = _combo()
    clean.update(500)
    clean.handle_event(_key("up"))
    assert clean._judgement == COMBO_CLEAN_TEXT
    plain = _combo()
    plain.update(800)
    plain.handle_event(_key("up"))
    assert plain._judgement is None


def test_repeated_prompts_resolve():
    prompts = ("up", "up", "down", "down", "left")
    ctrl = _combo(prompts)
    _run_correct(ctrl, prompts)
    assert ctrl.progress == 5
    assert ctrl.landed is True


def test_online_relays_each_accepted_press_with_direction_keyword():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    _run_correct(ctrl)
    assert on_shot.call_count == 5
    for relayed, direction in zip(on_shot.call_args_list, _PROMPTS):
        assert relayed.kwargs["direction"] == direction
    assert ctrl.landed is None, "the client never self-commits a terminal online"
    assert ctrl.progress == 5, "the displayed strip still advances optimistically"


def test_online_does_not_relay_a_lockout_swallowed_press():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    ctrl.update(150)
    ctrl.handle_event(_key("down"))
    assert on_shot.call_count == 1, "an accepted wrong press relays (server counts wrongs)"
    ctrl.update(200)
    ctrl.handle_event(_key("up"))
    assert on_shot.call_count == 1, "a lockout-swallowed press is never relayed"


def test_online_resolve_holds_then_finishes():
    ctrl = _combo(on_shot=MagicMock())
    _run_correct(ctrl)
    assert ctrl.landed is None
    ctrl.update(600)
    ctrl.resolve(True)
    assert ctrl.landed is True
    assert ctrl.done is False
    ctrl.update(600 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_passive_ignores_input_and_mirrors_progress():
    audio = MagicMock()
    ctrl = _combo(passive=True, audio=audio)
    assert ctrl.handle_event(_key("up")) is False
    ctrl.update(100)
    ctrl.spectate_shot(90, 0, False, progress=1)
    assert ctrl.progress == 1, "progress adoption advances the mirrored strip"
    ctrl.spectate_shot(150, 0, False, progress=1)
    assert ctrl.wrong_count == 1, "a non-advancing spectate shot registers a wrong pip"
    audio.play_combo_hit.assert_not_called()
    audio.play_combo_wrong.assert_not_called()


def test_registry_still_builds_wheel_and_aim():
    wheel = build_controller(SkillCheckKind.WHEEL, seed="s", cell_rect=pg.Rect(0, 0, 80, 80),
                             now_ms=0, deadline_ms=5000)
    assert isinstance(wheel, WheelController)
    aim = build_controller(SkillCheckKind.AIM, seed="s", cell_rect=pg.Rect(0, 0, 80, 80),
                           now_ms=0, deadline_ms=5000, value_diff=4,
                           victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                           board_rect=pg.Rect(0, 0, 640, 640))
    assert isinstance(aim, AimController)


def test_registry_builds_combo_from_seed_deterministically():
    kw = dict(cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000, value_diff=2,
              captured_value=3)
    one = build_controller(SkillCheckKind.COMBO, seed="x", **kw)
    two = build_controller(SkillCheckKind.COMBO, seed="x", **kw)
    assert isinstance(one, ComboController)
    assert one.challenge.prompts == two.challenge.prompts, "same seed -> same prompts"


def test_registry_builds_mole_when_mole_view_exists():
    if importlib.util.find_spec("chessshootout.frontend.skillcheck.mole_view") is None:
        pytest.skip("mole_view sibling not landed yet")
    from chessshootout.frontend.skillcheck.mole_view import MoleController
    ctrl = build_controller(
        SkillCheckKind.WHACK, seed="s", cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0,
        deadline_ms=5000, value_diff=2, captured_value=4,
        hole_squares=((3, 3), (3, 4), (4, 3), (4, 4)), px_to_board=lambda pos: (0.0, 0.0),
        board_rect=pg.Rect(0, 0, 640, 640), geom=lambda sq: (0, 0),
        victim_surface=pg.Surface((80, 80), pg.SRCALPHA))
    assert isinstance(ctrl, MoleController)


def test_determinism_same_script_same_strip_and_pips():
    script = [("up", 150), ("left", 450), ("down", 750)]

    def run():
        ctrl = _combo()
        for direction, t in script:
            ctrl.update(t)
            ctrl.handle_event(_key(direction))
        return ctrl.progress, ctrl.wrong_count

    assert run() == (2, 1)
    assert run() == run()


@pytest.mark.parametrize("cell", [60, 99, 160])
def test_draw_smoke_across_states_and_sizes(cell):
    surf = pg.Surface((700, 700), pg.SRCALPHA)

    mount = _combo_scene(_PROMPTS, cell)
    mount.update(50)
    mount.draw(surf)

    correct = _combo_scene(_PROMPTS, cell)
    correct.update(150)
    correct.handle_event(_key("up"))
    correct.draw(surf)

    wrong = _combo_scene(_PROMPTS, cell)
    wrong.update(150)
    wrong.handle_event(_key("down"))
    wrong.draw(surf)

    win = _combo_scene(_PROMPTS, cell)
    _run_correct(win)
    win.draw(surf)

    fail = _combo_scene(_PROMPTS, cell)
    t = 0
    for _ in range(COMBO_MAX_WRONGS):
        t += 300
        fail.update(t)
        fail.handle_event(_key("down"))
    fail.draw(surf)
    assert surf.get_size() == (700, 700)


def test_receptor_flash_brightens_the_receptor_region():
    base = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    base_surf = pg.Surface((700, 700))
    base_surf.fill((0, 0, 0))
    base.update(100)
    base.draw(base_surf)
    base_bright = _region_brightness(base_surf, base._receptors["up"])

    flashed = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    flashed_surf = pg.Surface((700, 700))
    flashed_surf.fill((0, 0, 0))
    flashed.update(150)
    flashed.handle_event(_key("up"))
    flashed.draw(flashed_surf)
    flash_bright = _region_brightness(flashed_surf, flashed._receptors["up"])

    assert flash_bright > base_bright, "a correct press flash-fills its receptor brighter"


def test_two_same_frame_presses_advance_and_relay_once():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    ctrl.handle_event(_key("up"))
    assert ctrl.progress == 1, "two KEYDOWNs in one frame advance the strip only once"
    assert on_shot.call_count == 1, "the paced-out second press never reaches the wire"


def test_press_below_human_floor_is_ignored_entirely():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    ctrl.update(100)
    ctrl.handle_event(_key("up"))
    assert ctrl.progress == 0, "an elapsed below the human floor never advances"
    assert ctrl.wrong_count == 0, "and never counts as a wrong"
    assert on_shot.call_count == 0, "and never relays"
    ctrl.update(130)
    ctrl.handle_event(_key("up"))
    assert ctrl.progress == 1, "a press at elapsed 130 is accepted"


def test_inter_press_gate_paces_accepted_presses():
    ctrl = _combo(("up", "down", "left", "right", "up"))
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    assert ctrl.progress == 1
    ctrl.update(150 + 79)
    ctrl.handle_event(_key("down"))
    assert ctrl.progress == 1, "a press 79 ms after an accepted press is paced out"
    ctrl.update(150 + 81)
    ctrl.handle_event(_key("down"))
    assert ctrl.progress == 2, "a press 81 ms after an accepted press lands"


def test_torn_victim_key_is_per_challenge():
    v = pg.Surface((80, 80), pg.SRCALPHA)
    pg.draw.circle(v, (210, 140, 60, 255), (40, 40), 26)
    a = ComboController(ComboChallenge(("up", "down", "left", "right", "up"), 5000.0),
                        pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000, victim_surface=v)
    b = ComboController(ComboChallenge(("down", "up", "right", "left", "down"), 5000.0),
                        pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000, victim_surface=v)
    ta, tb = a._torn_victim(), b._torn_victim()
    assert ta is not tb, "distinct challenges never share a cached torn victim"
    assert pg.image.tostring(ta, "RGBA") != pg.image.tostring(tb, "RGBA"), \
        "different seeds tear the victim in different places"
    assert a._torn_victim() is ta, "the same check re-uses its cached torn victim"


def test_spectate_wrong_shows_the_struck_pip_immediately():
    ctrl = _combo(passive=True, audio=MagicMock())
    ctrl.update(200)
    ctrl.spectate_shot(150, 0, False, progress=0)
    assert ctrl.wrong_count == 1, \
        "the server relays the pre-increment miss_count; the mirror shows one struck pip"


def test_combo_hit_plays_the_pitch_ladder_index():
    audio = MagicMock()
    ctrl = _combo(audio=audio)
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    ctrl.update(350)
    ctrl.handle_event(_key("down"))
    assert audio.play_combo_hit.call_args_list == [call(0), call(1)]


def test_combo_hit_pitch_ladder_muted_when_passive():
    audio = MagicMock()
    ctrl = _combo(passive=True, audio=audio)
    ctrl.update(150)
    ctrl.spectate_shot(140, 0, True, progress=1)
    audio.play_combo_hit.assert_not_called()


def test_no_logging_across_update_and_draw_frames(caplog):
    ctrl = _combo_scene(_PROMPTS, 99)
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    with caplog.at_level(logging.DEBUG):
        for i in range(100):
            ctrl.update(i * 16)
            ctrl.draw(surf)
    assert [r for r in caplog.records if r.name.startswith("chess")] == []
