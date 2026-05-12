from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, R,
    make_backend, piece, sq,
)


def test_threefold_repetition_via_knight_shuffle():
    bk = Backend()
    bk.new_game()
    # Both sides shuffle Nf3-Ng1 / Nc6-Nb8 returning to start; on the 8th ply the start
    # position has been seen 3 times → draw.
    moves = [
        (sq(7, 6), sq(5, 5)),  # Nf3
        (sq(0, 1), sq(2, 2)),  # Nc6
        (sq(5, 5), sq(7, 6)),  # Ng1
        (sq(2, 2), sq(0, 1)),  # Nb8
        (sq(7, 6), sq(5, 5)),
        (sq(0, 1), sq(2, 2)),
        (sq(5, 5), sq(7, 6)),
        (sq(2, 2), sq(0, 1)),
    ]
    last = None
    for m in moves:
        last = bk.try_move(*m)
        assert last.legal
    assert bk.game_result() == "draw_repetition"


def test_repetition_does_not_trigger_too_early():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(7, 6), sq(5, 5))
    bk.try_move(sq(0, 1), sq(2, 2))
    bk.try_move(sq(5, 5), sq(7, 6))
    bk.try_move(sq(2, 2), sq(0, 1))
    # Only 1 repetition of the start position so far (initial + once back).
    assert bk.game_result() is None


def test_castling_rights_in_position_key():
    # Same placement, different castling rights → different keys.
    pieces = {
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }
    bk1 = make_backend(pieces)
    bk2 = make_backend(pieces, castling_rights={"WK": False, "WQ": True, "BK": True, "BQ": True})
    assert bk1._position_key() != bk2._position_key()


def test_ep_target_in_position_key():
    pieces = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)}
    bk1 = make_backend(pieces)
    bk2 = make_backend(pieces, ep_target=sq(5, 4))
    assert bk1._position_key() != bk2._position_key()


def test_side_to_move_in_position_key():
    pieces = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)}
    bk1 = make_backend(pieces, turn=WHITE)
    bk2 = make_backend(pieces, turn=BLACK)
    assert bk1._position_key() != bk2._position_key()
