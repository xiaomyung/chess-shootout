import pytest

from tests.helpers import (
    BLACK, WHITE, K, R, P,
    make_backend, piece, sq,
)


def test_fifty_move_draw_at_100_halfmoves():
    """100 halfmoves (FIFTY_MOVE_HALFMOVES) is the draw boundary; a non-capture,
    non-pawn shuffle that ticks the clock from 99 -> 100 triggers it."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=99)
    bk.try_move(sq(7, 0), sq(7, 1))
    assert bk.halfmove_clock == 100
    assert bk.game_result() == "draw_fifty_move"


@pytest.mark.parametrize(
    "pieces, move_from, move_to, start_clock, expected_clock",
    [
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(6, 0): piece(P, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            sq(6, 0), sq(5, 0), 42, 0,
            id="pawn_push_resets_to_zero",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(4, 4): piece(R, WHITE),
                sq(4, 0): piece(R, BLACK),
                sq(0, 4): piece(K, BLACK),
            },
            sq(4, 4), sq(4, 0), 42, 0,
            id="capture_resets_to_zero",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 7): piece(R, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            sq(7, 4), sq(7, 6), 10, 11,
            id="castling_increments_no_reset",
        ),
    ],
)
def test_halfmove_clock_update(pieces, move_from, move_to, start_clock, expected_clock):
    """Pawn pushes and captures reset the halfmove clock to 0; castling is a quiet
    king move that only increments it (FIDE: castling is not a pawn move/capture)."""
    bk = make_backend(pieces, turn=WHITE, halfmove_clock=start_clock)
    bk.try_move(move_from, move_to)
    assert bk.halfmove_clock == expected_clock
