from backend.backend import Backend
from backend.utils import Square
from pieces.pieces import PieceColor, PieceType


def perft(backend, depth):
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
                # Each promotion counts as 4 distinct moves (Q, R, B, N).
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


def test_perft_initial_depth_1():
    bk = Backend()
    bk.new_game()
    assert perft(bk, 1) == 20


def test_perft_initial_depth_2():
    bk = Backend()
    bk.new_game()
    assert perft(bk, 2) == 400


def test_perft_initial_depth_3():
    bk = Backend()
    bk.new_game()
    assert perft(bk, 3) == 8902
