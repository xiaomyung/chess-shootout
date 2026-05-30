from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K,
    make_backend, piece, sq,
)


def test_same_position_same_key():
    """Two independent constructions of the start position hash equal; turn is in the key."""
    bk1 = Backend()
    bk1.new_game()
    bk2 = Backend()
    bk2.new_game()
    assert bk1._position_key() == bk2._position_key()

    bk2.turn = BLACK
    assert bk1._position_key() != bk2._position_key()


def test_position_key_changes_after_move():
    bk = Backend()
    bk.new_game()
    before = bk._position_key()
    bk.try_move(sq(6, 4), sq(4, 4))
    after = bk._position_key()
    assert before != after


def test_transposition_yields_same_key():
    """Two move orders reaching the same position must produce identical keys."""
    a = Backend()
    a.new_game()
    a.try_move(sq(6, 4), sq(4, 4))
    a.try_move(sq(1, 4), sq(3, 4))
    a.try_move(sq(7, 6), sq(5, 5))
    a.try_move(sq(0, 1), sq(2, 2))

    b = Backend()
    b.new_game()
    b.try_move(sq(7, 6), sq(5, 5))
    b.try_move(sq(1, 4), sq(3, 4))
    b.try_move(sq(6, 4), sq(4, 4))
    b.try_move(sq(0, 1), sq(2, 2))

    assert a._position_key() == b._position_key()


def test_piece_instances_not_in_key():
    """Key depends on (type, color), not Piece object identity."""
    pieces1 = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)}
    pieces2 = {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)}
    bk1 = make_backend(pieces1)
    bk2 = make_backend(pieces2)
    assert bk1._position_key() == bk2._position_key()
