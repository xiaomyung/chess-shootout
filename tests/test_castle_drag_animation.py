"""Castle-drag animation: king snaps under cursor; rook still animates."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from collections import Counter

import pygame as pg
import pytest

from backend.backend import Backend
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square


KING_HOME = Square(7, 4)
WHITE_KINGSIDE_TARGET = Square(7, 6)
WHITE_QUEENSIDE_TARGET = Square(7, 2)
WHITE_ROOK_KS_HOME = Square(7, 7)
WHITE_ROOK_KS_DEST = Square(7, 5)
WHITE_ROOK_QS_HOME = Square(7, 0)
WHITE_ROOK_QS_DEST = Square(7, 3)
BLACK_KING_HOME = Square(0, 4)


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


def _setup_castle_position(backend, kingside_only=False, queenside_only=False):
    """Reset the board to a minimal castle-ready position for white."""
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[KING_HOME.row][KING_HOME.col] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[BLACK_KING_HOME.row][BLACK_KING_HOME.col] = Piece(
        PieceType.KING, PieceColor.BLACK
    )
    if not queenside_only:
        backend.state[WHITE_ROOK_KS_HOME.row][WHITE_ROOK_KS_HOME.col] = Piece(
            PieceType.ROOK, PieceColor.WHITE
        )
    if not kingside_only:
        backend.state[WHITE_ROOK_QS_HOME.row][WHITE_ROOK_QS_HOME.col] = Piece(
            PieceType.ROOK, PieceColor.WHITE
        )
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1


def _trigger_drag_castle(board, target_sq):
    """Simulate the drag-release flow: drag-state still set when handle_click fires."""
    board.handle_click(KING_HOME)
    board.dragging_from = KING_HOME
    board.handle_click(target_sq)


def test_drag_castle_kingside_animates_rook_only(board):
    _setup_castle_position(board.backend, kingside_only=True)
    _trigger_drag_castle(board, WHITE_KINGSIDE_TARGET)

    # King has already snapped to its destination via the drag — only the rook anim.
    assert len(board.animations) == 1
    rook_anim = board.animations[0]
    assert rook_anim.piece.type == PieceType.ROOK
    assert rook_anim.piece.color == PieceColor.WHITE
    assert rook_anim.from_sq == WHITE_ROOK_KS_HOME
    assert rook_anim.to_sq == WHITE_ROOK_KS_DEST


def test_drag_castle_queenside_animates_rook_only(board):
    _setup_castle_position(board.backend, queenside_only=True)
    _trigger_drag_castle(board, WHITE_QUEENSIDE_TARGET)

    assert len(board.animations) == 1
    rook_anim = board.animations[0]
    assert rook_anim.piece.type == PieceType.ROOK
    assert rook_anim.from_sq == WHITE_ROOK_QS_HOME
    assert rook_anim.to_sq == WHITE_ROOK_QS_DEST


def test_drag_non_castle_skips_animation_entirely(board):
    """Regression: a regular drag move still snaps both ends — no animation."""
    # Default starting position; drag e2 -> e4.
    e2 = Square(6, 4)
    e4 = Square(4, 4)
    board.handle_click(e2)
    board.dragging_from = e2
    board.handle_click(e4)

    assert len(board.animations) == 0


def test_click_castle_animates_both_pieces(board):
    """Regression: click-castle (no drag) keeps both king and rook animations."""
    _setup_castle_position(board.backend, kingside_only=True)
    board.handle_click(KING_HOME)
    # Note: dragging_from stays None — this is a click-castle, not a drag.
    board.handle_click(WHITE_KINGSIDE_TARGET)

    kinds = sorted(a.piece.type.name for a in board.animations)
    assert kinds == ["KING", "ROOK"]


def test_drag_castle_rook_animation_carries_on_complete(board):
    """The rook animation must own the on_complete callback (it's the only one running)."""
    _setup_castle_position(board.backend, kingside_only=True)
    _trigger_drag_castle(board, WHITE_KINGSIDE_TARGET)

    rook_anim = board.animations[0]
    # In drag-castle the on_complete (move_landed_callback firing) is attached to the rook
    # — without this the post-move auto-flip + sound logic would never run.
    assert rook_anim.on_complete is not None


def test_drag_move_stamps_last_animation_completed_for_flip_delay(board):
    """A non-castle drag move snaps with no animation but must still trigger the
    post-move flip delay — otherwise the board flips instantly mid-drag-release,
    which feels jarring compared to clicked moves."""
    e2 = Square(6, 4)
    e4 = Square(4, 4)
    before = board.last_animation_completed_at_ms
    board.handle_click(e2)
    board.dragging_from = e2
    board.handle_click(e4)
    assert board.last_animation_completed_at_ms > before
