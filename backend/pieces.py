import os
from enum import Enum

from backend.paths import PIECES_IMG_DIR


class PieceColor(Enum):
    WHITE = "white"
    BLACK = "black"


def opponent_of(color):
    return PieceColor.BLACK if color == PieceColor.WHITE else PieceColor.WHITE


class PieceType(Enum):
    PAWN = "pawn"
    KNIGHT = "knight"
    BISHOP = "bishop"
    ROOK = "rook"
    QUEEN = "queen"
    KING = "king"


class Piece:

    def __init__(self, piece_type: PieceType, piece_color: PieceColor):
        self.type = piece_type
        self.color = piece_color

    @property
    def img_path(self):
        return os.path.join(PIECES_IMG_DIR, f"{self.type.value}_{self.color.value}.png")


BACK_RANK = [
    PieceType.ROOK, PieceType.KNIGHT, PieceType.BISHOP, PieceType.QUEEN,
    PieceType.KING, PieceType.BISHOP, PieceType.KNIGHT, PieceType.ROOK,
]


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


def king_home_row(color):
    return WHITE_KING_HOME_ROW if color == PieceColor.WHITE else BLACK_KING_HOME_ROW


def pawn_start_row(color):
    return WHITE_PAWN_START_ROW if color == PieceColor.WHITE else BLACK_PAWN_START_ROW


def pawn_forward(color):
    return -1 if color == PieceColor.WHITE else 1