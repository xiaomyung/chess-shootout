"""Whack-a-mole skill-check view controller: click/Space shots share one recoil
lockout — a locked shot gets NO muzzle/kick/casing, only a dry-click cue, so the
fire rate is felt — hits adjudicate through the engine's hit_at (grace window
included), and BOTH outcomes end on one shared jump-out: the victim rises out of
its home pit (RISE), hops through an arc half a cell high (HOP), lands with a
squash (LAND_SQUASH) and settles on its own square at exactly the rest position
the board draws a piece at — so the fail handoff has no seam and nothing appears
out of thin air. A win keeps the shredded tier through the jump and then plays the
deep-fry flash (WIN_HOLD covers hitstop + jump + fry); a fail knits the victim
back together across HEAL_BUCKETS steps spanning RISE + HOP + REGROW, holds its
home pit open until touchdown and then shrinks it closed over PIT_CLOSE (the
other pits keep their 300ms fade), and the session restores the piece WITHOUT
the board drop. The heal is a composite, not a second damage model: above a
seam that travels from the feet to the crown the sprite is still the plain torn
frame, below it the untouched source sprite, and an additive orange band rides
the seam with a pair of sparks struck off it on every bucket step. The hit
flash is suppressed for the whole heal — a white frame there would undo half
the repair — and the composites are cached per (tier, bucket) and thrown away
on relayout.
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

A WON check no longer walks the victim home to be shot a second time by the capture
choreography: on the killing hit the shredded tier-3 sprite freezes for the kill
hitstop and is then BLASTED off the pit it was shot at, continuing the shot line
(attacker square center -> hit pit) with an upward kick, a gravity arc, a
continuous per-frame rotation and an alpha fade, plus a debris burst at the
launch. Nothing is ever drawn on the home square again and the pit it left stays
open — the fail path owns the jump-out/heal/pit-close, the win path owns the toss.
"""

import gc
import logging
import math
from unittest.mock import MagicMock, call

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck import mole_view
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.mole_view import (
    MoleController, MOLE_VIEW_FAIL_FADE_MS, MOLE_VIEW_FAIL_HOLD_MS,
    MOLE_VIEW_WIN_HOLD_MS, MOLE_VIEW_HITSTOP_KILL_MS,
    MOLE_VIEW_RETREAT_MS, MOLE_VIEW_PIP_OFFSET_FRAC,
    MOLE_VIEW_JUMP_RISE_MS, MOLE_VIEW_JUMP_HOP_MS, MOLE_VIEW_LAND_SQUASH_MS,
    MOLE_VIEW_REGROW_MS, MOLE_VIEW_TOSS_MS, MOLE_VIEW_TOSS_SPEED_FRAC,
    MOLE_VIEW_TOSS_UP_FRAC, MOLE_VIEW_TOSS_GRAVITY_FRAC,
    MOLE_VIEW_TOSS_SPIN_DPS, MOLE_VIEW_TOSS_FADE_START,
    MOLE_VIEW_PIT_CLOSE_MS, MOLE_VIEW_DANGER_PULSE_MS, MOLE_VIEW_PULSE_MS,
    MOLE_VIEW_HEAL_BUCKETS, MOLE_VIEW_SEAM_BAND_FRAC, MOLE_VIEW_SPARK_MS,
    MOLE_VIEW_CASING_REST_MS, MOLE_VIEW_CASING_FADE_MS,
    _pit_telegraph_surface, _pit_surface, _pit_front_surface, _seam_band_surface,
    _MOLE_STATIC_CACHE)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.skillcheck.mole import (
    MoleChallenge, MolePop, MOLE_TAUNTS, pick_taunt,
    MOLE_HITBOX_RX_FRAC, MOLE_HITBOX_RY_FRAC, MOLE_HITBOX_CY_FRAC)

_JUMP_MS = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS
_JUMP_TOTAL_MS = _JUMP_MS + MOLE_VIEW_LAND_SQUASH_MS
_HEAL_WINDOW_MS = _JUMP_MS + MOLE_VIEW_REGROW_MS

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


