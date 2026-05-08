import pytest

from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.premoves import Premove, is_premove_shape_valid, speculative_board

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def whitepiece(pt):
    return Piece(pt, PieceColor.WHITE)


def blackpiece(pt):
    return Piece(pt, PieceColor.BLACK)


# ---------- Pawn shape ----------

def test_white_pawn_forward_one_valid():
    assert is_premove_shape_valid(whitepiece(P), Square(6, 4), Square(5, 4))


def test_white_pawn_forward_two_from_start_row_valid():
    assert is_premove_shape_valid(whitepiece(P), Square(6, 4), Square(4, 4))


def test_white_pawn_forward_two_not_from_start_row_invalid():
    assert not is_premove_shape_valid(whitepiece(P), Square(5, 4), Square(3, 4))


def test_white_pawn_diagonal_capture_valid():
    assert is_premove_shape_valid(whitepiece(P), Square(6, 4), Square(5, 5))
    assert is_premove_shape_valid(whitepiece(P), Square(6, 4), Square(5, 3))


def test_white_pawn_backward_invalid():
    assert not is_premove_shape_valid(whitepiece(P), Square(4, 4), Square(5, 4))


def test_white_pawn_sideways_invalid():
    assert not is_premove_shape_valid(whitepiece(P), Square(6, 4), Square(6, 5))


def test_white_pawn_l_shape_invalid():
    assert not is_premove_shape_valid(whitepiece(P), Square(6, 4), Square(4, 3))


def test_black_pawn_forward_one_valid():
    assert is_premove_shape_valid(blackpiece(P), Square(1, 4), Square(2, 4))


def test_black_pawn_forward_two_from_start_row_valid():
    assert is_premove_shape_valid(blackpiece(P), Square(1, 4), Square(3, 4))


def test_black_pawn_forward_two_not_from_start_row_invalid():
    assert not is_premove_shape_valid(blackpiece(P), Square(2, 4), Square(4, 4))


def test_black_pawn_diagonal_capture_valid():
    assert is_premove_shape_valid(blackpiece(P), Square(1, 4), Square(2, 5))
    assert is_premove_shape_valid(blackpiece(P), Square(1, 4), Square(2, 3))


def test_black_pawn_backward_invalid():
    assert not is_premove_shape_valid(blackpiece(P), Square(3, 4), Square(2, 4))


# ---------- Knight shape ----------

@pytest.mark.parametrize("dr,dc", [
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
])
def test_knight_l_shapes_valid(dr, dc):
    assert is_premove_shape_valid(whitepiece(N), Square(4, 4), Square(4 + dr, 4 + dc))


def test_knight_non_l_invalid():
    assert not is_premove_shape_valid(whitepiece(N), Square(4, 4), Square(4, 5))
    assert not is_premove_shape_valid(whitepiece(N), Square(4, 4), Square(5, 5))
    assert not is_premove_shape_valid(whitepiece(N), Square(4, 4), Square(2, 4))


# ---------- Bishop shape ----------

def test_bishop_diagonal_valid():
    assert is_premove_shape_valid(whitepiece(B), Square(4, 4), Square(7, 7))
    assert is_premove_shape_valid(whitepiece(B), Square(4, 4), Square(0, 0))
    assert is_premove_shape_valid(whitepiece(B), Square(4, 4), Square(7, 1))
    assert is_premove_shape_valid(whitepiece(B), Square(4, 4), Square(1, 7))


def test_bishop_straight_invalid():
    assert not is_premove_shape_valid(whitepiece(B), Square(4, 4), Square(4, 7))
    assert not is_premove_shape_valid(whitepiece(B), Square(4, 4), Square(0, 4))


# ---------- Rook shape ----------

def test_rook_rank_or_file_valid():
    assert is_premove_shape_valid(whitepiece(R), Square(4, 4), Square(4, 0))
    assert is_premove_shape_valid(whitepiece(R), Square(4, 4), Square(4, 7))
    assert is_premove_shape_valid(whitepiece(R), Square(4, 4), Square(0, 4))
    assert is_premove_shape_valid(whitepiece(R), Square(4, 4), Square(7, 4))


