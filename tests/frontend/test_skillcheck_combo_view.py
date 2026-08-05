import logging
from unittest.mock import MagicMock, call, patch

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.aim_view import AimController
from chessshootout.frontend.skillcheck.combo_view import (
    ComboController, COMBO_VIEW_RESULT_HOLD_MS, COMBO_VIEW_BRILLIANT_TEXT, COMBO_VIEW_CLEAN_TEXT,
    COMBO_VIEW_FAIL_TEXT, COMBO_VIEW_STREAK_FIRE,
    COMBO_VIEW_PLATE_ALPHA, COMBO_VIEW_PLATE_PAD_X_FRAC, COMBO_VIEW_PLATE_PAD_Y_FRAC,
    COMBO_VIEW_PLATE_FADE_X_FRAC, COMBO_VIEW_PLATE_FADE_Y_FRAC,
    COMBO_VIEW_CHEVRON_SHADOW_ALPHA, COMBO_VIEW_CHEVRON_SHADOW_OFF_FRAC,
    _JUDGE_BRILLIANT, _JUDGE_CLEAN, _JUDGE_FAIL, _JUDGE_TEXT,
    _PLATE_CACHE, _CHEVRON_SHADOW_CACHE, _strip_plate)
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.mole_view import MoleController
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.combo import (
    ComboChallenge, COMBO_MAX_WRONGS, COMBO_WRONG_LOCKOUT_MS)
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


def _wedge_center(ctrl, direction):
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
    cx, cy = ctrl._pad_center
    d = ctrl._pad_r * 0.6
    return (int(cx + dx * d), int(cy + dy * d))


def _wedge_probe_rect(ctrl, direction):
    side = max(int(ctrl._pad_r * 0.35), 8)
    rect = pg.Rect(0, 0, side, side)
    rect.center = _wedge_center(ctrl, direction)
    return rect


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
    assert ctrl._progress == 5
    assert ctrl.landed is True
    assert ctrl.done is False
    ctrl.update(750 + COMBO_VIEW_RESULT_HOLD_MS)
    assert ctrl.done is True
    audio.play_combo_complete.assert_called_once()
    assert audio.play_combo_hit.call_count == 5


def test_wrong_press_locks_and_lockout_press_is_ignored():
    ctrl = _combo()
    ctrl.update(150)
    ctrl.handle_event(_key("down"))
    assert ctrl._progress == 0
    assert ctrl._wrong_count == 1
    assert ctrl._lockout_until > ctrl._now
    ctrl.update(200)
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 0, "a press inside the lockout does not advance"
    assert ctrl._wrong_count == 1, "a lockout-swallowed press is not counted as a wrong"
    ctrl.update(400)
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 1, "after the lockout the correct press lands"


