from collections import Counter

from chessshootout.backend.backend import Backend, CASTLING_KEYS, SAN_FILES
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square, coord_from_square


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

EP_TARGET_RANKS = "36"


def export_fen(backend: Backend) -> str:
    """
    Write out the position a backend is holding as a FEN string, the spelling
    the server puts in every game-start and resume payload and the one the menu
    offers as a shareable link. FEN describes the position only -- the move
    history, the clocks and any skill-check state are not part of it. The move
    number counts on from the engine's fullmove baseline, so a position loaded
    at move 24 is still written out as move 24

    :param backend: engine whose current position is written out
    :returns: the six-field FEN string for that position
    """
    placement = "/".join(_rank_to_fen(backend, row) for row in range(Backend.SIZE))
    turn = "w" if backend.turn == PieceColor.WHITE else "b"
    rights = _castling_rights_to_fen(backend.castling_rights)
    ep = _square_to_algebraic(backend.en_passant_target)
    halfmove = backend.halfmove_clock
    plies = len(backend.move_history) + (1 if backend.baseline_black_to_move else 0)
    fullmove = backend.fullmove_baseline + plies // 2
    return f"{placement} {turn} {rights} {ep} {halfmove} {fullmove}"


def apply_fen(backend: Backend, fen: str) -> None:
    """
    Load a position into a backend from a FEN string, which is how a game is
    started from a pasted position. The board, side to move, castling rights,
    en-passant target, halfmove clock and move number all come from the FEN,
    while the move history is emptied and the repetition count restarts here, so
    a loaded game begins with no past to repeat or take back. The move number
    becomes the engine's fullmove baseline, which is what lets the position be
    written back out at the number it came in at. The two counters at the tail
    are the forgiving part of the paste: junk there costs the player only its
    default, while a broken board or side to move is refused outright

    :param backend: engine to overwrite; it is changed in place
    :param fen: FEN string carrying at least its first four fields, its side to
        move spelled exactly w or b
    """
    parts = fen.strip().split()
    if len(parts) < 4:
        raise ValueError(f"FEN must have at least 4 fields: {fen!r}")
    placement = parts[0]
    turn = parts[1]
    castling = parts[2]
    ep = parts[3]
    if turn not in ("w", "b"):
        raise ValueError(f"FEN side to move must be w or b: {turn!r}")
    halfmove = _parse_counter(parts[4], 0) if len(parts) >= 5 else 0
    fullmove = _parse_counter(parts[5], 1) if len(parts) >= 6 else 1

    state = _parse_placement(placement)
    backend.state = state
    backend.turn = PieceColor.WHITE if turn == "w" else PieceColor.BLACK
    backend.castling_rights = _parse_castling(castling)
    backend.en_passant_target = _parse_ep(ep)
    backend.halfmove_clock = halfmove
    backend.fullmove_baseline = fullmove
    backend.baseline_black_to_move = turn == "b"
    backend.move_history = []
    backend.reset_legal_move_memo()
    backend.position_counts = Counter()
    backend.position_counts[backend.position_key()] = 1


def _rank_to_fen(backend: Backend, row: int) -> str:
    """
    Write one rank of the board the way FEN spells it, with runs of empty
    squares collapsed into a single count and White's pieces in upper case

    :param backend: engine holding the position being written out
    :param row: board row to write, 0 being Black's back rank
    :returns: that rank as its FEN fragment
    """
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


def _castling_rights_to_fen(rights: dict[str, bool]) -> str:
    """
    Write the four castling rights as the FEN field, always in the standard
    white-then-black, king-then-queen order. A position where nobody may castle
    is spelled as a dash rather than as an empty field

    :param rights: castling flags keyed by WK, WQ, BK and BQ
    :returns: the castling field, or a dash when no side may castle
    """
    chars = "".join(c for key, c in CASTLING_FEN_CHARS if rights.get(key))
    return chars or "-"


