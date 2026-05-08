from backend.pieces import PieceColor, PieceType


PIECE_VALUES = {
    PieceType.QUEEN: 9,
    PieceType.ROOK: 5,
    PieceType.BISHOP: 3,
    PieceType.KNIGHT: 3,
    PieceType.PAWN: 1,
    PieceType.KING: 0,
}

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


def material_advantage(history, color):
    own = sum(PIECE_VALUES[t] for t in captured_by(history, color))
    other = PieceColor.BLACK if color == PieceColor.WHITE else PieceColor.WHITE
    opp = sum(PIECE_VALUES[t] for t in captured_by(history, other))
    return own - opp
