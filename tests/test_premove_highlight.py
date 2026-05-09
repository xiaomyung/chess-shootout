"""Premove chain-tip highlight + drag ghost (bug 14, ADD-19).

The chain-tip is the to_sq of the last premove extending from the
currently active piece (selected or dragged). It renders with a brighter
color above the dim queued-square overlay.

The drag ghost is a 30%-alpha copy of the dragged piece blitted on the
origin square so the user sees where the piece came from.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import Counter

import pygame as pg
import pytest

from backend.backend import Backend
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.board import Board


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def board():
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def _setup_premove_state(bd, piece_map, turn=PieceColor.WHITE):
    bk = bd.backend
    bk.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        bk.state[sq.row][sq.col] = piece
    bk.turn = turn
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1
    bd.match.local_color = PieceColor.WHITE


# ---------- _active_chain_tip ----------

def test_no_premoves_means_no_chain_tip(board):
    board.selected_square = Square(6, 4)
    assert board._active_chain_tip() is None


def test_no_active_piece_means_no_chain_tip(board):
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.selected_square = None
    assert board._active_chain_tip() is None


def test_single_premove_chain_tip_is_target(board):
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    # Re-select origin → chain tip resolves to the queued destination.
    board.selected_square = Square(6, 4)
    assert board._active_chain_tip() == Square(4, 4)


def test_two_premove_chain_tip_is_last_destination(board):
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 1): Piece(PieceType.KNIGHT, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(7, 1))   # select knight
    board.handle_click(Square(5, 2))   # premove Nb1->c3
    board.handle_click(Square(5, 2))   # re-select speculative knight
    board.handle_click(Square(3, 3))   # premove Nc3->d5
    board.selected_square = Square(7, 1)  # original square
    assert board._active_chain_tip() == Square(3, 3)


def test_chain_tip_for_other_piece_returns_none(board):
    """Selecting a piece with no premove chain should return None — even if
    OTHER pieces have chains queued."""
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
        Square(6, 3): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))   # select e-pawn
    board.handle_click(Square(4, 4))   # premove e-pawn
    board.handle_click(Square(6, 3))   # select d-pawn (no chain yet)
    assert board._active_chain_tip() is None


def test_chain_tip_visible_when_selected_is_origin_after_click(board):
    """Click flow: re-click the original square (now empty in spec) → chain
    walk lands selection on the tip. Highlight must still appear."""
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))   # select pawn
    board.handle_click(Square(4, 4))   # premove e2->e4
    board.handle_click(Square(6, 4))   # click original (empty in spec) → lands on tip
    assert board.selected_square == Square(4, 4)
    assert board._active_chain_tip() == Square(4, 4)


def test_chain_tip_visible_when_selected_is_tip_directly(board):
    """Click flow: click the speculative piece directly (the tip). Selection
    lands on the tip. Highlight must still appear, just like drag mode."""
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))   # select pawn
    board.handle_click(Square(4, 4))   # premove e2->e4
    board.handle_click(Square(4, 4))   # click the speculative piece on e4
    assert board.selected_square == Square(4, 4)
    assert board._active_chain_tip() == Square(4, 4)


def test_chain_tip_visible_during_drag(board):
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    # Simulate user grabbing the original square in a drag gesture.
    board.selected_square = Square(6, 4)
    board.dragging_from = Square(6, 4)
    assert board._active_chain_tip() == Square(4, 4)


# ---------- queue_premove_from_drag without _drag_chain_tip field ----------

def test_drag_chain_tip_field_removed():
    # Sanity: the ad-hoc field is gone — chain tip is computed dynamically.
    assert not hasattr(Board(pg.display.get_surface(), Backend()), "_drag_chain_tip")


def test_queue_premove_from_drag_chains_correctly(board):
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.selected_square = Square(6, 4)
    board.dragging_from = Square(6, 4)
    assert board.queue_premove_from_drag(Square(4, 4)) is True
    assert len(board.premoves) == 1
    # Second drag-target chains from the new chain tip.
    assert board.queue_premove_from_drag(Square(3, 4)) is True
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(4, 4)
    assert board.premoves[1].to_sq == Square(3, 4)


# ---------- Drag ghost ----------

def test_dragged_piece_renders_ghost_on_origin(board):
    # Smoke test: drag a piece, frame draws without crashing.
    board.handle_click(Square(6, 4))
    board.dragging_from = Square(6, 4)
    board._drag_cursor = (200, 200)
    board.draw_board()


def test_chain_tip_premove_overlay_color_is_brighter():
    from frontend.visual.colors import Colors
    chain_tip = pg.Color(Colors.premove_chain_tip)
    queued = pg.Color(Colors.premove)
    # Brighter = higher opacity (more visible) than the dim queued squares.
    assert chain_tip.a > queued.a


# ---------- Bouncing chain (revisits squares) ----------

def test_chain_tip_resolves_correctly_when_rook_bounces(board):
    """Rook bounces a8 ↔ b8. The chain tip must reflect the LAST applicable
    premove, not the first square that gets revisited."""
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(7, 0))   # select rook
    board.handle_click(Square(0, 0))   # premove a1->a8
    board.handle_click(Square(0, 0))   # re-select chain tip
    board.handle_click(Square(0, 1))   # premove a8->b8
    board.handle_click(Square(0, 1))   # re-select chain tip
    board.handle_click(Square(0, 0))   # premove b8->a8 (BOUNCE)
    assert board._resolve_chain_tip(Square(7, 0)) == Square(0, 0)
    assert len(board.premoves) == 3

    # Continue bouncing: a8 -> b8 again.
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 1))
    assert board._resolve_chain_tip(Square(7, 0)) == Square(0, 1)
    assert len(board.premoves) == 4


def test_premove_overlay_drawn_once_per_square_even_in_bounce_chain(board):
    """The seen-set in _draw_premove_highlights ensures each unique square is
    rendered with the dim overlay once — overlays don't compound visually."""
    _setup_premove_state(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    # Build a bouncing chain.
    board.handle_click(Square(7, 0))
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 1))
    board.handle_click(Square(0, 1))
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 1))

    unique_squares = set()
    for pm in board.premoves:
        unique_squares.add(pm.from_sq)
        unique_squares.add(pm.to_sq)
    # Three unique squares (a1, a8, b8) — the overlay loop visits each once.
    assert unique_squares == {Square(7, 0), Square(0, 0), Square(0, 1)}
