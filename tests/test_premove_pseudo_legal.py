"""Pseudo-legal premove validation (bugs 13 + 15).

A premove from→to is admissible iff a single piece of that type, alone on
an empty board at `from`, could plausibly reach `to`. Pawns are direction-
correct; knights L-shaped only; sliders along their lines; king 1-square
box plus castle-from-home. Engine remains authoritative on fire.
"""

import pytest

from backend.pieces import (
    BLACK_KING_HOME_ROW, BLACK_PAWN_START_ROW, CASTLE_TARGET_COLS,
    KING_HOME_COL, KNIGHT_OFFSETS, Piece, PieceColor, PieceType,
    WHITE_KING_HOME_ROW, WHITE_PAWN_START_ROW,
)
from backend.pseudo_legal import piece_can_pseudo_reach
from backend.utils import BOARD_SIZE, Square


def sq(row, col):
    return Square(row, col)


# ---------- Sanity guards ----------

@pytest.mark.parametrize("piece_type", list(PieceType))
def test_same_square_rejected(piece_type):
    piece = Piece(piece_type, PieceColor.WHITE)
    assert piece_can_pseudo_reach(piece, sq(4, 4), sq(4, 4)) is False


@pytest.mark.parametrize("piece_type", list(PieceType))
def test_off_board_target_rejected(piece_type):
    piece = Piece(piece_type, PieceColor.WHITE)
    assert piece_can_pseudo_reach(piece, sq(4, 4), sq(-1, 4)) is False
    assert piece_can_pseudo_reach(piece, sq(4, 4), sq(4, BOARD_SIZE)) is False


# ---------- Pawn ----------

@pytest.mark.parametrize("color,start_row,one_forward", [
    (PieceColor.WHITE, WHITE_PAWN_START_ROW, WHITE_PAWN_START_ROW - 1),
    (PieceColor.BLACK, BLACK_PAWN_START_ROW, BLACK_PAWN_START_ROW + 1),
])
def test_pawn_one_step_forward(color, start_row, one_forward):
    piece = Piece(PieceType.PAWN, color)
    assert piece_can_pseudo_reach(piece, sq(start_row, 4), sq(one_forward, 4)) is True


def test_pawn_two_step_only_from_starting_rank():
    white = Piece(PieceType.PAWN, PieceColor.WHITE)
    # From starting rank: 2 forward OK.
    assert piece_can_pseudo_reach(
        white, sq(WHITE_PAWN_START_ROW, 4), sq(WHITE_PAWN_START_ROW - 2, 4),
    )
    # From any other rank: 2 forward rejected.
    assert piece_can_pseudo_reach(white, sq(4, 4), sq(2, 4)) is False


def test_pawn_backward_rejected():
    white = Piece(PieceType.PAWN, PieceColor.WHITE)
    black = Piece(PieceType.PAWN, PieceColor.BLACK)
    # White moves up (decreasing row); going down is rejected.
    assert piece_can_pseudo_reach(white, sq(4, 4), sq(5, 4)) is False
    # Black moves down (increasing row); going up is rejected.
    assert piece_can_pseudo_reach(black, sq(4, 4), sq(3, 4)) is False


def test_pawn_diagonal_capture_shape():
    white = Piece(PieceType.PAWN, PieceColor.WHITE)
    assert piece_can_pseudo_reach(white, sq(4, 4), sq(3, 3)) is True
    assert piece_can_pseudo_reach(white, sq(4, 4), sq(3, 5)) is True


def test_pawn_diagonal_two_squares_rejected():
    white = Piece(PieceType.PAWN, PieceColor.WHITE)
    assert piece_can_pseudo_reach(white, sq(4, 4), sq(2, 6)) is False


