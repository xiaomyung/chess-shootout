from enum import Enum

from paths import PROJECT_ROOT


class PieceColor(Enum):
    WHITE = "white"
    BLACK = "black"


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
        return f"{PROJECT_ROOT}/pieces/img/{self.type.value}_{self.color.value}.png"


BACK_RANK = [
    PieceType.ROOK, PieceType.KNIGHT, PieceType.BISHOP, PieceType.QUEEN,
    PieceType.KING, PieceType.BISHOP, PieceType.KNIGHT, PieceType.ROOK,
]