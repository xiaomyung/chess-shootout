from backend.pieces import PieceColor, PieceType


KNIGHT_OFFSETS = [
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
]

KING_OFFSETS = [
    (-1, -1), (-1, 0), (-1, 1), (0, -1),
    (0, 1), (1, -1), (1, 0), (1, 1),
]

WHITE_KING_HOME_ROW = 7
BLACK_KING_HOME_ROW = 0
KING_HOME_COL = 4
CASTLE_TARGET_COLS = (2, 6)
WHITE_PAWN_START_ROW = 6
BLACK_PAWN_START_ROW = 1
BOARD_SIZE = 8


def piece_can_pseudo_reach(piece, from_sq, to_sq):
    if from_sq == to_sq:
        return False
    if not _on_board(to_sq) or not _on_board(from_sq):
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


def _on_board(sq):
    return 0 <= sq.row < BOARD_SIZE and 0 <= sq.col < BOARD_SIZE


def _pawn_can_reach(color, from_sq, to_sq):
    forward = -1 if color == PieceColor.WHITE else 1
    drow = to_sq.row - from_sq.row
    dcol = abs(to_sq.col - from_sq.col)
    if dcol == 0:
        if drow == forward:
            return True
        if drow == 2 * forward:
            start_row = (WHITE_PAWN_START_ROW if color == PieceColor.WHITE
                         else BLACK_PAWN_START_ROW)
            return from_sq.row == start_row
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
    home_row = (WHITE_KING_HOME_ROW if color == PieceColor.WHITE
                else BLACK_KING_HOME_ROW)
    if from_sq.row == home_row and from_sq.col == KING_HOME_COL:
        if to_sq.row == home_row and to_sq.col in CASTLE_TARGET_COLS:
            return True
    return False
