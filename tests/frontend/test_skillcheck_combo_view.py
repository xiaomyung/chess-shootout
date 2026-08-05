import logging
from unittest.mock import MagicMock, call

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.aim_view import AimController
from chessshootout.frontend.skillcheck.combo_view import (
    ComboController, COMBO_VIEW_RESULT_HOLD_MS, COMBO_VIEW_BRILLIANT_TEXT, COMBO_VIEW_CLEAN_TEXT,
    COMBO_VIEW_FAIL_TEXT, COMBO_VIEW_STREAK_FIRE,
    COMBO_VIEW_CHIP_ALPHA, COMBO_VIEW_CHIP_DONE_ALPHA, COMBO_VIEW_CHIP_CUT_FRAC,
    COMBO_VIEW_CHIP_GAP_FRAC, COMBO_VIEW_CHIP_GAP_MIN_PX,
    COMBO_VIEW_CHIP_PAD_FRAC, COMBO_VIEW_CHIP_PAD_MIN_PX,
    COMBO_VIEW_EXIT_FADE_MS, COMBO_VIEW_FIRE_IGNITE_MS, COMBO_VIEW_INTRO_ARROW_MS,
    COMBO_VIEW_INTRO_FADE_MS, COMBO_VIEW_INTRO_STAGGER_MS, COMBO_VIEW_JUDGE_FADE_FRAC,
    COMBO_VIEW_JUDGE_HOLD_MS, COMBO_VIEW_PRESS_NUDGE_MS,
    _JUDGE_BRILLIANT, _JUDGE_CLEAN, _JUDGE_FAIL, _JUDGE_TEXT,
    _CHIP_CACHE, _CHIP_DONE, _CHIP_IDLE, _CHIP_NEXT, _chip_surface, _direction_chevron)
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.skillcheck.mole_view import MoleController
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.combo import (
    ComboChallenge, COMBO_INTRO_MS, COMBO_MAX_WRONGS, COMBO_WRONG_LOCKOUT_MS)
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
    # the first prompt is anchored at the intro's end, so tier boundaries shift
    # by COMBO_INTRO_MS for the opening press; later presses anchor on the
    # previous press (covered by the streak tests).
    anchor = int(COMBO_INTRO_MS)
    brilliant = _combo()
    brilliant.update(anchor + 300)
    brilliant.handle_event(_key("up"))
    assert brilliant._judgement == _JUDGE_BRILLIANT
    clean = _combo()
    clean.update(anchor + 500)
    clean.handle_event(_key("up"))
    assert clean._judgement == _JUDGE_CLEAN
    plain = _combo()
    plain.update(anchor + 800)
    plain.handle_event(_key("up"))
    assert plain._judgement is None


def test_first_prompt_judgement_never_pays_for_the_intro():
    # a press 340 ms after the strip has finished arriving is BRILLIANT even
    # though the raw elapsed-from-open is 640 ms; the old anchor at check-open
    # made a first-press BRILLIANT humanly unreachable.
    ctrl = _combo()
    ctrl.update(int(COMBO_INTRO_MS) + 340)
    ctrl.handle_event(_key("up"))
    assert ctrl._judgement == _JUDGE_BRILLIANT


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


def _chip_core_rect(ctrl, i):
    inset = ctrl._chip_cut + 2
    rect = pg.Rect(0, 0, ctrl._chip - 2 * inset, ctrl._chip - 2 * inset)
    rect.center = (ctrl._strip_slots[i], ctrl._strip_y)
    return rect


def _lit_board_probe(ctrl, *, chipped, states=(400,)):
    # the strip lives over a lit, dancing board: probe every chip core on a white
    # field so each backing shows up as a straight brightness drop under its arrow.
    if not chipped:
        ctrl._draw_strip_chips = lambda window: None
    surf = pg.Surface((700, 700))
    surf.fill((255, 255, 255))
    for t in states:
        ctrl.update(t)
    ctrl.draw(surf)
    return [_region_brightness(surf, _chip_core_rect(ctrl, i))
            for i in range(len(ctrl._strip_slots))]


