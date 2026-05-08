from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def test_stalemate_reported_over_insufficient_material():
    # KB vs K is "insufficient material" by FIDE, but if black is also stalemated
    # we should report draw_stalemate (mate/stalemate is checked first).
    # Position: white Kc7 + Be3, black Ka8 to move.
    # Black has no legal moves: a7 covered by Be3, b8 by white king, b7 by both.
    # Black is not in check.
    bk = make_backend({
        sq(1, 2): piece(K, WHITE),
        sq(5, 4): piece(B, WHITE),
        sq(0, 0): piece(K, BLACK),
    }, turn=BLACK, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    assert not bk.is_in_check(BLACK)
    assert bk.game_result() == "draw_stalemate"


def test_mate_with_sufficient_material_reports_winner():
    # Standard fool's-mate-style position with rook in play — sufficient material on both sides.
    bk = make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    assert bk.game_result() == "black_wins"


# DEVIATION: FIDE 6.9 says timing out in a position the opponent cannot mate is a draw.
# We follow chess.com / lichess: timeout always loses. Documented in test_clock.py.
def test_timeout_outranks_insufficient_material():
    # K vs K+B is "insufficient material" if the bishop's owner can't mate.
    # White flags here; we expect "black_wins_on_time", not "draw_insufficient_material".
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 0): piece(B, BLACK),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=lambda: ts[0])
    ts[0] = 5.0
    bk.tick_clock()
    assert bk.game_result() == "black_wins_on_time"


def test_mate_outranks_timeout_when_no_clock_set():
    # Without a clock, mate is reported. Sanity check that the clock branch doesn't
    # spuriously fire on non-clocked games.
    bk = make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    assert bk.clock is None
    assert bk.game_result() == "black_wins"
