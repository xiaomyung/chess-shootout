from tests.helpers import (
    BLACK, WHITE, K, R, N,
    make_backend, piece, sq,
)


def _empty_back_rank(extra=None):
    pieces = {
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 0): piece(R, BLACK),
        sq(0, 7): piece(R, BLACK),
    }
    if extra:
        pieces.update(extra)
    return pieces


def test_white_kingside_castle_legal():
    bk = make_backend(_empty_back_rank())
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) in moves


def test_white_queenside_castle_legal():
    bk = make_backend(_empty_back_rank())
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 2) in moves


def test_kingside_castle_executes_correctly():
    bk = make_backend(_empty_back_rank())
    result = bk.try_move(sq(7, 4), sq(7, 6))
    assert result.legal
    assert bk.state[7][6].type == K
    assert bk.state[7][5].type == R  # rook jumped to f1
    assert bk.state[7][7] is None
    assert bk.state[7][4] is None
    # Castling rights for that color cleared.
    assert not bk.castling_rights["WK"]
    assert not bk.castling_rights["WQ"]


def test_queenside_castle_executes_correctly():
    bk = make_backend(_empty_back_rank())
    bk.try_move(sq(7, 4), sq(7, 2))
    assert bk.state[7][2].type == K
    assert bk.state[7][3].type == R
    assert bk.state[7][0] is None


def test_cannot_castle_through_check():
    # Black rook on f8 attacks f1 — blocks kingside castle.
    bk = make_backend(_empty_back_rank({sq(0, 5): piece(R, BLACK)}))
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves


def test_cannot_castle_out_of_check():
    # Black rook on e8 puts white king in check — castling not allowed.
    bk = make_backend(_empty_back_rank({sq(0, 4): piece(R, BLACK)}))
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves
    assert sq(7, 2) not in moves


def test_cannot_castle_into_check():
    # Black knight on h3 attacks g1 — blocks kingside castle destination.
    bk = make_backend(_empty_back_rank({sq(5, 7): piece(N, BLACK)}))
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves


def test_cannot_castle_when_king_has_moved():
    bk = make_backend(_empty_back_rank(),
                      castling_rights={"WK": False, "WQ": False, "BK": True, "BQ": True})
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves
    assert sq(7, 2) not in moves


def test_cannot_castle_when_kingside_rook_has_moved():
    bk = make_backend(_empty_back_rank(),
                      castling_rights={"WK": False, "WQ": True, "BK": True, "BQ": True})
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves
    assert sq(7, 2) in moves  # queenside still available


def test_cannot_castle_with_piece_between_king_and_rook():
    bk = make_backend(_empty_back_rank({sq(7, 6): piece(N, WHITE)}))
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves


def test_queenside_castle_legal_when_b1_attacked():
    # Black rook on b8 attacks b1 — but b1 is not on the king's path; queenside is still legal.
    bk = make_backend(_empty_back_rank({sq(0, 1): piece(R, BLACK)}))
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 2) in moves


def test_black_kingside_castle():
    bk = make_backend(_empty_back_rank(), turn=BLACK)
    moves = bk.legal_moves_from(sq(0, 4))
    assert sq(0, 6) in moves
    bk.try_move(sq(0, 4), sq(0, 6))
    assert bk.state[0][6].type == K
    assert bk.state[0][5].type == R


def test_black_queenside_castle():
    bk = make_backend(_empty_back_rank(), turn=BLACK)
    bk.try_move(sq(0, 4), sq(0, 2))
    assert bk.state[0][2].type == K
    assert bk.state[0][3].type == R


def test_capturing_h1_rook_revokes_only_kingside():
    # Black rook captures white rook on h1.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 7): piece(R, BLACK),
    }, turn=BLACK)
    bk.try_move(sq(0, 7), sq(7, 7))
    assert not bk.castling_rights["WK"]
    assert bk.castling_rights["WQ"]


def test_capturing_a8_rook_revokes_only_black_queenside():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 0): piece(R, BLACK),
    }, turn=WHITE)
    bk.try_move(sq(7, 0), sq(0, 0))
    assert bk.castling_rights["BK"]
    assert not bk.castling_rights["BQ"]
