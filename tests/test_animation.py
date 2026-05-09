import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from backend.backend import Backend
from backend.utils import Square
from frontend.animation import PieceAnimation
from backend.pieces import Piece, PieceColor, PieceType


DEFAULT_CONFIG = {
    "mode": "single_screen",
    "nickname": "Tester",
    "time_minutes": None,
    "increment_seconds": 5,
    "side": "white",
}


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def board():
    from frontend.board import Board
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def test_progress_clamps_to_zero_at_start():
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=1000, duration_ms=200,
    )
    assert a.progress(1000) == 0.0


def test_progress_midway():
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=1000, duration_ms=200,
    )
    assert a.progress(1100) == pytest.approx(0.5)


def test_progress_clamps_to_one_at_end():
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=1000, duration_ms=200,
    )
    assert a.progress(1200) == 1.0
    assert a.progress(2000) == 1.0
    assert a.is_done(1200) is True


def test_zero_duration_is_immediately_done():
    a = PieceAnimation(
        from_sq=Square(6, 4), to_sq=Square(4, 4),
        piece=Piece(PieceType.PAWN, PieceColor.WHITE),
        start_ms=1000, duration_ms=0,
    )
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
    backend = board.backend
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.ROOK, PieceColor.WHITE)
    backend.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    from collections import Counter
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1

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
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    # Cancel forward anim by completing it, then undo.
    app.board.cancel_animations()
    app._on_undo()
    assert app.board.is_animating()
    a = app.board.animations[0]
    # Reverse direction: animation from = original move's to_sq, to = from_sq.
    assert a.from_sq == Square(4, 4)
    assert a.to_sq == Square(6, 4)
    assert a.piece.type == PieceType.PAWN


def test_undo_during_forward_animation_replaces_with_reverse():
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    assert app.board.is_animating()
    forward = app.board.animations[0]
    app._on_undo()
    # Old animation gone; new reverse animation in flight.
    assert app.board.is_animating()
    assert app.board.animations[0] is not forward
    assert app.board.animations[0].from_sq == Square(4, 4)


def test_undo_castle_triggers_two_reverse_animations():
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    backend = app.backend
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.ROOK, PieceColor.WHITE)
    backend.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    from collections import Counter
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    app.board.handle_click(Square(7, 4))
    app.board.handle_click(Square(7, 6))
    app.board.cancel_animations()
    app._on_undo()
    kinds = sorted(a.piece.type.name for a in app.board.animations)
    assert kinds == ["KING", "ROOK"]
    # King reverses 7,6 -> 7,4; rook reverses 7,5 -> 7,7.
    king_anim = next(a for a in app.board.animations if a.piece.type == PieceType.KING)
    rook_anim = next(a for a in app.board.animations if a.piece.type == PieceType.ROOK)
    assert (king_anim.from_sq, king_anim.to_sq) == (Square(7, 6), Square(7, 4))
    assert (rook_anim.from_sq, rook_anim.to_sq) == (Square(7, 5), Square(7, 7))


def test_undo_with_empty_history_is_a_noop():
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    # No moves made; undo should not error or start an animation.
    app._on_undo()
    assert not app.board.is_animating()


def test_undo_clears_active_selection():
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    app.board.handle_click(Square(6, 4))
    assert app.board.selected_square == Square(6, 4)
    app._on_undo()
    assert app.board.selected_square is None


def test_undo_clears_selection_even_when_history_empty():
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    app.board.handle_click(Square(6, 4))
    app._on_undo()
    assert app.board.selected_square is None


def test_undo_no_op_when_manual_result_set():
    # Undo is fully blocked once the game has ended — it must not undo a move,
    # not dismiss the result, not even mutate selection.
    from frontend.frontend import Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    app.manual_result = "white_wins"
    app.board.selected_square = Square(6, 4)
    app._on_undo()
    assert app.manual_result == "white_wins"
    assert app.board.selected_square == Square(6, 4)


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
    from frontend.frontend import AUTO_FLIP_DELAY_MS, Frontend
    app = Frontend(800, 600)
    app._on_start_game(DEFAULT_CONFIG)
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app.board.animations[0].start_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    assert not app.board.is_animating()
    # Animation just completed; we're inside the post-animation delay window.
    app.board.last_animation_completed_at_ms = pg.time.get_ticks()
    app.draw_frame()
    assert app.board.flipped is False  # flip suppressed by delay
    # Pretend the delay elapsed.
    app.board.last_animation_completed_at_ms = pg.time.get_ticks() - AUTO_FLIP_DELAY_MS - 50
    app.draw_frame()
    assert app.board.flipped is True
