"""game_result() resolves competing end conditions in a fixed priority order:

mate/stalemate > flag (timeout) > insufficient material > repetition > fifty-move.

The ladder matters because a checkmate that happens to leave insufficient material
must report the winner, not a draw. Each case stacks lower-priority triggers under a
higher-priority one and asserts the higher one wins.
"""
import pytest

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, P,
    make_backend, piece, sq, NO_CASTLING,
)


MATE = {
    sq(7, 7): piece(K, WHITE),
    sq(6, 5): piece(P, WHITE),
    sq(6, 6): piece(P, WHITE),
    sq(6, 7): piece(P, WHITE),
    sq(7, 0): piece(R, BLACK),
    sq(0, 0): piece(K, BLACK),
}
K_VS_K = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)}
KQ_VS_K = {
    sq(7, 4): piece(K, WHITE),
    sq(7, 3): piece(Q, WHITE),
    sq(0, 4): piece(K, BLACK),
}


@pytest.mark.parametrize(
    "pieces, turn, halfmove_clock, threefold, expected",
    [
        pytest.param(MATE, WHITE, 0, False, "black_wins", id="mate_reports_winner"),
        pytest.param(
            MATE, WHITE, 100, True, "black_wins",
            id="mate_outranks_repetition_and_fifty",
        ),
        pytest.param(
            K_VS_K, WHITE, 100, True, "draw_insufficient_material",
            id="insufficient_outranks_repetition_and_fifty",
        ),
        pytest.param(
            KQ_VS_K, BLACK, 100, True, "draw_repetition",
            id="repetition_outranks_fifty_move",
        ),
        pytest.param(
            KQ_VS_K, BLACK, 100, False, "draw_fifty_move",
            id="fifty_move_when_nothing_higher",
        ),
    ],
)
def test_game_result_priority_ladder(pieces, turn, halfmove_clock, threefold, expected):
    bk = make_backend(
        pieces, turn=turn, castling_rights=NO_CASTLING, halfmove_clock=halfmove_clock,
    )
    if threefold:
        bk.position_counts[bk._position_key()] = 3
    assert bk.game_result() == expected


def test_stalemate_reported_over_insufficient_material():
    """KB vs K is insufficient material by FIDE, but a stalemated (not in check) side
    must report draw_stalemate because mate/stalemate is checked first. White Kc7+Be3,
    black Ka8 to move: a7 covered by Be3, b8 by the white king, b7 by both."""
    bk = make_backend({
        sq(1, 2): piece(K, WHITE),
        sq(5, 4): piece(B, WHITE),
        sq(0, 0): piece(K, BLACK),
    }, turn=BLACK, castling_rights=NO_CASTLING)
    assert not bk.is_in_check(BLACK)
    assert bk.game_result() == "draw_stalemate"


def test_timeout_outranks_insufficient_material():
    """K vs K+B is insufficient material, but a flagged clock loses regardless.
    DEVIATION: FIDE 6.9 draws a timeout the opponent cannot mate; we follow
    chess.com / lichess (timeout always loses). White flags here -> black_wins_on_time."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 0): piece(B, BLACK),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=lambda: ts[0])
    ts[0] = 5.0
    bk.tick_clock()
    assert bk.clock.flagged == WHITE
    assert bk.game_result() == "black_wins_on_time"


def test_mate_reported_when_no_clock_is_set():
    """The flag branch must not spuriously fire on an unclocked game: with clock None
    the rook mate still reports black_wins."""
    bk = make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights=NO_CASTLING)
    assert bk.clock is None
    assert bk.game_result() == "black_wins"
