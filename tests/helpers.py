from collections import Counter

from backend.backend import Backend, DEFAULT_CASTLING_RIGHTS
from backend.utils import Square
from backend.pieces import Piece, PieceColor, PieceType


WHITE = PieceColor.WHITE
BLACK = PieceColor.BLACK
NO_CASTLING = {"WK": False, "WQ": False, "BK": False, "BQ": False}

K = PieceType.KING
Q = PieceType.QUEEN
R = PieceType.ROOK
B = PieceType.BISHOP
N = PieceType.KNIGHT
P = PieceType.PAWN


def sq(row, col):
    return Square(row, col)


def make_backend(piece_map, turn=WHITE, castling_rights=None, ep_target=None, halfmove_clock=0):
    """Build a Backend with state set directly. piece_map: dict[Square, Piece]."""
    backend = Backend()
    for s, piece in piece_map.items():
        backend.state[s.row][s.col] = piece
    backend.turn = turn
    backend.castling_rights = (
        dict(castling_rights) if castling_rights is not None
        else dict(DEFAULT_CASTLING_RIGHTS)
    )
    backend.en_passant_target = ep_target
    backend.halfmove_clock = halfmove_clock
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    return backend


def piece(piece_type, color):
    return Piece(piece_type, color)


def kings_only(white_king=sq(7, 4), black_king=sq(0, 4)):
    """Two-king minimal board. Helpful baseline for many tests."""
    return {white_king: piece(K, WHITE), black_king: piece(K, BLACK)}


def play_moves(backend, moves):
    """Play a list of (from, to) tuples. Asserts each is legal. Returns last MoveResult."""
    last = None
    for from_sq, to_sq in moves:
        last = backend.try_move(from_sq, to_sq)
        assert last.legal, f"Move {from_sq} -> {to_sq} was rejected"
    return last


def sq_of(algebraic):
    """Algebraic square like "e4" -> Square. Rank 8 is row 0, file a is col 0."""
    col = "abcdefgh".index(algebraic[0])
    row = 8 - int(algebraic[1])
    return Square(row, col)


def squares(text):
    """Space-separated algebraic squares -> set of Squares ("" -> empty set)."""
    return {sq_of(token) for token in text.split()}


def assert_legal_moves(backend, from_sq, expected):
    """Assert legal destinations from from_sq equal expected, exactly.

    from_sq and expected accept algebraic strings ("d4", "c6 e6 b5") or a
    Square / iterable of Squares, so exact move-set checks stay terse.
    """
    if isinstance(from_sq, str):
        from_sq = sq_of(from_sq)
    expected = squares(expected) if isinstance(expected, str) else set(expected)
    actual = set(backend.legal_moves_from(from_sq))
    assert actual == expected, (
        f"from {from_sq}: missing={expected - actual} extra={actual - expected}"
    )


class FakeClock:
    """Monotonic clock stand-in for server-room/app tests. Advances explicitly."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def fake_uuid4(seed):
    """Build a deterministic UUID4-shaped string from an integer seed.

    Useful in server tests where the protocol now demands UUID4 format but
    we want short readable names. The result has version nibble = 4 and
    variant nibble in {8,9,a,b}, so it satisfies the regex.
    """
    n = int(seed)
    hex_pad = f"{n:032x}"
    return (
        f"{hex_pad[0:8]}-{hex_pad[8:12]}-4{hex_pad[13:16]}-"
        f"8{hex_pad[17:20]}-{hex_pad[20:32]}"
    )


def assert_pixel_color(surface, x, y, expected, tol=0):
    """Assert a surface pixel matches an expected RGB color within tolerance.

    `expected` may be a hex string (a Colors attribute) or an (r, g, b) tuple.
    Compares only the RGB channels, ignoring alpha.
    """
    import pygame as pg

    got = surface.get_at((int(x), int(y)))[:3]
    want = pg.Color(expected)[:3] if isinstance(expected, str) else tuple(expected)[:3]
    if tol == 0:
        assert got == want, f"pixel ({x},{y}) was {got}, expected {want}"
    else:
        assert all(abs(g - w) <= tol for g, w in zip(got, want)), \
            f"pixel ({x},{y}) was {got}, expected ~{want} (tol {tol})"
