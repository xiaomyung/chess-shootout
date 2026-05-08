from collections import Counter

from backend.backend import Backend, CASTLING_KEYS, SAN_FILES
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square


PIECE_TO_FEN = {
    PieceType.KING: "k",
    PieceType.QUEEN: "q",
    PieceType.ROOK: "r",
    PieceType.BISHOP: "b",
    PieceType.KNIGHT: "n",
    PieceType.PAWN: "p",
}

FEN_TO_PIECE = {v: k for k, v in PIECE_TO_FEN.items()}

CASTLING_FEN_CHARS = (("WK", "K"), ("WQ", "Q"), ("BK", "k"), ("BQ", "q"))


def export_fen(backend):
    placement = "/".join(_rank_to_fen(backend, row) for row in range(Backend.SIZE))
    turn = "w" if backend.turn == PieceColor.WHITE else "b"
    rights = _castling_rights_to_fen(backend.castling_rights)
    ep = _square_to_algebraic(backend.en_passant_target)
    halfmove = backend.halfmove_clock
    fullmove = 1 + len(backend.move_history) // 2
    return f"{placement} {turn} {rights} {ep} {halfmove} {fullmove}"


def apply_fen(backend, fen):
    parts = fen.strip().split()
    if len(parts) < 4:
        raise ValueError(f"FEN must have at least 4 fields: {fen!r}")
    placement = parts[0]
    turn = parts[1]
    castling = parts[2]
    ep = parts[3]
    halfmove = int(parts[4]) if len(parts) >= 5 else 0

    state = _parse_placement(placement)
    backend.state = state
    backend.turn = PieceColor.WHITE if turn == "w" else PieceColor.BLACK
    backend.castling_rights = _parse_castling(castling)
    backend.en_passant_target = _parse_ep(ep)
    backend.halfmove_clock = halfmove
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1


def _rank_to_fen(backend, row):
    out = []
    empty = 0
    for col in range(Backend.SIZE):
        piece = backend.state[row][col]
        if piece is None:
            empty += 1
            continue
        if empty:
            out.append(str(empty))
            empty = 0
        letter = PIECE_TO_FEN[piece.type]
        out.append(letter.upper() if piece.color == PieceColor.WHITE else letter)
    if empty:
        out.append(str(empty))
    return "".join(out)


def _castling_rights_to_fen(rights):
    chars = "".join(c for key, c in CASTLING_FEN_CHARS if rights.get(key))
    return chars or "-"


def _square_to_algebraic(square):
    if square is None:
        return "-"
    return f"{SAN_FILES[square.col]}{Backend.SIZE - square.row}"


def _parse_placement(placement):
    state = [[None] * Backend.SIZE for _ in range(Backend.SIZE)]
    ranks = placement.split("/")
    if len(ranks) != Backend.SIZE:
        raise ValueError(f"FEN placement must have {Backend.SIZE} ranks: {placement!r}")
    for row, rank in enumerate(ranks):
        col = 0
        for ch in rank:
            if ch.isdigit():
                col += int(ch)
                continue
            color = PieceColor.WHITE if ch.isupper() else PieceColor.BLACK
            piece_type = FEN_TO_PIECE[ch.lower()]
            state[row][col] = Piece(piece_type, color)
            col += 1
        if col != Backend.SIZE:
            raise ValueError(f"FEN rank {row} did not fill {Backend.SIZE} columns: {rank!r}")
    return state


def _parse_castling(field):
    if field == "-":
        return {key: False for key in CASTLING_KEYS}
    rights = {key: False for key in CASTLING_KEYS}
    for key, ch in CASTLING_FEN_CHARS:
        if ch in field:
            rights[key] = True
    return rights


def _parse_ep(field):
    if field == "-":
        return None
    if len(field) != 2:
        raise ValueError(f"Invalid en-passant field: {field!r}")
    file_ch, rank_ch = field
    return Square(Backend.SIZE - int(rank_ch), SAN_FILES.index(file_ch))
