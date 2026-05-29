import pytest

from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, Q, R, P,
    NO_CASTLING, make_backend, piece, sq, play_moves,
)


def test_fools_mate():
    """1. f3 e5 2. g4 Qh4# -- the fastest mate; full replay from new_game."""
    bk = Backend()
    bk.new_game()
    play_moves(bk, [
        (sq(6, 5), sq(5, 5)),
        (sq(1, 4), sq(3, 4)),
        (sq(6, 6), sq(4, 6)),
    ])
    result = bk.try_move(sq(0, 3), sq(4, 7))
    assert result.legal
    assert result.is_checkmate
    assert bk.game_result() == "black_wins"


BACK_RANK_MATE = {
    sq(7, 7): piece(K, WHITE),
    sq(6, 5): piece(P, WHITE),
    sq(6, 6): piece(P, WHITE),
    sq(6, 7): piece(P, WHITE),
    sq(7, 0): piece(R, BLACK),
    sq(0, 0): piece(K, BLACK),
}

CLASSIC_STALEMATE = {
    sq(0, 0): piece(K, BLACK),
    sq(1, 2): piece(K, WHITE),
    sq(2, 1): piece(Q, WHITE),
}


@pytest.mark.parametrize(
    "pieces, turn, in_check, expected",
    [
        pytest.param(
            BACK_RANK_MATE, WHITE, True, "black_wins",
            id="back_rank_rook_mates_boxed_king",
        ),
        pytest.param(
            CLASSIC_STALEMATE, BLACK, False, "draw_stalemate",
            id="boxed_king_no_moves_not_in_check",
        ),
    ],
)
def test_no_legal_moves_terminal_result(pieces, turn, in_check, expected):
    bk = make_backend(pieces, turn=turn, castling_rights=NO_CASTLING)
    assert bk.is_in_check(turn) is in_check
    assert bk.game_result() == expected
    assert bk.is_game_over()


def test_check_does_not_end_game_if_response_exists():
    """1. e4 e5 2. Bc4 -- no threats; game stays live and result is None."""
    bk = Backend()
    bk.new_game()
    play_moves(bk, [
        (sq(6, 4), sq(4, 4)),
        (sq(1, 4), sq(3, 4)),
        (sq(7, 5), sq(4, 2)),
    ])
    assert bk.game_result() is None
    assert not bk.is_game_over()