def test_third_hit_commits_the_win_after_the_toss_hold():
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
    assert ctrl.done is False, "the toss still owns the overlay"
    ctrl.update(3200 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_win_hold_covers_the_kill_hitstop_and_the_whole_toss():
    # The capture choreography may only take over once the body has finished
    # flying; a hold shorter than the sum would cut the arc mid-air, a longer one
    # would leave the player staring at an empty overlay.
    assert MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_TOSS_MS == MOLE_VIEW_WIN_HOLD_MS, \
        "the hold is exactly the freeze plus the flight — no dead air on either side"
    ctrl = _mole()
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    ctrl.update(int(3200 + MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_TOSS_MS) - 1)
    assert ctrl.done is False, "the body is still airborne, so the overlay may not hand over"
    ctrl.update(int(3200 + MOLE_VIEW_WIN_HOLD_MS))
    assert ctrl.done is True, "and it hands over the instant the body has landed"


def test_the_kill_flash_is_the_hit_flash_and_nothing_reignites_it():
    ctrl = _mole()
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    assert ctrl._flash_active() is True, "the killing hit flashes like any other hit"
    for dt in (200, 400, 600, 800, MOLE_VIEW_WIN_HOLD_MS - 1):
        ctrl.update(3200 + int(dt))
        assert ctrl._flash_active() is False, \
            "the deep-fry beat is gone — the victim is blasted away, not cooked"


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


def test_online_resolve_win_holds_through_the_toss():
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(900)
    ctrl.resolve(True)
    assert ctrl.landed is True
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the shredded body still has to fly online too"
    assert ctrl._toss is not None, "the server verdict launches the same toss"
    ctrl.update(900 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_spectator_resolve_holds_the_same_totals_as_the_mover():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.resolve(True)
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the mirror shows the same toss as the mover"
    assert ctrl._toss is not None, "the passive mirror blasts the body off too"
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
    for dt in (100, MOLE_VIEW_HITSTOP_KILL_MS + 1,
               MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_TOSS_MS / 2,
               MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_TOSS_MS + 10,
               MOLE_VIEW_WIN_HOLD_MS - 1):
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
_FAIL_POPS = _POPS[:3]


def _distinct_pops(pops):
    # Identical pop/retreat timings, a nudged telegraph. juice's torn cache is keyed
    # on (hash(pops), cell) and NOT on the victim surface, so a test that renders a
    # different sprite through the same pop script would otherwise inherit — or
    # poison — another test's cached damage frame.
    return tuple(MolePop(p.hole, p.t_telegraph_ms + 0.5, p.t_up_ms, p.t_down_ms)
                 for p in pops)


_SOLID_FAIL_POPS = _distinct_pops(_FAIL_POPS)
_WIN_ALT_POPS = _distinct_pops(_POPS)


def _fail_at_two_hits(pops=_FAIL_POPS, **kw):
    ctrl = _mole(challenge=_challenge(pops=pops, hits_required=3, deadline_ms=5000.0), **kw)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._progress == 2
    ctrl.update(_FAIL_AT_MS)
    assert ctrl.landed is False, "the last pop expired unhit — the 3-hit quota is out of reach"
    return ctrl


def _row_matches(a, b, y):
    return all(a.get_at((x, y)) == b.get_at((x, y)) for x in range(a.get_width()))


def _mean_rgb_row(surf, y):
    w = surf.get_width()
    return sum(sum(surf.get_at((x, y))[:3]) for x in range(w)) / (3.0 * w)


def _clean_tail_top(comp, clean):
    # The first row of the contiguous already-repaired run at the feet: the seam
    # is exactly where that run stops matching the untouched sprite.
    y = comp.get_height()
    while y > 0 and _row_matches(comp, clean, y - 1):
        y -= 1
    return y


def _lit_pixels(surf, region):
    return sum(1 for x in range(region.left, region.right)
               for y in range(region.top, region.bottom)
               if surf.get_at((x, y))[:3] != (0, 0, 0))


def test_heal_bucket_climbs_from_zero_to_full_across_the_whole_jump_window():
    # One continuous bucketed knit over RISE + HOP + REGROW: it starts the moment
    # the victim leaves the pit and only finishes on the standing beat.
    ctrl = _fail_at_two_hits()
    assert ctrl._heal_bucket() == 0, "it climbs out fully broken"
    steps = MOLE_VIEW_HEAL_BUCKETS * 3
    buckets = []
    for i in range(steps + 1):
        ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS * i / steps))
        buckets.append(ctrl._heal_bucket())
    assert buckets == sorted(buckets), "the repair only ever moves toward whole"
    assert buckets[0] == 0 and buckets[-1] == MOLE_VIEW_HEAL_BUCKETS
    assert set(buckets) == set(range(MOLE_VIEW_HEAL_BUCKETS + 1)), \
        "no bucket is skipped — the seam travels, it never jumps"


def test_the_heal_is_underway_mid_hop_and_only_completes_on_the_standing_beat():
    ctrl = _fail_at_two_hits()
    ctrl.update(int(_FAIL_AT_MS + MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS * 0.5))
    assert 0 < ctrl._heal_bucket() < MOLE_VIEW_HEAL_BUCKETS, "already knitting mid-hop"
    ctrl.update(int(_FAIL_AT_MS + _JUMP_MS))
    assert 0 < ctrl._heal_bucket() < MOLE_VIEW_HEAL_BUCKETS, \
        "it touches down still visibly seamed — REGROW is the beat it stands through"
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS) - 1)
    assert ctrl._heal_progress() < 1.0
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS))
    assert ctrl._heal_progress() == 1.0
    assert ctrl._heal_bucket() == MOLE_VIEW_HEAL_BUCKETS


def test_fail_hold_covers_the_jump_plus_the_heal_tail():
    assert MOLE_VIEW_FAIL_HOLD_MS >= _HEAL_WINDOW_MS, \
        "the overlay must stay alive until the piece finishes knitting back together"


