import pytest

from backend.backend import Backend
from backend.utils import Square
from backend.pieces import PieceType


def perft(backend, depth):
    """Count leaf nodes; each pawn promotion expands to 4 moves (Q, R, B, N)."""
    if depth == 0:
        return 1
    nodes = 0
    color = backend.turn
    own_squares = [
        Square(r, c)
        for r in range(8) for c in range(8)
        if backend.state[r][c] is not None and backend.state[r][c].color == color
    ]
    for from_sq in own_squares:
        for to_sq in backend.legal_moves_from(from_sq):
            piece = backend.state[from_sq.row][from_sq.col]
            if piece.type == PieceType.PAWN and to_sq.row in (0, 7):
                for promo in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
                    result = backend.try_move(from_sq, to_sq)
                    assert result.legal and result.promotion_required
                    backend.promote(to_sq, promo)
                    nodes += perft(backend, depth - 1)
                    backend.undo()
            else:
                result = backend.try_move(from_sq, to_sq)
                assert result.legal
                nodes += perft(backend, depth - 1)
                backend.undo()
    return nodes


@pytest.mark.parametrize(
    "depth, expected",
    [
        pytest.param(1, 20, id="depth_1"),
        pytest.param(2, 400, id="depth_2"),
        pytest.param(3, 8902, id="depth_3"),
    ],
)
def test_perft_initial(depth, expected):
    bk = Backend()
    bk.new_game()
    assert perft(bk, depth) == expected
