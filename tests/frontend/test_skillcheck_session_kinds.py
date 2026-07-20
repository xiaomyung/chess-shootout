"""Session integration for the two new skill-check kinds. A local WHACK gate hands
the controller the SAME hole squares the pure engine derives from the frozen board
(seed + captured value + capture square + occupied set), a COMBO gate threads the
capturer's cell-scaled sprite and the captured value into the challenge, and the
px->board inverse the session builds off Board.cell_rect round-trips square centers
on both orientations. Victim-square suppression now covers {AIM, WHACK, COMBO}
while sync_aim_check_gun stays an AIM-only coupling, and every path that discards a
live controller (teardown, screen exit, new-game reset, overlay replacement) calls
close() so the whack check's hidden OS cursor can never leak. The input swallow
path is pinned: arrows reach the combo pad, never move-stepping.
"""

from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.combo_view import ComboController, COMBO_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.mole_view import MoleController
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


def test_px_to_board_round_trips_square_centers_on_both_orientations():
    app = _local_app()
    session = app.game.skillcheck_session
    for flipped in (False, True):
        app.game.board.flipped = flipped
        for row, col in ((0, 0), (3, 3), (7, 7), (2, 5)):
            center = app.game.board.cell_rect(Square(row, col)).center
            assert session._px_to_board(center) == (row + 0.5, col + 0.5), \
                "flipped={} square ({},{})".format(flipped, row, col)
    app.game.board.flipped = False


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


def test_failed_whack_restores_the_suppressed_victim_and_clears_state():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, False)
    assert app.game.board.aim_suppressed_square is None
    assert app.game.skillcheck_session.active_kind is None
    assert any(a["sq"] == to for a in app.game.board._restore_anims), \
        "the surviving victim drops back onto its square, same as a failed aim"
    assert app.game.skillcheck.is_locked(frm, to) is True


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
    assert app.game.swallows_input() is True
    app.game.board.step_review = MagicMock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_LEFT, "unicode": "", "mod": 0}))
    app.input_router.check_events()
    app.game.board.step_review.assert_not_called()
    assert ctrl.progress + ctrl.wrong_count == 1, "the press registered on the combo pad"
    pg.event.clear()
    app.game.skillcheck_session.teardown_skillcheck_overlay()
