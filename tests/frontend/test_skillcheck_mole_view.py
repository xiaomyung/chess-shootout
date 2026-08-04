"""Whack-a-mole skill-check view controller: click/Space shots share one recoil
lockout — a locked shot gets NO muzzle/kick/casing, only a dry-click cue, so the
fire rate is felt — hits adjudicate through the engine's hit_at (grace window
included), and BOTH outcomes end on one shared jump-out: the victim rises out of
its home pit (RISE), hops through an arc half a cell high (HOP), lands with a
squash (LAND_SQUASH) and settles on its own square at exactly the rest position
the board draws a piece at — so the fail handoff has no seam and nothing appears
out of thin air. A win keeps the shredded tier through the jump and then plays the
deep-fry flash (WIN_HOLD covers hitstop + jump + fry); a fail heals the victim in
even steps through the arc so it lands intact, holds its home pit open until
touchdown and then shrinks it closed over PIT_CLOSE (the other pits keep their
300ms fade), and the session restores the piece WITHOUT the board drop.
Damage tiers interpolate over the quota (ceil(TORN_MAX_TIER * hits / required)) so
a queen's five hits break the sprite as evenly as a pawn's three. The taunt moved
out of the controller entirely — the pure engine's mole.pick_taunt(seed) is
deterministic per check seed so mover and spectator show the same line on the board
layer. A telegraphing pop that pop_mandatory marks as must-hit hard-blinks between
Colors.loss and near-white on a faster period with a thicker rim, instead of the
calm accent->white lerp. Online every registered shot relays exactly once
with a keyword (row_f, col_f) target and the client never self-commits —
resolve() carries the server verdict; both verdicts hold their own choreography
online and on the passive mirror. Passive mirrors
swallow no input, never touch the OS cursor, stay muted, and replay the mover's
shots via spectate_shot — which mirrors the mover's pop bookkeeping so a relayed
hit ducks the mole on the mirror too. The OS cursor hides on active construction
and is restored on every terminal path. CHESS_DEBUG_HITBOX draws the engine's true
hit region (MOLE_HITBOX_FRAC circle on each hole SQUARE center, mapped through the
controller's affine) and costs nothing when unset.
"""

import gc
import logging
from unittest.mock import MagicMock, call

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.mole_view import (
    MoleController, MOLE_VIEW_FAIL_FADE_MS, MOLE_VIEW_FAIL_HOLD_MS,
    MOLE_VIEW_WIN_HOLD_MS, MOLE_VIEW_HITSTOP_KILL_MS, MOLE_VIEW_WIN_FRY_MS,
    MOLE_VIEW_WIN_DEADPAN_MS, MOLE_VIEW_RETREAT_MS, MOLE_VIEW_PIP_OFFSET_FRAC,
    MOLE_VIEW_JUMP_RISE_MS, MOLE_VIEW_JUMP_HOP_MS, MOLE_VIEW_LAND_SQUASH_MS,
    MOLE_VIEW_REGROW_MS,
    MOLE_VIEW_PIT_CLOSE_MS, MOLE_VIEW_DANGER_PULSE_MS, MOLE_VIEW_PULSE_MS,
    _pit_telegraph_surface, _MOLE_STATIC_CACHE)
from chessshootout.frontend.skillcheck.juice import TORN_REGROW_STEPS
from chessshootout.frontend.visual.colors import Colors
from chessshootout.skillcheck.mole import (
    MoleChallenge, MolePop, MOLE_TAUNTS, pick_taunt)

_JUMP_MS = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS
_JUMP_TOTAL_MS = _JUMP_MS + MOLE_VIEW_LAND_SQUASH_MS

_pygame_init = pygame_display(640, 640)

_CELL = 80
_HOLES = ((2, 2), (2, 4), (5, 5))
_POPS = (MolePop(0, 500.0, 700.0, 1500.0),
         MolePop(1, 1700.0, 1900.0, 2700.0),
         MolePop(2, 2900.0, 3100.0, 3900.0),
         MolePop(0, 4100.0, 4300.0, 5100.0),
         MolePop(1, 5300.0, 5500.0, 6300.0))


