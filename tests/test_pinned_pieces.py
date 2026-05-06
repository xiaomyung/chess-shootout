from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def test_absolute_pin_blocks_move_off_line():
    # White king on e1, white knight on e2, black rook on e8 pins the knight.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 4): piece(N, WHITE),
        sq(0, 4): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    })
    moves = bk.legal_moves_from(sq(6, 4))
    # Knight cannot move at all (any knight move leaves king exposed).
    assert moves == []


def test_pinned_rook_can_move_along_pin_line():
    # White rook pinned along the e-file by black queen — can move within the pin.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 4): piece(R, WHITE),
        sq(0, 4): piece(Q, BLACK),
        sq(0, 0): piece(K, BLACK),
    })
    moves = set(bk.legal_moves_from(sq(6, 4)))
    # Rook can capture the queen or move to any e-file square between.
    assert sq(0, 4) in moves
    assert sq(5, 4) in moves
    # But cannot leave the e-file.
    assert sq(6, 5) not in moves


def test_check_must_be_addressed():
    # Black rook on e3 gives check to white king on e1; white must block, capture, or move out.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),  # rook can block at e2 or e3? No — rook on a1 reaches e1 along rank 1 only by moving.
        sq(5, 4): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    })
    # White rook on a1 cannot block (can't reach the e-file in one move) but king can move.
    # Verify only king-escape moves are legal for the king and the rook has no rescue.
    king_moves = set(bk.legal_moves_from(sq(7, 4)))
    # King can move to d1 or f1 (not blocked, not on e-file).
    assert sq(7, 3) in king_moves
    assert sq(7, 5) in king_moves
    # Rook on a1 can move along the rank or up the a-file; but none addresses check unless blocking the e-file.
    rook_moves = set(bk.legal_moves_from(sq(7, 0)))
    # Anything that doesn't address check is illegal — only blocking on the e-file (e.g., e7 e2) counts.
    # The rook on a1 cannot reach the e-file in one move, so it has no legal moves.
    assert rook_moves == set()