def test_heal_sprite_lands_on_the_source_surfaces_at_both_edges():
    ctrl = _fail_at_two_hits()
    tier = ctrl._damage_tier()
    assert tier > 0, "two of three hits really did break the sprite"
    assert ctrl._heal_sprite(tier, 0) is ctrl._torn_victim(tier), \
        "bucket 0 is the plain torn frame, not a composite of it with itself"
    assert ctrl._heal_sprite(tier, MOLE_VIEW_HEAL_BUCKETS) is ctrl._victim, \
        "the last bucket hands back the untouched source sprite, object identity included"
    assert ctrl._heal_sprite(tier, MOLE_VIEW_HEAL_BUCKETS + 4) is ctrl._victim
    assert ctrl._heal_sprite(0, MOLE_VIEW_HEAL_BUCKETS // 2) is ctrl._victim, \
        "an undamaged victim has nothing to knit"
    mid = ctrl._heal_sprite(tier, MOLE_VIEW_HEAL_BUCKETS // 2)
    assert mid is not ctrl._victim and mid is not ctrl._torn_victim(tier)


def test_heal_composites_are_cached_per_tier_and_bucket_and_die_on_relayout():
    ctrl = _fail_at_two_hits()
    tier = ctrl._damage_tier()
    first = ctrl._heal_sprite(tier, 8)
    assert ctrl._heal_sprite(tier, 8) is first, "one composite per step, not one per draw"
    assert ctrl._heal_cache[(tier, 8)] is first
    assert ctrl._heal_sprite(tier, 9) is not first, "the bucket is part of the key"
    assert ctrl._heal_sprite(tier - 1, 8) is not first, "and so is the tier"
    ctrl.relayout(pg.Rect(0, 0, 2 * _CELL, 2 * _CELL))
    assert ctrl._heal_cache == {}, \
        "every composite was built at the old cell size — a resize invalidates all of them"


def test_heal_composite_is_torn_above_the_seam_and_whole_below_it():
    ctrl = _fail_at_two_hits(pops=_SOLID_FAIL_POPS, victim_surface=_solid_victim())
    tier = ctrl._damage_tier()
    torn = ctrl._torn_victim(tier)
    bucket = MOLE_VIEW_HEAL_BUCKETS // 2
    comp = ctrl._heal_sprite(tier, bucket)
    w, h = comp.get_size()
    assert (w, h) == ctrl._victim.get_size(), "the composite never changes the footprint"
    seam_y = round(h * (1.0 - bucket / MOLE_VIEW_HEAL_BUCKETS))
    band_h = max(int(h * MOLE_VIEW_SEAM_BAND_FRAC), 3)
    above = range(0, seam_y - band_h // 2)
    below = range(seam_y - band_h // 2 + band_h, h)
    assert any(not _row_matches(torn, ctrl._victim, y) for y in above), \
        "the region under test really carries damage"
    assert all(_row_matches(comp, torn, y) for y in above), \
        "above the seam the composite is byte-identical to the torn frame"
    assert all(_row_matches(comp, ctrl._victim, y) for y in below), \
        "below it, byte-identical to the untouched source sprite"
    assert _mean_rgb_row(comp, seam_y) > _mean_rgb_row(ctrl._victim, seam_y) + 20, \
        "and an additive band glows on the seam row itself"


def test_the_seam_travels_up_from_the_feet_one_bucket_at_a_time():
    ctrl = _fail_at_two_hits(pops=_SOLID_FAIL_POPS, victim_surface=_solid_victim())
    tier = ctrl._damage_tier()
    tops = [_clean_tail_top(ctrl._heal_sprite(tier, b), ctrl._victim)
            for b in range(MOLE_VIEW_HEAL_BUCKETS + 1)]
    assert all(b <= a for a, b in zip(tops, tops[1:])), tops
    assert tops[0] > tops[MOLE_VIEW_HEAL_BUCKETS // 2] > 0, \
        "the whole part grows upward out of the feet, it does not appear all at once"
    assert tops[-1] == 0, "the last bucket is whole all the way to the crown"


def test_the_victim_sprite_is_the_heal_composite_for_the_whole_jump():
    ctrl = _fail_at_two_hits()
    tier = ctrl._damage_tier()
    assert ctrl._jump_elapsed() is not None
    for frac in (0.0, 0.2, 0.5, 0.8, 1.0):
        ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS * frac))
        assert ctrl._victim_sprite() is ctrl._heal_sprite(tier, ctrl._heal_bucket())
    assert ctrl._victim_sprite() is ctrl._victim, \
        "it settles on the exact sprite the board restores under the overlay"


def test_a_hit_flash_never_bleaches_a_frame_of_the_heal():
    live = _mole()
    live.update(800)
    live.handle_event(_click(_hole_px(0)))
    assert live._flash_active() is True
    assert live._victim_sprite() is not live._torn_victim(live._damage_tier()), \
        "outside the heal a fresh hit still whites the sprite out"
    ctrl = _fail_at_two_hits()
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS / 2))
    ctrl._hit_flash_ms = ctrl._now
    assert ctrl._flash_active() is True
    tier = ctrl._damage_tier()
    assert ctrl._victim_sprite() is ctrl._heal_sprite(tier, ctrl._heal_bucket()), \
        "a white frame mid-repair would throw away half the composite"


def test_each_bucket_step_strikes_one_spark_pair_off_the_seam():
    ctrl = _fail_at_two_hits()
    assert ctrl._seam_sparks == [], "nothing sparks before the piece leaves the pit"
    assert ctrl._last_heal_bucket == 0
    step = _HEAL_WINDOW_MS / MOLE_VIEW_HEAL_BUCKETS
    ctrl.update(math.ceil(_FAIL_AT_MS + step))
    assert ctrl._last_heal_bucket == 1
    assert len(ctrl._seam_sparks) == 2
    assert {side for _, side, _, _, _ in ctrl._seam_sparks} == {-1, 1}, \
        "one spark off each edge of the seam"
    assert ctrl._seam_sparks[0][2] == pytest.approx(1.0 - 1.0 / MOLE_VIEW_HEAL_BUCKETS), \
        "anchored on the seam height of the bucket that struck it"
    ctrl.update(math.ceil(_FAIL_AT_MS + step * 3))
    assert ctrl._last_heal_bucket == 3
    assert len(ctrl._seam_sparks) == 6, \
        "a frame that swallows two bucket steps still pays out both pairs"


def test_seam_sparks_expire_on_their_own_clock():
    ctrl = _fail_at_two_hits()
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS))
    assert ctrl._last_heal_bucket == MOLE_VIEW_HEAL_BUCKETS
    assert ctrl._seam_sparks, "the final bucket still throws its pair"
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS + MOLE_VIEW_SPARK_MS) - 1)
    assert ctrl._seam_sparks, "still burning one millisecond short of the TTL"
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS + MOLE_VIEW_SPARK_MS))
    assert ctrl._seam_sparks == [], "and every spark is dropped at MOLE_VIEW_SPARK_MS"


