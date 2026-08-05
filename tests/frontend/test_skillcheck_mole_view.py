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
home pit open until touchdown and then shrinks it closed over PIT_CLOSE, and the
session restores the piece WITHOUT the board drop. The heal is a composite, not
a second damage model: above a seam that travels from the feet to the crown the
sprite is still the plain torn frame, below it the untouched source sprite, an
additive orange band rides the seam inside the sprite and a wider world-space
glow bar rides it outside, anchored on the victim's own bounding box so the pair
of sparks struck off every bucket step leave from the body's edges instead of
the sprite's transparent margin. NOTHING of that presentation exists at damage
tier 0 — an untouched victim has nothing to repair, so no seam, no glow, no
sparks. The hit flash is suppressed for the whole heal — a white frame there
would undo half the repair — and the composites are cached per (tier, bucket)
and thrown away on relayout.

Emergence is one anchored model shared by the intro sink, every pop and the fail
climb-out: the ground line the body stands on interpolates from the pit's near
lip (pit_ry below the ellipse centre) up to the ellipse centre itself as the pop
height goes 0 -> 1, and the body is cut by a MASK anchored on the pit, not by a
straight clip on the sprite. The mask's boundary is the lower arc of the pit's
own dark mouth (_pit_mouth derives it off the very inset/rim fractions the pit
sprite is drawn with, so the two can never drift): deepest under the centre of
the hole, climbing to the ground line at both rims and staying there for every
column of a sprite wider than the mouth — the old straight cut left those wings
hanging over bare board, which is what read as a wall. A short alpha ramp above
the arc (EMERGE_FADE_FRAC of the mouth's depth) dissolves the body into the hole
instead of hard-cutting it. The sprite is composited into ONE reusable scratch
surface per sprite size, so nothing is allocated per frame. At full pop the piece
is whole and completely clear of the lip (POP_HEIGHT_FRAC is 1.0, with the
LIFT_CAP overshoot riding on top of it), and the fail hop picks the ground line
up at 0 and walks it down to the rest position without a step at either joint.

A pop is ONE continuous bounce, never a hold: out_cubic out of the hole to the
apex at POP_APEX_FRAC of the window (POP_OVERSHOOT past whole), then a gravity
fall back into it over the rest. The window is the pop's own up-time plus the
engine's MOLE_GRACE_MS, so the body is on screen exactly as long as the pop is
hittable, and because the engine ramps up-times per piece value the fall pace
varies per pop for free. The squash bucket is read straight off the height, so
the body is compressed leaving the pit and again as it drops back in, upright
only at the top. A registered hit interrupts the arc wherever it is: the height
at the hit is latched and driven to zero over RETREAT_MS.

The commit closes the check down instead of switching it off: every pit shrinks
shut through the same mouth animation that opened it, with the same per-hole
stagger, the brass takes a commit-relative fade cap so no casing pops off with
the overlay, the pips hold a beat and then fade, and the crosshair scales and
fades out. On a win the whole outro waits out the kill hitstop, so the pit the
body is frozen over is still open under it when it launches.
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

Whiffs are capped at MOLE_MAX_WHIFFS (3), mirroring combo's 3-wrongs rule,
because free unlimited misses made whack blindly automatable. The controller
counts its own registered whiffs (lockout-swallowed shots stay free, exactly
like the server's anti-mash gate keeps throttled shots silent); offline the 3rd
whiff commits the fail on the spot through the same jump-out presentation every
other fail path uses, online the count only fills the pips optimistically while
the server verdict arrives via resolve() as always, and the passive mirror
adopts the relayed pre-increment miss_count the way combo's mirror does. The
count renders as combo-style strike crosses — border ring slots that fill
loss-red with an X — in a row directly under the ATTACKER's cell, anchored
through the controller's geom mapping so a board flip carries them with the
piece, sized off the cell like every other element, cached per (size, struck)
in the module cache, and fading out on the same commit-relative outro as the
hit pips.

The static sprite builders (pit/glow/seam/crosshair/muzzle/casing/win-pop/
strike-cross), their _MOLE_STATIC_CACHE and the knobs only they consume live in
mole_art.py now — pure code motion, so the surfaces they mint are byte-identical
and the cache keys unchanged. Constants both a builder and the controller read
(pulse/bloom/cross-out buckets, the casing spin bucket) are defined in mole_art
and imported into mole_view, keeping the import one-directional. The fixed-TTL
particle sweeps (puffs, debris, impacts, seam sparks) run on juice.py's shared
expire_particles/particle_ages scaffolding; the casings keep their own sweep
because their TTL varies per item (t_land).
"""

import gc
import logging
import math
from unittest.mock import MagicMock, call

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.helpers import click_event as _click
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck import mole_view
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.mole_view import (
    MoleController, MOLE_VIEW_FAIL_HOLD_MS,
    MOLE_VIEW_WIN_HOLD_MS, MOLE_VIEW_HITSTOP_KILL_MS, MOLE_VIEW_HITSTOP_HIT_MS,
    MOLE_VIEW_RETREAT_MS, MOLE_VIEW_PIP_OFFSET_FRAC,
    MOLE_VIEW_JUMP_RISE_MS, MOLE_VIEW_JUMP_HOP_MS, MOLE_VIEW_LAND_SQUASH_MS,
    MOLE_VIEW_REGROW_MS, MOLE_VIEW_TOSS_MS, MOLE_VIEW_TOSS_SPEED_FRAC,
    MOLE_VIEW_TOSS_UP_FRAC, MOLE_VIEW_TOSS_GRAVITY_FRAC,
    MOLE_VIEW_TOSS_SPIN_DPS, MOLE_VIEW_TOSS_FADE_START,
    MOLE_VIEW_PIT_CLOSE_MS, MOLE_VIEW_DANGER_PULSE_MS, MOLE_VIEW_PULSE_MS,
    MOLE_VIEW_HEAL_BUCKETS, MOLE_VIEW_SEAM_BAND_FRAC, MOLE_VIEW_SPARK_MS,
    MOLE_VIEW_CASING_REST_MS, MOLE_VIEW_CASING_FADE_MS,
    MOLE_VIEW_CASING_COMMIT_FADE_MS, MOLE_VIEW_HOLE_STAGGER_MS,
    MOLE_VIEW_POP_HEIGHT_FRAC, MOLE_VIEW_POP_LIFT_CAP, MOLE_VIEW_POP_APEX_FRAC,
    MOLE_VIEW_POP_OVERSHOOT, MOLE_VIEW_SQUASH_BUCKETS, MOLE_VIEW_EMERGE_FADE_FRAC,
    MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS, MOLE_VIEW_CROSS_OUT_MS,
    MOLE_VIEW_SEAM_GLOW_W_FRAC, MOLE_VIEW_SEAM_GLOW_H_FRAC,
    MOLE_VIEW_SPARK_SPEED_FRAC, MOLE_VIEW_CROSS_GLOW_FRAC,
    MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC, MOLE_VIEW_KICK_MS)
from chessshootout.frontend.skillcheck.mole_art import (
    MOLE_VIEW_BLOOM_BUCKETS, MOLE_VIEW_BLOOM_SPIN_DEG, MOLE_VIEW_CROSS_ARC_PAD_FRAC,
    MOLE_VIEW_CROSS_ARC_SPAN_DEG, MOLE_VIEW_CROSS_BLADE_W_FRAC,
    MOLE_VIEW_CROSS_OUT_BUCKETS, MOLE_VIEW_CROSS_OUT_SCALE, MOLE_VIEW_CROSS_TIP_W_FRAC,
    MOLE_VIEW_SEAM_GLOW_CORE,
    _pit_telegraph_surface, _pit_surface, _pit_front_surface, _seam_band_surface,
    _seam_glow_surface, _pit_mouth, _emerge_mask, _crosshair_surface,
    _cross_glow_surface, _strike_cross_surface, _MOLE_STATIC_CACHE)
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.skillcheck.mole import MOLE_RECOIL_LOCKOUT_MS
from chessshootout.frontend.visual.colors import Colors
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.mole import (
    MoleChallenge, MolePop, MOLE_TAUNTS, pick_taunt, MOLE_GRACE_MS,
    MOLE_HITBOX_RX_FRAC, MOLE_HITBOX_RY_FRAC, MOLE_HITBOX_CY_FRAC, MOLE_MAX_WHIFFS)

_JUMP_MS = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS
_JUMP_TOTAL_MS = _JUMP_MS + MOLE_VIEW_LAND_SQUASH_MS
_HEAL_WINDOW_MS = _JUMP_MS + MOLE_VIEW_REGROW_MS
_HOLE_COUNT = 3
_CLOSED_MS = (_HOLE_COUNT - 1) * MOLE_VIEW_HOLE_STAGGER_MS + MOLE_VIEW_PIT_CLOSE_MS

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
    for dt in (MOLE_VIEW_JUMP_RISE_MS / 2, _JUMP_MS / 2, _CLOSED_MS + 50,
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
    # The first update after construction is the fire frame (one frame after the
    # gate opened, in production): it synchronizes the cue counters, and every
    # schedule edge crossed on a LATER frame cues exactly once.
    ctrl = _mole()
    ctrl._audio.play_mole_fall.assert_called_once()
    ctrl.update(0)
    ctrl.update(600)
    ctrl._audio.play_mole_telegraph.assert_called_once()
    ctrl._audio.play_mole_pop.assert_not_called()
    ctrl.update(750)
    ctrl._audio.play_mole_pop.assert_called_once()
    ctrl.update(1800)
    assert ctrl._audio.play_mole_telegraph.call_count == 2


def test_a_resumed_check_fast_forwards_past_stale_cues_without_stacking():
    # /resume rebuilds the controller with a backdated start_ms, so its first
    # schedule pass sees every already-elapsed telegraph/pop at once — the old
    # catch-up loops fired them ALL in that one frame, a machine-gun burst of
    # stale cues. The first pass now only synchronizes the counters; edges that
    # come up afterwards still cue normally.
    ctrl = _mole()
    ctrl.update(3000)
    ctrl._audio.play_mole_telegraph.assert_not_called()
    ctrl._audio.play_mole_pop.assert_not_called()
    ctrl.update(3150)
    ctrl._audio.play_mole_pop.assert_called_once(), "the pop at 3100 is genuinely new"
    ctrl._audio.play_mole_telegraph.assert_not_called()
    ctrl.update(4150)
    ctrl._audio.play_mole_telegraph.assert_called_once(), "and so is the telegraph at 4100"


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


def test_missing_geometry_skips_the_shot_instead_of_laundering_a_sentinel():
    # The old no-mapper path returned a (-1.0, -1.0) sentinel that the clamp
    # laundered into a LEGAL (0.0, 0.0) shot: a fabricated coordinate on the
    # wire and a phantom local adjudication at a8. With no affine there is no
    # shot at all that frame — nothing relays, nothing adjudicates, and none of
    # the shot feedback (muzzle, brass, recoil lockout) is spent on it.
    on_shot = MagicMock()
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), 0,
                          ch.deadline_ms, hole_squares=_HOLES, audio=MagicMock(),
                          victim_surface=_victim(_CELL), on_shot=on_shot)
    ctrl.update(800)
    assert ctrl.handle_event(_click((200, 200))) is True, \
        "the overlay still swallows the click — it just refuses to invent a shot"
    on_shot.assert_not_called()
    assert ctrl._progress == 0
    assert ctrl._casings == [] and ctrl._flash_ms is None
    assert ctrl._last_shot_ms is None, "a skipped shot spends no recoil lockout"
    ctrl._audio.play_whiff_ricochet.assert_not_called()


def test_local_edge_shot_adjudicates_on_the_clamped_value(monkeypatch):
    seen = []
    original = MoleChallenge.hit_at

    def spy(self, elapsed_ms, row_f, col_f, holes, last_hit_pop=-1, **kw):
        seen.append((row_f, col_f))
        return original(self, elapsed_ms, row_f, col_f, holes, last_hit_pop, **kw)

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


def test_resume_last_hit_pop_ctor_param_dedupes_the_already_hit_pop():
    # The resumed value is the server's own last_hit_pop from the /resume
    # snapshot, threaded in as a ctor param — the old code GUESSED it off the
    # wall clock ("whatever pop is up now"), which was wrong whenever the hit
    # pop had already ducked.
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), 0,
                          ch.deadline_ms, hole_squares=_HOLES, geom=_geom_for(_CELL),
                          audio=MagicMock(), victim_surface=_victim(_CELL), progress=1,
                          last_hit_pop=0)
    assert ctrl._last_hit_pop == 0, \
        "resuming mid-pop seeds the hit index so the pop can't be locally re-hit"
    ctrl.update(1000)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "the already-hit pop is deduped on the resumed client"
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._progress == 2, "a later pop still registers normally"


def test_last_hit_pop_defaults_to_no_hits_and_threads_through_the_registry():
    assert _mole()._last_hit_pop == -1
    guessy = _mole(progress=1)
    assert guessy._last_hit_pop == -1, \
        "progress alone no longer back-derives a hit pop from the wall clock"
    built = build_controller(
        SkillCheckKind.WHACK, seed="s", cell_rect=pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL),
        now_ms=0, deadline_ms=5000, value_diff=2, captured_value=4,
        hole_squares=_HOLES, geom=_geom_for(_CELL),
        victim_surface=_victim(_CELL), progress=1, last_hit_pop=2)
    assert built._last_hit_pop == 2, "the registry threads the snapshot value to the mole"


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


def _amber_lit(surf, region):
    # The heal presentation is the only thing on this layer that adds red over the
    # green test victim: the seam band inside the sprite and the world glow bar
    # outside it are both amber, additively blended.
    return [(x, y) for x in range(region.left, region.right)
            for y in range(region.top, region.bottom)
            if surf.get_at((x, y)).r > 60]


def _healed_frame(ctrl, at_ms):
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    _advance(ctrl, _FAIL_AT_MS, at_ms)
    ctrl.draw(surf)
    return surf


def test_an_undamaged_victim_gets_no_seam_no_glow_and_no_sparks():
    # A whack can be lost without a single hit landing. There is nothing to knit
    # back together there, and playing the repair anyway reads as damage the
    # player never took.
    clean = _mole(challenge=_one_pop_challenge(), victim_surface=_solid_victim())
    clean.update(2000)
    assert clean.landed is False and clean._damage_tier() == 0
    for frac in (0.1, 0.3, 0.5, 0.8, 1.0):
        _advance(clean, 2000, 2000 + _HEAL_WINDOW_MS * frac)
        assert clean._seam_sparks == [], "a clean victim strikes no sparks"
        assert clean._last_heal_bucket == 0, "and never even walks the bucket ladder"
        assert clean._healing() is False
        assert clean._victim_sprite() is clean._victim, "it is drawn plain, start to finish"
    # 0.8 of the window is the beat to look at: every pit has already shrunk shut
    # (nothing accent-coloured is left on the layer) and a victim that DID take
    # damage is still visibly knitting, as the twin below proves.
    late = _mole(challenge=_one_pop_challenge(), victim_surface=_solid_victim())
    late.update(2000)
    _advance(late, 2000, 2000 + _HEAL_WINDOW_MS * 0.8)
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    late.draw(surf)
    body = pg.Rect(late.center[0] - _CELL, late.center[1] - _CELL, 2 * _CELL, 2 * _CELL)
    assert _amber_lit(surf, body) == [], "not one amber pixel of repair is painted"
    torn = _fail_at_two_hits(pops=_SOLID_FAIL_POPS, victim_surface=_solid_victim())
    hurt = _healed_frame(torn, _FAIL_AT_MS + _HEAL_WINDOW_MS * 0.8)
    assert torn._healing() is True
    assert _amber_lit(hurt, body), \
        "the probe is blind if a victim that really was shredded lights nothing up"


def test_a_damaged_victim_glows_along_the_seam_past_both_body_edges():
    ctrl = _fail_at_two_hits(pops=_SOLID_FAIL_POPS, victim_surface=_solid_victim())
    assert ctrl._damage_tier() > 0
    surf = _healed_frame(ctrl, _FAIL_AT_MS + _HEAL_WINDOW_MS * 0.7)
    assert ctrl._healing() is True
    bbox = ctrl._victim_bbox
    rect = pg.Rect(ctrl.center[0] - bbox.width, ctrl.center[1] - 2 * _CELL,
                   2 * bbox.width, 3 * _CELL)
    lit = _amber_lit(surf, rect)
    assert lit, "the weld has to be visible at all"
    left_edge = ctrl.center[0] - ctrl._victim.get_width() // 2 + bbox.left
    right_edge = ctrl.center[0] - ctrl._victim.get_width() // 2 + bbox.right
    assert min(x for x, _ in lit) < left_edge, "the glow bar overhangs the body on the left"
    assert max(x for x, _ in lit) >= right_edge, "and on the right"
    span = max(x for x, _ in lit) - min(x for x, _ in lit)
    assert span <= bbox.width * MOLE_VIEW_SEAM_GLOW_W_FRAC + 2 * _CELL * MOLE_VIEW_SPARK_SPEED_FRAC
    key = ("seamglow", max(int(bbox.width * MOLE_VIEW_SEAM_GLOW_W_FRAC), 4),
           max(int(_CELL * MOLE_VIEW_SEAM_GLOW_H_FRAC), 3))
    assert key in _MOLE_STATIC_CACHE, \
        "the bar that was drawn is the one measured off the body box and the cell"


def test_the_seam_glow_bar_is_a_shared_cached_module_surface():
    bar = _seam_glow_surface(60, 8)
    assert _seam_glow_surface(60, 8) is bar, "one bar per size, not one per frame"
    assert ("seamglow", 60, 8) in _MOLE_STATIC_CACHE
    assert bar.get_size() == (60, 8)
    core = bar.get_at((30, 4))
    assert sum(core[:3]) > sum(bar.get_at((30, 0))[:3]), "hottest on the seam row"
    assert sum(core[:3]) > sum(bar.get_at((30, 7))[:3])
    assert sum(core[:3]) > sum(bar.get_at((1, 4))[:3]), "and it falls off to nothing at the ends"
    assert core[0] > core[2], "the weld glows orange, not white-blue"
    inside = bar.get_at((int(30 * MOLE_VIEW_SEAM_GLOW_CORE), 4))
    assert sum(inside[:3]) == sum(core[:3]), \
        "the bar is flat across the body itself and only ramps down over the overhang"


def test_the_glow_bar_is_sized_off_the_body_not_off_the_sprite_footprint():
    ctrl = _fail_at_two_hits()
    bbox = ctrl._victim_bbox
    assert bbox.width < ctrl._victim.get_width(), \
        "the test sprite really does carry transparent margins"
    ctrl.relayout(pg.Rect(0, 0, 2 * _CELL, 2 * _CELL))
    assert ctrl._victim_bbox.width > bbox.width, "the box is re-measured on the scaled victim"


def test_sparks_leave_from_the_bodys_own_edges_not_the_sprite_margin():
    ctrl = _fail_at_two_hits()
    bbox = ctrl._victim_bbox
    rect = pg.Rect(200, 200, ctrl._victim.get_width(), ctrl._victim.get_height())
    assert ctrl._body_edge_x(rect, -1) == rect.left + bbox.left
    assert ctrl._body_edge_x(rect, 1) == rect.left + bbox.right
    assert rect.left < ctrl._body_edge_x(rect, -1), "the left spark starts inside the sprite box"
    assert ctrl._body_edge_x(rect, 1) < rect.right
    ctrl._seam_sparks = [(ctrl._now, -1, 0.5, 1.0, 1.0), (ctrl._now, 1, 0.5, 1.0, 1.0)]
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    ctrl._draw_seam_sparks(surf, rect)
    lit = [(x, y) for x in range(640) for y in range(640)
           if surf.get_at((x, y))[:3] != (0, 0, 0)]
    assert lit, "both sparks painted"
    r = max(int(_CELL * 0.035), 1)
    assert min(x for x, _ in lit) >= ctrl._body_edge_x(rect, -1) - r
    assert max(x for x, _ in lit) <= ctrl._body_edge_x(rect, 1) + r, \
        "at birth a spark sits exactly on the edge it was struck off"


def test_sparks_travel_a_short_hop_off_the_edge_and_never_a_cell_wide_arc():
    assert MOLE_VIEW_SPARK_SPEED_FRAC <= 0.35, \
        "a long throw detaches the spark from the line that threw it"
    ctrl = _fail_at_two_hits()
    rect = pg.Rect(200, 200, ctrl._victim.get_width(), ctrl._victim.get_height())
    ctrl._seam_sparks = [(ctrl._now - MOLE_VIEW_SPARK_MS * 0.9, 1, 0.5, 1.4, 1.5)]
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    ctrl._draw_seam_sparks(surf, rect)
    lit = [x for x in range(640) for y in range(640)
           if surf.get_at((x, y))[:3] != (0, 0, 0)]
    assert lit
    reach = max(lit) - ctrl._body_edge_x(rect, 1)
    assert 0 < reach < _CELL * 0.5, "even the fastest spark dies within half a cell of the seam"


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


def test_the_win_outro_waits_out_the_kill_freeze_then_shuts_every_pit():
    # The body is frozen standing over the pit it was shot at for the whole kill
    # hitstop, and its blit repaints that pit's front lip over itself: start the
    # close any earlier and a full-size lip crescent would hang in the air over a
    # pit that is no longer there.
    ctrl = _won_at_the_far_pit()
    frozen = _draw_at(ctrl, _WIN_AT_MS + int(MOLE_VIEW_HITSTOP_KILL_MS) - 1)
    assert ctrl._home_pit_close_scale() == 1.0, "nothing moves while the freeze holds"
    assert all(ctrl._pit_close_scale(i) == 1.0 for i in range(len(_HOLES)))
    assert _pit_dark_pixels(frozen, ctrl) > 0
    _draw_at(ctrl, _WIN_AT_MS + int(MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_PIT_CLOSE_MS / 2))
    assert 0.0 < ctrl._home_pit_close_scale() < 1.0, "the ground closes as the body flies"
    shut = _draw_at(ctrl, _WIN_AT_MS + int(MOLE_VIEW_HITSTOP_KILL_MS + _CLOSED_MS))
    assert ctrl._home_pit_close_scale() == 0.0
    assert all(ctrl._pit_close_scale(i) == 0.0 for i in range(len(_HOLES)))
    assert _pit_dark_pixels(shut, ctrl) == 0, "no hole is left behind for the capture to land in"
    assert MOLE_VIEW_HITSTOP_KILL_MS + _CLOSED_MS < MOLE_VIEW_WIN_HOLD_MS, \
        "the whole close fits inside the hold it already had"


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


def _hole_dark_pixels(surf, ctrl, index):
    dark = pg.Color(Colors.well_deep)
    cx, cy = _hole_px(index)
    return sum(1 for x in range(cx - ctrl._pit_rx, cx + ctrl._pit_rx + 1)
               for y in range(cy - ctrl._pit_ry, cy + ctrl._pit_ry + 1)
               if surf.get_at((x, y))[:3] == (dark.r, dark.g, dark.b))


def test_every_pit_shrinks_shut_after_a_fail_on_the_stagger_that_opened_it():
    # The old fail cross-faded the holes out over 300ms — a patch of ground going
    # translucent and then simply not being there. They close the way they opened:
    # the same mouth animation, the same per-hole stagger, backwards.
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    assert ctrl.landed is False
    assert [ctrl._pit_close_scale(i) for i in range(len(_HOLES))] == [1.0] * len(_HOLES)
    open_surf = _draw_at(ctrl, 2000)
    assert _hole_dark_pixels(open_surf, ctrl, 1) > 0
    ctrl.update(2000 + int(MOLE_VIEW_PIT_CLOSE_MS))
    assert ctrl._pit_close_scale(0) == 0.0, "the first hole is already shut"
    assert 0.0 < ctrl._pit_close_scale(1) < ctrl._pit_close_scale(2), \
        "and the rest are still closing, one stagger step behind each other"
    scales = []
    for dt in range(0, int(_CLOSED_MS) + 1, 10):
        ctrl.update(2000 + dt)
        scales.append(ctrl._pit_close_scale(1))
    assert scales == sorted(scales, reverse=True), scales
    assert scales[0] == 1.0 and scales[-1] == 0.0
    shut = _draw_at(ctrl, 2000 + int(_CLOSED_MS))
    assert all(ctrl._pit_close_scale(i) == 0.0 for i in range(len(_HOLES)))
    assert _hole_dark_pixels(shut, ctrl, 1) == 0, "the ground is whole again"
    assert _CLOSED_MS < MOLE_VIEW_FAIL_HOLD_MS, "the close fits inside the hold it already had"


def test_the_home_pit_still_outlasts_the_climb_out_while_the_others_close():
    # The victim is standing in the home pit while the others shut: that one is
    # on the jump's clock, not the commit's.
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    ctrl.update(2000 + int(_CLOSED_MS))
    assert ctrl._home_pit_close_scale() == 1.0, "still open under the feet that are climbing out"
    assert all(ctrl._pit_close_scale(i) == 0.0 for i in range(len(_HOLES)))
    ctrl.update(2000 + int(_JUMP_MS + MOLE_VIEW_PIT_CLOSE_MS))
    assert ctrl._home_pit_close_scale() == 0.0, "and it shuts once the feet are down"


def test_the_commit_caps_the_brass_with_a_fade_so_nothing_pops_off():
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(800)
    ctrl.handle_event(_click((500, 400)))
    assert len(ctrl._casings) == 1
    amber = pg.Color(Colors.amber)
    region = pg.Rect(370, 370, 260, 120)

    def brass(now_ms):
        surf = _draw_at(ctrl, now_ms)
        return sum(1 for x in range(region.left, region.right)
                   for y in range(region.top, region.bottom)
                   if surf.get_at((x, y))[:3] == (amber.r, amber.g, amber.b))

    assert brass(1900) > 0, "the casing is lying there long before the verdict"
    ctrl.update(2000)
    assert ctrl.landed is False
    assert ctrl._commit_fade_alpha(0.0, MOLE_VIEW_CASING_COMMIT_FADE_MS) == 255, \
        "it is still solid on the commit frame itself"
    ctrl.update(2000 + int(MOLE_VIEW_CASING_COMMIT_FADE_MS / 2))
    assert 0 < ctrl._commit_fade_alpha(0.0, MOLE_VIEW_CASING_COMMIT_FADE_MS) < 255
    assert brass(2000 + int(MOLE_VIEW_CASING_COMMIT_FADE_MS)) == 0, \
        "and it is gone well before the overlay retires, instead of blinking out with it"
    assert ctrl._casings, "the cap only hides it — the normal life still owns the prune"
    assert MOLE_VIEW_CASING_COMMIT_FADE_MS < MOLE_VIEW_FAIL_HOLD_MS


def test_the_pips_hold_a_beat_after_the_verdict_and_then_fade_out():
    ctrl = _fail_at_two_hits()
    filled = _draw_at(ctrl, _FAIL_AT_MS)
    assert _accent_in_band(filled, ctrl) is True, "the score is still readable at the verdict"
    ctrl.update(_FAIL_AT_MS + int(MOLE_VIEW_PIP_FADE_DELAY_MS))
    assert ctrl._commit_fade_alpha(MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS) == 255, \
        "the player gets the whole delay to read it before it starts going"
    ctrl.update(_FAIL_AT_MS + int(MOLE_VIEW_PIP_FADE_DELAY_MS + MOLE_VIEW_PIP_FADE_MS / 2))
    mid = ctrl._commit_fade_alpha(MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS)
    assert 0 < mid < 255
    gone = _draw_at(ctrl, _FAIL_AT_MS + int(MOLE_VIEW_PIP_FADE_DELAY_MS + MOLE_VIEW_PIP_FADE_MS))
    assert ctrl._commit_fade_alpha(MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS) == 0
    assert _accent_in_band(gone, ctrl) is False, "and it is faded out, not switched off"
    assert MOLE_VIEW_PIP_FADE_DELAY_MS + MOLE_VIEW_PIP_FADE_MS < MOLE_VIEW_FAIL_HOLD_MS


def _draw_on_black(ctrl, now_ms):
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    ctrl.update(int(now_ms))
    ctrl.draw(surf)
    return surf


def _cross_lit(surf, at):
    box = pg.Rect(at[0] - 40, at[1] - 40, 80, 80)
    return sum(1 for x in range(box.left, box.right) for y in range(box.top, box.bottom)
               if sum(surf.get_at((x, y))[:3]) > 90)


def test_the_crosshair_scales_and_fades_out_instead_of_vanishing_on_the_verdict(monkeypatch):
    at = (600, 600)
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: at)
    ctrl = _mole(challenge=_one_pop_challenge())
    live = _draw_on_black(ctrl, 1900)
    assert ctrl._crosshair_fade() == 1.0
    assert _cross_lit(live, at) > 0, "the reticle is drawn while the check runs"
    ctrl.update(2000)
    assert ctrl.landed is False
    assert ctrl._crosshair_fade() == 1.0, "it is still whole on the commit frame"
    half = _draw_on_black(ctrl, 2000 + int(MOLE_VIEW_CROSS_OUT_MS / 2))
    assert 0.0 < ctrl._crosshair_fade() < 1.0
    assert 0 < _cross_lit(half, at) < _cross_lit(live, at), \
        "half way out it is dimmer and smaller, not missing"
    gone = _draw_on_black(ctrl, 2000 + int(MOLE_VIEW_CROSS_OUT_MS))
    assert ctrl._crosshair_fade() == 0.0
    assert _cross_lit(gone, at) == 0


def test_the_crosshair_fade_steps_through_a_bounded_set_of_bucketed_reticles(monkeypatch):
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (600, 600))
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    surf = pg.Surface((640, 640))
    before = {k for k in _MOLE_STATIC_CACHE if k[0] == "cross"}
    for dt in range(1, int(MOLE_VIEW_CROSS_OUT_MS), 2):
        ctrl.update(2000 + dt)
        ctrl.draw(surf)
    minted = {k for k in _MOLE_STATIC_CACHE if k[0] == "cross"} - before
    assert 0 < len(minted) <= MOLE_VIEW_CROSS_OUT_BUCKETS + 1, \
        "the fade builds one reticle per scale bucket, not one surface per frame"
    assert all(k[5] <= MOLE_VIEW_CROSS_OUT_BUCKETS for k in minted), \
        "and they live in the shared size-keyed cache keyed by out bucket"


def test_the_live_reticle_re_blits_one_cached_surface_and_one_glow(monkeypatch):
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (600, 600))
    ctrl = _mole()
    surf = pg.Surface((640, 640))
    ctrl.update(600)
    ctrl.draw(surf)
    key = ("cross", ctrl._cross_arm, ctrl._cross_gap, ctrl._cross_lw, 0, 0)
    glow_r = max(int(ctrl.cell_size * MOLE_VIEW_CROSS_GLOW_FRAC), 6)
    assert key in _MOLE_STATIC_CACHE
    assert _MOLE_STATIC_CACHE[("crossglow", glow_r)] is _cross_glow_surface(glow_r)
    before = {k for k in _MOLE_STATIC_CACHE if k[0] in ("cross", "crossglow")}
    for dt in range(1, 51):
        ctrl.update(600 + dt)
        ctrl.draw(surf)
    after = {k for k in _MOLE_STATIC_CACHE if k[0] in ("cross", "crossglow")}
    assert after == before, "steady state mints nothing — the cursor is two cached blits"


def _amberish(p):
    return p[0] > 180 and p[1] > 140 and p[2] < 130 and p[3] > 60


def _amber_on_east_ray(surf):
    c = surf.get_width() // 2
    return any(_amberish(surf.get_at((x, c))) for x in range(c + 17, surf.get_width()))


def test_full_bloom_spreads_the_reticle_and_sweeps_the_heated_ring_across_the_gap():
    rest = _crosshair_surface(15, 4, 2, 0, 0)
    full = _crosshair_surface(15, 4, 2, MOLE_VIEW_BLOOM_BUCKETS, 0)
    assert full.get_bounding_rect().width > rest.get_bounding_rect().width, \
        "recoil pushes the blades and ring outward"
    assert not _amber_on_east_ray(rest), \
        "at rest the ring gap sits on the blade line and the arcs stay accent-cool"
    assert _amber_on_east_ray(full), \
        "at full bloom the arcs rotate across the blade line and heat to amber"


def test_a_shot_lockout_mints_at_most_the_bloom_buckets_and_then_reuses_them(monkeypatch):
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (600, 600))
    ctrl = _mole()
    surf = pg.Surface((640, 640))
    ctrl.update(800)
    ctrl.draw(surf)
    before = {k for k in _MOLE_STATIC_CACHE if k[0] == "cross"}
    ctrl.handle_event(_click((600, 600)))
    for dt in range(0, int(MOLE_RECOIL_LOCKOUT_MS) + 1, 6):
        ctrl.update(800 + dt)
        ctrl.draw(surf)
    minted = {k for k in _MOLE_STATIC_CACHE if k[0] == "cross"} - before
    assert 0 < len(minted) <= MOLE_VIEW_BLOOM_BUCKETS + 1, \
        "the bloom walks bucketed reticles while the lockout runs"
    assert all(k[4] <= MOLE_VIEW_BLOOM_BUCKETS and k[5] == 0 for k in minted)
    steady = {k for k in _MOLE_STATIC_CACHE if k[0] == "cross"}
    ctrl.handle_event(_click((600, 600)))
    for dt in range(0, int(MOLE_RECOIL_LOCKOUT_MS) + 1, 6):
        ctrl.update(1000 + dt)
        ctrl.draw(surf)
    assert {k for k in _MOLE_STATIC_CACHE if k[0] == "cross"} == steady, \
        "every later shot re-blits the same bucketed set"


def _lit_centroid_y(surf, at):
    ys = [y for x in range(at[0] - 40, at[0] + 40) for y in range(at[1] - 40, at[1] + 40)
          if sum(surf.get_at((x, y))[:3]) > 90]
    return sum(ys) / len(ys)


def test_the_kick_lifts_the_reticle_and_settles_it_back(monkeypatch):
    at = (600, 600)
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: at)
    ctrl = _mole()
    rest = _draw_on_black(ctrl, 900)
    ctrl._flash_ms = 1000.0
    kicked = _draw_on_black(ctrl, 1000)
    assert _lit_centroid_y(rest, at) - _lit_centroid_y(kicked, at) >= 2.0, \
        "the whole reticle rides the recoil upward on the shot frame"
    settled = _draw_on_black(ctrl, 1000 + int(MOLE_VIEW_KICK_MS))
    assert abs(_lit_centroid_y(settled, at) - _lit_centroid_y(rest, at)) < 1.0, \
        "and settles back onto the cursor when the kick window closes"


def _bright_span(surf, x, c):
    return sum(1 for dy in range(-6, 7)
               if sum(surf.get_at((x, c + dy))[:3]) > 330
               and surf.get_at((x, c + dy))[3] > 120)


def test_reticle_anatomy_amber_dot_needle_blades_dark_contour_and_aligned_ring_gaps():
    surf = _crosshair_surface(15, 4, 2, 0, 0)
    c = surf.get_width() // 2
    center = surf.get_at((c, c))
    amber = pg.Color(Colors.amber_hi)
    assert all(abs(center[i] - amber[i]) < 20 for i in range(3)), \
        "the center dot burns amber_hi"
    assert 0 < _bright_span(surf, c + 6, c) < _bright_span(surf, c + 17, c) <= 3, \
        "each blade is a slim needle with a barely-there taper, never a petal wedge"
    band = [surf.get_at((c + 17, c + dy)) for dy in range(-6, 7)]
    assert any(sum(p[:3]) < 300 and p[3] > 60 for p in band), \
        "a dark contour wraps the white core so the cursor reads on light squares"
    arc_r = 4 + 15 + max(15 * MOLE_VIEW_CROSS_ARC_PAD_FRAC, 2.0)
    d = int(round(arc_r * math.cos(math.pi / 4)))
    diag = [surf.get_at((c + d + off, c + d + off)) for off in range(-2, 3)]
    assert any(p[0] > 180 and p[1] < 150 and p[2] < 130 and p[3] > 120 for p in diag), \
        "a hairline accent arc rides each diagonal"
    ray = [surf.get_at((x, c)) for x in range(c + 21, surf.get_width())]
    assert all(p[3] <= 60 for p in ray), \
        "and the ring gaps align with the blade lines, so the cardinal axes stay clear"


def test_the_crosshair_beats_stay_inside_the_choreography_windows():
    assert MOLE_VIEW_KICK_MS <= MOLE_RECOIL_LOCKOUT_MS
    assert MOLE_VIEW_CROSS_OUT_MS < min(MOLE_VIEW_WIN_HOLD_MS, MOLE_VIEW_FAIL_HOLD_MS)
    assert 0.0 < MOLE_VIEW_CROSS_OUT_SCALE < 1.0
    assert MOLE_VIEW_BLOOM_BUCKETS >= 4 and MOLE_VIEW_CROSS_OUT_BUCKETS >= 4
    assert 0.0 < MOLE_VIEW_BLOOM_SPIN_DEG < 45.0
    assert 0.0 < MOLE_VIEW_CROSS_ARC_SPAN_DEG < 90.0
    assert MOLE_VIEW_CROSS_TIP_W_FRAC < MOLE_VIEW_CROSS_BLADE_W_FRAC <= 0.15, \
        "needle blades stay needles — the propeller read came from fat bases"


def _corners_stay_board(surface):
    board = pg.Color(Colors.white_tile)
    canvas = pg.Surface(surface.get_size())
    canvas.fill(board)
    canvas.blit(surface, (0, 0))
    w, h = surface.get_size()
    return all(canvas.get_at(p)[:3] == (board.r, board.g, board.b)
               for p in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)))


def test_reticle_surfaces_are_transparent_off_the_marks_at_rest_bloom_and_fade():
    idle = _crosshair_surface(15, 4, 2, 0, 0)
    bloomed = _crosshair_surface(15, 4, 2, MOLE_VIEW_BLOOM_BUCKETS, 0)
    fading = _crosshair_surface(15, 4, 2, 0, MOLE_VIEW_CROSS_OUT_BUCKETS // 2)
    for surface in (idle, bloomed, fading):
        assert _corners_stay_board(surface), \
            "an opaque backing surface would stamp a dark box over the board"
    fading.set_alpha(128)
    assert _corners_stay_board(fading), \
        "the fade's blanket alpha rides on per-pixel alpha, not an opaque plate"
    fading.set_alpha(255)


def test_a_finished_fade_never_poisons_the_cached_reticles_into_opaque_boxes(monkeypatch):
    # set_alpha(None) on an SRCALPHA surface disables per-pixel alpha for every
    # later blit of that surface — the shipped bug: after one verdict fade the
    # next check's live reticle stamped a solid dark box over the board. The
    # draw path must restore with set_alpha(255), which keeps the channel armed.
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (600, 600))
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    surf = pg.Surface((640, 640))
    for dt in range(1, int(MOLE_VIEW_CROSS_OUT_MS), 2):
        ctrl.update(2000 + dt)
        ctrl.draw(surf)
    live_key = ("cross", ctrl._cross_arm, ctrl._cross_gap, ctrl._cross_lw, 0, 0)
    assert _corners_stay_board(_MOLE_STATIC_CACHE[live_key]), \
        "the reticle a later check re-blits still carries its transparency"


def test_the_draw_path_never_darkens_the_board_around_the_crosshair(monkeypatch):
    at = (600, 600)
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: at)
    ctrl = _mole()
    board = pg.Color(Colors.white_tile)
    surf = pg.Surface((640, 640))
    surf.fill(board)
    ctrl.update(600)
    ctrl._draw_crosshair(surf)
    half = _crosshair_surface(ctrl._cross_arm, ctrl._cross_gap, ctrl._cross_lw,
                              0, 0).get_width() // 2
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        p = surf.get_at((at[0] + dx * (half - 1), at[1] + dy * (half - 1)))
        assert p[:3] == (board.r, board.g, board.b), \
            "the reticle square's empty corners leave the tile untouched"
    inside = surf.get_at((at[0] + 6, at[1] + 6))
    assert all(inside[i] >= board[i] for i in range(3)), \
        "the additive glow can only brighten the tile, never shadow it"


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


def test_blit_victim_reports_the_ground_rect_it_stands_on():
    # The rect is what the seam sparks hang off, so it is the body's GROUND box:
    # crown to ground line. The standing branch paints exactly that box; the
    # emerging branch paints the same box plus whatever of the body the mouth arc
    # still shows below the ground line — and None when nothing is on screen.
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
    clipped = ctrl._blit_victim(clip_surf, ctrl.center, 0.5, (0, 0))
    assert clipped.width == full.width
    assert clipped.height == int(ctrl._victim.get_height() * 0.5)
    assert clipped.bottom == ctrl.center[1] + ctrl._emergence_dy(0.5), \
        "the half-risen mole's ground line is the emergence anchor, nothing else"
    assert clip_surf.get_at(clipped.topleft)[:3] == _TOSS_COLOR, \
        "the crown is out of the hole at full strength"
    assert clip_surf.get_at((clipped.centerx, clipped.top - 1))[:3] == (0, 0, 0), \
        "and nothing is painted above it"


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


def test_the_ground_line_rides_the_pit_wall_up_as_the_body_emerges():
    # The old model nailed the feet half a pit-radius BELOW the ellipse centre for
    # the whole pop, so a straight cut ran across the sprite on bare board either
    # side of the mouth. The anchor now travels: deep in the hole at zero height,
    # exactly on the ellipse centre once the body is all the way out.
    ctrl = _mole()
    assert ctrl._emergence_dy(0.0) == ctrl._pit_ry, "it starts down on the near lip"
    assert ctrl._emergence_dy(1.0) == 0, "and ends standing on the pit's own centre line"
    assert ctrl._emergence_dy(MOLE_VIEW_POP_LIFT_CAP) == 0, \
        "the overshoot bounce lifts off that line, it never digs back into the ground"
    steps = [ctrl._emergence_dy(i / 20.0) for i in range(21)]
    assert steps == sorted(steps, reverse=True), steps
    assert 0 < ctrl._emergence_dy(0.5) < ctrl._pit_ry


def test_a_full_pop_shows_the_whole_piece_clear_of_the_pit_lip():
    assert MOLE_VIEW_POP_HEIGHT_FRAC == 1.0, \
        "a pop that stops short of full height can never show the whole piece"
    ctrl = _mole(victim_surface=_solid_victim())
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    rect = ctrl._blit_victim(surf, ctrl.center, MOLE_VIEW_POP_HEIGHT_FRAC, (0, 0), lip=True)
    assert rect.height == ctrl._victim.get_height(), "not one row is clipped off"
    assert rect.bottom == ctrl.center[1], "the feet stand on the pit's centre line"
    dark = pg.Color(Colors.well_deep)
    for y in range(rect.top, rect.bottom):
        for x in range(rect.left, rect.right):
            px = surf.get_at((x, y))[:3]
            assert px == _TOSS_COLOR, \
                "the lip covers the body at ({}, {}) — it must sit entirely below it".format(x, y)
            assert px != (dark.r, dark.g, dark.b)


def test_an_emerging_body_is_always_cut_inside_the_pit_mouth():
    # Every intermediate frame's ground line has to live between the ellipse
    # centre and its near lip: that is the band the mouth arc is carved out of.
    ctrl = _mole(victim_surface=_solid_victim())
    surf = pg.Surface((640, 640))
    cy = ctrl.center[1]
    tops = []
    for i in range(1, 21):
        rect = ctrl._blit_victim(surf, ctrl.center, i / 20.0, (0, 0), lip=True)
        assert cy <= rect.bottom <= cy + ctrl._pit_ry, \
            "height {} cuts the body at {}, outside the mouth".format(i / 20.0, rect.bottom)
        tops.append(rect.top)
    assert tops == sorted(tops, reverse=True), "the crown only ever climbs"
    assert tops[-1] == cy - ctrl._victim.get_height()


def _emergence_frame(ctrl, height_frac):
    surf = pg.Surface((640, 640))
    surf.fill((0, 0, 0))
    rect = ctrl._blit_victim(surf, ctrl.center, height_frac, (0, 0), lip=True)
    return surf, rect


def _body_bottoms(surf, rect):
    # Lowest painted row per column of the emerging body: the boundary the player
    # reads as the edge of the hole the piece is climbing out of.
    bottoms = {}
    for x in range(rect.left, rect.right):
        lit = [y for y in range(rect.top, surf.get_height()) if surf.get_at((x, y)).g > 0]
        bottoms[x] = max(lit) if lit else None
    return bottoms


def _lit_span(surf, y, rect):
    return sum(1 for x in range(rect.left, rect.right) if surf.get_at((x, y)).g > 0)


def test_the_emerging_body_is_cut_on_the_pits_own_concave_mouth_arc():
    # The old cut was one straight row across the whole sprite: a wall the piece
    # hid behind, with the part of the body wider than the mouth hanging over bare
    # board below it. The boundary is the mouth's LOWER ARC now — deepest under
    # the centre of the hole, rising to the ground line at both rims.
    ctrl = _mole(victim_surface=_solid_victim())
    cy, cx = ctrl.center[1], ctrl.center[0]
    surf, rect = _emergence_frame(ctrl, 0.5)
    bottoms = _body_bottoms(surf, rect)
    band = ctrl._emerge_fade
    assert cy + ctrl._mouth_ry - band <= bottoms[cx] <= cy + ctrl._mouth_ry, \
        "the centre column dips to the deepest point of the mouth, inside its fade band"
    assert cy - band <= bottoms[rect.left] <= cy, \
        "and a column past the rim stops on the ground line"
    assert bottoms[cx] - bottoms[rect.left] >= ctrl._mouth_ry - 1, \
        "the dip is the whole depth of the mouth, not a rounding artefact"
    profile = [bottoms[x] for x in range(cx, rect.right)]
    assert profile == sorted(profile, reverse=True), \
        "the arc only ever climbs on the way out to the rim: {}".format(profile)
    mirrored = [bottoms[x] for x in range(rect.right - 1, cx - 1, -1)]
    assert all(abs(a - b) <= 1 for a, b in zip([bottoms[x] for x in range(rect.left, cx)],
                                               mirrored)), \
        "and it is symmetric about the hole"


def test_no_row_below_the_ground_line_is_painted_full_width():
    # The tell of the old wall: a fully opaque row of body running the entire
    # width of the sprite, below the ground line, on bare board.
    ctrl = _mole(victim_surface=_solid_victim())
    cy = ctrl.center[1]
    for height in (0.2, 0.4, 0.6, 0.8, 0.95):
        surf, rect = _emergence_frame(ctrl, height)
        for y in range(cy, cy + ctrl._pit_ry + 1):
            span = _lit_span(surf, y, rect)
            assert span <= 2 * ctrl._mouth_rx, \
                "height {} paints {} px of body across row {} — wider than the mouth".format(
                    height, span, y - cy)


def test_the_body_fades_in_across_the_mouth_line_instead_of_hard_cutting():
    ctrl = _mole(victim_surface=_solid_victim())
    fade = ctrl._emerge_fade
    assert 2 <= fade <= ctrl._mouth_ry // 2, "a short band, not half the hole"
    assert fade == max(int(ctrl._mouth_ry * MOLE_VIEW_EMERGE_FADE_FRAC), 2), \
        "the band is a fraction of the mouth's own depth, never a fixed pixel count"
    assert _mole(cell=2 * _CELL)._emerge_fade > fade, "so it scales with the board"
    mask = _emerge_mask(_CELL, ctrl._mouth_rx, ctrl._mouth_ry, fade)
    column = [mask.get_at((_CELL // 2, y)).a for y in range(mask.get_height())]
    band = column[ctrl._mouth_ry:ctrl._mouth_ry + fade]
    assert column[ctrl._mouth_ry - 1] == 255, "solid body right up to the band"
    assert all(b < a for a, b in zip([255] + band, band)), \
        "then a ramp, one step per row: {}".format(band)
    assert band[-1] == 0 and column[ctrl._mouth_ry + fade] == 0, \
        "and it is gone by the arc itself"
    surf, rect = _emergence_frame(ctrl, 0.5)
    edge = [surf.get_at((ctrl.center[0], y)).g
            for y in range(ctrl.center[1] + ctrl._mouth_ry - fade, ctrl.center[1] + ctrl._mouth_ry)]
    assert all(b < a for a, b in zip(edge, edge[1:])), \
        "the drawn body dissolves into the hole over the same band: {}".format(edge)


def _dark_extent(surf):
    dark = pg.Color(Colors.well_deep)
    w, h = surf.get_size()
    cols = [y for y in range(h) if surf.get_at((w // 2, y))[:3] == (dark.r, dark.g, dark.b)]
    rows = [x for x in range(w) if surf.get_at((x, h // 2))[:3] == (dark.r, dark.g, dark.b)]
    return (max(rows) - min(rows) + 1) / 2.0, (max(cols) - min(cols) + 1) / 2.0


@pytest.mark.parametrize("cell", [60, 80, 160])
def test_the_mouth_the_mask_carves_is_the_mouth_the_pit_sprite_draws(cell):
    # Both are derived off the same inset/rim fractions, so the arc can never
    # drift off the hole it is supposed to be the near lip of.
    ctrl = _mole(cell=cell)
    rx, ry = _dark_extent(_pit_surface(ctrl._pit_rx, ctrl._pit_ry))
    assert _pit_mouth(ctrl._pit_rx, ctrl._pit_ry) == (ctrl._mouth_rx, ctrl._mouth_ry)
    assert ctrl._mouth_rx == pytest.approx(rx, abs=1), \
        "the arc is measured through the same supersample the pit is drawn through"
    assert ctrl._mouth_ry == pytest.approx(ry, abs=1)
    assert ctrl._mouth_rx < ctrl._pit_rx and ctrl._mouth_ry < ctrl._pit_ry, \
        "the mouth sits inside the rim — the body slides under it, never over it"


def test_the_emergence_mask_and_its_scratch_are_cached_and_bounded():
    ctrl = _mole(victim_surface=_solid_victim())
    key = ("emerge", _CELL, ctrl._mouth_rx, ctrl._mouth_ry, ctrl._emerge_fade)
    mask = _emerge_mask(_CELL, ctrl._mouth_rx, ctrl._mouth_ry, ctrl._emerge_fade)
    assert _emerge_mask(_CELL, ctrl._mouth_rx, ctrl._mouth_ry, ctrl._emerge_fade) is mask
    assert key in _MOLE_STATIC_CACHE, "one mask per sprite width and pit mouth, shared"
    surf = pg.Surface((640, 640))
    pop = ctrl.challenge.pops[0]
    frames = range(int(pop.t_up_ms), int(pop.t_down_ms + MOLE_GRACE_MS), 4)
    before = sum(1 for k in _MOLE_STATIC_CACHE if k[0] == "emerge")
    for now in frames:
        ctrl.update(now)
        ctrl.draw(surf)
    minted = sum(1 for k in _MOLE_STATIC_CACHE if k[0] == "emerge") - before
    assert 0 < minted <= MOLE_VIEW_SQUASH_BUCKETS, \
        "a whole bounce mints one mask per squash width, not one per frame"
    assert 0 < len(ctrl._emerge_scratch) <= MOLE_VIEW_SQUASH_BUCKETS, \
        "and one reusable scratch per width: {}".format(list(ctrl._emerge_scratch))
    settled = sum(1 for k in _MOLE_STATIC_CACHE if k[0] == "emerge")
    scratches = dict(ctrl._emerge_scratch)
    for now in frames:
        ctrl.update(now + 1)
        ctrl.draw(surf)
    assert sum(1 for k in _MOLE_STATIC_CACHE if k[0] == "emerge") == settled
    assert ctrl._emerge_scratch == scratches, "a second bounce allocates nothing at all"
    ctrl.relayout(pg.Rect(0, 0, 2 * _CELL, 2 * _CELL))
    assert ctrl._emerge_scratch == {}, "every scratch was cut for the old sprite size"


def _pop_window(pop):
    # The visual window is the pop's own up-time plus the engine's grace: the body
    # is on screen for exactly as long as the pop is hittable, never a beat more.
    return pop.t_down_ms - pop.t_up_ms + MOLE_GRACE_MS


def _bounce_track(ctrl, pop, steps=240):
    window = _pop_window(pop)
    return [(i / steps, ctrl._render_pop(pop.t_up_ms + window * i / steps))
            for i in range(steps + 1)]


def _bounce_heights(ctrl, pop, steps=240):
    return [(u, 0.0 if frame is None else frame[1])
            for u, frame in _bounce_track(ctrl, pop, steps)]


def test_the_pop_never_stops_at_the_top_it_bounces_straight_back_down():
    # The old pop rose over a fixed 140ms, HELD at full height until t_down and
    # only then retreated — a flat plateau that made every pop feel identical and
    # dead at the top. It is one continuous arc now: out to the apex, straight
    # back into the hole, no hold anywhere in the window.
    ctrl = _mole()
    pop = ctrl.challenge.pops[0]
    track = _bounce_heights(ctrl, pop)
    up = [h for u, h in track if u <= MOLE_VIEW_POP_APEX_FRAC]
    down = [h for u, h in track if u >= MOLE_VIEW_POP_APEX_FRAC]
    assert all(b > a for a, b in zip(up, up[1:])), "the climb only ever climbs"
    assert all(b < a for a, b in zip(down, down[1:])), "and the fall only ever falls"
    peak = max(h for _, h in track)
    assert [h for _, h in track].count(peak) == 1, \
        "exactly one frame is at the top — a second one would be a hold"


def test_the_apex_lands_on_the_knob_fraction_at_a_touch_past_whole():
    assert 0.0 < MOLE_VIEW_POP_APEX_FRAC < 0.5, \
        "the apex is early in the window: a fast punch out, a long fall back"
    assert MOLE_VIEW_POP_OVERSHOOT > MOLE_VIEW_POP_HEIGHT_FRAC, \
        "the body clears the lip and lifts off it, it does not stop flush with the ground"
    assert MOLE_VIEW_POP_OVERSHOOT <= MOLE_VIEW_POP_LIFT_CAP, \
        "and the lift cap still bounds whatever the curve asks for"
    ctrl = _mole()
    pop = ctrl.challenge.pops[0]
    apex = MOLE_VIEW_POP_HEIGHT_FRAC * MOLE_VIEW_POP_OVERSHOOT
    at_apex = ctrl._render_pop(pop.t_up_ms + _pop_window(pop) * MOLE_VIEW_POP_APEX_FRAC)
    assert at_apex[1] == pytest.approx(apex), "full height plus the overshoot, exactly there"
    assert max(h for _, h in _bounce_heights(ctrl, pop)) == pytest.approx(apex), \
        "and nothing in the window ever goes higher"


def test_the_bounce_is_continuous_across_the_whole_window():
    ctrl = _mole()
    pop = ctrl.challenge.pops[0]
    heights = [h for _, h in _bounce_heights(ctrl, pop, steps=int(_pop_window(pop)))]
    assert heights[0] == 0.0, "it starts flush with the pit floor"
    assert heights[-1] == 0.0, "and ends back in it"
    apex = MOLE_VIEW_POP_HEIGHT_FRAC * MOLE_VIEW_POP_OVERSHOOT
    steps = [abs(b - a) for a, b in zip(heights, heights[1:])]
    assert max(steps) < apex * 0.02, \
        "no millisecond of the arc teleports: biggest step is {}".format(max(steps))


def test_the_pop_is_on_screen_for_exactly_as_long_as_it_is_hittable():
    ctrl = _mole()
    pop = ctrl.challenge.pops[0]
    assert ctrl.challenge.pop_up_at(pop.t_down_ms + MOLE_GRACE_MS - 1) == 0
    assert ctrl.challenge.pop_up_at(pop.t_down_ms + MOLE_GRACE_MS) is None
    assert ctrl._render_pop(pop.t_down_ms + MOLE_GRACE_MS - 1) is not None, \
        "the last hittable millisecond still shows something to shoot at"
    assert ctrl._render_pop(pop.t_down_ms + MOLE_GRACE_MS) is None, \
        "and the body is gone the instant the grace window closes"
    assert ctrl._render_pop(pop.t_up_ms) is None, "nothing is drawn on the launch frame itself"


def _front_rim_pixels(surf, ctrl, index):
    accent = pg.Color(Colors.accent)
    cx, cy = _hole_px(index)
    return sum(1 for x in range(cx - ctrl._pit_rx, cx + ctrl._pit_rx + 1)
               for y in range(cy, cy + ctrl._pit_ry + 1)
               if surf.get_at((x, y))[:3] == (accent.r, accent.g, accent.b))


def test_an_emerging_body_never_paints_over_the_rim_it_is_climbing_out_of():
    # The mask is carved on the pit's dark MOUTH, not on its outer ellipse, so the
    # accent rim in front of the hole survives every frame of the climb untouched
    # — which is what the front-half repaint used to be there for.
    ctrl = _mole(victim_surface=_solid_victim())
    pop = ctrl.challenge.pops[0]
    idle = _draw_at(ctrl, pop.t_down_ms + MOLE_GRACE_MS + 30)
    assert ctrl._render_pop(pop.t_down_ms + MOLE_GRACE_MS + 30) is None, \
        "the reference frame has no body over the hole at all"
    bare = _front_rim_pixels(idle, ctrl, pop.hole)
    assert bare > 0, "the rim really is painted there"
    for frac in (0.05, 0.15, 0.6, 0.75, 0.9):
        at = pop.t_up_ms + _pop_window(pop) * frac
        assert ctrl._render_pop(at)[1] < MOLE_VIEW_POP_HEIGHT_FRAC, \
            "every probe is a frame the mask owns, not one the front-half repaint does"
        frame = _draw_at(ctrl, at)
        assert _front_rim_pixels(frame, ctrl, pop.hole) == bare, \
            "the body ate the near rim at {} of the window".format(frac)


def _fall_rate(ctrl, pop):
    window = _pop_window(pop)
    late = MOLE_VIEW_POP_APEX_FRAC + (1.0 - MOLE_VIEW_POP_APEX_FRAC) / 2.0
    a = ctrl._render_pop(pop.t_up_ms + window * late)[1]
    b = ctrl._render_pop(pop.t_up_ms + window * late + 50.0)[1]
    return (a - b) / 50.0


def test_a_pop_with_a_longer_up_time_falls_slower_than_a_short_one():
    # The window is the pop's own up-time, so the ramp the engine builds per piece
    # value (and squeezes to fit a short deadline) shows up as pace: a queen's
    # compressed pops snap back down, a pawn's linger.
    slow = _mole(challenge=_challenge(pops=(MolePop(0, 100.0, 300.0, 1300.0),),
                                      hits_required=1))
    fast = _mole(challenge=_challenge(pops=(MolePop(0, 100.0, 300.0, 900.0),),
                                      hits_required=1))
    slow_rate = _fall_rate(slow, slow.challenge.pops[0])
    fast_rate = _fall_rate(fast, fast.challenge.pops[0])
    assert 0.0 < slow_rate < fast_rate, \
        "a 1000ms pop drops at {} per ms, a 600ms one at {}".format(slow_rate, fast_rate)


def test_the_body_squashes_at_the_launch_and_again_as_it_drops_back_in():
    # The same compression the fail jump lands on: flattened while it is punching
    # out of the hole and again as it slams back into it, upright at the apex.
    ctrl = _mole()
    pop = ctrl.challenge.pops[0]
    frames = [f for _, f in _bounce_track(ctrl, pop) if f is not None]
    launch = frames[0][2]
    apex = ctrl._render_pop(pop.t_up_ms + _pop_window(pop) * MOLE_VIEW_POP_APEX_FRAC)[2]
    landing = frames[-1][2]
    assert launch == MOLE_VIEW_SQUASH_BUCKETS - 1, "fully compressed leaving the pit"
    assert apex == 0, "and stretched out whole at the top"
    assert landing == MOLE_VIEW_SQUASH_BUCKETS - 1, "compressed again on the way back in"
    rising = [f[2] for u, f in _bounce_track(ctrl, pop)
              if f is not None and u <= MOLE_VIEW_POP_APEX_FRAC]
    assert rising == sorted(rising, reverse=True), "it unfolds as it climbs"


def test_a_hit_ducks_the_mole_from_wherever_the_bounce_had_it():
    # The duck is an interrupt: whatever height the arc was at when the slug
    # landed is where the retreat starts. Snapping to full height first would
    # yank the body UP on a hit.
    ctrl = _mole()
    pop = ctrl.challenge.pops[0]
    at = pop.t_up_ms + _pop_window(pop) * 0.75
    mid_fall = ctrl._render_pop(at)[1]
    assert 0.0 < mid_fall < MOLE_VIEW_POP_HEIGHT_FRAC, "the shot lands on a sinking mole"
    ctrl.update(int(at))
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1
    assert ctrl._last_hit_height == pytest.approx(mid_fall)
    assert ctrl._render_pop(at)[1] == pytest.approx(mid_fall), \
        "the duck picks the body up exactly where the bounce dropped it"
    ctrl.update(int(at + MOLE_VIEW_HITSTOP_HIT_MS / 2))
    assert ctrl._render_pop(at)[1] == pytest.approx(mid_fall), \
        "the hit freeze holds that frame — it never rewinds the body upward"
    heights = [mid_fall]
    for f in (0.4, 0.7):
        ctrl.update(int(at + MOLE_VIEW_HITSTOP_HIT_MS + MOLE_VIEW_RETREAT_MS * f))
        heights.append(ctrl._render_pop(at)[1])
    assert all(b < a for a, b in zip(heights, heights[1:])), \
        "and then drives it straight into the hole: {}".format(heights)
    ctrl.update(int(at + MOLE_VIEW_HITSTOP_HIT_MS + MOLE_VIEW_RETREAT_MS))
    assert ctrl._render_pop(at) is None, "gone one duck later, long before the window ends"


def test_the_duck_outruns_the_bounce_it_interrupted():
    assert MOLE_VIEW_RETREAT_MS < _pop_window(_POPS[0]) * (1.0 - MOLE_VIEW_POP_APEX_FRAC), \
        "a hit mole has to vanish faster than one that simply fell back on its own"


def _jump_bottoms(ctrl, step_ms=4.0):
    surf = pg.Surface((640, 640))
    samples = []
    t = 0.0
    while t <= _JUMP_TOTAL_MS + 40.0:
        rect = ctrl._jump_victim_rect(surf, t, (0, 0))
        if rect is not None:
            samples.append((t, rect.bottom))
        t += step_ms
    return samples


def test_the_fail_climb_out_hands_the_ground_line_over_without_a_step():
    # Three phases share one ground line: the climb walks it from the near lip up
    # to the pit centre, the hop walks it from there down to the rest position and
    # the landing holds it. A mismatch at either joint is a one-frame teleport.
    ctrl = _fail_at_two_hits()
    surf = pg.Surface((640, 640))
    cy = ctrl.center[1]
    rest = ctrl._rest_ground_dy()
    top_of_rise = ctrl._jump_victim_rect(surf, MOLE_VIEW_JUMP_RISE_MS - 1.0, (0, 0))
    hop_start = ctrl._jump_victim_rect(surf, MOLE_VIEW_JUMP_RISE_MS, (0, 0))
    assert top_of_rise.bottom == cy, "the climb finishes standing on the pit centre"
    assert hop_start.bottom == cy, "and the hop picks the line up at exactly that height"
    hop_end = ctrl._jump_victim_rect(surf, _JUMP_MS - 1.0, (0, 0))
    landed = ctrl._jump_victim_rect(surf, _JUMP_MS, (0, 0))
    assert landed.bottom == cy + rest, "touchdown is the board's own rest position"
    assert abs(hop_end.bottom - landed.bottom) <= 2, "and the arc arrives there, not near it"
    settled = ctrl._jump_victim_rect(surf, _JUMP_TOTAL_MS + 20.0, (0, 0))
    assert settled.bottom == landed.bottom, "the squash never moves the feet"
    samples = _jump_bottoms(ctrl)
    jumps = [(t, abs(b - a)) for (_, a), (t, b) in zip(samples, samples[1:])
             if abs(b - a) > _CELL * 0.06]
    assert not jumps, "ground line jumped at {}".format(jumps)


def test_the_intro_sink_runs_the_emergence_model_backwards():
    ctrl = _mole(victim_surface=_solid_victim())
    surf = pg.Surface((640, 640))
    bottoms = []
    for frac in (0.0, 0.25, 0.5, 0.75):
        ctrl.update(int(ctrl._intro_ms * frac))
        rect = ctrl._blit_victim(surf, ctrl.center, 1.0 - frac, (0, 0), lip=True)
        bottoms.append(rect.bottom)
    assert bottoms[0] == ctrl.center[1], "it drops in from the standing position"
    assert bottoms == sorted(bottoms), "and sinks down the same wall a pop climbs"
    assert bottoms[-1] <= ctrl.center[1] + ctrl._pit_ry


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


def test_pops_and_the_climb_out_belong_to_a_pit_but_the_landed_piece_does_not(monkeypatch):
    # The flag says "this body is in a hole, keep the near rim in front of it".
    # A body standing at full height gets the front half repainted over it; an
    # emerging one is cut by the mouth arc instead, which is strictly inside the
    # rim — same intent, and the pixel proof is the rim test below.
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
    # online: the offline whiff cap would commit a fail on the 3rd of these
    # shots and swallow the rest, and only online can a check run long anyway.
    ctrl = _mole(on_shot=MagicMock())
    for i in range(20):
        ctrl.update(800 + i * 200)
        ctrl.handle_event(_click((600, 600)))
    assert ctrl._casings, "the recent brass is still lying around"
    assert len(ctrl._casings) < 20, "the old brass is swept, not hoarded for the whole check"
    assert all(ctrl._casing_alpha(ctrl._now - c.spawn_ms - c.t_land * 1000.0) > 0
               for c in ctrl._casings), \
        "the prune boundary and the fade boundary are the same instant"


_STRIKE_ATTACKER = Square(2, 6)


def _strike_band_count(surf, ctrl, anchor):
    # Exact Colors.loss matches inside the strike row's own band: the struck fill
    # is a supersampled solid, so its interior downsamples to the exact hue, and
    # nothing else on this layer paints loss-red (the danger telegraph never
    # fires in these fixed schedules and the band sits clear of every pit).
    loss = pg.Color(Colors.loss)
    size, gap = ctrl._strike_size, ctrl._strike_gap
    total = MOLE_MAX_WHIFFS * size + (MOLE_MAX_WHIFFS - 1) * gap
    x0 = anchor[0] - total // 2 - 6
    y0 = anchor[1] + int(ctrl.cell_size * MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC) - 6
    count = 0
    for y in range(max(y0, 0), min(y0 + size + 12, surf.get_height())):
        for x in range(max(x0, 0), min(x0 + total + 12, surf.get_width())):
            if surf.get_at((x, y)) == loss:
                count += 1
    return count


def _band_painted(surf, ctrl, anchor, background):
    size, gap = ctrl._strike_size, ctrl._strike_gap
    total = MOLE_MAX_WHIFFS * size + (MOLE_MAX_WHIFFS - 1) * gap
    x0 = anchor[0] - total // 2 - 6
    y0 = anchor[1] + int(ctrl.cell_size * MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC) - 6
    return any(surf.get_at((x, y))[:3] != background
               for y in range(max(y0, 0), min(y0 + size + 12, surf.get_height()))
               for x in range(max(x0, 0), min(x0 + total + 12, surf.get_width())))


def test_strike_crosses_sit_under_the_attacker_and_fill_on_a_whiff():
    ctrl = _mole(from_sq=_STRIKE_ATTACKER)
    anchor = _geom_for(_CELL)(_STRIKE_ATTACKER)
    surf = pg.Surface((640, 640))
    surf.fill((30, 30, 30))
    ctrl.update(800)
    ctrl.draw(surf)
    assert _band_painted(surf, ctrl, anchor, (30, 30, 30)), \
        "the empty slot chrome is on screen from the start, under the attacker's cell"
    assert _strike_band_count(surf, ctrl, anchor) == 0, "but no cross is struck yet"
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == 1
    surf.fill((30, 30, 30))
    ctrl.draw(surf)
    one = _strike_band_count(surf, ctrl, anchor)
    assert one > 0, "the first whiff fills a loss-red strike under the attacker"
    ctrl.update(1000)
    ctrl.handle_event(_click((600, 600)))
    surf.fill((30, 30, 30))
    ctrl.draw(surf)
    assert _strike_band_count(surf, ctrl, anchor) > one, "the second whiff fills a second cross"


def test_strike_crosses_are_absent_without_an_attacker_square():
    ctrl = _mole()
    surf = pg.Surface((640, 640))
    surf.fill((30, 30, 30))
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    ctrl.draw(surf)
    anchor = _geom_for(_CELL)(_STRIKE_ATTACKER)
    assert not _band_painted(surf, ctrl, anchor, (30, 30, 30)), \
        "no from_sq means no anchor: the row is skipped whole, never misplaced"


def test_two_whiffs_leave_the_check_alive_locally():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    ctrl.update(1000)
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == MOLE_MAX_WHIFFS - 1
    assert ctrl.landed is None, "two whiffs are survivable — the cap is >= 3"
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._progress == 1, "and hits still land afterwards, untouched by the whiffs"


def test_the_third_whiff_fails_the_check_on_the_spot():
    ctrl = _mole(from_sq=_STRIKE_ATTACKER)
    for i in range(MOLE_MAX_WHIFFS):
        ctrl.update(800 + 200 * i)
        ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == MOLE_MAX_WHIFFS
    assert ctrl.landed is False, \
        "terminal the instant the 3rd whiff lands — the deadline (7s) and quota are untouched"
    assert ctrl._audio.play_whiff_ricochet.call_count == MOLE_MAX_WHIFFS
    ctrl.update(1200 + MOLE_VIEW_FAIL_HOLD_MS - 1)
    assert ctrl.done is False, "the shared fail outro (jump-out, heal, pit close) still runs"
    ctrl.update(1200 + MOLE_VIEW_FAIL_HOLD_MS)
    assert ctrl.done is True


def test_lockout_swallowed_shots_never_count_toward_the_whiff_cap():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == 1
    ctrl.update(900)
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == 1, \
        "a recoil-locked shot is dropped whole — the client mirror of the server's silent gate"


def test_online_third_whiff_relays_but_never_self_commits():
    on_shot = MagicMock()
    ctrl = _mole(on_shot=on_shot)
    for i in range(MOLE_MAX_WHIFFS):
        ctrl.update(800 + 200 * i)
        ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == MOLE_MAX_WHIFFS, "the mover's own pips fill optimistically"
    assert on_shot.call_count == MOLE_MAX_WHIFFS, "every registered whiff reaches the wire"
    assert ctrl.landed is None and ctrl.done is False, "the verdict online is the server's alone"
    ctrl.resolve(False)
    assert ctrl.landed is False


def test_spectate_whiffs_drive_the_mirror_pips_from_the_relayed_miss_count():
    ctrl = _mole(passive=True)
    ctrl.update(700)
    ctrl.spectate_shot(600.0, 0, False, progress=0, target=(7.5, 7.5))
    assert ctrl._miss_count == 1, \
        "the server relays the pre-increment count; the mirror shows one struck cross"
    ctrl.spectate_shot(650.0, 0, False, progress=0, target=(7.5, 7.5))
    assert ctrl._miss_count == 1, "a stale replay adds nothing"
    ctrl.spectate_shot(700.0, 1, False, progress=0, target=(7.5, 7.5))
    assert ctrl._miss_count == 2, "a genuinely new whiff lands on the mirror"
    ctrl.spectate_shot(750.0, MOLE_MAX_WHIFFS - 1, False, progress=0, target=(7.5, 7.5))
    assert ctrl._miss_count == MOLE_MAX_WHIFFS, "a snapshot jump adopts the count wholesale"
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    assert ctrl._miss_count == MOLE_MAX_WHIFFS, "a relayed hit never moves the whiff pips"
    assert ctrl._progress == 1


def test_strike_crosses_fade_with_the_pip_outro_and_restore_the_shared_alpha():
    ctrl = _mole(from_sq=_STRIKE_ATTACKER, challenge=_one_pop_challenge())
    anchor = _geom_for(_CELL)(_STRIKE_ATTACKER)
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    ctrl.update(2000)
    assert ctrl.landed is False
    held = _draw_at(ctrl, 2000 + MOLE_VIEW_PIP_FADE_DELAY_MS - 50)
    assert _strike_band_count(held, ctrl, anchor) > 0, "the crosses hold through the pip delay"
    mid_fade = _draw_at(ctrl, 2000 + MOLE_VIEW_PIP_FADE_DELAY_MS + MOLE_VIEW_PIP_FADE_MS / 2)
    assert _strike_band_count(mid_fade, ctrl, anchor) == 0, \
        "mid-fade the blend is no longer the pure hue — the row is genuinely dimming"
    struck = _strike_cross_surface(ctrl._strike_size, True)
    assert struck.get_alpha() == 255, \
        "the faded blit restores the cached surface to 255, never a lingering dim or None"
    gone = _draw_at(ctrl, 2000 + MOLE_VIEW_PIP_FADE_DELAY_MS + MOLE_VIEW_PIP_FADE_MS + 20)
    assert not _band_painted(gone, ctrl, anchor, (200, 200, 200)), \
        "then the row disappears on the same outro as the hit pips"


def test_strike_cross_surfaces_are_cached_per_size_and_state():
    ctrl = _mole(from_sq=_STRIKE_ATTACKER)
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    surf = pg.Surface((640, 640))
    ctrl.draw(surf)
    size = ctrl._strike_size
    assert ("strike", size, True) in _MOLE_STATIC_CACHE
    assert ("strike", size, False) in _MOLE_STATIC_CACHE, \
        "one draw pass materialises both slot states into the module cache"
    assert _strike_cross_surface(size, True) is _strike_cross_surface(size, True), \
        "every later frame reuses the cached sprite"
    assert pg.image.tostring(_strike_cross_surface(size, True), "RGBA") != \
        pg.image.tostring(_strike_cross_surface(size, False), "RGBA")


def test_flipped_board_keeps_the_strike_crosses_under_the_attacker():
    def flipped_geom(sq):
        return (sq.col * _CELL + _CELL // 2, (7 - sq.row) * _CELL + _CELL // 2)

    ctrl = _mole(geom=flipped_geom, from_sq=_STRIKE_ATTACKER)
    assert ctrl._affine is not None and ctrl._affine[3] < 0, "the mapping really is flipped"
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._miss_count == 1
    surf = pg.Surface((640, 640))
    surf.fill((30, 30, 30))
    ctrl.draw(surf)
    flipped_anchor = flipped_geom(_STRIKE_ATTACKER)
    plain_anchor = _geom_for(_CELL)(_STRIKE_ATTACKER)
    assert _strike_band_count(surf, ctrl, flipped_anchor) > 0, \
        "the row follows the attacker through the flip, still directly under the piece"
    assert not _band_painted(surf, ctrl, plain_anchor, (30, 30, 30)), \
        "and nothing is left stranded at the unflipped position"


def test_no_per_frame_logging(caplog):
    surf = pg.Surface((640, 640))
    ctrl = _mole()
    with caplog.at_level(logging.DEBUG):
        for i in range(100):
            ctrl.update(i * 16)
            ctrl.draw(surf)
    assert not caplog.records, "the mole view stays silent on the frame path"


def test_a_damaged_fail_cues_the_heal_scanner_once():
    # The heal scanner bed answers the teleporter seam, so it fires exactly when
    # the seam does: on a fail verdict over a damaged victim, once, at the jump
    # start -- the same gate _spawn_seam_sparks uses (damage_tier > 0).
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._damage_tier() > 0
    ctrl.resolve(False)
    ctrl._audio.play_mole_heal.assert_called_once()


def test_an_undamaged_fail_never_cues_the_heal_scanner():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.resolve(False)
    ctrl._audio.play_mole_heal.assert_not_called()


def test_a_win_never_cues_the_heal_scanner():
    ctrl = _mole()
    for i, ms in enumerate((800, 2000, 3200)):
        ctrl.update(ms)
        ctrl.handle_event(_click(_hole_px(i)))
    assert ctrl.landed is True
    ctrl._audio.play_mole_heal.assert_not_called()


def test_the_spectate_mirror_heals_silently():
    ctrl = _mole(passive=True)
    ctrl.update(800)
    ctrl.spectate_shot(800.0, 0, False, progress=1, target=(2.5, 2.5))
    assert ctrl._damage_tier() > 0
    ctrl.resolve(False)
    ctrl._audio.play_mole_heal.assert_not_called()
