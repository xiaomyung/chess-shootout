from chessshootout.backend.pieces import (
    PIECE_VALUES, PieceColor, PieceType, opponent_of,
)
from chessshootout.backend.utils import HistoryEntry


CAPTURE_ORDER = [
    PieceType.QUEEN,
    PieceType.ROOK,
    PieceType.BISHOP,
    PieceType.KNIGHT,
    PieceType.PAWN,
]


def captured_by(history: list[HistoryEntry], color: PieceColor) -> list[PieceType]:
    """
    List the pieces one side has taken, ordered the way the capture rows show
    them: queens first, pawns last. The player strips and every material
    readout are built on it, over whichever slice of history the caller passes,
    so browsing an earlier ply shows that ply's captures

    :param history: plies in play order, the whole game or a reviewed prefix
    :param color: the capturing side, not the side being captured
    :returns: types of the pieces that side took, strongest first
    """
    captured = []
    for entry in history:
        cap = entry.move.captured
        if cap is None or cap.color == color:
            continue
        if entry.move.piece.color != color:
            continue
        captured.append(cap.type)
    return sorted(captured, key=CAPTURE_ORDER.index)


def promotion_gain(history: list[HistoryEntry], color: PieceColor) -> int:
    """
    Score the material one side has won by promoting pawns, counting only what
    the new piece is worth beyond the pawn it replaced. Without it a player who
    just queened would look no richer than before on the material readout

    :param history: plies in play order, the whole game or a reviewed prefix
    :param color: side whose promotions are counted
    :returns: pawn-unit value that side gained through promotions
    """
    return sum(PIECE_VALUES[entry.move.promoted_to] - PIECE_VALUES[PieceType.PAWN]
               for entry in history
               if entry.move.promoted_to is not None and entry.move.piece.color == color)


def material_for(history: list[HistoryEntry], color: PieceColor) -> int:
    """
    Total what one side has won so far -- every piece it captured plus what its
    promotions added. This is the half figure the two sides are compared on to
    produce the advantage number

    :param history: plies in play order, the whole game or a reviewed prefix
    :param color: side being totalled
    :returns: that side's winnings in pawn units
    """
    return (sum(PIECE_VALUES[t] for t in captured_by(history, color))
            + promotion_gain(history, color))


def material_advantage(history: list[HistoryEntry], color: PieceColor) -> int:
    """
    Give the material lead one side holds, the +N badge on the player strips
    and in the end-of-game stats. Zero means level material and a negative
    value means that side is behind

    :param history: plies in play order, the whole game or a reviewed prefix
    :param color: side the lead is measured for
    :returns: pawn-unit difference between this side and its opponent
    """
    return material_for(history, color) - material_for(history, opponent_of(color))