def test_seam_sparks_are_skipped_when_there_is_no_body_to_hang_them_on():
    # _blit_victim reports None for a zero-height frame; with no seam to sit
    # against the sparks must not paint at some last-known position.
    ctrl = _fail_at_two_hits()
    ctrl.update(int(_FAIL_AT_MS + _HEAL_WINDOW_MS / 2))
    assert ctrl._seam_sparks
    region = pg.Rect(100, 190, 280, 100)
    drawn = pg.Surface((640, 640))
    drawn.fill((0, 0, 0))
    ctrl._draw_seam_sparks(drawn, pg.Rect(200, 200, _CELL, _CELL))
    assert _lit_pixels(drawn, region) > 0
    blank = pg.Surface((640, 640))
    blank.fill((0, 0, 0))
    ctrl._draw_seam_sparks(blank, None)
    assert _lit_pixels(blank, region) == 0


def test_the_seam_band_is_a_shared_cached_module_surface():
    band = _seam_band_surface(40, 12)
    assert _seam_band_surface(40, 12) is band, "one band per size, shared by every composite"
    assert ("seam", 40, 12) in _MOLE_STATIC_CACHE
    assert band.get_size() == (40, 12)
    core = band.get_at((20, 6))
    assert sum(core[:3]) > sum(band.get_at((20, 0))[:3]), \
        "it is hottest on the seam line and falls off to nothing at both edges"
    assert sum(core[:3]) > sum(band.get_at((20, 11))[:3])
    assert core[0] > core[2], "the weld glows orange, not white-blue"


def test_the_win_never_heals_the_victim_on_its_way_out():
    ctrl = _mole(challenge=_challenge(pops=_WIN_ALT_POPS))
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    for dt in (MOLE_VIEW_HITSTOP_KILL_MS, MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_TOSS_MS / 2,
               MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_TOSS_MS, MOLE_VIEW_WIN_HOLD_MS - 1):
        ctrl.update(3200 + int(dt))
        assert ctrl._jump_elapsed() is None, "the heal window is fail-only"
        assert ctrl._heal_bucket() == 0
        assert ctrl._damage_tier() == 3
        assert ctrl._victim_sprite() is ctrl._torn_victim(3), \
            "the body that flies away is the fully shredded one"
        assert ctrl._seam_sparks == [], "and nothing knits it back together"


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


def _advance(ctrl, start_ms, end_ms, step_ms=16):
    # Real frames, not one giant leap: the seam sparks are spawned per bucket
    # crossing and expire on a wall clock, so a single jumbo update would dump
    # every pair at once with zero drift and paint them on top of each other.
    now = float(start_ms)
    while now < end_ms:
        now = min(now + step_ms, float(end_ms))
        ctrl.update(int(now))


_TOSS_COLOR = (10, 200, 40)
_BODY_MARGIN = 40
_ATTACKER_SQ = Square(7, 0)
_WIN_AT_MS = 3200


def _solid_victim(cell=_CELL):
    surf = pg.Surface((cell, cell), pg.SRCALPHA)
    surf.fill((*_TOSS_COLOR, 255))
    return surf


def _body_pixels(surf, rect):
    # Green-dominance, not an exact match: the win-pop flash blends additively over
    # the body and the flight fades it out, but no other element on the mole layer
    # is green (Colors.win only ever paints under CHESS_DEBUG_HITBOX).
    return sum(1 for x in range(rect.x, rect.right) for y in range(rect.y, rect.bottom)
               if surf.get_at((x, y)).g - surf.get_at((x, y)).r > _BODY_MARGIN
               and surf.get_at((x, y)).g - surf.get_at((x, y)).b > _BODY_MARGIN)


