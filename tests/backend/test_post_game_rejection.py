import pytest

from tests.helpers import (
    BLACK, WHITE, K, Q, R, P,
    NO_CASTLING,
    make_backend, piece, sq,
)


def _checkmate():
    return make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights=NO_CASTLING)


def _stalemate():
    return make_backend({
        sq(0, 0): piece(K, BLACK),
        sq(1, 2): piece(K, WHITE),
        sq(2, 1): piece(Q, WHITE),
    }, turn=BLACK, castling_rights=NO_CASTLING)


def _fifty_move():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=99)
    bk.try_move(sq(7, 0), sq(7, 1))
    return bk


def _insufficient_material():
    return make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})


@pytest.mark.parametrize(
    "setup, move, expected_result",
    [
        pytest.param(
            _checkmate, (sq(7, 7), sq(7, 6)), "black_wins",
            id="checkmate",
        ),
        pytest.param(
            _stalemate, (sq(0, 0), sq(0, 1)), "draw_stalemate",
            id="stalemate",
        ),
        pytest.param(
            _fifty_move, (sq(0, 4), sq(0, 5)), "draw_fifty_move",
            id="fifty_move",
        ),
        pytest.param(
            _insufficient_material, (sq(7, 4), sq(7, 5)), "draw_insufficient_material",
            id="insufficient_material",
        ),
    ],
)
def test_try_move_rejected_after_game_over(setup, move, expected_result):
    bk = setup()
    assert bk.game_result() == expected_result
    assert bk.is_game_over()
    from_sq, to_sq = move
    assert not bk.try_move(from_sq, to_sq).legal