def _geom_for(cell):
    return lambda sq: (sq.col * cell + cell // 2, sq.row * cell + cell // 2)


def _victim(cell):
    surf = pg.Surface((cell, cell), pg.SRCALPHA)
    pg.draw.circle(surf, (120, 160, 210, 255), (cell // 2, cell // 2), cell // 3)
    return surf


def _challenge(pops=_POPS, hole_count=3, hits_required=3, deadline_ms=7000.0):
    return MoleChallenge(pops=pops, hole_count=hole_count, hits_required=hits_required,
                         deadline_ms=deadline_ms)


def _mole(cell=_CELL, challenge=None, **kw):
    challenge = challenge or _challenge()
    kw.setdefault("hole_squares", _HOLES)
    kw.setdefault("geom", _geom_for(cell))
    kw.setdefault("audio", MagicMock())
    kw.setdefault("victim_surface", _victim(cell))
    return MoleController(challenge, pg.Rect(3 * cell, 4 * cell, cell, cell), 0,
                          challenge.deadline_ms, **kw)


def _click(pos):
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": pos})


def _space():
    return pg.event.Event(pg.KEYDOWN, {"key": pg.K_SPACE, "unicode": " ", "mod": 0})


def _hole_px(index, cell=_CELL):
    row, col = _HOLES[index]
    return (col * cell + cell // 2, row * cell + cell // 2)


def test_click_at_hole_center_registers_a_hit():
    ctrl = _mole()
    ctrl.update(800)
    assert ctrl.handle_event(_click(_hole_px(0))) is True
    assert ctrl._progress == 1
    ctrl._audio.play_whack_hit.assert_called_once()
    assert ctrl.landed is None, "one hit is not the quota — nothing commits yet"


def test_second_click_inside_the_lockout_does_not_register():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(900)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "a shot inside the recoil lockout never registers"
    assert ctrl._audio.play_whack_hit.call_count == 1
    ctrl._audio.play_whiff_ricochet.assert_not_called()


def test_lockout_shot_gets_a_dry_click_and_none_of_the_shot_feedback():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl._audio.play_whack_dry.assert_not_called()
    assert len(ctrl._casings) == 1
    flash_ms = ctrl._flash_ms
    flash_px = ctrl._flash_px
    ctrl.update(900)
    ctrl.handle_event(_click((600, 600)))
    assert len(ctrl._casings) == 1, "a locked shot ejects no casing"
    assert ctrl._flash_ms == flash_ms, "a locked shot fires no muzzle flash"
    assert ctrl._flash_px == flash_px, "and never moves the flash anchor"
    ctrl._audio.play_whack_dry.assert_called_once()


def test_empty_spot_click_is_a_whiff():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._progress == 0
    ctrl._audio.play_whiff_ricochet.assert_called_once()
    ctrl._audio.play_whack_hit.assert_not_called()


def test_space_fires_at_the_mouse_and_shares_the_click_lockout(monkeypatch):
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: _hole_px(0))
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((40, 40)))
    assert ctrl._progress == 0, "the opener is a registered whiff"
    ctrl.update(880)
    ctrl.handle_event(_space())
    assert ctrl._progress == 0, "Space inside the click's lockout does not register"
    ctrl.update(1000)
    ctrl.handle_event(_space())
    assert ctrl._progress == 1, "Space after the lockout fires at the mouse position"


def test_third_hit_commits_the_win_after_the_jump_hold():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    ctrl.update(3200)
    ctrl.handle_event(_click(_hole_px(2)))
    assert ctrl.landed is True
    ctrl._audio.play_whack_kill.assert_called_once()
    assert ctrl.done is False
    ctrl.update(3200 + MOLE_VIEW_WIN_HOLD_MS - 50)
    assert ctrl.done is False, "the jump-out choreography still owns the overlay"
    ctrl.update(3200 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_win_hold_covers_the_hitstop_the_jump_and_the_whole_fry_flash():
    # The gun capture may only fire once the fry window has fully played; a hold
    # shorter than the sum would cut the flash mid-frame.
    total = (MOLE_VIEW_HITSTOP_KILL_MS + _JUMP_TOTAL_MS
             + MOLE_VIEW_WIN_DEADPAN_MS + MOLE_VIEW_WIN_FRY_MS)
    assert total <= MOLE_VIEW_WIN_HOLD_MS
    ctrl = _mole()
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    fry_start = 3200 + MOLE_VIEW_HITSTOP_KILL_MS + _JUMP_TOTAL_MS + MOLE_VIEW_WIN_DEADPAN_MS
    ctrl.update(int(fry_start) - 20)
    assert ctrl._flash_active() is False, "the fry waits for the landing plus the deadpan beat"
    ctrl.update(int(fry_start) + 10)
    assert ctrl._flash_active() is True
    ctrl.update(int(fry_start + MOLE_VIEW_WIN_FRY_MS) + 1)
    assert ctrl._flash_active() is False
    assert ctrl.done is False, "the fry finishes inside the hold, not after it"


def test_fail_hold_covers_the_jump_and_the_home_pit_closing():
    assert _JUMP_MS + MOLE_VIEW_PIT_CLOSE_MS <= MOLE_VIEW_FAIL_HOLD_MS
    assert _JUMP_TOTAL_MS <= MOLE_VIEW_FAIL_HOLD_MS


def test_grace_window_click_still_hits():
    ctrl = _mole()
    ctrl.update(1600)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "t_down + 100ms sits inside MOLE_GRACE_MS and still lands"


def _one_pop_challenge():
    return _challenge(pops=(MolePop(0, 500.0, 700.0, 1990.0),), hits_required=1,
                      deadline_ms=2000.0)


def test_deadline_commits_a_fast_fail_with_no_controller_taunt():
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(1999)
    assert ctrl.landed is None
    ctrl.update(2000)
    assert ctrl.landed is False
    ctrl.update(2000 + MOLE_VIEW_FAIL_HOLD_MS - 1)
    assert ctrl.done is False
    ctrl.update(2000 + MOLE_VIEW_FAIL_HOLD_MS)
    assert ctrl.done is True, "the fail hold runs the whole jump-out, then the pit close"
    ctrl._audio.play_mole_taunt.assert_not_called()
    for attr in ("_taunt", "_taunt_shown", "_taunt_text"):
        assert not hasattr(ctrl, attr), \
            "the taunt moved to the board layer — the controller keeps no taunt state"


def test_quota_exhaustion_commits_fail_before_the_deadline():
    ctrl = _mole()
    ctrl.update(4019)
    assert ctrl.landed is None, "the third pop is still hittable inside its grace window"
    ctrl.update(4020)
    assert ctrl.landed is False, \
        "three expired pops with two left cannot reach the 3-hit quota — fail early"


def test_online_registered_shot_relays_once_with_a_keyword_target():
    on_shot = MagicMock()
    ctrl = _mole(on_shot=on_shot)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    on_shot.assert_called_once()
    args, kwargs = on_shot.call_args
    assert args == (800,)
    assert kwargs == {"target": (2.5, 2.5)}
    assert isinstance(kwargs["target"][0], float) and isinstance(kwargs["target"][1], float)
    ctrl.update(900)
    ctrl.handle_event(_click(_hole_px(0)))
    assert on_shot.call_count == 1, "a lockout shot never reaches the wire"
    ctrl.update(1100)
    ctrl.handle_event(_click((600, 600)))
    assert on_shot.call_count == 2, "a registered whiff still relays"


def test_online_never_self_commits_a_terminal():
    ctrl = _mole(on_shot=MagicMock())
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    assert ctrl._progress == 3, "optimistic local hits still fill the displayed progress"
    assert ctrl.landed is None, "the quota online is only the server's to confirm"
    ctrl.update(9000)
    assert ctrl.landed is None and ctrl.done is False, "no self-fail at the deadline online"


def test_online_resolve_fail_holds_the_whole_jump_not_the_shared_result_hold():
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(900)
    ctrl.resolve(False)
    assert ctrl.landed is False
    assert ctrl.done is False
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the shared 200ms hold would cut the jump-out in half"
    ctrl.update(900 + MOLE_VIEW_FAIL_HOLD_MS)
    assert ctrl.done is True


def test_online_resolve_win_holds_through_the_jump():
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(900)
    ctrl.resolve(True)
    assert ctrl.landed is True
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the shredded jump-out plays online too"
    ctrl.update(900 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_spectator_resolve_holds_the_same_totals_as_the_mover():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.resolve(True)
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the mirror shows the same jump-out as the mover"
    ctrl.update(900 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True

    missed = _mole(passive=True)
    missed.update(900)
    missed.resolve(False)
    missed.update(900 + MOLE_VIEW_FAIL_HOLD_MS - 1)
    assert missed.done is False, "the mirror sits through the heal-and-land too"
    missed.update(900 + MOLE_VIEW_FAIL_HOLD_MS)
    assert missed.done is True


def test_passive_ignores_input_and_mutes_every_cue():
    audio = MagicMock()
    ctrl = _mole(passive=True, audio=audio)
    assert ctrl.handle_event(_click(_hole_px(0))) is False
    ctrl.update(800)
    ctrl.update(9000)
    assert ctrl.landed is None and ctrl.done is False
    assert audio.method_calls == [], "the passive guard silences the mount and schedule cues"


def test_passive_never_touches_the_cursor(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole(passive=True)
    ctrl.update(500)
    visible.assert_not_called()
    assert ctrl._cursor_hidden is False


def test_spectate_shot_adopts_progress_and_fires_the_hit_juice():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    assert ctrl._progress == 1
    assert ctrl._trauma.value > 0.0, "a relayed hit shakes the minigame layer"
    assert len(ctrl._impacts) == 1, "the impact marker lands at the mover's target"
    assert len(ctrl._casings) == 1
    ctrl.spectate_shot(820.0, 0, True, progress=1, target=(2.5, 2.5))
    assert ctrl._progress == 1, "a replay without a progress increase adopts nothing"


def test_spectate_hit_ducks_the_mole_like_the_mover_sees():
    # Without the pop bookkeeping the mirror would keep the mole standing until
    # t_down (1500ms) while the mover already saw it duck on the hit.
    ctrl = _mole(passive=True)
    ctrl.update(800)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    assert ctrl._last_hit_pop == 0, "the mirror adopts the pop the mover just hit"
    frame = ctrl._render_pop(800.0)
    assert frame is not None and frame[0] == 0, "the hit pop is the one being drawn"
    ctrl.update(800 + int(MOLE_VIEW_RETREAT_MS) + 40)
    assert ctrl._render_pop(800.0 + MOLE_VIEW_RETREAT_MS + 40) is None, \
        "the hit pop finishes its retreat instead of standing to t_down"


def test_spectate_miss_spawns_dust_without_progress():
    ctrl = _mole(passive=True)
    ctrl.update(700)
    ctrl.spectate_shot(600.0, 0, False, progress=0, target=(7.5, 7.5))
    assert ctrl._progress == 0
    assert len(ctrl._puffs) == 1, "the mover's whiff replays as a dust puff on the mirror"


def test_cursor_hidden_on_construction_and_restored_on_win(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole()
    assert visible.call_args_list[0] == call(False)
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    assert visible.call_args_list[-1] == call(True)


def test_cursor_restored_on_fail(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    assert ctrl.landed is False
    assert visible.call_args_list[-1] == call(True)


def test_cursor_restored_once_on_resolve_and_survives_the_drop(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(600)
    ctrl.resolve(False)
    ctrl.update(600 + MOLE_VIEW_FAIL_HOLD_MS)
    assert ctrl.done is True
    del ctrl
    gc.collect()
    assert visible.call_args_list.count(call(True)) == 1, \
        "the terminal path restores exactly once — dropping the object never double-restores"


def test_close_restores_the_cursor_without_committing(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole()
    ctrl.update(300)
    ctrl.close()
    assert visible.call_args_list[-1] == call(True)
    assert ctrl.landed is None and ctrl.done is False


@pytest.mark.parametrize("cell", [60, 99, 160])
def test_draw_smoke_across_states_and_sizes(cell):
    surf = pg.Surface((8 * cell, 8 * cell))
    surf.fill((200, 200, 200))
    ctrl = _mole(cell=cell)
    for now in (0, 200, 600):
        ctrl.update(now)
        ctrl.draw(surf)
    row, col = _HOLES[1]
    px = surf.get_at((col * cell + cell // 2, row * cell + cell // 2))
    assert px.r + px.g + px.b < 300, "an open pit paints darker than the light backdrop"
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.draw(surf)
        ctrl.handle_event(_click(_hole_px(hole, cell)))
        ctrl.draw(surf)
    assert ctrl.landed is True
    for dt in (100, MOLE_VIEW_HITSTOP_KILL_MS + 120,
               MOLE_VIEW_HITSTOP_KILL_MS + _JUMP_MS + 10,
               MOLE_VIEW_HITSTOP_KILL_MS + _JUMP_TOTAL_MS + MOLE_VIEW_WIN_DEADPAN_MS + 10):
        ctrl.update(3200 + int(dt))
        ctrl.draw(surf)
    failed = _mole(cell=cell, challenge=_one_pop_challenge())
    failed.update(2000)
    failed.draw(surf)
    for dt in (MOLE_VIEW_JUMP_RISE_MS / 2, _JUMP_MS / 2, MOLE_VIEW_FAIL_FADE_MS + 50,
               _JUMP_MS + 10, _JUMP_TOTAL_MS + MOLE_VIEW_PIT_CLOSE_MS,
               MOLE_VIEW_FAIL_HOLD_MS - 1):
        failed.update(2000 + int(dt))
        failed.draw(surf)
    assert failed.landed is False


def _accent_in_band(surf, ctrl):
    accent = pg.Color(Colors.accent)
    n = ctrl.challenge.hits_required
    total = n * ctrl._pip_w + (n - 1) * ctrl._pip_gap
    y0 = ctrl.center[1] + int(ctrl.cell_size * MOLE_VIEW_PIP_OFFSET_FRAC) - 10
    x0 = ctrl.center[0] - total // 2 - 12
    for y in range(max(y0, 0), min(y0 + ctrl._pip_h + 20, surf.get_height())):
        for x in range(max(x0, 0), min(x0 + total + 24, surf.get_width())):
            if surf.get_at((x, y)) == accent:
                return True
    return False


def test_pip_fill_changes_pixels_on_a_hit():
    before = pg.Surface((640, 640))
    before.fill((30, 30, 30))
    after = pg.Surface((640, 640))
    after.fill((30, 30, 30))
    ctrl = _mole()
    ctrl.update(800)
    ctrl.draw(before)
    assert _accent_in_band(before, ctrl) is False, "no pip is filled before the first hit"
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.draw(after)
    assert _accent_in_band(after, ctrl) is True, "the first hit fills a pip with the accent hue"


def test_same_challenge_and_script_reach_the_same_state():
    a, b = _mole(), _mole()
    for ctrl in (a, b):
        ctrl.update(800)
        ctrl.handle_event(_click(_hole_px(0)))
        ctrl.update(2000)
        ctrl.handle_event(_click(_hole_px(1)))
    assert (a._progress, a._last_hit_pop, a.landed) == (b._progress, b._last_hit_pop, b.landed)


def test_pick_taunt_is_deterministic_per_seed_and_varied_across_seeds():
    assert pick_taunt("seed-x") == pick_taunt("seed-x"), \
        "mover and spectator derive the same line from the same check seed"
    texts = {pick_taunt("seed-{}".format(i)) for i in range(30)}
    assert texts <= set(MOLE_TAUNTS)
    assert len(texts) >= 3, "fresh per-check seeds actually rotate the taunt pool"


def _telegraph_surface_for(captured_value, pop_index):
    challenge = MoleChallenge.from_seed("danger-seed", captured_value=captured_value)
    holes = tuple((7, col) for col in range(challenge.hole_count))
    ctrl = _mole(challenge=challenge, hole_squares=holes)
    tele = ctrl._telegraph_hole(challenge.pops[pop_index].t_telegraph_ms + 1.0)
    assert tele is not None and tele == (pop_index, challenge.pops[pop_index].hole)
    return ctrl._telegraph_surface(tele[0])


def test_queen_capture_telegraphs_the_danger_rim_where_the_pop_is_mandatory():
    queen = MoleChallenge.from_seed("danger-seed", captured_value=9)
    pawn = MoleChallenge.from_seed("danger-seed", captured_value=1)
    assert queen.hits_required == 5, \
        "the exact-fit budget solve keeps the queen's 5-of-5 quota at the 5s cap"
    assert queen.pop_mandatory(0, 0) is True, \
        "a perfect-run quota makes every pop mandatory from the first telegraph"
    assert pawn.pop_mandatory(0, 0) is False
    assert pawn.pop_mandatory(2, 0) is True
    danger = _telegraph_surface_for(9, 0)
    plain = _telegraph_surface_for(1, 0)
    assert danger is not plain, "a mandatory pop picks the danger-keyed telegraph surface"
    assert pg.image.tostring(danger, "RGBA") != pg.image.tostring(plain, "RGBA"), \
        "the danger rim blinks hard, visibly different from the calm accent->white pulse"


def _rim_span(surf):
    dark = pg.Color(Colors.well_deep)
    y = surf.get_height() // 2
    return sum(1 for x in range(surf.get_width())
               if surf.get_at((x, y))[:3] == (dark.r, dark.g, dark.b))


def test_danger_telegraph_hard_blinks_and_fattens_the_rim_at_the_same_bucket():
    # The old danger cue lerped toward Colors.loss with the same gentle cosine as
    # the plain one — near-invisible against the accent-red idle rim. The blink is
    # two hard states (loss-red -> near-white) and the hot state also thickens the
    # rim, so a mandatory pop cannot be missed.
    rx, ry = 33, 19
    cold = _pit_telegraph_surface(rx, ry, 0, danger=True)
    hot = _pit_telegraph_surface(rx, ry, 1, danger=True)
    plain = _pit_telegraph_surface(rx, ry, 1, danger=False)
    assert pg.image.tostring(hot, "RGBA") != pg.image.tostring(cold, "RGBA"), \
        "the two blink states are different surfaces, not neighbours on a ramp"
    assert pg.image.tostring(hot, "RGBA") != pg.image.tostring(plain, "RGBA"), \
        "the same bucket renders differently once the danger flag is set"
    assert ("pit_tele", rx, ry, 1, True) in _MOLE_STATIC_CACHE
    assert ("pit_tele", rx, ry, 1, False) in _MOLE_STATIC_CACHE, \
        "the cache key carries the danger flag — the two can never collide"
    assert _rim_span(hot) < _rim_span(cold), \
        "the hot blink eats into the pit mouth: a visibly fatter rim"


def test_danger_pulse_alternates_faster_than_the_calm_telegraph():
    assert MOLE_VIEW_DANGER_PULSE_MS < MOLE_VIEW_PULSE_MS
    challenge = MoleChallenge.from_seed("danger-seed", captured_value=9)
    holes = tuple((7, col) for col in range(challenge.hole_count))
    ctrl = _mole(challenge=challenge, hole_squares=holes)
    ctrl._anim_ms = 0.0
    cold = ctrl._telegraph_surface(0)
    ctrl._anim_ms = MOLE_VIEW_DANGER_PULSE_MS / 2.0
    hot = ctrl._telegraph_surface(0)
    assert cold is not hot, "half a danger period is a full swing to the other state"
    ctrl._anim_ms = float(MOLE_VIEW_DANGER_PULSE_MS)
    assert ctrl._telegraph_surface(0) is cold, "a whole period lands back on the cold state"


def test_mount_and_schedule_cues_fire_on_their_edges():
    ctrl = _mole()
    ctrl._audio.play_mole_fall.assert_called_once()
    ctrl.update(600)
    ctrl._audio.play_mole_telegraph.assert_called_once()
    ctrl._audio.play_mole_pop.assert_not_called()
    ctrl.update(750)
    ctrl._audio.play_mole_pop.assert_called_once()
    ctrl.update(1800)
    assert ctrl._audio.play_mole_telegraph.call_count == 2


def test_relayout_reanchors_geometry():
    ctrl = _mole()
    old_rx = ctrl._pit_rx
    ctrl.relayout(pg.Rect(480, 640, 160, 160))
    assert ctrl.center == (560, 720)
    assert ctrl.cell_size == 160
    assert ctrl._pit_rx > old_rx, "pit geometry rescales off the new cell"


def test_out_of_board_shot_clamps_target_within_wire_bounds():
    on_shot = MagicMock()
    ctrl = _mole(on_shot=on_shot)
    ctrl.update(800)
    ctrl.handle_event(_click((752, 200)))
    _, kwargs = on_shot.call_args
    r, c = kwargs["target"]
    assert 0.0 <= r < 8.0 and 0.0 <= c < 8.0, "an off-board shot never exceeds the wire bound"


def test_sentinel_target_clamps_into_wire_bounds():
    on_shot = MagicMock()
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), 0,
                          ch.deadline_ms, hole_squares=_HOLES, audio=MagicMock(),
                          victim_surface=_victim(_CELL), on_shot=on_shot)
    ctrl.update(800)
    ctrl.handle_event(_click((200, 200)))
    _, kwargs = on_shot.call_args
    assert kwargs["target"] == (0.0, 0.0), \
        "the no-mapper sentinel clamps to an in-range guaranteed miss"
    assert ctrl._progress == 0, "the clamped sentinel never registers a hit"


def test_local_edge_shot_adjudicates_on_the_clamped_value(monkeypatch):
    seen = []
    original = MoleChallenge.hit_at

    def spy(self, elapsed_ms, row_f, col_f, holes, last_hit_pop=-1):
        seen.append((row_f, col_f))
        return original(self, elapsed_ms, row_f, col_f, holes, last_hit_pop)

    monkeypatch.setattr(MoleChallenge, "hit_at", spy)
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((752, 752)))
    assert seen, "the local path adjudicates through the engine"
    for r, c in seen:
        assert r < 8.0 and c < 8.0, "no out-of-range coordinate reaches adjudication"


def test_torn_victim_key_is_per_challenge():
    v = _victim(_CELL)
    other_pops = (MolePop(2, 400.0, 600.0, 1400.0),
                  MolePop(0, 1500.0, 1700.0, 2500.0),
                  MolePop(1, 2600.0, 2800.0, 3600.0))
    a = _mole(victim_surface=v, progress=1)
    b = _mole(challenge=_challenge(pops=other_pops), victim_surface=v, progress=1)
    sa, sb = a._victim_sprite(), b._victim_sprite()
    assert sa is not sb, "distinct challenges never share a cached torn victim"
    assert pg.image.tostring(sa, "RGBA") != pg.image.tostring(sb, "RGBA"), \
        "different pop scripts tear the victim differently"
    assert a._victim_sprite() is sa, "the same check re-uses its cached torn victim"


def test_resume_with_progress_seeds_the_already_hit_pop():
    now = pg.time.get_ticks()
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), now - 1000,
                          ch.deadline_ms, hole_squares=_HOLES, geom=_geom_for(_CELL),
                          audio=MagicMock(), victim_surface=_victim(_CELL), progress=1)
    assert ctrl._last_hit_pop == 0, \
        "resuming mid-pop seeds the hit index so the pop can't be locally re-hit"
    ctrl.update(now)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "the already-hit pop is deduped on the resumed client"
    ctrl.update(now + 900)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._progress == 2, "a later pop still registers normally"


def test_whack_hit_plays_the_pitch_ladder_index():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._audio.play_whack_hit.call_args_list == [call(0), call(1)]


def test_whack_hit_pitch_ladder_muted_when_passive():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    ctrl._audio.play_whack_hit.assert_not_called()


@pytest.mark.parametrize("required, ladder", [
    pytest.param(3, (1, 2, 3), id="pawn_three_hits"),
    pytest.param(4, (1, 2, 3, 3), id="rook_four_hits"),
    pytest.param(5, (1, 2, 2, 3, 3), id="queen_five_hits"),
])
def test_damage_tiers_interpolate_over_the_hit_quota(required, ladder):
    # min(progress, 3) saturated a queen at full shred by hit three and left the
    # last two hits with nothing to show; the ceil interpolation spreads the same
    # three tiers evenly across whatever quota the captured piece bought.
    clean = _mole(challenge=_challenge(hits_required=required))
    assert clean._damage_tier() == 0, "an untouched victim is intact"
    for progress, tier in enumerate(ladder, start=1):
        ctrl = _mole(challenge=_challenge(hits_required=required), progress=progress)
        assert ctrl._damage_tier() == tier, "hit {} of {}".format(progress, required)


_FAIL_AT_MS = 4020


def _fail_at_two_hits():
    ctrl = _mole(challenge=_challenge(pops=_POPS[:3], hits_required=3, deadline_ms=5000.0))
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._progress == 2
    ctrl.update(_FAIL_AT_MS)
    assert ctrl.landed is False, "the last pop expired unhit — the 3-hit quota is out of reach"
    return ctrl


def test_fail_regrow_happens_standing_on_the_square_after_the_jump():
    # The regrow got its own readable beat: the victim stays FULLY damaged
    # through the whole hop (motion would mask the heal), lands, and only then
    # knits itself back over MOLE_VIEW_REGROW_MS while standing still — a
    # bucketed continuous regrowth (juice.TORN_REGROW_STEPS), never one snap.
    ctrl = _fail_at_two_hits()
    jump_ms = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS
    for frac in (0.0, 0.4, 0.8, 0.99):
        ctrl.update(int(_FAIL_AT_MS + jump_ms * frac))
        assert ctrl._regrow_bucket() == 0, \
            "damage is held through the whole arc so the heal is visible at rest"
    sprites = []
    buckets = []
    steps = 10
    for i in range(steps + 1):
        ctrl.update(int(_FAIL_AT_MS + jump_ms + MOLE_VIEW_REGROW_MS * i / steps))
        buckets.append(ctrl._regrow_bucket())
        sprites.append(ctrl._victim_sprite())
    assert buckets == sorted(buckets), "regrowth only ever moves toward clean"
    assert buckets[0] == 0 and buckets[-1] == TORN_REGROW_STEPS
    assert len(set(id(s) for s in sprites)) >= 6, \
        "the repair passes through many distinct frames, not one snap"
    assert sprites[-1] is ctrl._victim, "the heal ends on the untouched source sprite"


def test_fail_hold_covers_the_jump_plus_the_standing_regrow():
    assert MOLE_VIEW_FAIL_HOLD_MS >= (MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS
                                      + MOLE_VIEW_REGROW_MS), \
        "the overlay must stay alive until the piece finishes growing back"


def test_regrow_motes_converge_only_during_the_standing_heal():
    ctrl = _fail_at_two_hits()
    jump_ms = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS
    surf = pg.Surface((640, 640))

    def mote_pixels(t):
        ctrl.update(int(t))
        surf.fill((0, 0, 0))
        ctrl._draw_regrow_motes(surf, (0, 0))
        return sum(1 for x in range(0, 640, 3) for y in range(0, 640, 3)
                   if surf.get_at((x, y))[:3] != (0, 0, 0))

    assert mote_pixels(_FAIL_AT_MS + jump_ms * 0.5) == 0, "no motes mid-hop"
    assert mote_pixels(_FAIL_AT_MS + jump_ms + MOLE_VIEW_REGROW_MS * 0.5) > 0, \
        "parts visibly fly back into the piece while it heals"
    assert mote_pixels(_FAIL_AT_MS + jump_ms + MOLE_VIEW_REGROW_MS + 50) == 0, \
        "motes end with the heal"


def test_win_jump_keeps_the_shredded_victim_all_the_way_down():
    ctrl = _mole()
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    for dt in (MOLE_VIEW_HITSTOP_KILL_MS, MOLE_VIEW_HITSTOP_KILL_MS + _JUMP_MS / 2,
               MOLE_VIEW_HITSTOP_KILL_MS + _JUMP_TOTAL_MS, MOLE_VIEW_WIN_HOLD_MS - 1):
        ctrl.update(3200 + int(dt))
        assert ctrl._regrow_bucket() == 0, "only the fail repairs the victim"
        assert ctrl._damage_tier() == 3


def _pit_dark_pixels(surf, ctrl):
    dark = pg.Color(Colors.well_deep)
    cx, cy = ctrl.center
    count = 0
    for x in range(cx - ctrl._pit_rx, cx + ctrl._pit_rx + 1):
        for y in range(cy - ctrl._pit_ry, cy + ctrl._pit_ry + 1):
            if surf.get_at((x, y))[:3] == (dark.r, dark.g, dark.b):
                count += 1
    return count


def _draw_at(ctrl, now_ms):
    surf = pg.Surface((640, 640))
    surf.fill((200, 200, 200))
    ctrl.update(int(now_ms))
    ctrl.draw(surf)
    return surf


def test_home_pit_holds_open_under_the_fail_jump_then_shrinks_shut():
    # The old fail faded every pit at 300ms, so the victim emerged from a patch of
    # bare board. The home pit is the one it climbs out of — it stays until the feet
    # are down and only then closes.
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    assert ctrl.landed is False
    mid = _draw_at(ctrl, 2000 + MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS / 2)
    assert _pit_dark_pixels(mid, ctrl) > 0, "the home pit is still open mid-hop"
    assert ctrl._home_pit_close_scale() == 1.0, "nothing closes while the feet are in the air"
    _draw_at(ctrl, 2000 + _JUMP_MS + MOLE_VIEW_PIT_CLOSE_MS / 2)
    assert 0.0 < ctrl._home_pit_close_scale() < 1.0, \
        "the mouth shrinks the same way it grew open, only backwards"
    shut = _draw_at(ctrl, 2000 + _JUMP_MS + MOLE_VIEW_PIT_CLOSE_MS)
    assert ctrl._home_pit_close_scale() == 0.0
    assert _pit_dark_pixels(shut, ctrl) == 0, "the ground is whole again before the overlay ends"


def test_fail_landing_frame_sits_exactly_where_the_board_draws_the_piece():
    # The seam that made the piece "appear out of thin air": the overlay's last
    # frame and the board's restored piece must occupy the same pixels.
    rect = pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL)
    solid = pg.Surface((_CELL, _CELL))
    solid.fill((10, 200, 40))
    challenge = _one_pop_challenge()
    ctrl = MoleController(challenge, rect, 0, challenge.deadline_ms, hole_squares=_HOLES,
                          geom=_geom_for(_CELL), audio=MagicMock(), victim_surface=solid)
    ctrl.update(2000)
    surf = _draw_at(ctrl, 2000 + MOLE_VIEW_FAIL_HOLD_MS - 1)
    assert surf.get_at(rect.topleft)[:3] == (10, 200, 40)
    assert surf.get_at((rect.right - 1, rect.bottom - 1))[:3] == (10, 200, 40)
    assert surf.get_at((rect.x - 1, rect.bottom - 1))[:3] != (10, 200, 40), \
        "the settled sprite covers its own cell and not a pixel more"


def test_hitbox_overlay_only_draws_when_the_debug_flag_is_set(monkeypatch):
    monkeypatch.delenv("CHESS_DEBUG_HITBOX", raising=False)
    off = _draw_at(_mole(), 800)
    monkeypatch.setenv("CHESS_DEBUG_HITBOX", "1")
    ctrl = _mole()
    assert ctrl._debug_hitbox is True, "the flag is read once, at construction"
    on = _draw_at(ctrl, 800)
    assert pg.image.tostring(on, "RGBA") != pg.image.tostring(off, "RGBA")


def test_hitbox_outline_traces_the_engine_hit_region_on_the_square_center(monkeypatch):
    monkeypatch.setenv("CHESS_DEBUG_HITBOX", "1")
    ctrl = _mole()
    surf = _draw_at(ctrl, 800)
    row, col = _HOLES[2]
    cx, cy = _hole_px(2)
    edge = int(_CELL * 0.55)
    outline = pg.Color(Colors.spectate)
    assert surf.get_at((cx + edge - 1, cy))[:3] == (outline.r, outline.g, outline.b), \
        "the ring sits MOLE_HITBOX_FRAC of a cell out from the square center"
    assert ctrl._board_to_px(row + 0.5, col + 0.5) == (float(cx), float(cy)), \
        "the ring is anchored on the square center the engine measures from"


def test_on_hit_px_fires_once_per_registered_hit_at_the_impact():
    # The attacker's gun shoots at what the bullet actually hit — the popped
    # mole's hole, not the raw cursor — so the slug and the debris agree.
    shots = []
    ctrl = _mole(on_hit_px=shots.append)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    assert shots == [_hole_px(0)], "one registered hit, one projectile, on the hit hole"


def test_on_hit_px_stays_silent_on_whiffs_and_locked_shots():
    shots = []
    ctrl = _mole(on_hit_px=shots.append)
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    assert shots == [], "a whiff throws no projectile"
    ctrl.handle_event(_click(_hole_px(0)))
    assert shots == [], "and neither does a shot swallowed by the recoil lockout"
    ctrl.update(1000)
    ctrl.handle_event(_click(_hole_px(0)))
    assert len(shots) == 1, "the first shot past the lockout fires for real"


def test_on_hit_px_fires_on_the_quota_hit_too():
    shots = []
    ctrl = _mole(on_hit_px=shots.append)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    ctrl.update(3200)
    ctrl.handle_event(_click(_hole_px(2)))
    assert ctrl.landed is True
    assert len(shots) == 3, "the kill shot is a shot like any other"


def test_spectated_hits_fire_the_mirrors_gun_at_the_relayed_point():
    shots = []
    ctrl = _mole(passive=True, on_hit_px=shots.append)
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    assert shots == [ctrl._board_to_px(2.5, 2.5)], \
        "the spectator watches the opponent's gun fire at the relayed impact"
    ctrl.spectate_shot(600.0, 0, False, progress=1, target=(7.5, 7.5))
    assert len(shots) == 1, "a relay without a progress increase is a miss — no projectile"


def test_no_per_frame_logging(caplog):
    surf = pg.Surface((640, 640))
    ctrl = _mole()
    with caplog.at_level(logging.DEBUG):
        for i in range(100):
            ctrl.update(i * 16)
            ctrl.draw(surf)
    assert not caplog.records, "the mole view stays silent on the frame path"