def _won_at_the_far_pit():
    # The attacker sits down-left of the last pit, so the shot line points up and to
    # the right and the flight can never wander over the home square by accident.
    ctrl = _mole(victim_surface=_solid_victim(), from_sq=_ATTACKER_SQ)
    for now, hole in ((800, 0), (2000, 1), (_WIN_AT_MS, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    assert ctrl.landed is True
    return ctrl


def test_a_won_check_never_walks_the_victim_home():
    # The old win jumped the shredded body back onto its own square, where the
    # capture choreography then shot it a second time. Nothing may land there.
    ctrl = _won_at_the_far_pit()
    home = pg.Rect(ctrl.center[0] - _CELL, ctrl.center[1] - 2 * _CELL, 2 * _CELL, 3 * _CELL)
    for dt in range(0, MOLE_VIEW_WIN_HOLD_MS, 25):
        surf = _draw_at(ctrl, _WIN_AT_MS + dt)
        assert _body_pixels(surf, home) == 0, \
            "the victim is drawn on its home square at +{}ms".format(dt)


def test_the_kill_blasts_the_victim_off_the_pit_along_the_shot_line():
    ctrl = _won_at_the_far_pit()
    assert ctrl._toss is None, "nothing launches while the kill hitstop still holds"
    ctrl.update(int(_WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS))
    toss = ctrl._toss
    assert toss is not None, "the launch happens the frame the freeze ends"
    origin = _hole_px(2)
    assert (toss.x0, toss.y0) == (float(origin[0]), float(origin[1])), \
        "it leaves from the pit it was shot at, not from its home square"
    ax, ay = _geom_for(_CELL)(_ATTACKER_SQ)
    dist = math.hypot(origin[0] - ax, origin[1] - ay)
    speed = _CELL * MOLE_VIEW_TOSS_SPEED_FRAC
    assert toss.vx == pytest.approx((origin[0] - ax) / dist * speed)
    assert toss.vy == pytest.approx((origin[1] - ay) / dist * speed
                                    - _CELL * MOLE_VIEW_TOSS_UP_FRAC), \
        "the shot direction carries straight through, with the upward kick on top"


def test_the_tossed_body_arcs_away_from_the_pit_and_falls():
    ctrl = _won_at_the_far_pit()
    ctrl.update(int(_WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS))
    start = ctrl._toss_point(0.0)
    mid = ctrl._toss_point(MOLE_VIEW_TOSS_MS / 2)
    end = ctrl._toss_point(MOLE_VIEW_TOSS_MS)
    assert start == (ctrl._toss.x0, ctrl._toss.y0)
    assert mid[0] > start[0] and mid[1] < start[1], "up and away along the shot line"
    assert end[0] > mid[0], "it never stops travelling"
    assert end[1] > mid[1], "and gravity has already bent the arc back down"
    flight = MOLE_VIEW_TOSS_MS / 1000.0
    assert end[1] == pytest.approx(
        ctrl._toss.y0 + ctrl._toss.vy * flight
        + 0.5 * _CELL * MOLE_VIEW_TOSS_GRAVITY_FRAC * flight * flight), \
        "the fall is the plain cells-per-second-squared pull, nothing hand-tweaked"
    assert math.hypot(end[0] - start[0], end[1] - start[1]) > _CELL, \
        "the body clears the pit by more than a whole cell"


def test_the_launch_bursts_its_own_debris():
    ctrl = _won_at_the_far_pit()
    ctrl.update(int(_WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS) - 1)
    before = len(ctrl._debris)
    ctrl.update(int(_WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS))
    assert len(ctrl._debris) == before + 1, "the blast throws chunks as the body leaves"


def test_the_tossed_body_is_in_the_air_mid_flight_and_gone_by_the_hold():
    ctrl = _won_at_the_far_pit()
    whole = pg.Rect(0, 0, 640, 640)
    flying = _draw_at(ctrl, _WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS + 40)
    assert _body_pixels(flying, whole) > 0, "the body is mid-air"
    gone = _draw_at(ctrl, _WIN_AT_MS + MOLE_VIEW_WIN_HOLD_MS - 1)
    assert _body_pixels(gone, whole) == 0, \
        "the flight is over and nothing is left for the capture to shoot at"


def _rotozoom_spy(monkeypatch):
    # rotozoom is only ever reached through _draw_toss on this layer, so every
    # recorded angle belongs to the flight.
    calls = []
    original = pg.transform.rotozoom

    def spy(surface, angle, scale):
        out = original(surface, angle, scale)
        calls.append((surface, angle, out))
        return out

    monkeypatch.setattr(pg.transform, "rotozoom", spy)
    return calls


def test_the_toss_spins_continuously_instead_of_snapping_between_buckets(monkeypatch):
    calls = _rotozoom_spy(monkeypatch)
    ctrl = _won_at_the_far_pit()
    surf = pg.Surface((640, 640))
    launch = int(_WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS)
    for now in range(launch, int(launch + MOLE_VIEW_TOSS_MS), 4):
        ctrl.update(now)
        ctrl.draw(surf)
    angles = [angle for _, angle, _ in calls]
    assert len(angles) > 100, "every frame of the flight goes through a rotation"
    assert angles[0] == 0.0, "it leaves the pit upright"
    assert len(set(angles)) == len(angles), \
        "no two frames share an angle — the spin is time-continuous, not bucketed"
    assert all(b > a for a, b in zip(angles, angles[1:])) or \
        all(b < a for a, b in zip(angles, angles[1:])), "and it turns one way only"
    per_frame = MOLE_VIEW_TOSS_SPIN_DPS * 4 / 1000.0
    assert all(abs(b - a) == pytest.approx(per_frame, abs=1e-6)
               for a, b in zip(angles, angles[1:])), \
        "a flat TOSS_SPIN_DPS degrees per second of flight time"
    assert len({id(out) for _, _, out in calls}) == len(calls), \
        "each frame gets its own surface to fade — nothing cached is tinted"


def test_the_toss_keeps_no_bucketed_spin_cache():
    assert not hasattr(mole_view, "MOLE_VIEW_TOSS_SPIN_BUCKET_DEG")
    assert not hasattr(mole_view, "_toss_sprite")
    ctrl = _won_at_the_far_pit()
    assert not hasattr(ctrl, "_toss_cache")


def test_the_fade_never_tints_the_sprites_the_board_and_the_cache_share(monkeypatch):
    # The flight sets a blanket alpha every frame; the surface it touches must be
    # one the controller just built, never the board's piece image or juice's
    # shared torn cache entry.
    calls = _rotozoom_spy(monkeypatch)
    ctrl = _won_at_the_far_pit()
    torn = ctrl._torn_victim(3)
    before = pg.image.tostring(torn, "RGBA")
    surf = pg.Surface((640, 640))
    launch = int(_WIN_AT_MS + MOLE_VIEW_HITSTOP_KILL_MS)
    for now in range(launch, int(launch + MOLE_VIEW_TOSS_MS), 20):
        ctrl.update(now)
        ctrl.draw(surf)
    assert calls, "the flight really was drawn"
    assert all(src is torn for src, _, _ in calls), "the shredded frame is what flies"
    assert all(out is not torn and out is not ctrl._victim for _, _, out in calls)
    assert ctrl._victim.get_alpha() == 255, "the source sprite is never faded"
    assert torn.get_alpha() == 255, "and neither is the shared torn cache entry"
    assert pg.image.tostring(torn, "RGBA") == before


def test_the_body_fades_out_over_the_tail_of_the_flight():
    assert MoleController._toss_alpha(0.0) == 255
    assert MoleController._toss_alpha(MOLE_VIEW_TOSS_FADE_START) == 255, \
        "it stays solid while it is still readable as the piece"
    half = MoleController._toss_alpha((MOLE_VIEW_TOSS_FADE_START + 1.0) / 2.0)
    assert 0 < half < 255
    assert MoleController._toss_alpha(1.0) == 0, "and it is fully gone at touchdown"


def test_no_pit_closes_on_a_win():
    ctrl = _won_at_the_far_pit()
    for dt in (MOLE_VIEW_HITSTOP_KILL_MS, MOLE_VIEW_WIN_HOLD_MS - 1):
        surf = _draw_at(ctrl, _WIN_AT_MS + int(dt))
        assert ctrl._home_pit_close_scale() == 1.0, "the close animation is fail-only"
        assert _pit_dark_pixels(surf, ctrl) > 0, "the ground stays torn open"


def test_a_toss_with_no_shot_line_still_leaves_upward():
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), 0,
                          ch.deadline_ms, hole_squares=_HOLES, audio=MagicMock(),
                          victim_surface=_victim(_CELL), on_shot=MagicMock())
    ctrl.update(900)
    ctrl.resolve(True)
    ctrl.update(int(900 + MOLE_VIEW_HITSTOP_KILL_MS))
    toss = ctrl._toss
    assert toss is not None
    assert (toss.x0, toss.y0) == (float(ctrl.center[0]), float(ctrl.center[1])), \
        "with no hit pit on record the body leaves from the check's own square"
    assert toss.vy < 0.0, "the seeded fallback still throws it up, never into the floor"


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
    _advance(ctrl, 2000, 2000 + MOLE_VIEW_FAIL_HOLD_MS - 1)
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


