from enum import Enum


class PieceColor(Enum):
    """
    The two sides of a chess game. The string values are the spelling used on
    the wire, in saved PGN and in asset filenames, so they are stable names
    rather than display text
    """

    WHITE = "white"
    BLACK = "black"


def opponent_of(color: PieceColor) -> PieceColor:
    """
    Give the other side of the board, the flip behind every turn switch,
    check test and castling test in the engine

    :param color: side to flip
    :returns: the opposing color
    """
    return PieceColor.BLACK if color == PieceColor.WHITE else PieceColor.WHITE


class PieceType(Enum):
    """
    The six kinds of chess piece. The lowercase string values double as asset
    filename stems and as the keys the sound and gun-effect tables are looked
    up by, so they are not free-form labels
    """

    PAWN = "pawn"
    KNIGHT = "knight"
    BISHOP = "bishop"
    ROOK = "rook"
    QUEEN = "queen"
    KING = "king"


class Piece:
    """
    A single piece on the board: what it is and whose it is. The same instance
    is shared by reference between the board array and the move history, so it
    is created fresh rather than mutated when a pawn promotes
    """

    def __init__(self, piece_type: PieceType, piece_color: PieceColor) -> None:
        """
        Build one piece, done when a game is set up, when a position is loaded
        from FEN and when a pawn promotes

        :param piece_type: which of the six kinds this piece is
        :param piece_color: side that owns it
        """
        self.type = piece_type
        self.color = piece_color


BACK_RANK = [
    PieceType.ROOK, PieceType.KNIGHT, PieceType.BISHOP, PieceType.QUEEN,
    PieceType.KING, PieceType.BISHOP, PieceType.KNIGHT, PieceType.ROOK,
]

PIECE_VALUES = {
    PieceType.PAWN: 1,
    PieceType.KNIGHT: 3,
    PieceType.BISHOP: 3,
    PieceType.ROOK: 5,
    PieceType.QUEEN: 9,
    PieceType.KING: 0,
}


KNIGHT_OFFSETS = [
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
]

KING_OFFSETS = [
    (-1, -1), (-1, 0), (-1, 1), (0, -1),
    (0, 1), (1, -1), (1, 0), (1, 1),
]

BISHOP_DIRECTIONS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
ROOK_DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
QUEEN_DIRECTIONS = BISHOP_DIRECTIONS + ROOK_DIRECTIONS

WHITE_KING_HOME_ROW = 7
BLACK_KING_HOME_ROW = 0
KING_HOME_COL = 4
CASTLE_TARGET_COLS = (2, 6)
WHITE_PAWN_START_ROW = 6
BLACK_PAWN_START_ROW = 1


def king_home_row(color: PieceColor) -> int:
    """
    Give the rank a king starts on, the anchor castling uses to recognise a
    king that is still on its original square

    :param color: side whose home rank is wanted
    :returns: board row index, 7 for White and 0 for Black
    """
    return WHITE_KING_HOME_ROW if color == PieceColor.WHITE else BLACK_KING_HOME_ROW


def pawn_start_row(color: PieceColor) -> int:
    """
    Give the rank that side's pawns start on, which is what makes the
    two-square opening push legal for a pawn that has not moved

    :param color: side whose pawn rank is wanted
    :returns: board row index, 6 for White and 1 for Black
    """
    return WHITE_PAWN_START_ROW if color == PieceColor.WHITE else BLACK_PAWN_START_ROW


def pawn_forward(color: PieceColor) -> int:
    """
    Give the direction a pawn of this color advances in, since board rows are
    numbered from Black's side down. Pushes, diagonal captures and pawn attack
    tests are all built on it

    :param color: side whose marching direction is wanted
    :returns: row delta of one step forward, -1 for White and 1 for Black
    """
    return -1 if color == PieceColor.WHITE else 1
