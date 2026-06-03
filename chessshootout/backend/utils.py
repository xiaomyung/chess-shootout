from dataclasses import dataclass
from typing import Optional

from chessshootout.backend.pieces import Piece, PieceType


BOARD_SIZE = 8

PROMO_LETTER_BY_TYPE = {
    PieceType.QUEEN: "q",
    PieceType.ROOK: "r",
    PieceType.BISHOP: "b",
    PieceType.KNIGHT: "n",
}
PROMO_TYPE_BY_LETTER = {v: k for k, v in PROMO_LETTER_BY_TYPE.items()}


@dataclass(frozen=True)
class Square:
    row: int
    col: int


def on_board(sq):
    return 0 <= sq.row < BOARD_SIZE and 0 <= sq.col < BOARD_SIZE


def coord_from_square(sq):
    return chr(ord("a") + sq.col) + str(BOARD_SIZE - sq.row)


def square_from_coord(coord):
    if len(coord) != 2:
        raise ValueError(f"invalid coord: {coord!r}")
    file_ch, rank_ch = coord[0], coord[1]
    col = ord(file_ch) - ord("a")
    row = BOARD_SIZE - int(rank_ch)
    if not (0 <= col < BOARD_SIZE and 0 <= row < BOARD_SIZE):
        raise ValueError(f"out-of-board coord: {coord!r}")
    return Square(row, col)


@dataclass(frozen=True)
class Move:
    from_sq: Square
    to_sq: Square
    piece: Piece
    captured: Optional[Piece] = None
    is_castle: bool = False
    is_en_passant: bool = False
    promoted_to: Optional[PieceType] = None


@dataclass
class MoveResult:
    legal: bool
    captured: Optional[Piece] = None
    is_check: bool = False
    is_checkmate: bool = False
    is_stalemate: bool = False
    promotion_required: bool = False


@dataclass
class HistoryEntry:
    move: Move
    prev_castling_rights: tuple
    prev_en_passant_target: Optional[Square]
    prev_halfmove_clock: int
    position_key_added: Optional[tuple]
    gives_check: bool = False
    gives_checkmate: bool = False
    san: str = ""
    prev_clock_snapshot: Optional[tuple] = None