def _color_bbox(surf, color, region):
    hits = [(x, y) for x in range(region.left, region.right)
            for y in range(region.top, region.bottom)
            if surf.get_at((x, y))[:3] == (color.r, color.g, color.b)]
    assert hits, "nothing was painted in {}".format(color)
    xs = [x for x, _ in hits]
    ys = [y for _, y in hits]
    return pg.Rect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def test_hitbox_outline_traces_the_tall_oval_the_engine_shifted_up(monkeypatch):
    # hit_at measures a tall ellipse whose centre sits CY_FRAC of a cell ABOVE the
    # square centre — that is where a popped mole's head actually is. The overlay
    # has to trace that exact shape or it is worse than no overlay at all.
    monkeypatch.setenv("CHESS_DEBUG_HITBOX", "1")
    ctrl = _mole()
    surf = _draw_at(ctrl, 800)
    row, col = _HOLES[2]
    cx, cy = _hole_px(2)
    box = _color_bbox(surf, pg.Color(Colors.spectate),
                      pg.Rect(cx - 2 * _CELL, cy - 2 * _CELL, 4 * _CELL, 4 * _CELL))
    assert box.centerx == pytest.approx(cx, abs=2)
    assert box.centery == pytest.approx(cy + _CELL * MOLE_HITBOX_CY_FRAC, abs=2), \
        "the oval rides above the square centre, on the head and not on the feet"
    assert box.width == pytest.approx(2 * _CELL * MOLE_HITBOX_RX_FRAC, abs=2)
    assert box.height == pytest.approx(2 * _CELL * MOLE_HITBOX_RY_FRAC, abs=2)
    assert box.height > box.width, "the hit region is a tall oval, not a circle"
    assert ctrl._board_to_px(row + 0.5, col + 0.5) == (float(cx), float(cy)), \
        "and it is anchored on the square center the engine measures from"


