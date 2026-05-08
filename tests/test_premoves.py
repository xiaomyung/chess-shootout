from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.premoves import Premove, speculative_board

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


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
