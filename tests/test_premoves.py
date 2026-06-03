"""speculative_board projects a premove queue onto a copy of the live board.

Invariant: each premove is applied to the *current grid tip*, not the original
board, and the moved occupant is read from the grid (not from Premove.piece).
This is the lax "bouncing chain" rule — a chain may relay through the same
piece's freshly-vacated square (e.g. e2->e3 then e3->e4). The source board is
never mutated.
"""

import pytest

from backend.utils import Square
from domain.premoves import Premove, speculative_board

from tests.helpers import (
    BLACK, WHITE, K, P,
    make_backend, piece, sq,
)


THREE_PIECE = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
               sq(6, 0): piece(P, WHITE)}
FOUR_PIECE = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
              sq(6, 0): piece(P, WHITE), sq(6, 7): piece(P, WHITE)}


def test_speculative_empty_queue_leaves_board_unchanged():
    bk = make_backend(THREE_PIECE)
    grid = speculative_board(bk, [])
    for r in range(8):
        for c in range(8):
            assert grid[r][c] == bk.state[r][c]


def test_speculative_does_not_mutate_source_board():
    bk = make_backend(THREE_PIECE)
    pawn = bk.state[6][0]
    speculative_board(bk, [Premove(Square(6, 0), Square(4, 0), pawn)])
    assert bk.state[6][0] is pawn
    assert bk.state[4][0] is None


@pytest.mark.parametrize(
    "piece_map, steps, expected_empty, expected_occupied",
    [
        pytest.param(
            THREE_PIECE,
            [((6, 0), (4, 0))],
            [(6, 0)],
            [((4, 0), (6, 0))],
            id="single_premove_moves_piece",
        ),
        pytest.param(
            THREE_PIECE,
            [((6, 0), (5, 0)), ((5, 0), (4, 0))],
            [(6, 0), (5, 0)],
            [((4, 0), (6, 0))],
            id="chain_relays_through_same_piece_tip",
        ),
        pytest.param(
            FOUR_PIECE,
            [((6, 0), (4, 0)), ((6, 7), (4, 7))],
            [(6, 0), (6, 7)],
            [((4, 0), (6, 0)), ((4, 7), (6, 7))],
            id="two_independent_pieces_both_move",
        ),
    ],
)
def test_speculative_applies_queue(piece_map, steps, expected_empty, expected_occupied):
    bk = make_backend(piece_map)
    queue = [
        Premove(Square(*frm), Square(*to), bk.state[frm[0]][frm[1]])
        for frm, to in steps
    ]
    grid = speculative_board(bk, queue)
    for r, c in expected_empty:
        assert grid[r][c] is None
    for (dr, dc), (sr, sc) in expected_occupied:
        assert grid[dr][dc] is bk.state[sr][sc]