def _hit_px_sink():
    # on_hit_px carries (impact point, was-this-the-kill): the session aims the
    # attacker's gun at the point and only stages the kill choreography on the flag.
    shots = []
    return shots, lambda px, kill: shots.append((px, kill))


def test_on_hit_px_fires_once_per_registered_hit_at_the_impact():
    # The attacker's gun shoots at what the bullet actually hit — the popped
    # mole's hole, not the raw cursor — so the slug and the debris agree.
    shots, sink = _hit_px_sink()
    ctrl = _mole(on_hit_px=sink)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    assert shots == [(_hole_px(0), False)], \
        "one registered hit, one projectile, on the hit hole — and no kill yet"


def test_on_hit_px_stays_silent_on_whiffs_and_locked_shots():
    shots, sink = _hit_px_sink()
    ctrl = _mole(on_hit_px=sink)
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    assert shots == [], "a whiff throws no projectile"
    ctrl.handle_event(_click(_hole_px(0)))
    assert shots == [], "and neither does a shot swallowed by the recoil lockout"
    ctrl.update(1000)
    ctrl.handle_event(_click(_hole_px(0)))
    assert len(shots) == 1, "the first shot past the lockout fires for real"


def test_on_hit_px_flags_only_the_quota_hit_as_the_kill():
    shots, sink = _hit_px_sink()
    ctrl = _mole(on_hit_px=sink)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    ctrl.update(3200)
    ctrl.handle_event(_click(_hole_px(2)))
    assert ctrl.landed is True
    assert len(shots) == 3, "the kill shot is a shot like any other"
    assert [kill for _, kill in shots] == [False, False, True], \
        "only the hit that fills the quota carries the kill flag"


def test_spectated_hits_fire_the_mirrors_gun_at_the_relayed_point():
    shots, sink = _hit_px_sink()
    ctrl = _mole(passive=True, on_hit_px=sink)
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    assert shots == [(ctrl._board_to_px(2.5, 2.5), False)], \
        "the spectator watches the opponent's gun fire at the relayed impact"
    ctrl.spectate_shot(600.0, 0, False, progress=1, target=(7.5, 7.5))
    assert len(shots) == 1, "a relay without a progress increase is a miss — no projectile"
    ctrl.spectate_shot(2000.0, 0, True, progress=3, target=(2.5, 2.5))
    assert shots[-1][1] is True, \
        "the mirror reads the kill off the relayed progress, not off a local commit"


def test_blit_victim_reports_the_rect_it_painted():
    # The rect is what the seam sparks hang off, so it has to be the real painted
    # box in both branches — and None when there is nothing on screen at all.
    ctrl = _mole(victim_surface=_solid_victim())
    ground = ctrl._rest_ground_dy()
    blank = pg.Surface((640, 640))
    blank.fill((0, 0, 0))
    assert ctrl._blit_victim(blank, ctrl.center, 0.0, (0, 0), ground_dy=ground) is None
    assert blank.get_at(ctrl.center)[:3] == (0, 0, 0), "and it painted nothing either"
    full_surf = pg.Surface((640, 640))
    full_surf.fill((0, 0, 0))
    full = ctrl._blit_victim(full_surf, ctrl.center, 1.0, (0, 0), ground_dy=ground)
    assert full.size == ctrl._victim.get_size()
    assert full_surf.get_at(full.topleft)[:3] == _TOSS_COLOR
    assert full_surf.get_at((full.right - 1, full.bottom - 1))[:3] == _TOSS_COLOR
    assert full_surf.get_at((full.left - 1, full.centery))[:3] == (0, 0, 0), \
        "the reported rect is the painted rect, not a pixel wider"
    assert full_surf.get_at((full.centerx, full.top - 1))[:3] == (0, 0, 0)
    clip_surf = pg.Surface((640, 640))
    clip_surf.fill((0, 0, 0))
    clipped = ctrl._blit_victim(clip_surf, ctrl.center, 0.5, (0, 0), ground_dy=ground)
    assert clipped.width == full.width
    assert clipped.height == int(ctrl._victim.get_height() * 0.5)
    assert clipped.bottom == full.bottom, "a half-risen mole stands on the same ground line"
    assert clip_surf.get_at(clipped.topleft)[:3] == _TOSS_COLOR
    assert clip_surf.get_at((clipped.centerx, clipped.top - 1))[:3] == (0, 0, 0), \
        "and the frame really is cut off at the rim, not squashed into it"


