import pytest

from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, R, P,
    make_backend, piece, sq,
)


def test_en_passant_capture_executes():
    """1. e4 a6 2. e5 f5 3. exf6 e.p. lands on f6 and removes the f5 pawn."""
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.try_move(sq(1, 0), sq(2, 0))
    bk.try_move(sq(4, 4), sq(3, 4))
    bk.try_move(sq(1, 5), sq(3, 5))
    assert bk.en_passant_target == sq(2, 5)
    moves = bk.legal_moves_from(sq(3, 4))
    assert sq(2, 5) in moves
    result = bk.try_move(sq(3, 4), sq(2, 5))
    assert result.legal
    assert bk.state[2][5].type == P
    assert bk.state[2][5].color == WHITE
    assert bk.state[3][5] is None
    assert bk.state[3][4] is None


@pytest.mark.parametrize(
    "from_sq, to_sq, expected_target",
    [
        pytest.param(sq(6, 4), sq(4, 4), sq(5, 4), id="white_double_push_sets_e3"),
        pytest.param(sq(1, 5), sq(3, 5), sq(2, 5), id="black_double_push_sets_f6"),
        pytest.param(sq(6, 4), sq(5, 4), None, id="white_single_push_sets_none"),
    ],
)
def test_pawn_push_sets_en_passant_target(from_sq, to_sq, expected_target):
    """Only a two-square push sets the EP target, to the midpoint square."""
    bk = Backend()
    bk.new_game()
    if from_sq.row == 1:
        bk.try_move(sq(6, 0), sq(5, 0))
    bk.try_move(from_sq, to_sq)
    assert bk.en_passant_target == expected_target


def test_ep_target_cleared_after_one_ply():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    assert bk.en_passant_target == sq(5, 4)
    bk.try_move(sq(1, 0), sq(2, 0))
    assert bk.en_passant_target is None


def test_ep_pin_is_illegal():
    """exd6 e.p. clears both pawns from the king's rank, exposing it to the rook."""
    bk = make_backend({
        sq(3, 7): piece(K, WHITE),
        sq(3, 4): piece(P, WHITE),
        sq(3, 3): piece(P, BLACK),
        sq(3, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, ep_target=sq(2, 3))
    moves = bk.legal_moves_from(sq(3, 4))
    assert sq(2, 3) not in moves


def test_ep_resets_halfmove_clock():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(3, 4): piece(P, WHITE),
        sq(3, 3): piece(P, BLACK),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, ep_target=sq(2, 3), halfmove_clock=42)
    bk.try_move(sq(3, 4), sq(2, 3))
    assert bk.halfmove_clock == 0
    assert bk.state[2][3].type == P
    assert bk.state[2][3].color == WHITE
    assert bk.state[3][3] is None
