"""Session integration for the two new skill-check kinds. A local WHACK gate hands
the controller the SAME hole squares the pure engine derives from the frozen board
(seed + captured value + capture square + occupied set), a COMBO gate threads the
capturer's cell-scaled sprite and the captured value into the challenge, and the
controller's own geom-derived affine — the single owner of the px->board inverse —
round-trips square centers on both orientations. Victim-square suppression now covers
{AIM, WHACK, COMBO}
while sync_aim_check_gun stays an AIM-only coupling, and every path that discards a
live controller (teardown, screen exit, new-game reset, overlay replacement) calls
close() so the whack check's hidden OS cursor can never leak. The input swallow
path is pinned: arrows reach the combo pad, never move-stepping.

A failed WHACK hands the taunt to the BOARD layer: the session stores the check
seed at overlay-open, and on a fail calls screen.show_taunt(victim_sq,
mole.pick_taunt(seed)) — deterministic per seed, so mover and spectator show the
same line — plus the taunt sound for the mover only (the spectate mirror stays muted).
The seed clears on every terminal path so a stale seed can never leak into the
next check's taunt. The failed WHACK is also the one restore that skips the board
drop (restore_piece(drop=False)): its overlay already set the victim down on its
own square, so the piece must simply be there the frame the overlay ends.

While a WHACK runs, the CAPTURER on the board keeps its gun out and tracks the live
crosshair (the mirror tracks the last relayed impact instead, falling back to the
victim square before the first relay), and every REGISTERED hit fires that piece's
own capture projectile at the impact point — whiffs, lockout shots and locked moves
throw nothing. sync_whack_gun is the single owner of that state: one call per frame
arms it while the overlay is a live whack and releases it (tumbling drop) the moment
it is not, which is what covers every teardown path at once. The terminal paths
release explicitly too, because a screen that stops drawing stops syncing — the gun
must never survive into the next game.

A WON whack is the one ending that does NOT tumble: the piece hands the same gun to
the capture choreography (hand_off_gun_px -> predrawn capture, AIM_MS only), so the
killing shot flows straight into the capture with no drop and no second
draw-flourish. That handoff also arms the capture ADVANCE-ONLY — the whack already
blasted the victim off the pit, so the capture keeps the aimed gun and the slide but
fires nothing at the empty square. Every other ending — fail, teardown, Esc, resign,
new game — keeps the approved tumble and its own drawn-and-fired shot, and a capture
with no check behind it is untouched.
"""

import math
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.frontend.focus_helpers import FakeTicks, install_clock
from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.combo_view import ComboController, COMBO_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.mole_view import MoleController
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.frontend.visual.effects import AIM_MS, DRAW_MS, PROJECTILE_TRAVEL_MS
from chessshootout.frontend.visual.gunfx import GUNS, PIECE_GUN
from chessshootout.skillcheck import mole
from chessshootout.skillcheck.combo import ComboChallenge
from chessshootout.skillcheck.coordinator import move_roll_key
from chessshootout.skillcheck.mole import MoleChallenge
from chessshootout.skillcheck.rng import ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind
from tests.helpers import BLACK, K, P, Q, R, WHITE, make_app, make_backend, piece, sq, \
    start_single_screen


_pygame_init = pygame_display(1100, 800)


def _local_app():
    app = make_app(1100, 800)
    start_single_screen(app)
    return app


def _capture_board(app, victim=P):
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(victim, BLACK),
    }, turn=WHITE)
    return sq(4, 3), sq(3, 3)


def _kind_seed(backend, frm, to, want):
    for i in range(8000):
        seed = "kseed-{}".format(i)
        roll = ply_roll(seed, move_roll_key(0, frm, to))
        if select_skillcheck(backend, frm, to, roll) == want:
            return seed
    raise AssertionError("no seed found for {}".format(want))


def _gate(app, want, victim=P):
    frm, to = _capture_board(app, victim=victim)
    seed = _kind_seed(app.game.match.backend, frm, to, want)
    app.game.skillcheck.reset(enabled=True, seed=seed)
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    composed = "{}:{}:{}{}{}{}:{}".format(
        seed, 0, frm.row, frm.col, to.row, to.col, want.value)
    return frm, to, composed


