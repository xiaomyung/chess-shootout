from tests.helpers import (
    BLACK, WHITE, K, R, P,
    make_backend, piece, sq,
)


def test_fifty_move_draw_at_100_halfmoves():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=99)
    bk.try_move(sq(7, 0), sq(7, 1))  # rook shuffle, no capture, no pawn — clock += 1
    assert bk.halfmove_clock == 100
    assert bk.game_result() == "draw_fifty_move"


def test_pawn_move_resets_halfmove_clock():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 0): piece(P, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=42)
    bk.try_move(sq(6, 0), sq(5, 0))
    assert bk.halfmove_clock == 0


def test_capture_resets_halfmove_clock():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(4, 4): piece(R, WHITE),
        sq(4, 0): piece(R, BLACK),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=42)
    bk.try_move(sq(4, 4), sq(4, 0))
    assert bk.halfmove_clock == 0


def test_castling_does_not_reset_clock():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, halfmove_clock=10)
    bk.try_move(sq(7, 4), sq(7, 6))
    assert bk.halfmove_clock == 11