def test_every_chip_darkens_the_lit_board_under_its_own_arrow():
    bare = _lit_board_probe(_combo_scene(_PROMPTS, 99), chipped=False)
    chipped = _lit_board_probe(_combo_scene(_PROMPTS, 99), chipped=True)
    for i, (b, c) in enumerate(zip(bare, chipped)):
        assert c < b * 0.6, \
            "chip {} has to swallow the dancing board behind its own prompt".format(i)


def test_spectator_mirror_gets_the_same_chips():
    def mirror(chipped):
        ctrl = _combo(passive=True, audio=MagicMock(), board_rect=pg.Rect(0, 0, 700, 700))
        probes = _lit_board_probe(ctrl, chipped=chipped)
        return sum(probes) / len(probes)

    assert mirror(True) < mirror(False) * 0.6, \
        "the read-only spectate mirror draws the chips too, not a bare strip"


def test_chip_silhouette_is_a_crisp_alpha_step_never_a_feathered_ramp():
    # the plate this replaced feathered its edges over ~14% of its width and the
    # gradient smeared across the checkerboard; the chip is pinned to the opposite:
    # full strength at the first edge pixel, dead flat across the whole silhouette.
    ctrl = _combo_scene(_PROMPTS, 99)
    chip = _chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_IDLE)
    mid = ctrl._chip // 2
    row = [chip.get_at((x, mid)).a for x in range(ctrl._chip)]
    core = max(row)
    assert COMBO_VIEW_CHIP_ALPHA - 3 <= core <= COMBO_VIEW_CHIP_ALPHA, \
        "the fill carries the knob alpha — dark enough to read against the board"
    assert row[0] >= core * 0.9, "the left edge starts at full strength: a step, not a ramp"
    assert row[-1] >= core * 0.9, "so does the right edge"
    assert min(row) >= core * 0.9, "no fade band anywhere across the row"
    col = [chip.get_at((mid, y)).a for y in range(ctrl._chip)]
    assert col[0] >= core * 0.9 and col[-1] >= core * 0.9 and min(col) >= core * 0.9

    top = [chip.get_at((x, 1)).a for x in range(ctrl._chip)]
    assert top[-2] == 0, "the tr cut corner is genuinely cut away"
    blend = [a for a in top if 0 < a < core * 0.85]
    assert len(blend) <= 3, "the cut diagonal gets antialiasing pixels, never a feather band"


def test_next_expected_chip_wears_the_accent_and_it_moves_with_progress():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    n = len(_PROMPTS)
    assert [ctrl._chip_state(i) for i in range(n)] == [_CHIP_NEXT] + [_CHIP_IDLE] * (n - 1), \
        "the opening chip is the you-are-here affordance"
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    assert [ctrl._chip_state(i) for i in range(n)] == \
        [_CHIP_DONE, _CHIP_NEXT] + [_CHIP_IDLE] * (n - 2), \
        "a correct press hands the accent to the next chip"
    done = _combo()
    _run_correct(done)
    assert [done._chip_state(i) for i in range(n)] == [_CHIP_DONE] * n, \
        "a completed run leaves no chip claiming to be next"


def _accent_border_pixels(surf):
    hits = 0
    for x in range(surf.get_width()):
        for y in (0, 1):
            c = surf.get_at((x, y))
            if c.a > 80 and c.r > 140 and c.r > c.b + 50:
                hits += 1
    return hits


def test_only_the_next_chip_carries_the_accent_border():
    ctrl = _combo_scene(_PROMPTS, 99)
    nxt = _chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_NEXT)
    assert _accent_border_pixels(nxt) > ctrl._chip // 3, \
        "the next chip's top edge is an unbroken accent line"
    assert _accent_border_pixels(_chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_IDLE)) == 0
    assert _accent_border_pixels(_chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_DONE)) == 0, \
        "upcoming and consumed chips keep the quiet steel border"


def test_consumed_chips_dim_but_keep_a_real_backing():
    ctrl = _combo_scene(_PROMPTS, 99)
    mid = ctrl._chip // 2
    done = _chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_DONE).get_at((mid, mid)).a
    idle = _chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_IDLE).get_at((mid, mid)).a
    assert COMBO_VIEW_CHIP_DONE_ALPHA - 3 <= done <= COMBO_VIEW_CHIP_DONE_ALPHA
    assert done < idle, "a consumed chip recedes behind its green arrow"
    assert done > 90, "but never vanishes — the run stays a legible token row"