def test_third_wrong_commits_fail():
    ctrl = _combo()
    t = 0
    for _ in range(COMBO_MAX_WRONGS):
        t += 300
        ctrl.update(t)
        ctrl.handle_event(_key("down"))
    assert ctrl._wrong_count == COMBO_MAX_WRONGS
    assert ctrl.landed is False
    assert ctrl._judgement == _JUDGE_FAIL
    ctrl.update(t + COMBO_VIEW_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_deadline_commits_fail():
    ctrl = _combo()
    ctrl.update(4999)
    assert ctrl.landed is None
    ctrl.update(5000)
    assert ctrl.landed is False
    ctrl.update(5000 + COMBO_VIEW_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_wasd_matches_arrows():
    ctrl = _combo()
    _run_correct(ctrl, key=_wasd)
    assert ctrl.landed is True


def test_mouse_click_on_wedge_advances():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    ctrl.update(150)
    ctrl.handle_event(_click(_wedge_center(ctrl, "up")))
    assert ctrl._progress == 1
    ctrl.handle_event(_click((5, 5)))
    assert ctrl._progress == 1, "a click outside the pad circle is ignored"


def test_wedge_hit_test_resolves_all_four_directions():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    for direction in ("up", "down", "left", "right"):
        assert ctrl._receptor_hit(_wedge_center(ctrl, direction)) == direction


def test_wedge_hit_test_hub_and_outside_are_dead_zones():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    cx, cy = ctrl._pad_center
    assert ctrl._receptor_hit((cx, cy)) is None, "the hub centre is a dead zone"
    hub_pt = (cx + ctrl._hub_r // 2, cy)
    assert ctrl._receptor_hit(hub_pt) is None, "inside the hub radius never registers"
    assert ctrl._receptor_hit((cx + ctrl._pad_r + 10, cy)) is None, \
        "outside the pad circle never registers"


def test_wedge_hit_test_diagonal_adjacent_resolves_by_dominant_axis():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    cx, cy = ctrl._pad_center
    r = ctrl._pad_r
    assert ctrl._receptor_hit((cx + int(r * 0.5), cy + int(r * 0.2))) == "right"
    assert ctrl._receptor_hit((cx + int(r * 0.2), cy + int(r * 0.5))) == "down"
    assert ctrl._receptor_hit((cx - int(r * 0.5), cy - int(r * 0.2))) == "left"
    assert ctrl._receptor_hit((cx - int(r * 0.2), cy - int(r * 0.5))) == "up"


def test_judgement_tiers_track_driven_latency():
    brilliant = _combo()
    brilliant.update(300)
    brilliant.handle_event(_key("up"))
    assert brilliant._judgement == _JUDGE_BRILLIANT
    clean = _combo()
    clean.update(500)
    clean.handle_event(_key("up"))
    assert clean._judgement == _JUDGE_CLEAN
    plain = _combo()
    plain.update(800)
    plain.handle_event(_key("up"))
    assert plain._judgement is None


def test_judgement_tokens_map_to_the_shipped_copy():
    # the state token is decoupled from the display string; the rendered copy is pinned
    # here so a token rename can never silently change what the player reads.
    assert _JUDGE_TEXT == {
        _JUDGE_BRILLIANT: COMBO_VIEW_BRILLIANT_TEXT,
        _JUDGE_CLEAN: COMBO_VIEW_CLEAN_TEXT,
        _JUDGE_FAIL: COMBO_VIEW_FAIL_TEXT,
    }
    assert (COMBO_VIEW_BRILLIANT_TEXT, COMBO_VIEW_CLEAN_TEXT, COMBO_VIEW_FAIL_TEXT) == (
        "BRILLIANT!", "CLEAN!", "BLUNDER??")


def test_repeated_prompts_resolve():
    prompts = ("up", "up", "down", "down", "left")
    ctrl = _combo(prompts)
    _run_correct(ctrl, prompts)
    assert ctrl._progress == 5
    assert ctrl.landed is True


def test_online_relays_each_accepted_press_with_direction_keyword():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    _run_correct(ctrl)
    assert on_shot.call_count == 5
    for relayed, direction in zip(on_shot.call_args_list, _PROMPTS):
        assert relayed.kwargs["direction"] == direction
    assert ctrl.landed is None, "the client never self-commits a terminal online"
    assert ctrl._progress == 5, "the displayed strip still advances optimistically"


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
    assert ctrl._progress == 1, "progress adoption advances the mirrored strip"
    ctrl.spectate_shot(150, 0, False, progress=1)
    assert ctrl._wrong_count == 1, "a non-advancing spectate shot registers a wrong pip"
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


def test_registry_builds_mole_for_the_whack_kind():
    ctrl = build_controller(
        SkillCheckKind.WHACK, seed="s", cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0,
        deadline_ms=5000, value_diff=2, captured_value=4,
        hole_squares=((3, 3), (3, 4), (4, 3), (4, 4)),
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
        return ctrl._progress, ctrl._wrong_count

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


def test_receptor_flash_brightens_the_wedge_region():
    base = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    base_surf = pg.Surface((700, 700))
    base_surf.fill((0, 0, 0))
    base.update(100)
    base.draw(base_surf)
    base_bright = _region_brightness(base_surf, _wedge_probe_rect(base, "up"))

    flashed = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    flashed_surf = pg.Surface((700, 700))
    flashed_surf.fill((0, 0, 0))
    flashed.update(150)
    flashed.handle_event(_key("up"))
    flashed.draw(flashed_surf)
    flash_bright = _region_brightness(flashed_surf, _wedge_probe_rect(flashed, "up"))

    assert flash_bright > base_bright, "a correct press flash-fills its wedge brighter"


def test_spotlight_radius_shrinks_with_the_deadline():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    ctrl.update(500)
    r1 = ctrl._spot_radius()
    ctrl.update(2000)
    r2 = ctrl._spot_radius()
    ctrl.update(4000)
    r3 = ctrl._spot_radius()
    assert r1 > r2 > r3, "the closing light IS the countdown: strictly shrinking"


def test_spotlight_radius_freezes_once_the_check_commits():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    t = 0
    for _ in range(COMBO_MAX_WRONGS):
        t += 300
        ctrl.update(t)
        ctrl.handle_event(_key("down"))
    assert ctrl.landed is False
    frozen = ctrl._spot_radius()
    ctrl.update(3000)
    assert ctrl._spot_radius() == frozen, "a committed fail stops the countdown light"


def test_passive_never_allocates_or_draws_the_spotlight_layer():
    ctrl = _combo(passive=True, audio=MagicMock(), board_rect=pg.Rect(0, 0, 700, 700))
    assert ctrl._spot_layer is None, "the spectator mirror keeps the live board readable"
    ctrl.set_board_rect(pg.Rect(0, 0, 640, 640))
    assert ctrl._spot_layer is None, "set_board_rect never allocates for a passive mirror"
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.update(2000)
    ctrl.draw(surf)


def test_spotlight_scrims_the_corner_but_not_the_hole():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    surf = pg.Surface((700, 700))
    surf.fill((255, 255, 255))
    ctrl.update(4000)
    ctrl.draw(surf)
    corner = surf.get_at((5, 5))
    hole_pt = (ctrl._pad_center[0] + ctrl._pad_r + 20, ctrl._pad_center[1])
    hole = surf.get_at(hole_pt)
    assert sum(corner[:3]) < sum(hole[:3]), \
        "outside the shrunken light the board is dark; under the hole it stays lit"


def test_brilliant_streak_ignites_fire_and_a_wrong_resets_it():
    ctrl = _combo()
    for i, direction in enumerate(_PROMPTS[:3]):
        ctrl.update(150 * (i + 1))
        ctrl.handle_event(_key(direction))
    assert ctrl._brilliant_streak == COMBO_VIEW_STREAK_FIRE, \
        "three sub-350ms presses each judge BRILLIANT and chain the streak"
    assert ctrl._fire_active() is True
    ctrl.update(700)
    ctrl.handle_event(_key("up"))
    assert ctrl._brilliant_streak == 0, "a wrong press douses the streak"
    assert ctrl._fire_active() is False


def test_slow_correct_press_also_resets_the_streak():
    ctrl = _combo()
    for i, direction in enumerate(_PROMPTS[:3]):
        ctrl.update(150 * (i + 1))
        ctrl.handle_event(_key(direction))
    assert ctrl._fire_active() is True
    ctrl.update(1000)
    ctrl.handle_event(_key("right"))
    assert ctrl._progress == 4, "the slow press still lands"
    assert ctrl._brilliant_streak == 0, "only BRILLIANT judgements keep the fire burning"


def test_fire_streak_draw_smoke():
    ctrl = _combo_scene(_PROMPTS, 99)
    for i, direction in enumerate(_PROMPTS[:3]):
        ctrl.update(150 * (i + 1))
        ctrl.handle_event(_key(direction))
    assert ctrl._fire_active() is True
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.draw(surf)
    assert surf.get_size() == (700, 700)


def test_passive_never_tracks_a_fire_streak():
    ctrl = _combo(passive=True, audio=MagicMock())
    for p in (1, 2, 3):
        ctrl.update(150 * p)
        ctrl.spectate_shot(150 * p, 0, True, progress=p)
    assert ctrl._progress == 3
    assert ctrl._brilliant_streak == 0, "the mirror never claims the mover's streak"
    assert ctrl._fire_active() is False


def test_two_same_frame_presses_advance_and_relay_once():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 1, "two KEYDOWNs in one frame advance the strip only once"
    assert on_shot.call_count == 1, "the paced-out second press never reaches the wire"


def test_press_below_human_floor_is_ignored_entirely():
    on_shot = MagicMock()
    ctrl = _combo(on_shot=on_shot)
    ctrl.update(100)
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 0, "an elapsed below the human floor never advances"
    assert ctrl._wrong_count == 0, "and never counts as a wrong"
    assert on_shot.call_count == 0, "and never relays"
    ctrl.update(130)
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 1, "a press at elapsed 130 is accepted"


def test_inter_press_gate_paces_accepted_presses():
    ctrl = _combo(("up", "down", "left", "right", "up"))
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 1
    ctrl.update(150 + 79)
    ctrl.handle_event(_key("down"))
    assert ctrl._progress == 1, "a press 79 ms after an accepted press is paced out"
    ctrl.update(150 + 81)
    ctrl.handle_event(_key("down"))
    assert ctrl._progress == 2, "a press 81 ms after an accepted press lands"


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
    assert ctrl._wrong_count == 1, \
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


def _plate_core_rect(ctrl):
    rect = pg.Rect(ctrl._plate_left, ctrl._plate_top, ctrl._plate_w, ctrl._plate_h)
    return rect.inflate(-2 * ctrl._plate_fade_x, -2 * ctrl._plate_fade_y)


def _lit_board_brightness(ctrl, *, plated, states=(150,)):
    # the strip lives over a lit, dancing board: probe it on a white field so any
    # backing shows up as a straight brightness drop over the same drawn arrows.
    if not plated:
        ctrl._draw_strip_plate = lambda window: None
    surf = pg.Surface((700, 700))
    surf.fill((255, 255, 255))
    for t in states:
        ctrl.update(t)
    ctrl.draw(surf)
    return _region_brightness(surf, _plate_core_rect(ctrl))


def test_strip_plate_darkens_the_lit_board_behind_the_arrows():
    bare = _lit_board_brightness(_combo_scene(_PROMPTS, 99), plated=False)
    plated = _lit_board_brightness(_combo_scene(_PROMPTS, 99), plated=True)
    assert plated < bare * 0.6, \
        "the backing plate has to swallow the dancing board behind the prompts"


def test_spectator_mirror_gets_the_same_backing_plate():
    def mirror(plated):
        ctrl = _combo(passive=True, audio=MagicMock(), board_rect=pg.Rect(0, 0, 700, 700))
        return _lit_board_brightness(ctrl, plated=plated)

    assert mirror(True) < mirror(False) * 0.6, \
        "the read-only spectate mirror draws the plate too, not a bare strip"


def test_strip_plate_edges_fade_out_instead_of_ending_in_a_hard_box():
    ctrl = _combo_scene(_PROMPTS, 99)
    plate = _strip_plate(ctrl._plate_w, ctrl._plate_h, ctrl._plate_cut,
                         ctrl._plate_fade_x, ctrl._plate_fade_y)
    mid_x, mid_y = ctrl._plate_w // 2, ctrl._plate_h // 2
    assert plate.get_at((mid_x, mid_y)).a == COMBO_VIEW_PLATE_ALPHA, \
        "the core of the plate carries the full knob alpha"

    row = [plate.get_at((x, mid_y)).a for x in range(ctrl._plate_fade_x + 1)]
    assert row[0] == 0, "the left edge is fully transparent — no hard box seam"
    assert row[-1] == COMBO_VIEW_PLATE_ALPHA
    assert all(b >= a for a, b in zip(row, row[1:])), "the horizontal ramp climbs monotonically"
    assert 0 < row[len(row) // 2] < COMBO_VIEW_PLATE_ALPHA, "and it really is a ramp, not a step"
    assert plate.get_at((ctrl._plate_w - 1, mid_y)).a == 0, "the right edge fades out as well"

    col = [plate.get_at((mid_x, y)).a for y in range(ctrl._plate_fade_y + 1)]
    assert col[0] == 0 and col[-1] == COMBO_VIEW_PLATE_ALPHA
    assert all(b >= a for a, b in zip(col, col[1:])), "the vertical ramp climbs monotonically"
    assert plate.get_at((mid_x, ctrl._plate_h - 1)).a == 0
    assert plate.get_at((0, 0)).a == 0, "corners take the softer of the two ramps"


def test_strip_plate_draws_over_the_scrim_and_under_the_arrows_and_judgement():
    ctrl = _combo_scene(_PROMPTS, 99)
    order = []
    for name in ("_draw_dance_floor", "_draw_spotlight", "_draw_strip_plate", "_draw_strip",
                 "_draw_flying", "_draw_confetti", "_draw_judgement"):
        setattr(ctrl, name, (lambda tag: lambda window: order.append(tag))(name))
    ctrl.update(150)
    ctrl.draw(pg.Surface((700, 700), pg.SRCALPHA))
    assert order.index("_draw_dance_floor") < order.index("_draw_strip_plate")
    assert order.index("_draw_spotlight") < order.index("_draw_strip_plate"), \
        "the plate sits above the dance-floor tint and the spotlight scrim"
    for above in ("_draw_strip", "_draw_flying", "_draw_confetti", "_draw_judgement"):
        assert order.index("_draw_strip_plate") < order.index(above), \
            "arrows, the popped-off arrow and the judgement all read on top of the plate"


def test_fire_streak_still_reads_over_the_plate():
    def fire_brightness(plated):
        ctrl = _combo_scene(_PROMPTS, 99)
        if not plated:
            ctrl._draw_strip_plate = lambda window: None
        for i, direction in enumerate(_PROMPTS[:3]):
            ctrl.update(150 * (i + 1))
            ctrl.handle_event(_key(direction))
        assert ctrl._fire_active() is True
        surf = pg.Surface((700, 700))
        surf.fill((0, 0, 0))
        ctrl.draw(surf)
        rect = pg.Rect(0, 0, ctrl._fire_size // 2, ctrl._fire_size // 2)
        rect.center = (ctrl._strip_slots[ctrl._progress], ctrl._strip_y)
        return _region_brightness(surf, rect)

    plated = fire_brightness(True)
    assert plated > fire_brightness(False) * 0.9, \
        "the fire-streak flame is drawn after the plate, so it keeps its punch"


def test_each_chevron_gets_a_drop_shadow_for_contrast():
    def arrow_brightness(shadowed):
        ctrl = _combo_scene(_PROMPTS, 99)
        surf = pg.Surface((700, 700))
        surf.fill((255, 255, 255))
        ctrl.update(150)
        if shadowed:
            ctrl.draw(surf)
        else:
            with patch("chessshootout.frontend.skillcheck.combo_view._chevron_shadow",
                       return_value=pg.Surface((1, 1), pg.SRCALPHA)):
                ctrl.draw(surf)
        rect = pg.Rect(0, 0, int(ctrl._strip_big * 1.6), ctrl._strip_big)
        rect.center = (ctrl._strip_slots[0], ctrl._strip_y)
        return _region_brightness(surf, rect)

    assert arrow_brightness(True) < arrow_brightness(False), \
        "a dark silhouette under every chevron separates it from the flames behind it"


def test_strip_plate_spans_every_slot_and_never_shrinks_as_arrows_are_consumed():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    geometry = (ctrl._plate_left, ctrl._plate_top, ctrl._plate_w, ctrl._plate_h)
    half_chevron = int(ctrl._strip_big * 0.8)
    assert ctrl._plate_left <= ctrl._strip_slots[0] - half_chevron, \
        "the plate reaches past the first chevron's outer edge"
    assert ctrl._plate_left + ctrl._plate_w >= ctrl._strip_slots[-1] + half_chevron
    _run_correct(ctrl)
    assert ctrl._progress == len(_PROMPTS)
    assert (ctrl._plate_left, ctrl._plate_top, ctrl._plate_w, ctrl._plate_h) == geometry, \
        "the consumed arrows stay on the strip, so the plate keeps its full length"


def test_plate_geometry_derives_from_the_named_knobs():
    cell = 99
    ctrl = _combo_scene(_PROMPTS, cell)
    pad_x = int(cell * COMBO_VIEW_PLATE_PAD_X_FRAC)
    pad_y = int(cell * COMBO_VIEW_PLATE_PAD_Y_FRAC)
    span = ctrl._strip_slots[-1] - ctrl._strip_slots[0] + ctrl._strip_big
    assert ctrl._plate_w == span + 2 * pad_x
    assert ctrl._plate_h == max(ctrl._strip_big, ctrl._fire_size) + 2 * pad_y
    assert ctrl._plate_fade_x == int(ctrl._plate_w * COMBO_VIEW_PLATE_FADE_X_FRAC)
    assert ctrl._plate_fade_y == int(ctrl._plate_h * COMBO_VIEW_PLATE_FADE_Y_FRAC)
    assert 0 < COMBO_VIEW_PLATE_ALPHA < 255, "the plate is translucent, never an opaque slab"
    assert 0 < COMBO_VIEW_PLATE_FADE_X_FRAC < 0.5 and 0 < COMBO_VIEW_PLATE_FADE_Y_FRAC < 0.5, \
        "both fades have to leave a solid core between them"
    assert 0 < COMBO_VIEW_CHEVRON_SHADOW_ALPHA < 255
    assert 0 < COMBO_VIEW_CHEVRON_SHADOW_OFF_FRAC < 0.5


def test_relayout_resizes_the_plate_with_the_cell():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    small = (ctrl._plate_w, ctrl._plate_h)
    ctrl.relayout(pg.Rect(0, 0, 160, 160))
    assert ctrl._plate_w > small[0] and ctrl._plate_h > small[1], \
        "a resize rebuilds the plate for the new cell instead of stretching a stale one"
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.update(200)
    ctrl.draw(surf)


def test_plate_and_chevron_shadows_allocate_nothing_per_frame():
    ctrl = _combo_scene(_PROMPTS, 99)
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.update(16)
    ctrl.draw(surf)
    plate = _strip_plate(ctrl._plate_w, ctrl._plate_h, ctrl._plate_cut,
                         ctrl._plate_fade_x, ctrl._plate_fade_y)
    sizes = (len(_PLATE_CACHE), len(_CHEVRON_SHADOW_CACHE))
    for i in range(2, 60):
        ctrl.update(i * 16)
        ctrl.draw(surf)
    assert (len(_PLATE_CACHE), len(_CHEVRON_SHADOW_CACHE)) == sizes, \
        "60 frames must not add a single cache entry"
    assert _strip_plate(ctrl._plate_w, ctrl._plate_h, ctrl._plate_cut,
                        ctrl._plate_fade_x, ctrl._plate_fade_y) is plate


def test_wrong_press_cues_the_scratch_inside_the_press_handler():
    audio = MagicMock()
    ctrl = _combo(audio=audio)
    at_cue = {}
    audio.play_combo_wrong.side_effect = lambda: at_cue.update(
        wrongs=ctrl._wrong_count, lockout=ctrl._lockout_until)
    ctrl.update(150)
    audio.play_combo_wrong.assert_not_called()
    ctrl.handle_event(_key("down"))
    assert audio.play_combo_wrong.call_count == 1, \
        "handle_event returns with the scratch already cued — never a frame later"
    assert at_cue == {"wrongs": 1, "lockout": 150 + int(COMBO_WRONG_LOCKOUT_MS)}, \
        "the cue fires inside the wrong-press handler, after the miss is booked"


def test_the_scratch_is_never_re_cued_by_a_later_frame_or_the_lockout_ending():
    audio = MagicMock()
    ctrl = _combo(audio=audio)
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.update(150)
    ctrl.handle_event(_key("down"))
    for t in range(160, 160 + 3 * int(COMBO_WRONG_LOCKOUT_MS), 16):
        ctrl.update(t)
        ctrl.draw(surf)
    ctrl.handle_event(_key("up"))
    assert ctrl._progress == 1, "the next correct press lands once the lockout expires"
    assert audio.play_combo_wrong.call_count == 1, \
        "no deferred scratch trails the player into the next prompt"


def test_no_logging_across_update_and_draw_frames(caplog):
    ctrl = _combo_scene(_PROMPTS, 99)
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    with caplog.at_level(logging.DEBUG):
        for i in range(100):
            ctrl.update(i * 16)
            ctrl.draw(surf)
    assert [r for r in caplog.records if r.name.startswith("chess")] == []
