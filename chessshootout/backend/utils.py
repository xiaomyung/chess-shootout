from dataclasses import dataclass

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
    """
    One square of the board in the engine's own coordinate space, where row 0
    is Black's back rank and column 0 is the a-file. Frozen and hashable, so
    squares are used directly as dict keys and set members across the game
    """

    row: int
    col: int


def on_board(sq: Square) -> bool:
    """
    Tell whether a square lies inside the 8x8 board. This is the bounds check
    every move generator runs before it reads a target cell, so generated
    offsets can safely walk off the edge

    :param sq: candidate square, possibly with negative or oversized indices
    :returns: True when the square can be indexed on the board
    """
    return 0 <= sq.row < BOARD_SIZE and 0 <= sq.col < BOARD_SIZE


def coord_from_square(sq: Square) -> str:
    """
    Render a square as its algebraic name (e4, a1), the spelling used in SAN,
    FEN and every player-facing label. Column 0 becomes file a and row 0
    becomes rank 8

    :param sq: square to name; expected to be on the board already
    :returns: two-character file-plus-rank string
    """
    return chr(ord("a") + sq.col) + str(BOARD_SIZE - sq.row)


def square_from_coord(coord: str) -> Square:
    """
    Parse an algebraic square name back into engine coordinates, the inverse
    of coord_from_square used when reading FEN and stored squares. Anything
    that is not a real board square is rejected rather than clamped

    :param coord: two-character file-plus-rank string, lowercase file letter
    :returns: the matching board square
    """
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
    """
    One ply as the engine records it: which piece went where, what it took and
    which special rule applied. Frozen on purpose -- a promotion builds a
    fresh Move rather than mutating the one already in the history
    """

    from_sq: Square
    to_sq: Square
    piece: Piece
    captured: Piece | None = None
    is_castle: bool = False
    is_en_passant: bool = False
    promoted_to: PieceType | None = None


@dataclass
class MoveResult:
    """
    The engine's answer to a move attempt, handed to the UI and the server so
    they know whether the ply landed and what it did to the position. When
    promotion_required is set the ply is only half applied until promote()
    picks a piece
    """

    legal: bool
    captured: Piece | None = None
    is_check: bool = False
    is_checkmate: bool = False
    is_stalemate: bool = False
    promotion_required: bool = False


@dataclass
class HistoryEntry:
    """
    One entry of the move history: the move itself, the pre-ply state undo
    needs to rewind (castling rights, en-passant target, halfmove clock, clock
    snapshot) and the SAN built at move time. A position_key_added of None
    marks a promotion that has not been completed yet
    """

    move: Move
    prev_castling_rights: tuple[bool, ...]
    prev_en_passant_target: Square | None
    prev_halfmove_clock: int
    position_key_added: tuple | None
    gives_check: bool = False
    gives_checkmate: bool = False
    san: str = ""
    prev_clock_snapshot: tuple | None = None
