"""Click-other-piece-while-selected re-selects in one click (Bug 4).

Previously a click on a different own piece deselected without re-selecting,
forcing a second click. Existing premove chains stay queued across a focus
switch — the chain belongs to its piece, not to the current selection.
"""

import inspect
from collections import Counter

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.board import Board


_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def board():
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def _setup_position(bd, piece_map, turn=PieceColor.WHITE):
    bk = bd.backend
    bk.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        bk.state[sq.row][sq.col] = piece
    bk.turn = turn
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1


@pytest.mark.parametrize(
    "click_sq, expected_selection",
    [
        pytest.param(Square(6, 3), Square(6, 3), id="own_piece_d2_reselects_in_one_click"),
        pytest.param(Square(6, 4), None, id="same_square_e2_deselects"),
        pytest.param(Square(3, 0), None, id="empty_illegal_square_deselects_no_reselect"),
        pytest.param(Square(1, 4), None, id="opponent_e7_capture_illegal_deselects"),
    ],
)
def test_second_click_selection_from_selected_e2(board, click_sq, expected_selection):
    """With e2 selected, the second click resolves selection without re-selecting foes."""
    board.handle_click(Square(6, 4))
    assert board.selected_square == Square(6, 4)
    board.handle_click(click_sq)
    assert board.selected_square == expected_selection


def test_click_legal_target_still_makes_move(board):
    """Clicking a legal destination from the selection plays the move."""
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert board.selected_square is None
    assert board.match.move_history, "expected one move in history"


def test_click_own_piece_during_opp_turn_with_chain_keeps_chain_intact(board):
    """Online not-our-turn: switching focus to another own piece keeps the queued chain."""
    board.match.local_color = PieceColor.WHITE
    _setup_position(
        board,
        {
            Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
            Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
            Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
            Square(6, 3): Piece(PieceType.PAWN, PieceColor.WHITE),
        },
        turn=PieceColor.BLACK,
    )

    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.WHITE
    chain_count_before = len(board.premoves)

    board.handle_click(Square(6, 3))
    assert board.selected_square == Square(6, 3)
    assert len(board.premoves) == chain_count_before
    assert board.premoves[0].from_sq == Square(6, 4)
    assert board.premoves[0].to_sq == Square(4, 4)


def test_click_then_chain_two_independent_pieces(board):
    """Two own pieces' premove chains coexist and fire in order on the opponent's move."""
    board.match.local_color = PieceColor.WHITE
    _setup_position(
        board,
        {
            Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
            Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
            Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
            Square(6, 3): Piece(PieceType.PAWN, PieceColor.WHITE),
        },
        turn=PieceColor.BLACK,
    )

    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))

    board.handle_click(Square(6, 3))
    assert board.selected_square == Square(6, 3)

    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 2
    moves = {(pm.from_sq, pm.to_sq) for pm in board.premoves}
    assert (Square(6, 4), Square(4, 4)) in moves
    assert (Square(6, 3), Square(4, 3)) in moves


def test_focus_switch_predicate_takes_only_what_it_reads(board):
    """The clicked square was passed in and never read.

    _should_switch_focus_to decides from the current selection, the projected
    grid and the live piece under the cursor -- the square itself was a leftover
    that made the call site look as though it mattered. Calling positionally
    with only the four values it uses pins the signature to its real inputs.
    """
    board.handle_click(Square(6, 4))
    assert board._should_switch_focus_to(
        board.match.state, board.match.piece_at(Square(6, 3)), PieceColor.WHITE, None)
    assert list(inspect.signature(Board._should_switch_focus_to).parameters) == [
        "self", "grid", "live_at_clicked", "current_turn", "local_color"]