def test_the_pit_lip_is_repainted_over_the_body_only_when_asked():
    ctrl = _mole(victim_surface=_solid_victim())
    dark = pg.Color(Colors.well_deep)

    def lip_pixels(lip):
        surf = pg.Surface((640, 640))
        surf.fill((0, 0, 0))
        ctrl._blit_victim(surf, ctrl.center, 1.0, (0, 0), lip=lip)
        return sum(1 for x in range(ctrl.center[0] - _CELL, ctrl.center[0] + _CELL)
                   for y in range(ctrl.center[1] - _CELL, ctrl.center[1] + _CELL)
                   if surf.get_at((x, y))[:3] == (dark.r, dark.g, dark.b))

    assert lip_pixels(True) > 0, "the front half of the pit is painted back over the body"
    assert lip_pixels(False) == 0, "and nothing masks a body standing on bare board"


def test_the_pit_lip_is_the_front_half_of_the_pit_sprite():
    front = _pit_front_surface(30, 18)
    pit = _pit_surface(30, 18)
    assert front.get_width() == pit.get_width()
    assert front.get_height() == pit.get_height() // 2, "only the near rim is redrawn"
    assert _pit_front_surface(30, 18) is front, "one lip per pit size, cached like the pit"
    assert ("pit_front", 30, 18) in _MOLE_STATIC_CACHE


def _lip_spy(monkeypatch):
    seen = []
    original = MoleController._blit_victim

    def spy(self, window, center_px, height_frac, group, squash=0, lift_px=0.0,
            ground_dy=None, lip=False):
        seen.append(lip)
        return original(self, window, center_px, height_frac, group, squash, lift_px,
                        ground_dy, lip)

    monkeypatch.setattr(MoleController, "_blit_victim", spy)
    return seen


def test_pops_and_the_climb_out_wear_the_pit_lip_but_the_landed_piece_does_not(monkeypatch):
    seen = _lip_spy(monkeypatch)
    surf = pg.Surface((640, 640))
    ctrl = _mole()
    ctrl.update(100)
    ctrl.draw(surf)
    assert seen == [True], "the drop-in falls behind the mouth of its own pit"
    seen.clear()
    ctrl.update(800)
    ctrl.draw(surf)
    assert seen == [True], "a popped mole is cut off by the rim of the hole it stands in"
    failed = _mole(challenge=_one_pop_challenge())
    failed.update(2000)
    assert failed.landed is False
    seen.clear()
    failed.update(int(2000 + MOLE_VIEW_JUMP_RISE_MS / 2))
    failed.draw(surf)
    assert seen == [True], "the climb-out is still down in the pit"
    seen.clear()
    failed.update(int(2000 + MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS / 2))
    failed.draw(surf)
    assert seen == [False], "mid-hop it is over the board, in front of everything"
    seen.clear()
    failed.update(int(2000 + _JUMP_TOTAL_MS + 50))
    failed.draw(surf)
    assert seen == [False], "and the settled piece stands on its square, unmasked"


def test_casing_alpha_holds_on_the_ground_then_ramps_to_nothing():
    assert MoleController._casing_alpha(0.0) == 255
    assert MoleController._casing_alpha(MOLE_VIEW_CASING_REST_MS) == 255, \
        "the brass lies there at full opacity for the whole rest beat"
    half = MoleController._casing_alpha(MOLE_VIEW_CASING_REST_MS
                                        + MOLE_VIEW_CASING_FADE_MS / 2.0)
    assert half == int(255 * 0.5), "then a straight linear ramp, not a step"
    assert MoleController._casing_alpha(MOLE_VIEW_CASING_REST_MS
                                        + MOLE_VIEW_CASING_FADE_MS) == 0
    assert MoleController._casing_alpha(9999.0) == 0, "and it never goes negative"


def test_spent_casings_are_dropped_the_frame_they_turn_invisible():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    assert len(ctrl._casings) == 1
    life = (ctrl._casings[0].t_land * 1000.0 + MOLE_VIEW_CASING_REST_MS
            + MOLE_VIEW_CASING_FADE_MS)
    ctrl.update(800 + life - 1.0)
    assert len(ctrl._casings) == 1, "it is still on the ground, fading out"
    ctrl.update(800 + life)
    assert ctrl._casings == [], "and it goes the moment it can no longer paint a pixel"


def test_casings_never_pile_up_across_a_long_check():
    ctrl = _mole()
    for i in range(20):
        ctrl.update(800 + i * 200)
        ctrl.handle_event(_click((600, 600)))
    assert ctrl._casings, "the recent brass is still lying around"
    assert len(ctrl._casings) < 20, "the old brass is swept, not hoarded for the whole check"
    assert all(ctrl._casing_alpha(ctrl._now - c.spawn_ms - c.t_land * 1000.0) > 0
               for c in ctrl._casings), \
        "the prune boundary and the fade boundary are the same instant"


def test_no_per_frame_logging(caplog):
    surf = pg.Surface((640, 640))
    ctrl = _mole()
    with caplog.at_level(logging.DEBUG):
        for i in range(100):
            ctrl.update(i * 16)
            ctrl.draw(surf)
    assert not caplog.records, "the mole view stays silent on the frame path"
