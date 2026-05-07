import pytest

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def _white_promotion_setup():
    # White pawn on a7 ready to promote on a8. Black king tucked far away.
    return make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })


def test_promote_to_queen():
    bk = _white_promotion_setup()
    result = bk.try_move(sq(1, 0), sq(0, 0))
    assert result.legal
    assert result.promotion_required
    assert bk.state[0][0].type == P  # still a pawn until promote() called
    bk.promote(sq(0, 0), Q)
    assert bk.state[0][0].type == Q
    assert bk.state[0][0].color == WHITE
    assert bk.turn == BLACK  # turn switched after promote


def test_promote_to_each_minor():
    for new_type in (R, B, N):
        bk = _white_promotion_setup()
        bk.try_move(sq(1, 0), sq(0, 0))
        bk.promote(sq(0, 0), new_type)
        assert bk.state[0][0].type == new_type


def test_promotion_with_capture():
    # White pawn on b7 captures black rook on a8 and promotes.
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
    # Capturing the a8 rook revokes BQ castling right.
    assert not bk.castling_rights["BQ"]


def test_promotion_with_mate():
    # White king on f7 defends g8; white pawn on g7 promotes to queen, mating the black king on h8.
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
