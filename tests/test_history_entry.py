import pytest

from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, Q, R, P,
    make_backend, piece, play_moves, sq,
)


def _new_game():
    bk = Backend()
    bk.new_game()
    return bk


def _castle_setup():
    return make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })


def _promotion_setup():
    return make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })


def _en_passant_setup():
    return make_backend({
        sq(3, 4): piece(P, WHITE),
        sq(1, 3): piece(P, BLACK),
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=BLACK)


@pytest.mark.parametrize(
    "build, moves, promote_at, promote_to, finalized, is_castle, "
    "is_en_passant, promoted_to, san",
    [
        pytest.param(
            _new_game, [(sq(6, 4), sq(4, 4))], None, None,
            True, False, False, None, "e4",
            id="quiet_pawn_push_finalized",
        ),
        pytest.param(
            _castle_setup, [(sq(7, 4), sq(7, 6))], None, None,
            True, True, False, None, "O-O",
            id="kingside_castle_marked_finalized",
        ),
        pytest.param(
            _promotion_setup, [(sq(1, 0), sq(0, 0))], None, None,
            False, False, False, None, "a8",
            id="pending_promotion_unfinalized",
        ),
        pytest.param(
            _promotion_setup, [(sq(1, 0), sq(0, 0))], sq(0, 0), Q,
            True, False, False, Q, "a8=Q+",
            id="completed_promotion_finalized",
        ),
        pytest.param(
            _en_passant_setup, [(sq(1, 3), sq(3, 3)), (sq(3, 4), sq(2, 3))],
            None, None,
            True, False, True, None, "exd6",
            id="en_passant_capture_marked_finalized",
        ),
    ],
)
def test_history_entry_records_move_shape(
    build, moves, promote_at, promote_to, finalized,
    is_castle, is_en_passant, promoted_to, san,
):
    """The latest HistoryEntry mirrors the ply: castle / e.p. / promotion flags,
    and position_key_added is None until the ply is finalized (pending promotion)."""
    bk = build()
    play_moves(bk, moves)
    if promote_at is not None:
        bk.promote(promote_at, promote_to)
    entry = bk.move_history[-1]
    assert (entry.position_key_added is not None) is finalized
    assert entry.move.is_castle is is_castle
    assert entry.move.is_en_passant is is_en_passant
    assert entry.move.promoted_to == promoted_to
    assert entry.san == san


def test_prev_state_round_trips_via_undo():
    """Undo restores the pre-ply castling rights and halfmove clock snapshotted
    into the HistoryEntry, not just the board."""
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
    assert bk.move_history == []
