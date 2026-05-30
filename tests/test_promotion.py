import pytest

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def _white_promotion_setup():
    return make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })


@pytest.mark.parametrize(
    "new_type",
    [
        pytest.param(Q, id="queen"),
        pytest.param(R, id="rook"),
        pytest.param(B, id="bishop"),
        pytest.param(N, id="knight"),
    ],
)
def test_promote_replaces_pawn_and_switches_turn(new_type):
    bk = _white_promotion_setup()
    result = bk.try_move(sq(1, 0), sq(0, 0))
    assert result.legal
    assert result.promotion_required
    assert bk.state[0][0].type == P
    bk.promote(sq(0, 0), new_type)
    assert bk.state[0][0].type == new_type
    assert bk.state[0][0].color == WHITE
    assert bk.turn == BLACK


def test_promotion_with_capture():
    bk = make_backend({
        sq(1, 1): piece(P, WHITE),
        sq(0, 0): piece(R, BLACK),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })
    result = bk.try_move(sq(1, 1), sq(0, 0))
    assert result.legal
    assert result.promotion_required
    assert result.captured.type == R
    bk.promote(sq(0, 0), Q)
    assert bk.state[0][0].type == Q
    assert not bk.castling_rights["BQ"]


def test_promotion_with_mate():
    bk = make_backend({
        sq(1, 6): piece(P, WHITE),
        sq(1, 5): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    }, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    bk.try_move(sq(1, 6), sq(0, 6))
    result = bk.promote(sq(0, 6), Q)
    assert result.is_checkmate
    assert bk.game_result() == "white_wins"


def test_promote_invalid_target_raises():
    bk = _white_promotion_setup()
    bk.try_move(sq(1, 0), sq(0, 0))
    with pytest.raises(ValueError):
        bk.promote(sq(0, 0), K)


def test_promote_when_nothing_pending_raises():
    bk = _white_promotion_setup()
    with pytest.raises(ValueError):
        bk.promote(sq(0, 0), Q)
