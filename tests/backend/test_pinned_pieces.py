from tests.helpers import (
    BLACK, WHITE, K, Q, R, N,
    make_backend, piece, sq,
)


def test_absolute_pin_blocks_move_off_line():
    """A knight pinned to its king by a rook on the same file has no legal move."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 4): piece(N, WHITE),
        sq(0, 4): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    })
    assert bk.legal_moves_from(sq(6, 4)) == []


def test_pinned_rook_can_move_along_pin_line():
    """A rook pinned along the e-file may slide anywhere on the line, including the capture."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 4): piece(R, WHITE),
        sq(0, 4): piece(Q, BLACK),
        sq(0, 0): piece(K, BLACK),
    })
    moves = set(bk.legal_moves_from(sq(6, 4)))
    assert moves == {sq(5, 4), sq(4, 4), sq(3, 4), sq(2, 4), sq(1, 4), sq(0, 4)}


def test_check_must_be_addressed():
    """In check from a rook on the e-file, only king escapes off the line are legal."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(5, 4): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    })
    assert set(bk.legal_moves_from(sq(7, 4))) == {sq(7, 3), sq(7, 5), sq(6, 3), sq(6, 5)}
    assert bk.legal_moves_from(sq(7, 0)) == []