def _occupied(app):
    state = app.game.match.state
    return [(row, col) for row in range(8) for col in range(8)
            if state[row][col] is not None]


def test_local_whack_gate_hands_the_controller_the_engine_hole_squares():
    app = _local_app()
    frm, to, composed = _gate(app, SkillCheckKind.WHACK)
    ctrl = app.game.skillcheck_overlay._controller
    assert isinstance(ctrl, MoleController)
    holes = mole.hole_squares(composed, 1, (to.row, to.col), _occupied(app), 8)
    assert ctrl._hole_squares == holes, \
        "the session derives exactly the engine's holes from the frozen board"
    assert (to.row, to.col) not in ctrl._hole_squares, "holes never spawn on occupied squares"


def test_local_whack_gate_threads_the_captured_value_into_the_challenge():
    app = _local_app()
    frm, to, composed = _gate(app, SkillCheckKind.WHACK, victim=R)
    ctrl = app.game.skillcheck_overlay._controller
    deadline = app.game.skillcheck_session._skillcheck_deadline_ms()
    assert ctrl.challenge == MoleChallenge.from_seed(composed, 4, deadline, 5), \
        "the rook's value (5) reaches the challenge, not a defaulted 0"
    assert ctrl.challenge.hole_count == 5, "a rook kill digs five pits"
    assert len(ctrl._hole_squares) == 5


def test_shot_inverse_round_trips_square_centers_on_both_orientations():
    # The controller's affine (derived from the geom the session hands it) is the
    # only px->board inverse left — it must agree with Board.cell_rect either way up.
    app = _local_app()
    board = app.game.board
    for flipped in (False, True):
        board.flipped = flipped
        ctrl = build_controller(
            SkillCheckKind.WHACK, seed="inv-seed", cell_rect=board.cell_rect(Square(3, 3)),
            now_ms=0, deadline_ms=5000, captured_value=1, hole_squares=((2, 2),),
            geom=lambda sq: board.cell_rect(sq).center)
        for row, col in ((0, 0), (3, 3), (7, 7), (2, 5)):
            center = board.cell_rect(Square(row, col)).center
            assert ctrl._shot_target(center) == (row + 0.5, col + 0.5), \
                "flipped={} square ({},{})".format(flipped, row, col)
        ctrl.close()
    board.flipped = False


def test_local_combo_gate_passes_attacker_surface_and_captured_value():
    app = _local_app()
    frm, to, composed = _gate(app, SkillCheckKind.COMBO, victim=R)
    ctrl = app.game.skillcheck_overlay._controller
    assert isinstance(ctrl, ComboController)
    queen_sprite = app.game.board.piece_images_scaled[(PieceType.QUEEN, PieceColor.WHITE)]
    assert ctrl._attacker_src is queen_sprite, "the capturer's cell-scaled sprite dances"
    deadline = min(app.game.skillcheck_session._skillcheck_deadline_ms(), COMBO_TIME_LIMIT_MS)
    assert ctrl.challenge == ComboChallenge.from_seed(composed, 4, deadline, 5)
    assert ctrl.challenge.prompt_count == 6, "the rook's value stretches the combo"


def test_whack_and_combo_suppress_the_victim_square():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    assert app.game.skillcheck_session.skillcheck_target == to
    assert app.game.board.aim_suppressed_square == to, "the overlay owns drawing the victim"
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    assert app.game.board.aim_suppressed_square is None

    frm, to, _ = _gate(app, SkillCheckKind.COMBO)
    assert app.game.board.aim_suppressed_square == to
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    assert app.game.board.aim_suppressed_square is None