def _square_to_algebraic(square: Square | None) -> str:
    """
    Write the en-passant field of a FEN, which names a square only in the reply
    to a pawn's double push and is a dash at every other moment of the game

    :param square: en-passant target square, or None when there is none
    :returns: the square name, or a dash when there is no target
    """
    if square is None:
        return "-"
    return coord_from_square(square)


def _parse_placement(placement: str) -> list[list[Piece | None]]:
    """
    Turn the piece-placement field of a FEN into the board grid the engine plays
    on, refusing a field that does not describe exactly eight full ranks. Letter
    case chooses the side, so an upper-case letter is a White piece. A rank that
    runs past the eighth file is turned away as a bad paste like any other,
    rather than being allowed to index off the end of the row

    :param placement: first FEN field, its ranks separated by slashes
    :returns: 8x8 grid of pieces, row 0 being Black's back rank
    """
    state: list[list[Piece | None]] = [[None] * Backend.SIZE for _ in range(Backend.SIZE)]
    ranks = placement.split("/")
    if len(ranks) != Backend.SIZE:
        raise ValueError(f"FEN placement must have {Backend.SIZE} ranks: {placement!r}")
    for row, rank in enumerate(ranks):
        col = 0
        for ch in rank:
            if ch.isdigit():
                col += int(ch)
                continue
            if col >= Backend.SIZE:
                raise ValueError(
                    f"FEN rank {row} runs past {Backend.SIZE} columns: {rank!r}")
            color = PieceColor.WHITE if ch.isupper() else PieceColor.BLACK
            piece_type = FEN_TO_PIECE[ch.lower()]
            state[row][col] = Piece(piece_type, color)
            col += 1
        if col != Backend.SIZE:
            raise ValueError(f"FEN rank {row} did not fill {Backend.SIZE} columns: {rank!r}")
    return state


def _parse_castling(field: str) -> dict[str, bool]:
    """
    Read the castling field of a FEN into the four flags the engine keeps.
    A right the field does not mention is off, so a dash leaves nobody able to
    castle in the loaded position

    :param field: castling field of the FEN, such as KQkq or a dash
    :returns: castling flags keyed by WK, WQ, BK and BQ
    """
    rights = {key: False for key in CASTLING_KEYS}
    for key, ch in CASTLING_FEN_CHARS:
        if ch in field:
            rights[key] = True
    return rights


def _parse_ep(field: str) -> Square | None:
    """
    Read the en-passant field of a FEN into the square a pawn may be captured
    on. The engine keeps that target inside its repetition key, so a loaded
    position with one is a different position from the same board without it.
    Only the two ranks a double push can be answered on are accepted: a target
    anywhere else would let a pawn capture en passant onto a rank no pawn can
    reach, taking a piece of the mover's own side off the board with it

    :param field: en-passant field of the FEN, a square name on rank 3 or 6,
        or a dash
    :returns: the target square, or None when the FEN names no target
    """
    if field == "-":
        return None
    if len(field) != 2 or field[0] not in SAN_FILES or field[1] not in EP_TARGET_RANKS:
        raise ValueError(f"FEN en-passant target must sit on rank 3 or 6: {field!r}")
    return Square(Backend.SIZE - int(field[1]), SAN_FILES.index(field[0]))


def _parse_counter(field: str, floor: int) -> int:
    """
    Read one of the two move counters at the tail of a FEN, falling back to its
    smallest meaningful value when the field is not a number that big. Those
    fields are the ones exporters most often leave out, annotate or mangle, and
    a position loads perfectly well without them, so a spoiled counter must not
    cost the player the whole paste

    :param field: the halfmove or fullmove field exactly as it was written
    :param floor: smallest value the counter can mean -- 0 for the halfmove
        clock, 1 for the move number -- which is also the fallback
    :returns: the counter to load, never below the floor
    """
    try:
        value = int(field)
    except ValueError:
        return floor
    return max(value, floor)
