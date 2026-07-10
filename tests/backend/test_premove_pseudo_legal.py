"""Pseudo-legal premove validation (lax move-shape gate, bugs 13 + 15).

A premove from->to is admissible iff a single piece of that type, alone on an
empty board at `from`, could plausibly reach `to` by shape alone: pawns
direction-correct, knights L-shaped, sliders along their lines, king a 1-square
box plus castle-from-home. This is intentionally LAX (no occupancy, no check) --
the engine stays authoritative when the premove fires. Chain extension reuses
the same gate from the speculative chain tip, so a multi-step premove chain must
stay shape-legal at every hop.
"""

import pytest

from chessshootout.backend.pieces import (
    BLACK_KING_HOME_ROW, BLACK_PAWN_START_ROW, CASTLE_TARGET_COLS,
    KING_HOME_COL, KING_OFFSETS, KNIGHT_OFFSETS, Piece, PieceColor, PieceType,
    WHITE_KING_HOME_ROW, WHITE_PAWN_START_ROW,
)
from chessshootout.backend.pseudo_legal import piece_can_pseudo_reach
from chessshootout.backend.utils import BOARD_SIZE, Square

from tests.helpers import sq, sq_of

WHITE = PieceColor.WHITE
BLACK = PieceColor.BLACK


@pytest.mark.parametrize("piece_type", list(PieceType))
def test_same_square_rejected(piece_type):
    p = Piece(piece_type, WHITE)
    assert piece_can_pseudo_reach(p, sq(4, 4), sq(4, 4)) is False


@pytest.mark.parametrize("piece_type", list(PieceType))
def test_off_board_target_rejected(piece_type):
    p = Piece(piece_type, WHITE)
    assert piece_can_pseudo_reach(p, sq(4, 4), sq(-1, 4)) is False
    assert piece_can_pseudo_reach(p, sq(4, 4), sq(4, BOARD_SIZE)) is False


@pytest.mark.parametrize("color, from_sq, to_sq, admissible", [
    pytest.param(WHITE, sq(WHITE_PAWN_START_ROW, 4), sq(WHITE_PAWN_START_ROW - 1, 4),
                 True, id="white_one_step_forward"),
    pytest.param(BLACK, sq(BLACK_PAWN_START_ROW, 4), sq(BLACK_PAWN_START_ROW + 1, 4),
                 True, id="black_one_step_forward"),
    pytest.param(WHITE, sq(WHITE_PAWN_START_ROW, 4), sq(WHITE_PAWN_START_ROW - 2, 4),
                 True, id="white_two_step_from_start_rank"),
    pytest.param(WHITE, sq(4, 4), sq(2, 4), False, id="white_two_step_off_start_rank"),
    pytest.param(WHITE, sq(4, 4), sq(5, 4), False, id="white_backward_rejected"),
    pytest.param(BLACK, sq(4, 4), sq(3, 4), False, id="black_backward_rejected"),
    pytest.param(WHITE, sq(4, 4), sq(3, 3), True, id="white_diagonal_left_capture"),
    pytest.param(WHITE, sq(4, 4), sq(3, 5), True, id="white_diagonal_right_capture"),
    pytest.param(WHITE, sq(4, 4), sq(2, 6), False, id="white_diagonal_two_squares_rejected"),
    pytest.param(WHITE, sq(1, 4), sq(0, 4), True, id="white_forward_onto_last_rank_promo"),
    pytest.param(BLACK, sq(6, 4), sq(7, 4), True, id="black_forward_onto_last_rank_promo"),
])
def test_pawn_pseudo_reach(color, from_sq, to_sq, admissible):
    p = Piece(PieceType.PAWN, color)
    assert piece_can_pseudo_reach(p, from_sq, to_sq) is admissible


_KNIGHT_L = [
    pytest.param(sq(4 + dr, 4 + dc), True, id=f"l_shape_{i}")
    for i, (dr, dc) in enumerate(KNIGHT_OFFSETS)
]


@pytest.mark.parametrize("to_sq, admissible", _KNIGHT_L + [
    pytest.param(sq(4, 0), False, id="same_rank_rejected"),
    pytest.param(sq(0, 4), False, id="same_file_rejected"),
    pytest.param(sq(0, 0), False, id="diagonal_rejected"),
    pytest.param(sq(3, 3), False, id="one_diagonal_step_rejected"),
    pytest.param(sq(4, 5), False, id="adjacent_rejected"),
])
def test_knight_pseudo_reach(to_sq, admissible):
    p = Piece(PieceType.KNIGHT, WHITE)
    assert piece_can_pseudo_reach(p, sq(4, 4), to_sq) is admissible


@pytest.mark.parametrize("to_sq, admissible", [
    pytest.param(sq_of("a8"), True, id="diagonal_up_left"),
    pytest.param(sq_of("h1"), True, id="diagonal_down_right"),
    pytest.param(sq_of("b1"), True, id="diagonal_down_left"),
    pytest.param(sq_of("h7"), True, id="diagonal_up_right"),
    pytest.param(sq_of("d5"), True, id="one_diagonal_step"),
    pytest.param(sq_of("a4"), False, id="rank_rejected"),
    pytest.param(sq_of("e8"), False, id="file_rejected"),
    pytest.param(sq_of("f4"), False, id="adjacent_rank_rejected"),
])
def test_bishop_pseudo_reach(to_sq, admissible):
    p = Piece(PieceType.BISHOP, WHITE)
    assert piece_can_pseudo_reach(p, sq_of("e4"), to_sq) is admissible


