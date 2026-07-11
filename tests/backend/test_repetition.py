import pytest

from chessshootout.backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, R,
    make_backend, piece, sq,
)


def test_threefold_repetition_via_knight_shuffle():
    """Both knights shuffle out and back; the 8th ply restores the start position a
    third time, so game_result reports draw_repetition."""
    bk = Backend()
    bk.new_game()
    moves = [
        (sq(7, 6), sq(5, 5)),
        (sq(0, 1), sq(2, 2)),
        (sq(5, 5), sq(7, 6)),
        (sq(2, 2), sq(0, 1)),
        (sq(7, 6), sq(5, 5)),
        (sq(0, 1), sq(2, 2)),
        (sq(5, 5), sq(7, 6)),
        (sq(2, 2), sq(0, 1)),
    ]
    last = None
    for m in moves:
        last = bk.try_move(*m)
        assert last.legal
    assert bk.game_result() == "draw_repetition"


def test_repetition_does_not_trigger_too_early():
    """After one round-trip the start position has been seen only twice (initial +
    once back), so no threefold draw is claimed yet."""
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(7, 6), sq(5, 5))
    bk.try_move(sq(0, 1), sq(2, 2))
    bk.try_move(sq(5, 5), sq(7, 6))
    bk.try_move(sq(2, 2), sq(0, 1))
    assert bk.game_result() is None


KR_BK_KINGS_AND_ROOKS = {
    sq(7, 4): piece(K, WHITE),
    sq(7, 0): piece(R, WHITE),
    sq(7, 7): piece(R, WHITE),
    sq(0, 4): piece(K, BLACK),
}
TWO_KINGS = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)}


@pytest.mark.parametrize(
    "pieces, kwargs1, kwargs2",
    [
        pytest.param(
            KR_BK_KINGS_AND_ROOKS,
            {},
            {"castling_rights": {"WK": False, "WQ": True, "BK": True, "BQ": True}},
            id="castling_rights_differ",
        ),
        pytest.param(
            TWO_KINGS, {}, {"ep_target": sq(5, 4)}, id="ep_target_differs"
        ),
        pytest.param(
            TWO_KINGS, {"turn": WHITE}, {"turn": BLACK}, id="side_to_move_differs"
        ),
    ],
)
def test_position_key_distinguishes_state(pieces, kwargs1, kwargs2):
    """Identical placement with a differing repetition-key field (castling rights, EP
    target, or side to move) must yield distinct position keys."""
    bk1 = make_backend(pieces, **kwargs1)
    bk2 = make_backend(pieces, **kwargs2)
    assert bk1._position_key() != bk2._position_key()
