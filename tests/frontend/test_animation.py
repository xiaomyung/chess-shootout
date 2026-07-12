"""Piece-slide animation curve + board/frontend animation wiring.

`PieceAnimation.progress` is a clamped linear ramp: 0 before/at start, linear to
1 across `duration_ms`, then pinned at 1. The board defers promotion pickers and
auto-flip until the slide lands; undo replays the move in reverse.
"""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import Square
from chessshootout.frontend.visual.animation import PieceAnimation
from chessshootout.backend.pieces import Piece, PieceColor, PieceType

DEFAULT_CONFIG = {
    "mode": "single_screen",
    "nickname": "Tester",
    "time_minutes": None,
    "increment_seconds": 5,
    "side": "white",
}


_pygame_init = pygame_display(800, 600)


@pytest.fixture
def board():
    from chessshootout.frontend.board import Board
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def _start_game():
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    return app


def _seed_white_castle(backend):
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.ROOK, PieceColor.WHITE)
    backend.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    from collections import Counter
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1


@pytest.mark.parametrize(
    "now_ms, expected, done",
    [
        pytest.param(900, 0.0, False, id="before_start_clamps_to_zero"),
        pytest.param(1000, 0.0, False, id="at_start_is_zero"),
        pytest.param(1050, 0.25, False, id="quarter_through"),
        pytest.param(1100, 0.5, False, id="midway"),
        pytest.param(1150, 0.75, False, id="three_quarter_through"),
        pytest.param(1200, 1.0, True, id="at_end_is_one_and_done"),
        pytest.param(2000, 1.0, True, id="past_end_clamps_to_one_and_done"),
    ],
)
def test_progress_curve(now_ms, expected, done):
    """Clamped linear ramp over [start, start+duration]; is_done iff progress hits 1."""
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=1000, duration_ms=200,
    )
    assert a.progress(now_ms) == pytest.approx(expected)
    assert a.is_done(now_ms) is done


def test_zero_duration_is_immediately_done():
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=1000, duration_ms=0,
    )
    assert a.progress(1000) == 1.0
    assert a.is_done(1000) is True


def test_start_animation_appends_and_sets_animating(board):
    assert not board.is_animating()
    board.start_animation(
        Square(6, 4), Square(4, 4),
        Piece(PieceType.PAWN, PieceColor.WHITE),
    )
    assert board.is_animating()
    assert len(board.animations) == 1


def test_cancel_animations_clears_list(board):
    for _ in range(3):
        board.start_animation(
            Square(6, 4), Square(4, 4),
            Piece(PieceType.PAWN, PieceColor.WHITE),
        )
    assert board.is_animating()
    board.cancel_animations()
    assert not board.is_animating()


def test_normal_move_triggers_one_animation(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.animations) == 1
    a = board.animations[0]
    assert a.from_sq == Square(6, 4)
    assert a.to_sq == Square(4, 4)
    assert a.piece.type == PieceType.PAWN


def test_castle_triggers_two_animations(board):
    _seed_white_castle(board.backend)
    board.handle_click(Square(7, 4))
    board.handle_click(Square(7, 6))
    assert len(board.animations) == 2
    kinds = sorted(a.piece.type.name for a in board.animations)
    assert kinds == ["KING", "ROOK"]


def test_handle_click_ignored_during_animation(board):
    board.start_animation(
        Square(6, 4), Square(4, 4),
        Piece(PieceType.PAWN, PieceColor.WHITE),
    )
    history_before = len(board.backend.move_history)
    board.handle_click(Square(6, 0))
    assert len(board.backend.move_history) == history_before
    assert board.selected_square is None


def test_animation_to_sq_skipped_in_draw_pieces(board):
    board.start_animation(
        Square(6, 4), Square(4, 4),
        Piece(PieceType.PAWN, PieceColor.WHITE),
    )
    hidden = {a.to_sq for a in board.animations}
    assert Square(4, 4) in hidden


def test_on_complete_fires_when_done(board):
    fired = []
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=pg.time.get_ticks() - 1000,
        duration_ms=200,
        on_complete=lambda: fired.append(True),
    )
    board.animations.append(a)
    board._draw_animations()
    assert fired == [True]
    assert not board.is_animating()


def test_promotion_picker_deferred_until_animation_completes(board):
    backend = board.backend
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    from collections import Counter
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1

    board.handle_click(Square(1, 0))
    board.handle_click(Square(0, 0))
    assert board.pending_promotion_square is None
    assert board.is_animating()

    board.animations[0].start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()
    assert board.pending_promotion_square == Square(0, 0)


