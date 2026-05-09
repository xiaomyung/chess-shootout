"""Click-other-piece-while-selected re-selects in one click.

Bug 4: previously deselected without re-selecting; user had to click twice.
Existing premove chains stay queued — the chain belongs to its piece, not the selection.
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
    pg.display.set_mode((1000, 800))
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


def _setup_position(bd, piece_map, turn=PieceColor.WHITE):
    bk = bd.backend
    bk.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        bk.state[sq.row][sq.col] = piece
    bk.turn = turn
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1


# ---------- Offline (single-screen) ----------

def test_click_own_piece_with_another_selected_reselects_in_one_click(board):
    # White to move. Select e2 pawn, then click d2 pawn (also white).
    board.handle_click(Square(6, 4))
    assert board.selected_square == Square(6, 4)
    board.handle_click(Square(6, 3))
    assert board.selected_square == Square(6, 3)


def test_click_same_square_still_deselects(board):
    # Regression: clicking the selected square deselects without re-selecting.
    board.handle_click(Square(6, 4))
    board.handle_click(Square(6, 4))
    assert board.selected_square is None


def test_click_legal_target_still_makes_move(board):
    # Regression: clicking a legal destination plays the move.
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert board.match.move_history, "expected one move in history"


def test_click_empty_illegal_square_deselects_without_reselect(board):
    # Selecting e2, then clicking an empty distant square (illegal) deselects.
    board.handle_click(Square(6, 4))
    assert board.selected_square == Square(6, 4)
    board.handle_click(Square(3, 0))
    assert board.selected_square is None


def test_click_opponent_piece_deselects_via_existing_capture_path(board):
    # Selecting white pawn e2, clicking black pawn at e7 — capture is illegal
    # from e2 (not adjacent), so the move attempt fails and selection clears.
    board.handle_click(Square(6, 4))
    board.handle_click(Square(1, 4))
    assert board.selected_square is None
    # Crucially we did NOT re-select the opponent's piece.


# ---------- Online (premove flow, not-our-turn) ----------

def test_click_own_piece_during_opp_turn_with_chain_keeps_chain_intact(board):
    # Bring board to an online-style state: not our turn, queued chain for piece A,
    # click own piece B → B selected, chain for A still in self.premoves.
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

    # Select e2, queue premove e2→e4.
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.WHITE
    chain_count_before = len(board.premoves)

    # Now click another own piece (d2). Selection switches; chain stays queued.
    board.handle_click(Square(6, 3))
    assert board.selected_square == Square(6, 3)
    assert len(board.premoves) == chain_count_before
    assert board.premoves[0].from_sq == Square(6, 4)
    assert board.premoves[0].to_sq == Square(4, 4)


def test_click_then_chain_two_independent_pieces(board):
    # Both pieces' chains coexist and fire in order on opponent's move.
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

    # Premove e2→e4 (piece A).
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))

    # Switch focus to d2 in one click.
    board.handle_click(Square(6, 3))
    assert board.selected_square == Square(6, 3)

    # Chain a premove for d2→d4 (piece B).
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 2
    moves = {(pm.from_sq, pm.to_sq) for pm in board.premoves}
    assert (Square(6, 4), Square(4, 4)) in moves
    assert (Square(6, 3), Square(4, 3)) in moves