def test_rook_diagonal_invalid():
    assert not is_premove_shape_valid(whitepiece(R), Square(4, 4), Square(7, 7))


# ---------- Queen shape ----------

def test_queen_rank_file_diagonal_valid():
    assert is_premove_shape_valid(whitepiece(Q), Square(4, 4), Square(4, 0))
    assert is_premove_shape_valid(whitepiece(Q), Square(4, 4), Square(0, 4))
    assert is_premove_shape_valid(whitepiece(Q), Square(4, 4), Square(7, 7))
    assert is_premove_shape_valid(whitepiece(Q), Square(4, 4), Square(1, 7))


def test_queen_l_shape_invalid():
    assert not is_premove_shape_valid(whitepiece(Q), Square(4, 4), Square(2, 3))


# ---------- King shape ----------

@pytest.mark.parametrize("dr,dc", [
    (-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1),
])
def test_king_one_square_valid(dr, dc):
    assert is_premove_shape_valid(whitepiece(K), Square(4, 4), Square(4 + dr, 4 + dc))


def test_king_castle_kingside_valid():
    assert is_premove_shape_valid(whitepiece(K), Square(7, 4), Square(7, 6))
    assert is_premove_shape_valid(blackpiece(K), Square(0, 4), Square(0, 6))


def test_king_castle_queenside_valid():
    assert is_premove_shape_valid(whitepiece(K), Square(7, 4), Square(7, 2))
    assert is_premove_shape_valid(blackpiece(K), Square(0, 4), Square(0, 2))


def test_king_two_squares_not_castle_invalid():
    # Two squares from non-home square = invalid even for king.
    assert not is_premove_shape_valid(whitepiece(K), Square(5, 4), Square(5, 6))


def test_king_three_squares_invalid():
    assert not is_premove_shape_valid(whitepiece(K), Square(4, 4), Square(4, 7))


# ---------- Same-square ----------

@pytest.mark.parametrize("pt", [P, N, B, R, Q, K])
def test_same_square_invalid(pt):
    assert not is_premove_shape_valid(whitepiece(pt), Square(4, 4), Square(4, 4))


# ---------- speculative_board ----------

def test_speculative_empty_queue_returns_unchanged():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
                       sq(6, 0): piece(P, WHITE)})
    grid = speculative_board(bk, [])
    for r in range(8):
        for c in range(8):
            assert grid[r][c] == bk.state[r][c]


def test_speculative_one_premove_moves_piece():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
                       sq(6, 0): piece(P, WHITE)})
    pawn = bk.state[6][0]
    pm = Premove(Square(6, 0), Square(4, 0), pawn)
    grid = speculative_board(bk, [pm])
    assert grid[6][0] is None
    assert grid[4][0] is pawn


def test_speculative_chained_premoves_on_same_piece():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
                       sq(6, 0): piece(P, WHITE)})
    pawn = bk.state[6][0]
    pm1 = Premove(Square(6, 0), Square(5, 0), pawn)
    pm2 = Premove(Square(5, 0), Square(4, 0), pawn)
    grid = speculative_board(bk, [pm1, pm2])
    assert grid[6][0] is None
    assert grid[5][0] is None
    assert grid[4][0] is pawn


def test_speculative_chained_independent_pieces():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
                       sq(6, 0): piece(P, WHITE), sq(6, 7): piece(P, WHITE)})
    p1 = bk.state[6][0]
    p2 = bk.state[6][7]
    pms = [Premove(Square(6, 0), Square(4, 0), p1),
           Premove(Square(6, 7), Square(4, 7), p2)]
    grid = speculative_board(bk, pms)
    assert grid[6][0] is None and grid[4][0] is p1
    assert grid[6][7] is None and grid[4][7] is p2