def test_wheel_still_never_suppresses_a_square():
    app = _local_app()
    _gate(app, SkillCheckKind.WHEEL)
    assert app.game.board.aim_suppressed_square is None
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def test_sync_aim_check_gun_is_inert_for_whack_and_combo():
    app = _local_app()
    for want in (SkillCheckKind.WHACK, SkillCheckKind.COMBO):
        _gate(app, want)
        assert app.game.board.aim_suppressed_square is not None
        app.game.skillcheck_session.sync_aim_check_gun()
        fx = app.game.board.effects
        assert fx.aim_victim is None, \
            "{}: the aim held-gun must not draw over the overlay's victim".format(want.value)
        assert fx.aim_victim_scale == 1.0
        app.game.skillcheck_session.teardown_skillcheck_overlay()


def test_sync_aim_check_gun_still_arms_for_aim():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.AIM)
    app.game.skillcheck_session.sync_aim_check_gun()
    assert app.game.board.effects.aim_victim == to, "the AIM coupling is untouched"
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    app.game.skillcheck_session.sync_aim_check_gun()
    assert app.game.board.effects.aim_victim is None


def test_failed_whack_restores_the_suppressed_victim_instantly_and_clears_state():
    # The whack overlay already landed the victim on its own square with the
    # jump-out; dropping it a second time from above read as the piece appearing
    # out of thin air and repairing itself mid-air.
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, False)
    assert app.game.board.aim_suppressed_square is None, "the square stops being suppressed"
    assert app.game.skillcheck_session.active_kind is None
    assert app.game.board._restore_anims == [], \
        "no drop animation is queued — the piece simply is on its square"
    assert app.game.match.piece_at(to) is not None
    assert app.game.skillcheck.is_locked(frm, to) is True


@pytest.mark.parametrize("kind", [SkillCheckKind.AIM, SkillCheckKind.COMBO])
def test_other_failed_kinds_still_drop_the_victim_back_in(kind):
    # Driven through the done handler directly: the drop policy is a property of
    # the kind, not of which roll opened the check.
    app = _local_app()
    frm, to = _capture_board(app)
    app.game.board.aim_suppressed_square = to
    app.game.skillcheck_session._on_skillcheck_done((frm, to, None, kind), False)
    assert any(a["sq"] == to for a in app.game.board._restore_anims), \
        "only the whack skips the drop; the approved aim/combo restore is untouched"


def test_failed_whack_taunts_from_the_victim_square_on_the_board_layer():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    seed = app.game.skillcheck_session.active_seed
    assert seed is not None, "the session stores the check seed at overlay-open"
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, False)
    assert app.game._taunt_square == to, "the taunt bubble anchors to the surviving victim"
    assert app.game.taunt_bubble.shown_at is not None
    assert app.game.taunt_bubble.text == mole.pick_taunt(seed).upper(), \
        "the line comes from the per-check seed, not the controller"
    app.sound_manager.play_mole_taunt.assert_called_once()
    assert app.game.skillcheck_session.active_seed is None, "the seed clears at resolution"


def test_won_whack_never_taunts():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, True)
    assert app.game.taunt_bubble.shown_at is None
    app.sound_manager.play_mole_taunt.assert_not_called()
    assert app.game.skillcheck_session.active_seed is None


def test_online_whack_fail_shows_the_board_taunt_with_sound():
    app = _local_app()
    session = app.game.skillcheck_session
    session.skillcheck_target = sq(3, 3)
    session.active_seed = "wire-seed"
    session._on_online_skillcheck_done(
        (sq(4, 3), sq(3, 3), None, SkillCheckKind.WHACK), False)
    assert app.game._taunt_square == sq(3, 3)
    assert app.game.taunt_bubble.text == mole.pick_taunt("wire-seed").upper(), \
        "both clients derive the same line from the same wire seed"
    app.sound_manager.play_mole_taunt.assert_called_once()
    assert session.active_seed is None


def test_spectated_online_whack_fail_taunts_silently():
    # _begin_online_verdict nulls online_spectate_kind BEFORE the done handler runs,
    # so spectator-ness must survive on the online_was_spectator latch instead.
    app = _local_app()
    session = app.game.skillcheck_session
    session.skillcheck_target = sq(3, 3)
    session.active_seed = "wire-seed"
    session.online_was_spectator = True
    session.online_spectate_kind = None
    session._on_online_skillcheck_done(
        (sq(4, 3), sq(3, 3), None, SkillCheckKind.WHACK), False)
    assert app.game.taunt_bubble.shown_at is not None, \
        "the mirror still shows the victim's line"
    app.sound_manager.play_mole_taunt.assert_not_called()
    assert session.online_was_spectator is False