def test_consumed_chip_reads_dimmer_than_the_next_chip_on_the_board():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    surf = pg.Surface((700, 700))
    surf.fill((255, 255, 255))
    ctrl.update(400)
    ctrl.draw(surf)
    consumed = _region_brightness(surf, _chip_core_rect(ctrl, 0))
    upcoming = _region_brightness(surf, _chip_core_rect(ctrl, 1))
    assert consumed > upcoming * 1.2, \
        "the dimmer consumed backing lets more board through than the live chip"


def test_chips_draw_over_the_scrim_and_under_the_arrows_and_judgement():
    ctrl = _combo_scene(_PROMPTS, 99)
    order = []
    for name in ("_draw_dance_floor", "_draw_spotlight", "_draw_strip_chips", "_draw_strip",
                 "_draw_flying", "_draw_confetti", "_draw_judgement"):
        setattr(ctrl, name, (lambda tag: lambda window: order.append(tag))(name))
    ctrl.update(150)
    ctrl.draw(pg.Surface((700, 700), pg.SRCALPHA))
    assert order.index("_draw_dance_floor") < order.index("_draw_strip_chips")
    assert order.index("_draw_spotlight") < order.index("_draw_strip_chips"), \
        "the chips sit above the dance-floor tint and the spotlight scrim"
    for above in ("_draw_strip", "_draw_flying", "_draw_confetti", "_draw_judgement"):
        assert order.index("_draw_strip_chips") < order.index(above), \
            "arrows, the popped-off arrow and the judgement all read on top of the chips"