def test_undo_starts_reverse_animation_via_frontend():
    """Undo plays the last move backward: anim from = move's to_sq, to = from_sq."""
    app = _start_game()
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    app.game.board.cancel_animations()
    app.game._on_undo()
    assert app.game.board.is_animating()
    a = app.game.board.animations[0]
    assert a.from_sq == Square(4, 4)
    assert a.to_sq == Square(6, 4)
    assert a.piece.type == PieceType.PAWN


def test_undo_during_forward_animation_replaces_with_reverse():
    """Undo mid-slide drops the in-flight forward anim and starts a reverse one."""
    app = _start_game()
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    assert app.game.board.is_animating()
    forward = app.game.board.animations[0]
    app.game._on_undo()
    assert app.game.board.is_animating()
    assert app.game.board.animations[0] is not forward
    assert app.game.board.animations[0].from_sq == Square(4, 4)


def test_undo_castle_triggers_two_reverse_animations():
    """Undoing O-O reverses both king (g1->e1) and rook (f1->h1)."""
    app = _start_game()
    backend = app.game.match.backend
    _seed_white_castle(backend)
    app.game.board.handle_click(Square(7, 4))
    app.game.board.handle_click(Square(7, 6))
    app.game.board.cancel_animations()
    app.game._on_undo()
    kinds = sorted(a.piece.type.name for a in app.game.board.animations)
    assert kinds == ["KING", "ROOK"]
    king_anim = next(a for a in app.game.board.animations if a.piece.type == PieceType.KING)
    rook_anim = next(a for a in app.game.board.animations if a.piece.type == PieceType.ROOK)
    assert (king_anim.from_sq, king_anim.to_sq) == (Square(7, 6), Square(7, 4))
    assert (rook_anim.from_sq, rook_anim.to_sq) == (Square(7, 5), Square(7, 7))


def test_undo_with_empty_history_is_a_noop():
    app = _start_game()
    app.game._on_undo()
    assert not app.game.board.is_animating()


@pytest.mark.parametrize(
    "make_move",
    [
        pytest.param(False, id="history_empty_only_selection"),
        pytest.param(True, id="history_nonempty_pops_move"),
    ],
)
def test_undo_clears_selection(make_move):
    """Undo always nulls the active selection, with or without a move to pop."""
    app = _start_game()
    if make_move:
        app.game.board.handle_click(Square(6, 4))
        app.game.board.handle_click(Square(4, 4))
        app.game.board.cancel_animations()
        assert len(app.game.match.move_history) == 1
    app.game.board.handle_click(Square(6, 0))
    assert app.game.board.selected_square == Square(6, 0)
    app.game._on_undo()
    assert app.game.board.selected_square is None
    if make_move:
        assert len(app.game.match.move_history) == 0


def test_undo_no_op_when_manual_result_set():
    """Undo is fully blocked after game end: no move pop, no selection mutation."""
    app = _start_game()
    app.game.manual_result = "white_wins"
    app.game.board.selected_square = Square(6, 4)
    app.game._on_undo()
    assert app.game.manual_result == "white_wins"
    assert app.game.board.selected_square == Square(6, 4)


def test_last_animation_completed_at_ms_initial_zero(board):
    assert board.last_animation_completed_at_ms == 0


def test_last_animation_completed_at_ms_updates_on_natural_completion(board):
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=pg.time.get_ticks() - 1000,
        duration_ms=200,
    )
    board.animations.append(a)
    before = board.last_animation_completed_at_ms
    board._draw_animations()
    assert board.last_animation_completed_at_ms > before


def test_last_animation_completed_at_ms_unchanged_on_cancel(board):
    board.start_animation(
        Square(6, 4), Square(4, 4),
        Piece(PieceType.PAWN, PieceColor.WHITE),
    )
    before = board.last_animation_completed_at_ms
    board.cancel_animations()
    assert board.last_animation_completed_at_ms == before


def test_auto_flip_blocked_during_post_animation_delay():
    """Auto-flip is suppressed for AUTO_FLIP_DELAY_MS after a slide lands."""
    from chessshootout.frontend.screens.game import AUTO_FLIP_DELAY_MS
    app = _start_game()
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    app.game.board.animations[0].start_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    assert not app.game.board.is_animating()
    app.game.board.last_animation_completed_at_ms = pg.time.get_ticks()
    app.draw_frame()
    assert app.game.board.flipped is False
    app.game.board.last_animation_completed_at_ms = pg.time.get_ticks() - AUTO_FLIP_DELAY_MS - 50
    app.draw_frame()
    assert app.game.board.flipped is True
