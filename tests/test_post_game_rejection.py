from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def _checkmate_position():
    return make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights={'WK': False, 'WQ': False, 'BK': False, 'BQ': False})


def test_try_move_rejected_after_checkmate():
    bk = _checkmate_position()
    assert bk.is_game_over()
    result = bk.try_move(sq(7, 7), sq(7, 6))
    assert not result.legal


def test_try_move_rejected_after_stalemate():
    bk = make_backend({
        sq(0, 0): piece(K, BLACK),
        sq(1, 2): piece(K, WHITE),
        sq(2, 1): piece(Q, WHITE),
    }, turn=BLACK, castling_rights={'WK': False, 'WQ': False, 'BK': False, 'BQ': False})
    assert bk.is_game_over()
    assert not bk.try_move(sq(0, 0), sq(0, 1)).legal


def test_try_move_rejected_after_fifty_move():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=99)
    bk.try_move(sq(7, 0), sq(7, 1))
    assert bk.is_game_over()
    # Black's turn now; any black move should be rejected.
    assert not bk.try_move(sq(0, 4), sq(0, 5)).legal


def test_try_move_rejected_after_insufficient_material():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    assert bk.is_game_over()
    assert not bk.try_move(sq(7, 4), sq(7, 5)).legal