def test_fire_streak_still_reads_over_the_chips():
    # the flames were the plate's hardest customer and they stay the chips':
    # drawn after the chip pass, they must lose none of their punch to it.
    def fire_brightness(chipped):
        ctrl = _combo_scene(_PROMPTS, 99)
        if not chipped:
            ctrl._draw_strip_chips = lambda window: None
        for i, direction in enumerate(_PROMPTS[:3]):
            ctrl.update(150 * (i + 1))
            ctrl.handle_event(_key(direction))
        assert ctrl._fire_active() is True
        ctrl.update(450 + int(COMBO_VIEW_FIRE_IGNITE_MS))
        surf = pg.Surface((700, 700))
        surf.fill((0, 0, 0))
        ctrl.draw(surf)
        rect = pg.Rect(0, 0, ctrl._fire_size // 2, ctrl._fire_size // 2)
        rect.center = (ctrl._strip_slots[ctrl._progress], ctrl._strip_y)
        return _region_brightness(surf, rect)

    assert fire_brightness(True) > fire_brightness(False) * 0.9


def test_chips_cover_every_slot_and_geometry_survives_consumption():
    # the chevron drop shadow died with the plate: a solid chip under every arrow
    # is the contrast backing now, so each slot must actually own a full chip.
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    assert len(ctrl._strip_slots) == len(_PROMPTS)
    arrow_span = _direction_chevron(ctrl._strip_big, Colors.accent, "up").get_width()
    assert ctrl._chip >= arrow_span, \
        "the chip contains the biggest arrow footprint in any orientation"
    spacing = ctrl._strip_slots[1] - ctrl._strip_slots[0]
    assert spacing > ctrl._chip, "tokens keep daylight between them"
    geometry = (ctrl._chip, ctrl._chip_cut, tuple(ctrl._strip_slots))
    _run_correct(ctrl)
    assert ctrl._progress == len(_PROMPTS)
    assert (ctrl._chip, ctrl._chip_cut, tuple(ctrl._strip_slots)) == geometry, \
        "consumed arrows stay on their chips, so the row never reflows mid-check"


def test_chip_geometry_derives_from_the_named_knobs():
    cell = 99
    ctrl = _combo_scene(_PROMPTS, cell)
    pad = max(int(cell * COMBO_VIEW_CHIP_PAD_FRAC), COMBO_VIEW_CHIP_PAD_MIN_PX)
    arrow_span = _direction_chevron(ctrl._strip_big, Colors.accent, "up").get_width()
    assert ctrl._chip == arrow_span + 2 * pad
    assert ctrl._chip_cut == max(int(ctrl._chip * COMBO_VIEW_CHIP_CUT_FRAC), 3)
    gap = max(int(cell * COMBO_VIEW_CHIP_GAP_FRAC), COMBO_VIEW_CHIP_GAP_MIN_PX)
    assert ctrl._strip_slots[1] - ctrl._strip_slots[0] == ctrl._chip + gap
    assert 0 < COMBO_VIEW_CHIP_DONE_ALPHA < COMBO_VIEW_CHIP_ALPHA < 255, \
        "chips are translucent, never opaque slabs, and consumed ones sit dimmer"
    assert 0 < COMBO_VIEW_CHIP_CUT_FRAC < 0.5, "the cut leaves a chip, not a triangle"


def test_relayout_resizes_the_chips_with_the_cell():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    small = ctrl._chip
    ctrl.relayout(pg.Rect(0, 0, 160, 160))
    assert ctrl._chip > small, \
        "a resize rebuilds the chips for the new cell instead of stretching stale ones"
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.update(200)
    ctrl.draw(surf)


def test_chips_arrive_staggered_with_their_arrows():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    surf = pg.Surface((700, 700))
    surf.fill((255, 255, 255))
    ctrl.update(int(COMBO_VIEW_INTRO_ARROW_MS))
    ctrl.draw(surf)
    first = _region_brightness(surf, _chip_core_rect(ctrl, 0))
    last = _region_brightness(surf, _chip_core_rect(ctrl, len(_PROMPTS) - 1))
    assert first < last * 0.6, \
        "the first chip has landed dark while the last is still arriving with its arrow"


def test_exit_fade_lifts_the_chips_with_the_check():
    def bottom_probe(ctrl, surf):
        rect = pg.Rect(0, 0, ctrl._chip // 3, 5)
        rect.centerx = ctrl._strip_slots[1]
        rect.bottom = ctrl._strip_y + ctrl._chip // 2 - 3
        return _region_brightness(surf, rect)

    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    last = _three_wrongs(ctrl, start=3000, step=300)
    ctrl.update(last + int(COMBO_VIEW_EXIT_FADE_MS) // 2)
    mid_surf = pg.Surface((700, 700))
    mid_surf.fill((255, 255, 255))
    ctrl.draw(mid_surf)
    mid = bottom_probe(ctrl, mid_surf)
    ctrl.update(last + int(COMBO_VIEW_EXIT_FADE_MS) + 50)
    after_surf = pg.Surface((700, 700))
    after_surf.fill((255, 255, 255))
    ctrl.draw(after_surf)
    after = bottom_probe(ctrl, after_surf)
    assert after >= 750, "once the exit fade completes the chips are fully lifted"
    assert mid < after - 80, "mid-fade the chips are still visibly there"


def test_exit_fade_lifts_arrows_pad_and_pips_in_sync_with_the_chips():
    # Shipped bug: only the chip alpha multiplied the exit fade, so chips vanished
    # under still-solid arrows and the pad/pips snapped off with the overlay. The
    # whole unit must ride the same curve: visible mid-fade, fully gone at the end.
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    last = _three_wrongs(ctrl, start=3000, step=300)

    def probes(at_ms):
        ctrl.update(at_ms)
        surf = pg.Surface((700, 700))
        surf.fill((255, 255, 255))
        ctrl.draw(surf)
        arrow = pg.Rect(0, 0, 8, 8)
        arrow.center = (ctrl._strip_slots[2], ctrl._strip_y)
        pad = pg.Rect(0, 0, 8, 8)
        pad.center = (ctrl._pad_center[0], ctrl._pad_center[1] - int(ctrl._pad_r * 0.6))
        from chessshootout.frontend.skillcheck.combo_view import \
            COMBO_VIEW_PIP_ROW_GAP_FRAC
        pip = pg.Rect(0, 0, 8, 8)
        pip.center = (ctrl._pad_center[0],
                      ctrl._pad_bottom
                      + max(int(ctrl._cell * COMBO_VIEW_PIP_ROW_GAP_FRAC), 10))
        return [_region_brightness(surf, r) for r in (arrow, pad, pip)]

    mid = probes(last + int(COMBO_VIEW_EXIT_FADE_MS) // 2)
    after = probes(last + int(COMBO_VIEW_EXIT_FADE_MS) + 50)
    for name, m, a in zip(("arrow", "pad", "pip"), mid, after):
        assert a >= 750, f"the {name} must be fully lifted when the exit fade completes"
        assert m < a - 40, f"the {name} is still visibly present mid-fade"


def test_chip_surfaces_allocate_nothing_per_frame():
    ctrl = _combo_scene(_PROMPTS, 99)
    surf = pg.Surface((700, 700), pg.SRCALPHA)
    ctrl.update(16)
    ctrl.draw(surf)
    chip = _chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_NEXT)
    size = len(_CHIP_CACHE)
    for i in range(2, 60):
        ctrl.update(i * 16)
        ctrl.draw(surf)
    assert len(_CHIP_CACHE) == size, "60 frames must not add a single cache entry"
    assert _chip_surface(ctrl._chip, ctrl._chip_cut, _CHIP_NEXT) is chip


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


def _three_wrongs(ctrl, start=300, step=300):
    t = start
    for _ in range(COMBO_MAX_WRONGS):
        ctrl.update(t)
        ctrl.handle_event(_key("down"))
        t += step
    return t - step


def test_resize_reanchors_the_pad_to_the_new_board_center():
    # game.relayout hands the new cell rect BEFORE the new board rect; the old
    # code left the pad anchored on the stale board center until the next check.
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    assert ctrl._pad_center == (350, 350)
    ctrl.relayout(pg.Rect(0, 0, 90, 90))
    ctrl.set_board_rect(pg.Rect(100, 60, 480, 480))
    assert ctrl._pad_center == (340, 300), "the pad re-centers on the new board rect"
    assert ctrl._spot_layer.get_size() == (480, 480)


def test_relayout_drops_stale_inflight_pop_offs():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    assert len(ctrl._flying) == 1
    ctrl.relayout(pg.Rect(0, 0, 120, 120))
    assert ctrl._flying == [], "a resize drops pop-offs pinned to the old strip pixels"


def test_online_deadline_resolve_presents_the_fail():
    # an online check never self-fails at the deadline; when the server's fail
    # verdict lands on a still-open controller the verdict itself must present
    # (wheel/aim/mole emit theirs via _emit_verdict; combo was silent+blank).
    audio = MagicMock()
    ctrl = _combo(on_shot=MagicMock(), audio=audio)
    ctrl.update(5200)
    assert ctrl.landed is None and ctrl._judgement is None
    ctrl.resolve(False)
    assert ctrl._judgement == _JUDGE_FAIL
    assert ctrl._fail_started is not None, "the strip deflate runs off the verdict"
    audio.play_combo_fail.assert_called_once()


def test_online_resolve_win_on_an_unpresented_controller_presents_the_win():
    audio = MagicMock()
    ctrl = _combo(on_shot=MagicMock(), audio=audio)
    ctrl.update(600)
    ctrl.resolve(True)
    assert ctrl._confetti is not None
    audio.play_combo_complete.assert_called_once()


def test_online_resolve_matching_the_optimistic_win_never_double_presents():
    audio = MagicMock()
    ctrl = _combo(on_shot=MagicMock(), audio=audio)
    _run_correct(ctrl)
    audio.play_combo_complete.assert_called_once()
    confetti = ctrl._confetti
    ctrl.update(900)
    ctrl.resolve(True)
    audio.play_combo_complete.assert_called_once()
    assert ctrl._confetti is confetti, "the running confetti burst is kept, not respawned"


def test_online_verdict_mismatch_retracts_the_optimistic_win():
    audio = MagicMock()
    ctrl = _combo(on_shot=MagicMock(), audio=audio)
    _run_correct(ctrl)
    assert ctrl._confetti is not None
    ctrl.update(900)
    ctrl.resolve(False)
    assert ctrl.landed is False
    assert ctrl._confetti is None and ctrl._torn_until is None, \
        "a server fail on an optimistic win takes the party back"
    assert ctrl._judgement == _JUDGE_FAIL
    audio.play_combo_fail.assert_called_once()


def test_optimistic_online_close_freezes_the_spotlight_before_the_verdict():
    ctrl = _combo(on_shot=MagicMock(), board_rect=pg.Rect(0, 0, 700, 700))
    _three_wrongs(ctrl)
    assert ctrl.landed is None, "online: the server owns the verdict"
    frozen = ctrl._spot_radius()
    ctrl.update(4500)
    assert ctrl._spot_radius() == frozen, \
        "the countdown light stops at the local close, not at the late verdict"


def test_exit_fade_holds_full_while_live_then_decays_to_zero():
    ctrl = _combo()
    ctrl.update(2000)
    assert ctrl._exit_fade() == 1.0
    last = _three_wrongs(ctrl)
    ctrl.update(last + int(COMBO_VIEW_EXIT_FADE_MS) // 2)
    assert 0.0 < ctrl._exit_fade() < 1.0
    ctrl.update(last + int(COMBO_VIEW_EXIT_FADE_MS) + 50)
    assert ctrl._exit_fade() == 0.0


def test_exit_fade_lifts_the_scrim_off_the_board():
    ctrl = _combo(board_rect=pg.Rect(0, 0, 700, 700))
    last = _three_wrongs(ctrl, start=3000, step=300)
    ctrl.update(last + int(COMBO_VIEW_EXIT_FADE_MS) + 50)
    surf = pg.Surface((700, 700))
    surf.fill((255, 255, 255))
    ctrl.draw(surf)
    corner = surf.get_at((5, 5))
    assert corner[:3] == (255, 255, 255), \
        "once the exit fade completes the board corner is fully lit again"


def test_beat_phase_is_continuous_across_the_tempo_ramp():
    ctrl = _combo()
    for t in range(0, 160, 16):
        ctrl.update(t)
    before = ctrl._beat()
    ctrl.handle_event(_key("up"))
    assert ctrl._beat() == before, "a press ramps the bpm without snapping the phase"
    ctrl.update(176)
    assert ctrl._beat() != before, "the beat keeps advancing at the new tempo"


def test_hitstop_pauses_the_beat():
    ctrl = _combo()
    ctrl.update(300)
    ctrl.handle_event(_key("down"))
    frozen = ctrl._beat()
    ctrl.update(330)
    assert ctrl._beat() == frozen, "the dance freezes for the wrong-press hitstop"
    ctrl.update(1000)
    assert ctrl._beat() != frozen


def test_accepted_press_nudges_the_pad_toward_the_direction():
    ctrl = _combo()
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    dx, dy = ctrl._press_offset()
    assert dx == 0 and dy < 0, "the pad dips toward the pressed wedge"
    ctrl.update(150 + int(COMBO_VIEW_PRESS_NUDGE_MS))
    assert ctrl._press_offset() == (0, 0), "the nudge springs back and stays put"


def test_paced_out_press_does_not_restart_the_nudge():
    ctrl = _combo()
    ctrl.update(150)
    ctrl.handle_event(_key("up"))
    nudge = ctrl._press_nudge
    ctrl.update(190)
    ctrl.handle_event(_key("down"))
    assert ctrl._press_nudge is nudge, "a press the pacer swallowed moves nothing"


def test_intro_staggers_the_arrows_and_raises_the_pad():
    ctrl = _combo()
    assert ctrl._intro_k() == 0.0
    assert ctrl._slot_intro_k(0) == 0.0
    ctrl.update(int(COMBO_VIEW_INTRO_ARROW_MS))
    assert ctrl._slot_intro_k(0) == 1.0
    assert ctrl._slot_intro_k(len(_PROMPTS) - 1) < 1.0, \
        "the last arrow is still arriving while the first has landed"
    ctrl.update(int(COMBO_VIEW_INTRO_ARROW_MS
                    + COMBO_VIEW_INTRO_STAGGER_MS * (len(_PROMPTS) - 1)))
    assert ctrl._slot_intro_k(len(_PROMPTS) - 1) == 1.0
    assert ctrl._intro_k() == 1.0


def test_intro_finishes_inside_the_engine_intro_budget():
    n = 7
    last_arrow = COMBO_VIEW_INTRO_ARROW_MS + COMBO_VIEW_INTRO_STAGGER_MS * (n - 1)
    assert max(last_arrow, COMBO_VIEW_INTRO_FADE_MS) <= COMBO_INTRO_MS + 50, \
        "the arrival animation must not eat into the answering time the engine reserves"


def test_intro_leaves_the_strip_region_empty_on_the_first_frames():
    ctrl = _combo_scene(_PROMPTS, 99)
    surf = pg.Surface((700, 700))
    surf.fill((0, 0, 0))
    ctrl.update(5)
    ctrl.draw(surf)
    rect = pg.Rect(0, 0, ctrl._strip_big, ctrl._strip_big)
    rect.center = (ctrl._strip_slots[0], ctrl._strip_y)
    early = _region_brightness(surf, rect)
    surf.fill((0, 0, 0))
    ctrl.update(600)
    ctrl.draw(surf)
    settled = _region_brightness(surf, rect)
    assert settled > early * 3, "arrows fade and drop in instead of popping fully formed"


def test_resume_mid_check_skips_the_intro():
    ctrl = ComboController(
        ComboChallenge(prompts=_PROMPTS, deadline_ms=5000.0),
        pg.Rect(0, 0, 80, 80), now_ms=-800, deadline_ms=5000,
        on_shot=MagicMock(), miss_count=1, progress=2)
    ctrl.update(0)
    assert ctrl._intro_k() == 1.0
    assert ctrl._slot_intro_k(len(_PROMPTS) - 1) == 1.0, \
        "a resumed check re-opens fully formed at its true elapsed"


def test_fire_ignition_cues_the_streak_sound_once():
    audio = MagicMock()
    ctrl = _combo(audio=audio)
    for i, direction in enumerate(_PROMPTS[:3]):
        ctrl.update(150 * (i + 1))
        ctrl.handle_event(_key(direction))
    audio.play_combo_streak.assert_called_once()
    assert ctrl._fire_started_ms == 450, "ignition is stamped at the third BRILLIANT"
    ctrl.update(600)
    ctrl.handle_event(_key(_PROMPTS[3]))
    audio.play_combo_streak.assert_called_once(), "a fourth BRILLIANT never re-cues"


def test_wrong_press_douses_the_ignition_stamp():
    ctrl = _combo(audio=MagicMock())
    for i, direction in enumerate(_PROMPTS[:3]):
        ctrl.update(150 * (i + 1))
        ctrl.handle_event(_key(direction))
    assert ctrl._fire_started_ms is not None
    ctrl.update(700)
    ctrl.handle_event(_key("up"))
    assert ctrl._fire_started_ms is None


def test_passive_mirror_never_cues_the_streak_sound():
    audio = MagicMock()
    ctrl = _combo(passive=True, audio=audio)
    for p in (1, 2, 3):
        ctrl.update(150 * p)
        ctrl.spectate_shot(150 * p, 0, True, progress=p)
    audio.play_combo_streak.assert_not_called()


def test_judgement_alpha_holds_full_then_fades():
    ctrl = _combo()
    hold = COMBO_VIEW_JUDGE_HOLD_MS * COMBO_VIEW_JUDGE_FADE_FRAC
    assert ctrl._judge_alpha(0) == 255
    assert ctrl._judge_alpha(hold) == 255, "the word stays readable through the hold"
    fading = ctrl._judge_alpha((hold + COMBO_VIEW_JUDGE_HOLD_MS) / 2)
    assert 0 < fading < 255
    assert ctrl._judge_alpha(COMBO_VIEW_JUDGE_HOLD_MS) <= 1


def test_spectate_fast_forward_uses_expected_directions_for_intermediate_steps():
    ctrl = _combo(passive=True, audio=MagicMock())
    ctrl.update(400)
    ctrl.spectate_shot(390, 0, False, progress=2, direction="left")
    assert ctrl._progress == 2
    assert set(ctrl._receptor_flash) == {"up", "left"}, \
        "the catch-up step flashes the prompt it consumed; only the live press " \
        "uses the relayed direction"