def test_spectate_open_arms_the_spectator_latch():
    app = _local_app()
    session = app.game.skillcheck_session
    session.open_spectate_overlay(
        SkillCheckKind.WHACK, "spec-seed", 0, 5000, sq(4, 3), sq(3, 3), None, 1)
    assert session.online_was_spectator is True
    session.teardown_skillcheck_overlay()


def _mock_controller():
    ctrl = MagicMock()
    ctrl._passive = False
    return ctrl


def test_teardown_closes_the_live_controller():
    app = _local_app()
    ctrl = _mock_controller()
    app.game.skillcheck_overlay.start(ctrl, (sq(4, 3), sq(3, 3)), lambda c, landed: None)
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    ctrl.close.assert_called_once()


def test_screen_exit_closes_the_live_controller():
    app = _local_app()
    ctrl = _mock_controller()
    app.game.skillcheck_overlay.start(ctrl, (sq(4, 3), sq(3, 3)), lambda c, landed: None)
    app.game.exit()
    ctrl.close.assert_called_once()
    assert not app.game.skillcheck_overlay.is_active()


def test_reset_to_new_game_closes_the_live_controller():
    app = _local_app()
    ctrl = _mock_controller()
    app.game.skillcheck_overlay.start(ctrl, (sq(4, 3), sq(3, 3)), lambda c, landed: None)
    app.game._reset_to_new_game()
    ctrl.close.assert_called_once()


def test_overlay_replacement_closes_the_displaced_controller():
    app = _local_app()
    stale = _mock_controller()
    stale._passive = True
    app.game.skillcheck_overlay.start(stale, (sq(1, 1), sq(2, 2)), lambda c, landed: None)
    _gate(app, SkillCheckKind.WHACK)
    stale.close.assert_called_once()
    assert app.game.skillcheck_overlay._controller is not stale
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def test_normal_overlay_finish_also_closes_the_controller():
    app = _local_app()
    done = []
    ctrl = _mock_controller()
    ctrl.done = True
    ctrl.landed = True
    app.game.skillcheck_overlay.start(ctrl, ("ctx",), lambda c, landed: done.append(landed))
    app.game.skillcheck_overlay.update(0)
    ctrl.close.assert_called_once()
    assert done == [True]


def test_arrow_keys_reach_the_combo_pad_not_move_stepping():
    app = _local_app()
    _gate(app, SkillCheckKind.COMBO)
    ctrl = app.game.skillcheck_overlay._controller
    ctrl.update(ctrl.start_ms + 200)
    assert app.game.swallows_input() is True
    app.game.board.step_review = MagicMock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_LEFT, "unicode": "", "mod": 0}))
    app.input_router.check_events()
    app.game.board.step_review.assert_not_called()
    assert ctrl._progress + ctrl._wrong_count == 1, "the press registered on the combo pad"
    pg.event.clear()
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def _whack_app(monkeypatch):
    app = _local_app()
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    return app, clock, frm, to


def _aim_angle(app, frm, target_px):
    px, py = app.game.board.effects._pivot(frm, app.game.board.cell_size)
    return math.atan2(target_px[1] - py, target_px[0] - px)


def _spin(session, clock, frames=200, step=16):
    for _ in range(frames):
        clock.advance(step)
        session.sync_whack_gun()


def _fire_at(ctrl, px, at_ms):
    ctrl.update(at_ms)
    ctrl.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": px}))


def _live_pop_shot(ctrl):
    pop = ctrl.challenge.pops[0]
    return ctrl._hole_px[pop.hole], ctrl.start_ms + int(pop.t_up_ms) + 10


