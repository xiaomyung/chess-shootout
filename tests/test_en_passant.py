from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, R, P,
    make_backend, piece, sq,
)


def test_en_passant_capture_executes():
    # White pawn on e5; black plays f7-f5; white captures e.p. landing on f6.
    bk = Backend()
    bk.new_game()
    # Manually arrange: white pawn to e5, black pawn to f7 (already there).
    # Play: 1. e4 a6 2. e5 f5 (black double-push next to white e5 pawn)
    bk.try_move(sq(6, 4), sq(4, 4))
    bk.try_move(sq(1, 0), sq(2, 0))
    bk.try_move(sq(4, 4), sq(3, 4))
    bk.try_move(sq(1, 5), sq(3, 5))
    # EP target should be f6 = (2, 5).
    assert bk.en_passant_target == sq(2, 5)
    moves = bk.legal_moves_from(sq(3, 4))
    assert sq(2, 5) in moves
    result = bk.try_move(sq(3, 4), sq(2, 5))
    assert result.legal
    assert bk.state[2][5].type == P  # white pawn lands on f6
    assert bk.state[3][5] is None  # black pawn on f5 captured


def test_ep_target_cleared_after_one_ply():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    assert bk.en_passant_target == sq(5, 4)
    bk.try_move(sq(1, 0), sq(2, 0))
    assert bk.en_passant_target is None


def test_ep_pin_is_illegal():
    # Classic en-passant pin: white K and P share the same rank as a black rook,
    # with the just-pushed black pawn between them. exd6 e.p. clears two pawns from
    # the rank and exposes the white king.
    bk = make_backend({
        sq(3, 7): piece(K, WHITE),
        sq(3, 4): piece(P, WHITE),
        sq(3, 3): piece(P, BLACK),
        sq(3, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, ep_target=sq(2, 3))
    moves = bk.legal_moves_from(sq(3, 4))
    assert sq(2, 3) not in moves


def test_two_square_push_only_sets_target_on_that_ply():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(5, 4))  # single push e3
    assert bk.en_passant_target is None


def test_ep_resets_halfmove_clock():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(3, 4): piece(P, WHITE),
        sq(3, 3): piece(P, BLACK),
        sq(0, 4): piece(K, BLACK),
    }, turn=WHITE, ep_target=sq(2, 3), halfmove_clock=42)
    bk.try_move(sq(3, 4), sq(2, 3))
    assert bk.halfmove_clock == 0