def test_pawn_promotion_squares_admissible():
    # Forward to last rank counts as a forward push of 1.
    white = Piece(PieceType.PAWN, PieceColor.WHITE)
    black = Piece(PieceType.PAWN, PieceColor.BLACK)
    assert piece_can_pseudo_reach(white, sq(1, 4), sq(0, 4)) is True
    assert piece_can_pseudo_reach(black, sq(6, 4), sq(7, 4)) is True


# ---------- Knight ----------

def test_knight_each_l_shape_offset_admissible():
    knight = Piece(PieceType.KNIGHT, PieceColor.WHITE)
    origin = sq(4, 4)
    for drow, dcol in KNIGHT_OFFSETS:
        target = sq(origin.row + drow, origin.col + dcol)
        assert piece_can_pseudo_reach(knight, origin, target), \
            f"knight L-shape ({drow},{dcol}) should be admissible"


@pytest.mark.parametrize("target", [
    Square(4, 0),  # same rank
    Square(0, 4),  # same file
    Square(0, 0),  # diagonal
    Square(3, 3),  # one diagonal step
    Square(4, 5),  # adjacent
])
def test_knight_non_l_rejected(target):
    knight = Piece(PieceType.KNIGHT, PieceColor.WHITE)
    assert piece_can_pseudo_reach(knight, sq(4, 4), target) is False


# ---------- Bishop ----------

@pytest.mark.parametrize("target", [
    Square(0, 0), Square(7, 7), Square(7, 1), Square(1, 7), Square(3, 3),
])
def test_bishop_diagonals_admissible(target):
    bishop = Piece(PieceType.BISHOP, PieceColor.WHITE)
    assert piece_can_pseudo_reach(bishop, sq(4, 4), target) is True


@pytest.mark.parametrize("target", [
    Square(4, 0), Square(0, 4), Square(4, 5),
])
def test_bishop_non_diagonal_rejected(target):
    bishop = Piece(PieceType.BISHOP, PieceColor.WHITE)
    assert piece_can_pseudo_reach(bishop, sq(4, 4), target) is False


# ---------- Rook ----------

@pytest.mark.parametrize("target", [
    Square(4, 0), Square(4, 7), Square(0, 4), Square(7, 4),
])
def test_rook_lines_admissible(target):
    rook = Piece(PieceType.ROOK, PieceColor.WHITE)
    assert piece_can_pseudo_reach(rook, sq(4, 4), target) is True


@pytest.mark.parametrize("target", [
    Square(0, 0), Square(3, 3), Square(5, 6),
])
def test_rook_off_lines_rejected(target):
    rook = Piece(PieceType.ROOK, PieceColor.WHITE)
    assert piece_can_pseudo_reach(rook, sq(4, 4), target) is False


# ---------- Queen ----------

@pytest.mark.parametrize("target", [
    Square(4, 0), Square(0, 4), Square(7, 7), Square(0, 0),
])
def test_queen_lines_and_diagonals_admissible(target):
    queen = Piece(PieceType.QUEEN, PieceColor.WHITE)
    assert piece_can_pseudo_reach(queen, sq(4, 4), target) is True


def test_queen_off_pattern_rejected():
    queen = Piece(PieceType.QUEEN, PieceColor.WHITE)
    # Knight-shape jump.
    assert piece_can_pseudo_reach(queen, sq(4, 4), sq(2, 5)) is False


# ---------- King ----------

def test_king_one_square_box_admissible():
    king = Piece(PieceType.KING, PieceColor.WHITE)
    origin = sq(4, 4)
    for drow in (-1, 0, 1):
        for dcol in (-1, 0, 1):
            if drow == 0 and dcol == 0:
                continue
            assert piece_can_pseudo_reach(king, origin, sq(origin.row + drow, origin.col + dcol))


def test_king_two_squares_rejected():
    king = Piece(PieceType.KING, PieceColor.WHITE)
    assert piece_can_pseudo_reach(king, sq(4, 4), sq(4, 6)) is False
    assert piece_can_pseudo_reach(king, sq(4, 4), sq(2, 4)) is False


