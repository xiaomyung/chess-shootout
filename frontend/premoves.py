from dataclasses import dataclass

from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square


@dataclass(frozen=True)
class Premove:
    from_sq: Square
    to_sq: Square
    piece: Piece


def is_premove_shape_valid(piece, from_sq, to_sq):
    if from_sq == to_sq:
        return False
    dr = to_sq.row - from_sq.row
    dc = to_sq.col - from_sq.col
    pt = piece.type

    if pt == PieceType.PAWN:
        direction = -1 if piece.color == PieceColor.WHITE else 1
        start_row = 6 if piece.color == PieceColor.WHITE else 1
        if dc == 0 and dr == direction:
            return True
        if dc == 0 and dr == 2 * direction and from_sq.row == start_row:
            return True
        if abs(dc) == 1 and dr == direction:
            return True
        return False

    if pt == PieceType.KNIGHT:
        return {abs(dr), abs(dc)} == {1, 2}

    if pt == PieceType.BISHOP:
        return abs(dr) == abs(dc) and dr != 0

    if pt == PieceType.ROOK:
        return (dr == 0) != (dc == 0)

    if pt == PieceType.QUEEN:
        if abs(dr) == abs(dc) and dr != 0:
            return True
        return (dr == 0) != (dc == 0)

    if pt == PieceType.KING:
        if max(abs(dr), abs(dc)) == 1:
            return True
        home_row = 7 if piece.color == PieceColor.WHITE else 0
        if from_sq == Square(home_row, 4) and dr == 0 and abs(dc) == 2:
            return True
        return False

    return False


def speculative_board(backend, queue):
    grid = [row[:] for row in backend.state]
    for pm in queue:
        grid[pm.to_sq.row][pm.to_sq.col] = grid[pm.from_sq.row][pm.from_sq.col]
        grid[pm.from_sq.row][pm.from_sq.col] = None
    return grid
