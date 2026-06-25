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


def material_advantage(history, color):
    own = sum(PIECE_VALUES[t] for t in captured_by(history, color))
    opp = sum(PIECE_VALUES[t] for t in captured_by(history, opponent_of(color)))
    return own - opp
