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