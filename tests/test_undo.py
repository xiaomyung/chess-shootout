from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def _snapshot(backend):
    state = tuple(
        tuple((p.type, p.color) if p is not None else None for p in row)
        for row in backend.state
    )
    return {
        'state': state,
        'turn': backend.turn,
        'castling_rights': dict(backend.castling_rights),
        'en_passant_target': backend.en_passant_target,
        'halfmove_clock': backend.halfmove_clock,
        'position_counts': dict(backend.position_counts),
        'move_history_len': len(backend.move_history),
    }


def _assert_states_equal(a, b):
    assert a == b


def test_undo_normal_move():
    bk = Backend()
    bk.new_game()
    snap = _snapshot(bk)
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_capture():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(4, 4): piece(R, WHITE),
        sq(4, 0): piece(R, BLACK),
        sq(0, 4): piece(K, BLACK),
    })
    snap = _snapshot(bk)
    bk.try_move(sq(4, 4), sq(4, 0))
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_double_pawn_push():
    bk = Backend()
    bk.new_game()
    snap = _snapshot(bk)
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_en_passant():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.try_move(sq(1, 0), sq(2, 0))
    bk.try_move(sq(4, 4), sq(3, 4))
    bk.try_move(sq(1, 5), sq(3, 5))
    snap = _snapshot(bk)
    bk.try_move(sq(3, 4), sq(2, 5))  # exf6 e.p.
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_kingside_castle():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    snap = _snapshot(bk)
    bk.try_move(sq(7, 4), sq(7, 6))
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_queenside_castle():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    snap = _snapshot(bk)
    bk.try_move(sq(7, 4), sq(7, 2))
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_promotion():
    bk = make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })
    snap = _snapshot(bk)
    bk.try_move(sq(1, 0), sq(0, 0))
    bk.promote(sq(0, 0), Q)
    bk.undo()
    _assert_states_equal(_snapshot(bk), snap)


def test_undo_promotion_with_capture():
    bk = make_backend({
        sq(1, 1): piece(P, WHITE),
        sq(0, 0): piece(R, BLACK),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    })
    snap = _snapshot(bk)
    bk.try_move(sq(1, 1), sq(0, 0))
    bk.promote(sq(0, 0), Q)
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
