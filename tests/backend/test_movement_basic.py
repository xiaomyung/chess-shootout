import pytest

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    assert_legal_moves, make_backend, piece, sq,
)


@pytest.mark.parametrize(
    "pieces, from_sq, expected",
    [
        pytest.param(
            {sq(4, 3): piece(N, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "d4", "c6 e6 b5 f5 b3 f3 c2 e2",
            id="knight_open_board_eight_moves",
        ),
        pytest.param(
            {sq(7, 0): piece(N, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "a1", "b3 c2",
            id="knight_corner_two_moves",
        ),
        pytest.param(
            {sq(4, 3): piece(B, WHITE), sq(2, 5): piece(P, WHITE),
             sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "d4", "a7 b6 c5 e5 c3 e3 b2 f2 a1 g1",
            id="bishop_stops_short_of_friendly_blocker",
        ),
        pytest.param(
            {sq(4, 3): piece(B, WHITE), sq(2, 5): piece(P, BLACK),
             sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "d4", "a7 b6 c5 e5 f6 c3 e3 b2 f2 a1 g1",
            id="bishop_captures_enemy_not_past_it",
        ),
        pytest.param(
            {sq(4, 4): piece(R, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 0): piece(K, BLACK)},
            "e4", "e8 e7 e6 e5 a4 b4 c4 d4 f4 g4 h4 e3 e2",
            id="rook_horizontal_and_vertical_king_blocks",
        ),
        pytest.param(
            {sq(4, 4): piece(Q, WHITE), sq(7, 0): piece(K, WHITE), sq(0, 7): piece(K, BLACK)},
            "e4",
            "a8 e8 b7 e7 h7 c6 e6 g6 d5 e5 f5 a4 b4 c4 d4 f4 g4 h4 d3 e3 f3 c2 e2 g2 b1 e1 h1",
            id="queen_combines_rook_and_bishop_27",
        ),
        pytest.param(
            {sq(4, 4): piece(K, WHITE), sq(0, 0): piece(K, BLACK)},
            "e4", "d5 e5 f5 d4 f4 d3 e3 f3",
            id="king_one_square_in_all_directions",
        ),
        pytest.param(
            {sq(6, 4): piece(P, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "e2", "e3 e4",
            id="pawn_single_and_double_push_from_start",
        ),
        pytest.param(
            {sq(3, 4): piece(P, WHITE), sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "e5", "e6",
            id="pawn_no_double_push_after_first_move",
        ),
        pytest.param(
            {sq(4, 4): piece(P, WHITE), sq(3, 3): piece(P, BLACK), sq(3, 5): piece(P, BLACK),
             sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "e4", "d5 e5 f5",
            id="pawn_pushes_and_captures_both_diagonals",
        ),
        pytest.param(
            {sq(6, 4): piece(P, WHITE), sq(5, 4): piece(P, BLACK),
             sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "e2", "",
            id="pawn_blocked_head_on_has_no_moves",
        ),
    ],
)
def test_legal_moves_match_piece_shape(pieces, from_sq, expected):
    assert_legal_moves(make_backend(pieces), from_sq, expected)


@pytest.mark.parametrize(
    "target, expected",
    [
        pytest.param(sq(3, 4), False, id="pawn_does_not_attack_forward_square"),
        pytest.param(sq(3, 3), True, id="pawn_attacks_left_diagonal"),
        pytest.param(sq(3, 5), True, id="pawn_attacks_right_diagonal"),
    ],
)
def test_pawn_attack_geometry(target, expected):
    """A pawn threatens only its two forward diagonals, never the push square."""
    bk = make_backend({
        sq(4, 4): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 0): piece(K, BLACK),
    })
    assert bk._is_square_attacked(target, WHITE) is expected
