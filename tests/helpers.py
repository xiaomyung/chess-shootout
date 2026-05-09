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
    # 32 hex chars, then formatted with version + variant fixed.
    hex_pad = f"{n:032x}"
    return (
        f"{hex_pad[0:8]}-{hex_pad[8:12]}-4{hex_pad[13:16]}-"
        f"8{hex_pad[17:20]}-{hex_pad[20:32]}"
    )
