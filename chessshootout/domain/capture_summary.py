from chessshootout.backend.pieces import PIECE_VALUES, PieceType, opponent_of


CAPTURE_ORDER = [
    PieceType.QUEEN,
    PieceType.ROOK,
    PieceType.BISHOP,
    PieceType.KNIGHT,
    PieceType.PAWN,
]


def captured_by(history, color):
    captured = []
    for entry in history:
        cap = entry.move.captured
        if cap is None or cap.color == color:
            continue
        if entry.move.piece.color != color:
            continue
        captured.append(cap.type)
    return sorted(captured, key=CAPTURE_ORDER.index)


def promotion_gain(history, color):
    return sum(PIECE_VALUES[entry.move.promoted_to] - PIECE_VALUES[PieceType.PAWN]
               for entry in history
               if entry.move.promoted_to is not None and entry.move.piece.color == color)


def material_for(history, color):
    return (sum(PIECE_VALUES[t] for t in captured_by(history, color))
            + promotion_gain(history, color))


def material_advantage(history, color):
    return material_for(history, color) - material_for(history, opponent_of(color))