def test_sync_whack_gun_arms_the_capturers_gun_and_eases_after_the_crosshair(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    right = board.cell_rect(sq(4, 7)).center
    up = board.cell_rect(sq(0, 3)).center
    cursor = {"px": right}
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: cursor["px"])
    session.sync_whack_gun()
    assert fx.has_gun_px() is True, "a live whack puts the gun in the attacker's hand"
    assert fx._whack_gun["from_sq"] == frm, "the CAPTURER aims, not the victim"
    assert fx._whack_gun["aim"] == pytest.approx(_aim_angle(app, frm, right)), \
        "it starts pointing at the crosshair instead of swinging in from nowhere"
    cursor["px"] = up
    clock.advance(16)
    session.sync_whack_gun()
    want = _aim_angle(app, frm, up)
    swung = fx._whack_gun["aim"]
    assert want < swung < _aim_angle(app, frm, right), \
        "one frame after the crosshair moves the barrel is on its way, not there"
    _spin(session, clock)
    assert fx._whack_gun["aim"] == pytest.approx(want, abs=0.02), "and it catches up"
    session.teardown_skillcheck_overlay()


def test_teardown_tumbles_the_gun_and_the_next_whack_rearms_clean(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    session.teardown_skillcheck_overlay()
    assert fx.has_gun_px() is False, "the gun leaves with the overlay"
    assert len(fx.drops) == 1, "and tumbles away instead of blinking out"
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "no later frame can resurrect a torn-down check"
    frm2, _, _ = _gate(app, SkillCheckKind.WHACK)
    session.sync_whack_gun()
    assert fx.has_gun_px() is True and fx._whack_gun["from_sq"] == frm2, \
        "the second check arms its own capturer"
    session.teardown_skillcheck_overlay()


def test_a_new_game_never_inherits_a_held_whack_gun(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    app.game._reset_to_new_game()
    assert fx.has_gun_px() is False
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "the stale-overlay invariant holds on the next frame too"


def test_leaving_the_screen_releases_the_held_whack_gun(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    app.game.exit()
    assert fx.has_gun_px() is False, \
        "a screen that stops drawing stops syncing — exit must release it itself"


def test_a_registered_hit_fires_the_capturers_own_projectile(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    ctrl = app.game.skillcheck_overlay._controller
    px, at_ms = _live_pop_shot(ctrl)
    _fire_at(ctrl, px, at_ms)
    assert ctrl._progress == 1, "the shot registered"
    spec = GUNS[PIECE_GUN["queen"]]
    assert len(fx.projectiles) == spec.pellets, "the queen's blunderbuss empties its spread"
    assert {pr["color"] for pr in fx.projectiles} == {spec.color}
    assert all(pr["capture"] is None for pr in fx.projectiles), "the volley is cosmetic"
    assert fx._whack_gun["fired_at"] is not None, "and the gun kicks"
    session.teardown_skillcheck_overlay()


def test_whiffs_and_lockout_shots_throw_nothing(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    ctrl = app.game.skillcheck_overlay._controller
    _fire_at(ctrl, app.game.board.cell_rect(frm).center, ctrl.start_ms + 300)
    assert ctrl._progress == 0
    assert fx.projectiles == [], "a whiff never leaves the barrel"
    px, at_ms = _live_pop_shot(ctrl)
    _fire_at(ctrl, px, at_ms)
    fired = len(fx.projectiles)
    assert fired > 0
    _fire_at(ctrl, px, at_ms + 1)
    assert len(fx.projectiles) == fired, "a shot eaten by the recoil lockout fires nothing"
    session.teardown_skillcheck_overlay()


def test_a_locked_move_reopens_no_check_and_holds_no_gun(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    session._on_skillcheck_done(context, False)
    assert app.game.skillcheck.is_locked(frm, to) is True
    session.sync_whack_gun()
    assert fx.has_gun_px() is False
    assert session.skillcheck_gate(frm, to) is True, "the locked move is swallowed"
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "a locked retry arms nothing"


def test_the_mirror_aims_at_the_victim_then_at_the_relayed_impact(monkeypatch):
    app = _local_app()
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    frm, to = _capture_board(app)
    session.open_spectate_overlay(
        SkillCheckKind.WHACK, "spec-seed", 0, 5000, frm, to, None, 1)
    session.sync_whack_gun()
    assert fx.has_gun_px() is True, "the spectator sees the opponent draw too"
    victim_px = board.cell_rect(to).center
    assert fx._whack_gun["aim"] == pytest.approx(_aim_angle(app, frm, victim_px)), \
        "before the first relay the barrel rests on the victim"
    ctrl = app.game.skillcheck_overlay._controller
    ctrl.update(ctrl.start_ms + 900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(0.5, 0.5))
    impact = board.cell_rect(sq(0, 0)).center
    assert fx.projectiles, "the relayed hit fires the mirror's gun"
    assert {pr["color"] for pr in fx.projectiles} == {GUNS[PIECE_GUN["queen"]].color}
    _spin(session, clock)
    assert fx._whack_gun["aim"] == pytest.approx(_aim_angle(app, frm, impact), abs=0.02), \
        "and the barrel follows the opponent's shots from there on"
    session.teardown_skillcheck_overlay()


@pytest.mark.parametrize("kind", [SkillCheckKind.WHEEL, SkillCheckKind.AIM,
                                  SkillCheckKind.COMBO])
def test_no_other_kind_ever_arms_the_px_gun(kind, monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    _gate(app, kind)
    app.game.skillcheck_session.sync_whack_gun()
    assert app.game.board.effects.has_gun_px() is False, \
        "{}: only the whack check hands the piece a tracking gun".format(kind.value)
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def _finish_check(app, landed):
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, landed)


def test_a_won_whack_hands_the_same_gun_to_the_capture(monkeypatch):
    # The check gun and the capture gun are the same weapon in the same hand: no
    # tumble-drop, no second draw-flourish, only the aim beat before it advances.
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    _finish_check(app, True)
    assert fx.has_gun_px() is False and fx.drops == [], \
        "a won check never throws the gun away mid-shootout"
    entry = fx.captures[0]
    assert entry["predrawn"] is True
    assert entry["fire_at"] == entry["start"] + AIM_MS, "no DRAW_MS — it is already drawn"
    assert entry["advance_only"] is True, \
        "the whack already killed the victim — the capture must not shoot the empty square"
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "and the whack state stays gone afterwards"


def test_a_won_whacks_capture_advances_without_firing_a_shot(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    session.sync_whack_gun()
    _finish_check(app, True)
    entry = fx.captures[0]
    clock.advance(AIM_MS)
    fx.update(entry["fire_at"])
    assert fx.projectiles == [], "no volley leaves the barrel"
    assert [p["kind"] for p in fx.particles if p["kind"] in ("flash", "impact", "blood",
                                                             "ragdoll")] == [], \
        "and nothing is shot, wounded or thrown around"
    assert fx.holes == []
    clock.advance(PROJECTILE_TRAVEL_MS)
    fx.update(entry["fire_at"] + PROJECTILE_TRAVEL_MS)
    assert fx.captures == [], "the capture retires on its slide"
    assert board.is_animating() is True, "the attacker still slides onto the square"


def test_a_failed_whack_still_tumbles_and_the_miss_gun_still_flourishes(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    _finish_check(app, False)
    assert fx.has_gun_px() is False
    assert len(fx.drops) == 1, "the fail keeps the approved tumble"
    entry = fx.captures[0]
    assert not entry.get("predrawn"), "the SKILL ISSUE shot draws its own gun"
    assert not entry.get("advance_only"), "and it really does fire at the survivor"
    assert entry["fire_at"] == entry["start"] + DRAW_MS + AIM_MS


def test_a_plain_capture_is_untouched_by_the_handoff(monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    frm, to = _capture_board(app)
    app.game.board.apply_gated_move(frm, to)
    entry = app.game.board.effects.captures[0]
    assert entry["predrawn"] is False
    assert entry["advance_only"] is False, "it has a victim to shoot and it shoots it"
    assert entry["fire_at"] == entry["start"] + DRAW_MS + AIM_MS, \
        "a capture with no check behind it still draws, aims, then fires"
