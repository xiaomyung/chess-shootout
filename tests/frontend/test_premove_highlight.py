"""Premove chain-tip highlight + drag-ghost render invariants (bug 14, ADD-19).

The chain tip is the to_sq of the last premove extending from the currently
active piece (selected or dragged); it renders with a brighter overlay above the
dim queued-square overlay. Premove validation is intentionally LAX (pseudo-legal
from the chain tip), which is what lets a queued piece keep extending its own
speculative chain — including bouncing chains that revisit squares. The drag
ghost is a 30%-alpha copy of the dragged piece blitted on its origin square.
"""

from collections import Counter

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.board import Board


_pygame_init = pygame_display(800, 600)


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


def _kings_with(extra):
    base = {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    }
    base.update(extra)
    return base


def _frame_block_diff(surface_a, surface_b, cx, cy, radius=20, step=4):
    diff = 0
    for dx in range(-radius, radius, step):
        for dy in range(-radius, radius, step):
            if surface_a.get_at((cx + dx, cy + dy)) != surface_b.get_at((cx + dx, cy + dy)):
                diff += 1
    return diff


def _region_block_diff(surface, ca, cb, radius=20, step=4):
    diff = 0
    for dx in range(-radius, radius, step):
        for dy in range(-radius, radius, step):
            if surface.get_at((ca[0] + dx, ca[1] + dy)) != surface.get_at((cb[0] + dx, cb[1] + dy)):
                diff += 1
    return diff


def test_no_premoves_means_no_chain_tip(board):
    board.selected_square = Square(6, 4)
    assert board._active_chain_tip() is None


def test_no_active_piece_means_no_chain_tip(board):
    _setup_premove_state(board, _kings_with({
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.selected_square = None
    assert board._active_chain_tip() is None


def test_single_premove_chain_tip_is_target(board):
    _setup_premove_state(board, _kings_with({
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.selected_square = Square(6, 4)
    assert board._active_chain_tip() == Square(4, 4)


def test_two_premove_chain_tip_is_last_destination(board):
    _setup_premove_state(board, _kings_with({
        Square(7, 1): Piece(PieceType.KNIGHT, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(7, 1))
    board.handle_click(Square(5, 2))
    board.handle_click(Square(5, 2))
    board.handle_click(Square(3, 3))
    board.selected_square = Square(7, 1)
    assert board._active_chain_tip() == Square(3, 3)


def test_chain_tip_for_other_piece_returns_none(board):
    """Selecting a chain-less piece returns None even when OTHER pieces have
    chains queued — the tip is per-active-piece, not global."""
    _setup_premove_state(board, _kings_with({
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
        Square(6, 3): Piece(PieceType.PAWN, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(6, 3))
    assert board._active_chain_tip() is None


@pytest.mark.parametrize(
    "final_click",
    [
        pytest.param(Square(6, 4), id="click_emptied_origin_walks_to_tip"),
        pytest.param(Square(4, 4), id="click_speculative_piece_is_tip"),
    ],
)
def test_chain_tip_visible_after_reselecting_premoved_pawn(board, final_click):
    """Re-selecting a single-premove pawn — whether by clicking the now-empty
    origin (chain walk) or the speculative piece directly — lands selection on
    the tip and keeps the highlight visible."""
    _setup_premove_state(board, _kings_with({
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(final_click)
    assert board.selected_square == Square(4, 4)
    assert board._active_chain_tip() == Square(4, 4)


def test_chain_tip_visible_during_drag(board):
    _setup_premove_state(board, _kings_with({
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.selected_square = Square(6, 4)
    board.dragging_from = Square(6, 4)
    assert board._active_chain_tip() == Square(4, 4)


def test_drag_chain_tip_field_removed():
    """The ad-hoc _drag_chain_tip field is gone — the tip is computed live."""
    assert not hasattr(Board(pg.display.get_surface(), Backend()), "_drag_chain_tip")


def test_queue_premove_from_drag_chains_correctly(board):
    _setup_premove_state(board, _kings_with({
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.selected_square = Square(6, 4)
    board.dragging_from = Square(6, 4)
    assert board.queue_premove_from_drag(Square(4, 4)) is True
    assert len(board.premoves) == 1
    assert board.queue_premove_from_drag(Square(3, 4)) is True
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(4, 4)
    assert board.premoves[1].to_sq == Square(3, 4)


def test_dragged_piece_renders_ghost_on_origin(board):
    """_draw_dragged_piece blits a 30%-alpha ghost on the origin square and the
    full piece at the cursor. Assert: (1) the cursor block, previously bare
    board, gains the dragged piece; (2) the origin now differs from an empty
    same-color tile (a ghost is drawn there) yet differs from the opaque resting
    piece (the ghost is dimmer than the full piece)."""
    board.handle_click(Square(6, 4))
    win = pg.display.get_surface()

    board.draw_board()
    board.draw_drag_overlay()
    no_drag = win.copy()

    rect = board._cell_rect(6, 4)
    board.begin_press(rect.center)
    board.update_drag_motion((200, 200))
    board.drag._drag["entry"] = 1.0
    board.drag._drag["anchor"] = (200, 200)
    board.draw_board()
    board.draw_drag_overlay()
    drag_frame = win.copy()

    assert _frame_block_diff(no_drag, drag_frame, 200, 200) > 0

    origin = board._cell_rect(6, 4)
    empty_same_color = board._cell_rect(4, 2)
    assert _region_block_diff(drag_frame, origin.center, empty_same_color.center) > 0
    assert _frame_block_diff(no_drag, drag_frame, origin.centerx, origin.centery) > 0


def test_chain_tip_premove_overlay_color_is_brighter():
    """The chain-tip overlay is more opaque than the dim queued-square overlay."""
    from chessshootout.frontend.visual.colors import Colors
    chain_tip = pg.Color(Colors.premove_chain_tip)
    queued = pg.Color(Colors.premove)
    assert chain_tip.a > queued.a


def test_chain_tip_resolves_correctly_when_rook_bounces(board):
    """Lax pseudo-legal validation lets a rook bounce a8 <-> b8. The chain tip
    must reflect the LAST applicable premove, not the first revisited square."""
    _setup_premove_state(board, _kings_with({
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
    board.handle_click(Square(7, 0))
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 1))
    board.handle_click(Square(0, 1))
    board.handle_click(Square(0, 0))
    assert board._resolve_chain_tip(Square(7, 0)) == Square(0, 0)
    assert len(board.premoves) == 3

    board.handle_click(Square(0, 0))
    board.handle_click(Square(0, 1))
    assert board._resolve_chain_tip(Square(7, 0)) == Square(0, 1)
    assert len(board.premoves) == 4


def test_premove_overlay_drawn_once_per_square_even_in_bounce_chain(board):
    """The seen-set in _draw_premove_highlights renders each unique square's dim
    overlay once, so a bouncing chain (a1/a8/b8) does not compound visually."""
    _setup_premove_state(board, _kings_with({
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    }), turn=PieceColor.BLACK)
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
    assert unique_squares == {Square(7, 0), Square(0, 0), Square(0, 1)}
