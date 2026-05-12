from backend.pieces import (
    CASTLE_TARGET_COLS,
    KING_HOME_COL, KING_OFFSETS, KNIGHT_OFFSETS, PieceType,
    king_home_row, pawn_forward,
    pawn_start_row,
)
from backend.utils import on_board


def piece_can_pseudo_reach(piece, from_sq, to_sq):
    if from_sq == to_sq:
        return False
    if not on_board(to_sq) or not on_board(from_sq):
        return False
    if piece.type == PieceType.PAWN:
        return _pawn_can_reach(piece.color, from_sq, to_sq)
    if piece.type == PieceType.KNIGHT:
        return _knight_can_reach(from_sq, to_sq)
    if piece.type == PieceType.BISHOP:
        return _bishop_can_reach(from_sq, to_sq)
    if piece.type == PieceType.ROOK:
        return _rook_can_reach(from_sq, to_sq)
    if piece.type == PieceType.QUEEN:
        return _bishop_can_reach(from_sq, to_sq) or _rook_can_reach(from_sq, to_sq)
    if piece.type == PieceType.KING:
        return _king_can_reach(piece.color, from_sq, to_sq)
    return False


def _pawn_can_reach(color, from_sq, to_sq):
    forward = pawn_forward(color)
    drow = to_sq.row - from_sq.row
    dcol = abs(to_sq.col - from_sq.col)
    if dcol == 0:
        if drow == forward:
            return True
        if drow == 2 * forward:
            return from_sq.row == pawn_start_row(color)
        return False
    if dcol == 1 and drow == forward:
        return True
    return False


def _knight_can_reach(from_sq, to_sq):
    delta = (to_sq.row - from_sq.row, to_sq.col - from_sq.col)
    return delta in KNIGHT_OFFSETS


def _bishop_can_reach(from_sq, to_sq):
    drow = to_sq.row - from_sq.row
    dcol = to_sq.col - from_sq.col
    return abs(drow) == abs(dcol) and drow != 0


def _rook_can_reach(from_sq, to_sq):
    return (from_sq.row == to_sq.row) != (from_sq.col == to_sq.col)


def _king_can_reach(color, from_sq, to_sq):
    delta = (to_sq.row - from_sq.row, to_sq.col - from_sq.col)
    if delta in KING_OFFSETS:
        return True
    home_row = king_home_row(color)
    if from_sq.row == home_row and from_sq.col == KING_HOME_COL:
        if to_sq.row == home_row and to_sq.col in CASTLE_TARGET_COLS:
            return True
    return False
