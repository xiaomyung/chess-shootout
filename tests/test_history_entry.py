from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def test_normal_move_entry_finalized():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    entry = bk.move_history[-1]
    assert entry.position_key_added is not None
    assert entry.move.is_castle is False
    assert entry.move.is_en_passant is False
    assert entry.move.promoted_to is None


def test_castle_entry_marked():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    bk.try_move(sq(7, 4), sq(7, 6))
    entry = bk.move_history[-1]
    assert entry.move.is_castle
    assert entry.position_key_added is not None


def test_pending_promotion_entry_unfinalized():
    bk = make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })
    bk.try_move(sq(1, 0), sq(0, 0))
    entry = bk.move_history[-1]
    assert entry.position_key_added is None
    assert entry.move.promoted_to is None


def test_completed_promotion_entry_finalized():
    bk = make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })
    bk.try_move(sq(1, 0), sq(0, 0))
    bk.promote(sq(0, 0), Q)
    entry = bk.move_history[-1]
    assert entry.position_key_added is not None
    assert entry.move.promoted_to == Q


def test_prev_state_round_trips_via_undo():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, halfmove_clock=37)
    bk.try_move(sq(7, 4), sq(7, 6))
    entry = bk.move_history[-1]
    assert entry.prev_halfmove_clock == 37
    assert entry.prev_castling_rights == (True, True, True, True)
    bk.undo()
    assert bk.halfmove_clock == 37
    assert bk.castling_rights == {"WK": True, "WQ": True, "BK": True, "BQ": True}
