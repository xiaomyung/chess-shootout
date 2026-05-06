from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def test_knight_open_board_eight_moves():
    # Knight on d4 (row 4, col 3) on an empty board should have 8 moves.
    bk = make_backend({sq(4, 3): piece(N, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    moves = bk.legal_moves_from(sq(4, 3))
    assert len(moves) == 8


def test_knight_corner_two_moves():
    # Knight on a1 has only 2 legal moves (b3, c2).
    bk = make_backend({sq(7, 0): piece(N, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    moves = bk.legal_moves_from(sq(7, 0))
    assert set(moves) == {sq(5, 1), sq(6, 2)}


def test_bishop_blocked_by_friendly():
    # Bishop on d4, friendly pawn on f6 blocks the NE diagonal.
    bk = make_backend({
        sq(4, 3): piece(B, WHITE),
        sq(2, 5): piece(P, WHITE),
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    moves = set(bk.legal_moves_from(sq(4, 3)))
    assert sq(2, 5) not in moves
    assert sq(3, 4) in moves
    assert sq(1, 6) not in moves


def test_bishop_captures_enemy():
    bk = make_backend({
        sq(4, 3): piece(B, WHITE),
        sq(2, 5): piece(P, BLACK),
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    moves = set(bk.legal_moves_from(sq(4, 3)))
    assert sq(2, 5) in moves
    assert sq(1, 6) not in moves  # cannot pass through captured piece


def test_rook_horizontal_and_vertical():
    # Rook on e4, friendly king on e1. Up=4, down=2 (blocked by king), left=4, right=3.
    bk = make_backend({sq(4, 4): piece(R, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 0): piece(K, BLACK)})
    moves = set(bk.legal_moves_from(sq(4, 4)))
    assert len(moves) == 4 + 2 + 4 + 3
    assert sq(7, 4) not in moves


def test_queen_combines_rook_and_bishop():
    bk = make_backend({sq(4, 4): piece(Q, WHITE), sq(7, 0): piece(K, WHITE), sq(0, 7): piece(K, BLACK)})
    moves = bk.legal_moves_from(sq(4, 4))
    assert len(moves) == 27  # max queen mobility on otherwise empty board


def test_king_one_square_moves():
    bk = make_backend({sq(4, 4): piece(K, WHITE), sq(0, 0): piece(K, BLACK)})
    moves = set(bk.legal_moves_from(sq(4, 4)))
    assert moves == {sq(3, 3), sq(3, 4), sq(3, 5), sq(4, 3), sq(4, 5), sq(5, 3), sq(5, 4), sq(5, 5)}


def test_pawn_single_and_double_push_from_start():
    bk = make_backend({sq(6, 4): piece(P, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    moves = set(bk.legal_moves_from(sq(6, 4)))
    assert moves == {sq(5, 4), sq(4, 4)}


def test_pawn_no_double_push_after_first_move():
    # Pawn on rank 5 (row 3) — only single push.
    bk = make_backend({sq(3, 4): piece(P, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    moves = set(bk.legal_moves_from(sq(3, 4)))
    assert moves == {sq(2, 4)}


def test_pawn_diagonal_capture():
    bk = make_backend({
        sq(4, 4): piece(P, WHITE),
        sq(3, 3): piece(P, BLACK),
        sq(3, 5): piece(P, BLACK),
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    moves = set(bk.legal_moves_from(sq(4, 4)))
    assert sq(3, 3) in moves
    assert sq(3, 5) in moves
    assert sq(3, 4) in moves


def test_pawn_blocked_cannot_push():
    bk = make_backend({
        sq(6, 4): piece(P, WHITE),
        sq(5, 4): piece(P, BLACK),
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    moves = bk.legal_moves_from(sq(6, 4))
    assert moves == []


def test_pawn_does_not_attack_forward_square():
    # Existing behavior: a pawn does not threaten its forward square.
    bk = make_backend({sq(4, 4): piece(P, WHITE), sq(7, 7): piece(K, WHITE), sq(0, 0): piece(K, BLACK)})
    assert not bk._is_square_attacked(sq(3, 4), WHITE)


def test_pawn_attacks_diagonals():
    bk = make_backend({sq(4, 4): piece(P, WHITE), sq(7, 7): piece(K, WHITE), sq(0, 0): piece(K, BLACK)})
    assert bk._is_square_attacked(sq(3, 3), WHITE)
    assert bk._is_square_attacked(sq(3, 5), WHITE)
