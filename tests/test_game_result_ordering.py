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
