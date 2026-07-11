import pytest

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


@pytest.mark.parametrize(
    "king_target_col",
    [
        pytest.param(6, id="kingside_g1_available"),
        pytest.param(2, id="queenside_c1_available"),
    ],
)
def test_white_castle_target_in_legal_moves(king_target_col):
    bk = make_backend(_empty_back_rank())
    assert sq(7, king_target_col) in bk.legal_moves_from(sq(7, 4))


@pytest.mark.parametrize(
    "color, home_row, king_to_col, rook_from_col, rook_to_col, prefix",
    [
        pytest.param(WHITE, 7, 6, 7, 5, "W", id="white_kingside"),
        pytest.param(WHITE, 7, 2, 0, 3, "W", id="white_queenside"),
        pytest.param(BLACK, 0, 6, 7, 5, "B", id="black_kingside"),
        pytest.param(BLACK, 0, 2, 0, 3, "B", id="black_queenside"),
    ],
)
def test_castle_moves_king_and_rook_and_revokes_rights(
    color, home_row, king_to_col, rook_from_col, rook_to_col, prefix
):
    bk = make_backend(_empty_back_rank(), turn=color)
    result = bk.try_move(sq(home_row, 4), sq(home_row, king_to_col))
    assert result.legal
    assert bk.state[home_row][king_to_col].type == K
    assert bk.state[home_row][rook_to_col].type == R
    assert bk.state[home_row][rook_from_col] is None
    assert bk.state[home_row][4] is None
    assert not bk.castling_rights[prefix + "K"]
    assert not bk.castling_rights[prefix + "Q"]


def test_cannot_castle_through_check():
    """Black rook on f8 attacks f1, the king's transit square — blocks kingside."""
    bk = make_backend(_empty_back_rank({sq(0, 5): piece(R, BLACK)}))
    assert sq(7, 6) not in bk.legal_moves_from(sq(7, 4))


def test_cannot_castle_out_of_check():
    """Black rook on e8 checks the white king — neither side may castle."""
    bk = make_backend(_empty_back_rank({sq(0, 4): piece(R, BLACK)}))
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves
    assert sq(7, 2) not in moves


def test_cannot_castle_into_check():
    """Black knight on h3 attacks g1, the king's destination — blocks kingside."""
    bk = make_backend(_empty_back_rank({sq(5, 7): piece(N, BLACK)}))
    assert sq(7, 6) not in bk.legal_moves_from(sq(7, 4))


def test_cannot_castle_when_king_has_moved():
    bk = make_backend(_empty_back_rank(),
                      castling_rights={"WK": False, "WQ": False, "BK": True, "BQ": True})
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves
    assert sq(7, 2) not in moves


def test_cannot_castle_when_kingside_rook_has_moved():
    """Losing one rook's rights leaves the other side castleable."""
    bk = make_backend(_empty_back_rank(),
                      castling_rights={"WK": False, "WQ": True, "BK": True, "BQ": True})
    moves = bk.legal_moves_from(sq(7, 4))
    assert sq(7, 6) not in moves
    assert sq(7, 2) in moves


def test_cannot_castle_with_piece_between_king_and_rook():
    bk = make_backend(_empty_back_rank({sq(7, 6): piece(N, WHITE)}))
    assert sq(7, 6) not in bk.legal_moves_from(sq(7, 4))


def test_queenside_castle_legal_when_b1_attacked():
    """b1 is attacked but not on the king's path, so queenside stays legal."""
    bk = make_backend(_empty_back_rank({sq(0, 1): piece(R, BLACK)}))
    assert sq(7, 2) in bk.legal_moves_from(sq(7, 4))


def test_capturing_h1_rook_revokes_only_kingside():
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
