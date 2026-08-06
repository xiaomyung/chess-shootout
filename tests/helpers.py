from collections import Counter

from chessshootout.backend.backend import Backend, DEFAULT_CASTLING_RIGHTS
from chessshootout.backend.utils import Square, Move, HistoryEntry
from chessshootout.backend.pieces import Piece, PieceColor, PieceType


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

    def set(self, t):
        self.t = t


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


def make_app(w=1000, h=800, *, mock_sound=True):
    """Build a bare single-screen Frontend at the given window size.

    Does not start a game -- pair with start_single_screen() for that.
    mock_sound=True (default) replaces sound_manager with a MagicMock so
    tests don't touch the real mixer; pass False to keep the real one. The
    mock seeds master_volume/menu_volume/enabled with plausible values so
    widgets that read them (e.g. the Options volume sliders) don't choke on
    an unconfigured MagicMock during a plain draw_frame().
    """
    from unittest.mock import MagicMock

    from chessshootout.frontend.frontend import Frontend

    app = Frontend(w, h)
    if mock_sound:
        app.sound_manager = MagicMock(master_volume=1.0, menu_volume=1.0, enabled=True)
    return app


def start_single_screen(app, *, nickname="alice", side="white",
                         time_minutes=5, increment_seconds=0):
    """Start a local single-screen game on an existing Frontend.

    Drives the same request_nav path the real start-menu callback uses;
    _on_start_game queues the Nav and executes it immediately so this stays
    synchronous for callers.
    """
    app._on_start_game({
        "mode": "single_screen", "nickname": nickname, "side": side,
        "time_minutes": time_minutes, "increment_seconds": increment_seconds,
    })
    return app


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


def rgb(color):
    """A color spec (hex string like "#334455" or an (r, g, b[, a]) sequence)
    reduced to a plain (r, g, b) tuple, ignoring alpha."""
    import pygame as pg

    return pg.Color(color)[:3] if isinstance(color, str) else tuple(color)[:3]


def scan_region(surface, rect, color, *, tol=0, step=1, count=False, clamp=False):
    """Scan a rectangular region of a surface for pixels matching `color`.

    tol=0 -> exact RGB match; tol>0 -> per-channel abs diff <= tol on all three
    channels. step subsamples the region (stride on both axes). clamp keeps the
    scan inside the surface bounds. count=False returns whether ANY sampled pixel
    matched (bool); count=True returns how many did (int). One source for the
    region colour scans that used to be copy-pasted per file, each with its own
    tolerance/step semantics.
    """
    want = rgb(color)
    x0, y0, x1, y1 = rect.x, rect.y, rect.right, rect.bottom
    if clamp:
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, surface.get_width()), min(y1, surface.get_height())

    def matches(px):
        if tol == 0:
            return px[:3] == want
        return all(abs(a - b) <= tol for a, b in zip(px[:3], want))

    hits = (
        matches(surface.get_at((x, y)))
        for x in range(x0, x1, step)
        for y in range(y0, y1, step)
    )
    return sum(1 for hit in hits if hit) if count else any(hits)


def valid_pgn_text():
    """A short, legal 3-ply game rendered to PGN (white_wins). Shared by the menu
    history/navigation views that just need any loadable file on disk."""
    from chessshootout.backend.backend import Backend
    from chessshootout.domain.pgn.generate import generate_pgn

    backend = Backend()
    backend.new_game()
    for san in ["e4", "e5", "Nf3"]:
        backend.apply_san(san)
    return generate_pgn(backend.move_history, "white_wins",
                        white_name="alice", black_name="Bob")


def freeze_ticks(monkeypatch):
    """Freeze pg.time.get_ticks() at a fixed base through a mutable holder so
    tween/transition tests are deterministic. Returns the holder: bump
    holder["ms"] to advance the frozen clock."""
    import pygame as pg

    holder = {"ms": 100_000}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: holder["ms"])
    return holder


def fire_animation(board):
    """Force every in-flight board animation to its end and draw the final frame,
    landing an animated move instantly in review/board tests."""
    import pygame as pg

    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


def key_event(key, unicode=""):
    """Build a pygame KEYDOWN event (mod=0) for the given key/unicode."""
    import pygame as pg

    return pg.event.Event(pg.KEYDOWN, key=key, mod=0, unicode=unicode)


def click_event(pos, button=1):
    """Build a pygame left-click MOUSEBUTTONDOWN event at pos."""
    import pygame as pg

    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": button, "pos": pos})


def history_entry(san):
    """A minimal HistoryEntry carrying a pawn move and the given SAN, for move-list
    scroll tests that just need N filler rows."""
    move = Move(Square(6, 0), Square(5, 0), Piece(PieceType.PAWN, PieceColor.WHITE))
    return HistoryEntry(move=move, prev_castling_rights=(), prev_en_passant_target=None,
                        prev_halfmove_clock=0, position_key_added=("k",), san=san)


def draw_strip(strip):
    """Fill the strip's window black and redraw it (player/review strip pixel tests)."""
    strip.window.fill((0, 0, 0))
    strip.draw()


def strip_avatar_pixels(strip):
    """Sample the top and bottom of a strip's flat avatar (the same geometry the
    strip uses to place it), returning (top_color, bottom_color)."""
    pad = max(int(strip.rect.height * 0.16), 4)
    av = strip.rect.height - 2 * pad
    cx = strip.rect.x + pad + av // 2
    top = strip.window.get_at((cx, strip.rect.y + pad + max(3, av // 6)))
    bottom = strip.window.get_at((cx, strip.rect.y + pad + av - max(3, av // 6)))
    return top, bottom


def write_pgn_fixture(tmp_path, name, white, black, result, moves="1. e4 e5"):
    """Write a minimal single-game PGN under tmp_path/games/ and return its path.
    Shared by the Profile/rail-cards views that scan the games dir for stats."""
    games = tmp_path / "games"
    games.mkdir(exist_ok=True)
    path = games / name
    path.write_text(
        f'[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n\n{moves} {result}\n',
        encoding="utf-8")
    return path


def online_start_payload(**overrides):
    """The game_start / match-found payload the coordinator consumes, defaulting to
    white, alice vs bob, 5+0. Pass overrides to vary a field."""
    payload = {
        "your_color": "white", "white_name": "alice", "black_name": "bob",
        "time_minutes": 5, "increment_seconds": 0,
    }
    payload.update(overrides)
    return payload