@pytest.mark.parametrize("color,home_row", [
    (PieceColor.WHITE, WHITE_KING_HOME_ROW),
    (PieceColor.BLACK, BLACK_KING_HOME_ROW),
])
def test_king_castle_admissible_only_from_home(color, home_row):
    king = Piece(PieceType.KING, color)
    home = sq(home_row, KING_HOME_COL)
    for col in CASTLE_TARGET_COLS:
        assert piece_can_pseudo_reach(king, home, sq(home_row, col)) is True


def test_king_castle_rejected_when_not_on_home():
    king = Piece(PieceType.KING, PieceColor.WHITE)
    # King moved off home (e2): cannot castle from there.
    assert piece_can_pseudo_reach(king, sq(6, 4), sq(7, 6)) is False
    assert piece_can_pseudo_reach(king, sq(6, 4), sq(7, 2)) is False


# ---------- Chain extension via Board._queue_premove gate ----------

def _setup(board, piece_map, turn=PieceColor.BLACK):
    from collections import Counter
    bk = board.backend
    bk.state = [[None] * BOARD_SIZE for _ in range(BOARD_SIZE)]
    for s, p in piece_map.items():
        bk.state[s.row][s.col] = p
    bk.turn = turn
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1
    board.match.local_color = PieceColor.WHITE
    board.premoves.clear()
    board.premove_color = None
    board.selected_square = None


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame as pg
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def board():
    import pygame as pg
    from backend.backend import Backend
    from frontend.board import Board
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def test_chain_rook_rejects_non_line_extension(board):
    """User's example: rook a1 → a5 (file), then a5 → e5 (rank), then e5 → d4 (off-line)."""
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    })
    board.handle_click(Square(7, 0))   # select rook
    board.handle_click(Square(3, 0))   # premove a1->a5
    board.handle_click(Square(3, 0))   # re-select speculative rook
    board.handle_click(Square(3, 4))   # chain a5->e5 (rank — admissible)
    assert len(board.premoves) == 2

    board.handle_click(Square(3, 4))   # re-select on e5
    board.handle_click(Square(4, 3))   # try chain e5->d4 (diagonal — REJECTED)
    assert len(board.premoves) == 2, "diagonal extension on rook should be rejected"


def test_chain_knight_rejects_non_l_shape(board):
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 6): Piece(PieceType.KNIGHT, PieceColor.WHITE),
    })
    board.handle_click(Square(7, 6))   # select knight (g1)
    board.handle_click(Square(7, 0))   # try Ng1->a1 (illegal shape — rejected)
    assert board.premoves == []
    board.handle_click(Square(7, 6))   # re-select
    board.handle_click(Square(5, 5))   # Ng1->f3 (L-shape — admissible)
    assert len(board.premoves) == 1


def test_chain_pawn_direction_correct(board):
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 0): Piece(PieceType.PAWN, PieceColor.WHITE),
    })
    board.handle_click(Square(6, 0))  # select pawn
    board.handle_click(Square(7, 0))  # try backward (REJECTED)
    assert board.premoves == []
    board.handle_click(Square(6, 0))  # re-select
    board.handle_click(Square(4, 0))  # forward 2 from start (admissible)
    assert len(board.premoves) == 1


def test_chain_castle_from_home_only(board):
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    board.handle_click(Square(7, 4))  # select king (e1)
    board.handle_click(Square(7, 6))  # premove e1->g1 (castle from home — admissible)
    assert len(board.premoves) == 1
    # Now imagine king moved off home in a previous chain step. Re-init.
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    board.handle_click(Square(7, 4))  # select king
    board.handle_click(Square(6, 4))  # premove e1->e2 (one step)
    assert len(board.premoves) == 1
    board.handle_click(Square(6, 4))  # re-select on e2 chain tip
    board.handle_click(Square(7, 6))  # try castle from e2 (REJECTED)
    assert len(board.premoves) == 1, "castle premove not allowed when king not on home in chain"
