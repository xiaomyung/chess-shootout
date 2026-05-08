from dataclasses import dataclass
from typing import Optional

from pieces import Piece, PieceType


@dataclass(frozen=True)
class Square:
    row: int
    col: int


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