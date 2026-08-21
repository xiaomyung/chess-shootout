from itertools import product

from chessshootout.backend.pieces import (
    CASTLE_TARGET_COLS,
    KING_HOME_COL, KING_OFFSETS, KNIGHT_OFFSETS, Piece, PieceColor, PieceType,
    king_home_row, pawn_forward,
    pawn_start_row,
)
from chessshootout.backend.utils import on_board, Square, BOARD_SIZE

_SLIDERS = (PieceType.BISHOP, PieceType.ROOK, PieceType.QUEEN)


def piece_can_pseudo_reach(piece: Piece, from_sq: Square, to_sq: Square) -> bool:
    """
    Say whether a piece could move between two squares by its own movement rule
    alone, with no regard for what occupies the board, for checks or for whose
    turn it is. This is the lax test premoves are validated with: a queued move
    only has to be shaped like a real move, because the position it will
    eventually land in is not known yet

    :param piece: piece being moved; its type and color choose the rule
    :param from_sq: square the piece starts on
    :param to_sq: square it is aimed at; a move to its own square never counts
    :returns: True when the shape of the move suits this piece
    """
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


def _pawn_can_reach(color: PieceColor, from_sq: Square, to_sq: Square) -> bool:
    """
    Apply the pawn's movement shape: one square forward, two from its own
    starting rank, or one square diagonally. The diagonal is admitted with
    nothing to capture on it, because a premoved pawn capture is queued before
    the opponent has put anything there

    :param color: side the pawn belongs to, which sets its marching direction
    :param from_sq: square the pawn starts on
    :param to_sq: square it is aimed at
    :returns: True when a pawn of this color could move that way
    """
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


def _knight_can_reach(from_sq: Square, to_sq: Square) -> bool:
    """
    Apply the knight's movement shape, which is simply whether the step between
    the two squares is one of the eight L-jumps

    :param from_sq: square the knight starts on
    :param to_sq: square it is aimed at
    :returns: True when the offset between the squares is a knight jump
    """
    delta = (to_sq.row - from_sq.row, to_sq.col - from_sq.col)
    return delta in KNIGHT_OFFSETS


def _bishop_can_reach(from_sq: Square, to_sq: Square) -> bool:
    """
    Apply the bishop's movement shape: any distance along a diagonal. Pieces
    standing in the way are ignored, since a premove may well be queued through
    a square that clears before its turn comes

    :param from_sq: square the bishop starts on
    :param to_sq: square it is aimed at
    :returns: True when the two squares lie on a common diagonal
    """
    drow = to_sq.row - from_sq.row
    dcol = to_sq.col - from_sq.col
    return abs(drow) == abs(dcol) and drow != 0


def _rook_can_reach(from_sq: Square, to_sq: Square) -> bool:
    """
    Apply the rook's movement shape: any distance along a rank or a file, again
    without caring what stands between the two squares

    :param from_sq: square the rook starts on
    :param to_sq: square it is aimed at
    :returns: True when the squares share exactly one of their row and column
    """
    return (from_sq.row == to_sq.row) != (from_sq.col == to_sq.col)


def _king_can_reach(color: PieceColor, from_sq: Square, to_sq: Square) -> bool:
    """
    Apply the king's movement shape: one square in any direction, plus the two
    castling destinations when the king still sits on its home square. Castling
    is admitted here so that a castle can be premoved like any other move

    :param color: side the king belongs to, which picks its home rank
    :param from_sq: square the king starts on
    :param to_sq: square it is aimed at
    :returns: True when the king could move that way, castling included
    """
    delta = (to_sq.row - from_sq.row, to_sq.col - from_sq.col)
    if delta in KING_OFFSETS:
        return True
    home_row = king_home_row(color)
    if from_sq.row == home_row and from_sq.col == KING_HOME_COL:
        if to_sq.row == home_row and to_sq.col in CASTLE_TARGET_COLS:
            return True
    return False


def king_square(state: list[list[Piece | None]], color: PieceColor) -> Square | None:
    """
    Find where one side's king stands on a board grid. It anchors the in-check
    highlight and the shot effects that aim at a king, and it reads a plain grid
    rather than the live engine, so it works on a reviewed past position too

    :param state: 8x8 grid of pieces, row 0 being Black's back rank
    :param color: side whose king is wanted
    :returns: the king's square, or None when that king is not on the grid
    """
    return piece_square(state, PieceType.KING, color)


def piece_square(state: list[list[Piece | None]], ptype: PieceType,
                 color: PieceColor) -> Square | None:
    """
    Find one piece of a given kind and color on a board grid, scanning row by
    row from Black's back rank and answering with the first hit. The shot
    effects use it to pick something worth aiming at, so which duplicate wins
    only has to be stable, not meaningful

    :param state: 8x8 grid of pieces, row 0 being Black's back rank
    :param ptype: kind of piece to look for
    :param color: side that owns it
    :returns: first matching square in scan order, or None when there is none
    """
    for row, col in product(range(BOARD_SIZE), repeat=2):
        piece = state[row][col]
        if piece is not None and piece.type == ptype and piece.color == color:
            return Square(row, col)
    return None


def checking_square(state: list[list[Piece | None]], king_sq: Square,
                    by_color: PieceColor) -> Square | None:
    """
    Find the piece that is giving check, which is what lets the board draw the
    threat line from the attacker to the king. A sliding piece only counts when
    the squares between it and the king are empty, and in a double check the
    first attacker in scan order is the one reported

    :param state: 8x8 grid of pieces, row 0 being Black's back rank
    :param king_sq: square of the king that is in check
    :param by_color: side delivering the check
    :returns: the checking piece's square, or None when nothing checks
    """
    for row, col in product(range(BOARD_SIZE), repeat=2):
        piece = state[row][col]
        if piece is None or piece.color != by_color:
            continue
        sq = Square(row, col)
        if not piece_can_pseudo_reach(piece, sq, king_sq):
            continue
        if piece.type in _SLIDERS and not _segment_empty(state, sq, king_sq):
            continue
        return sq
    return None


def _segment_empty(state: list[list[Piece | None]], a: Square, b: Square) -> bool:
    """
    Tell whether every square strictly between two squares is empty, the
    blocking test a sliding checker has to pass. Both ends are excluded, and the
    two squares are assumed to already share a rank, a file or a diagonal

    :param state: 8x8 grid of pieces, row 0 being Black's back rank
    :param a: one end of the segment, excluded from the walk
    :param b: the other end, excluded from the walk
    :returns: True when nothing stands between the two squares
    """
    dr = (b.row > a.row) - (b.row < a.row)
    dc = (b.col > a.col) - (b.col < a.col)
    r, c = a.row + dr, a.col + dc
    while (r, c) != (b.row, b.col):
        if state[r][c] is not None:
            return False
        r, c = r + dr, c + dc
    return True
