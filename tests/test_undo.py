import pytest

from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, Q, R, P,
    make_backend, piece, sq,
)


def _snapshot(backend):
    state = tuple(
        tuple((p.type, p.color) if p is not None else None for p in row)
        for row in backend.state
    )
    return {
        "state": state,
        "turn": backend.turn,
        "castling_rights": dict(backend.castling_rights),
        "en_passant_target": backend.en_passant_target,
        "halfmove_clock": backend.halfmove_clock,
        "position_counts": dict(backend.position_counts),
        "move_history_len": len(backend.move_history),
    }


def _assert_states_equal(a, b):
    assert a == b


_CAPTURE = {
    sq(7, 4): piece(K, WHITE),
    sq(4, 4): piece(R, WHITE),
    sq(4, 0): piece(R, BLACK),
    sq(0, 4): piece(K, BLACK),
}
_CASTLE = {
    sq(7, 4): piece(K, WHITE),
    sq(7, 0): piece(R, WHITE),
    sq(7, 7): piece(R, WHITE),
    sq(0, 4): piece(K, BLACK),
}
_PROMOTION = {
    sq(1, 0): piece(P, WHITE),
    sq(7, 7): piece(K, WHITE),
    sq(0, 7): piece(K, BLACK),
}
_PROMOTION_CAPTURE = {
    sq(1, 1): piece(P, WHITE),
    sq(0, 0): piece(R, BLACK),
    sq(7, 7): piece(K, WHITE),
    sq(0, 7): piece(K, BLACK),
}


@pytest.mark.parametrize(
    "piece_map, frm, to, promote_to",
    [
        pytest.param(_CAPTURE, sq(4, 4), sq(4, 0), None, id="capture"),
        pytest.param(_CASTLE, sq(7, 4), sq(7, 6), None, id="kingside_castle"),
        pytest.param(_CASTLE, sq(7, 4), sq(7, 2), None, id="queenside_castle"),
        pytest.param(_PROMOTION, sq(1, 0), sq(0, 0), Q, id="promotion"),
        pytest.param(_PROMOTION_CAPTURE, sq(1, 1), sq(0, 0), Q, id="promotion_with_capture"),
    ],
)
def test_undo_roundtrip_restores_state(piece_map, frm, to, promote_to):
    """Undo of any single ply round-trips every snapshotted state field."""
    bk = make_backend(piece_map)
    snap = _snapshot(bk)
    bk.try_move(frm, to)
    if promote_to is not None:
        bk.promote(to, promote_to)
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_double_pawn_push_restores_ep_target():
    bk = Backend()
    bk.new_game()
    snap = _snapshot(bk)
    bk.try_move(sq(6, 4), sq(4, 4))
    assert bk.en_passant_target == sq(5, 4)
    bk.undo()
    assert bk.en_passant_target is None
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_en_passant_restores_captured_pawn():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.try_move(sq(1, 0), sq(2, 0))
    bk.try_move(sq(4, 4), sq(3, 4))
    bk.try_move(sq(1, 5), sq(3, 5))
    snap = _snapshot(bk)
    bk.try_move(sq(3, 4), sq(2, 5))
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_pending_promotion_before_promote():
    bk = make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })
    snap = _snapshot(bk)
    result = bk.try_move(sq(1, 0), sq(0, 0))
    assert result.promotion_required
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_multiple_plies_returns_to_start():
    bk = Backend()
    bk.new_game()
    snap = _snapshot(bk)
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.try_move(sq(1, 4), sq(3, 4))
    bk.try_move(sq(7, 6), sq(5, 5))
    bk.try_move(sq(0, 1), sq(2, 2))
    bk.try_move(sq(7, 5), sq(4, 2))
    for _ in range(5):
        bk.undo()
    _assert_states_equal(_snapshot(bk), snap)