@pytest.mark.parametrize("to_sq, admissible", [
    pytest.param(sq_of("a4"), True, id="rank_left"),
    pytest.param(sq_of("h4"), True, id="rank_right"),
    pytest.param(sq_of("e8"), True, id="file_up"),
    pytest.param(sq_of("e1"), True, id="file_down"),
    pytest.param(sq_of("a8"), False, id="diagonal_rejected"),
    pytest.param(sq_of("d5"), False, id="one_diagonal_rejected"),
    pytest.param(sq_of("g3"), False, id="off_line_rejected"),
])
def test_rook_pseudo_reach(to_sq, admissible):
    p = Piece(PieceType.ROOK, WHITE)
    assert piece_can_pseudo_reach(p, sq_of("e4"), to_sq) is admissible


@pytest.mark.parametrize("to_sq, admissible", [
    pytest.param(sq_of("a4"), True, id="rank"),
    pytest.param(sq_of("e8"), True, id="file"),
    pytest.param(sq_of("h1"), True, id="diagonal_down_right"),
    pytest.param(sq_of("a8"), True, id="diagonal_up_left"),
    pytest.param(sq_of("f6"), False, id="knight_shape_rejected"),
])
def test_queen_pseudo_reach(to_sq, admissible):
    p = Piece(PieceType.QUEEN, WHITE)
    assert piece_can_pseudo_reach(p, sq_of("e4"), to_sq) is admissible


_KING_BOX = [
    pytest.param(sq(4 + dr, 4 + dc), True, id=f"box_{i}")
    for i, (dr, dc) in enumerate(KING_OFFSETS)
]


@pytest.mark.parametrize("to_sq, admissible", _KING_BOX + [
    pytest.param(sq(4, 6), False, id="two_squares_horizontal_rejected"),
    pytest.param(sq(2, 4), False, id="two_squares_vertical_rejected"),
])
def test_king_box_pseudo_reach(to_sq, admissible):
    p = Piece(PieceType.KING, WHITE)
    assert piece_can_pseudo_reach(p, sq(4, 4), to_sq) is admissible


@pytest.mark.parametrize("color, from_sq, to_col, admissible", [
    pytest.param(WHITE, sq(WHITE_KING_HOME_ROW, KING_HOME_COL), CASTLE_TARGET_COLS[0],
                 True, id="white_queenside_from_home"),
    pytest.param(WHITE, sq(WHITE_KING_HOME_ROW, KING_HOME_COL), CASTLE_TARGET_COLS[1],
                 True, id="white_kingside_from_home"),
    pytest.param(BLACK, sq(BLACK_KING_HOME_ROW, KING_HOME_COL), CASTLE_TARGET_COLS[0],
                 True, id="black_queenside_from_home"),
    pytest.param(BLACK, sq(BLACK_KING_HOME_ROW, KING_HOME_COL), CASTLE_TARGET_COLS[1],
                 True, id="black_kingside_from_home"),
    pytest.param(WHITE, sq(6, 4), CASTLE_TARGET_COLS[1], False, id="white_kingside_off_home"),
    pytest.param(WHITE, sq(6, 4), CASTLE_TARGET_COLS[0], False, id="white_queenside_off_home"),
])
def test_king_castle_pseudo_reach(color, from_sq, to_col, admissible):
    """Castle-from is admissible only when the king sits on its home square."""
    p = Piece(PieceType.KING, color)
    to_sq = sq(from_sq.row, to_col)
    assert piece_can_pseudo_reach(p, from_sq, to_sq) is admissible


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
    import pygame as pg
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def board():
    import pygame as pg
    from chessshootout.backend.backend import Backend
    from chessshootout.frontend.board import Board
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def test_chain_rook_rejects_non_line_extension(board):
    """Rook a1->a5 (file), a5->e5 (rank, OK), then e5->d4 (diagonal, rejected)."""
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    })
    board.handle_click(Square(7, 0))
    board.handle_click(Square(3, 0))
    board.handle_click(Square(3, 0))
    board.handle_click(Square(3, 4))
    assert len(board.premoves) == 2

    board.handle_click(Square(3, 4))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 2, "diagonal extension on rook should be rejected"


def test_chain_knight_rejects_non_l_shape(board):
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 6): Piece(PieceType.KNIGHT, PieceColor.WHITE),
    })
    board.handle_click(Square(7, 6))
    board.handle_click(Square(7, 0))
    assert board.premoves == []
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 1


def test_chain_pawn_direction_correct(board):
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 0): Piece(PieceType.PAWN, PieceColor.WHITE),
    })
    board.handle_click(Square(6, 0))
    board.handle_click(Square(7, 0))
    assert board.premoves == []
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    assert len(board.premoves) == 1


def test_chain_castle_from_home_only(board):
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    board.handle_click(Square(7, 4))
    board.handle_click(Square(7, 6))
    assert len(board.premoves) == 1
    _setup(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    board.handle_click(Square(7, 4))
    board.handle_click(Square(6, 4))
    assert len(board.premoves) == 1
    board.handle_click(Square(6, 4))
    board.handle_click(Square(7, 6))
    assert len(board.premoves) == 1, "castle premove not allowed when king not on home in chain"
