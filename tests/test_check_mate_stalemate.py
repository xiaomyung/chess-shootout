from backend.backend import Backend
from tests.helpers import (
    BLACK, WHITE, K, Q, R, P,
    make_backend, piece, sq, play_moves,
)


def test_fools_mate():
    # 1. f3 e5 2. g4 Qh4#  -- the fastest mate.
    bk = Backend()
    bk.new_game()
    play_moves(bk, [
        (sq(6, 5), sq(5, 5)),  # white f2-f3
        (sq(1, 4), sq(3, 4)),  # black e7-e5
        (sq(6, 6), sq(4, 6)),  # white g2-g4
    ])
    result = bk.try_move(sq(0, 3), sq(4, 7))  # Qd8-h4#
    assert result.legal
    assert result.is_checkmate
    assert bk.game_result() == "black_wins"


def test_back_rank_mate():
    # White king on h1, white pawns on f2/g2/h2, black rook on a1 sweeping the rank.
    bk = make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    assert bk.is_in_check(WHITE)
    assert bk.game_result() == "black_wins"


def test_classic_stalemate():
    # Black king a8, white king c7, white queen b6 — black to move, no legal moves, not in check.
    bk = make_backend({
        sq(0, 0): piece(K, BLACK),
        sq(1, 2): piece(K, WHITE),
        sq(2, 1): piece(Q, WHITE),
    }, turn=BLACK, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    assert not bk.is_in_check(BLACK)
    assert bk.game_result() == "draw_stalemate"


def test_check_does_not_end_game_if_response_exists():
    bk = Backend()
    bk.new_game()
    # 1. e4 e5 2. Bc4 — no immediate threats; game ongoing.
    play_moves(bk, [
        (sq(6, 4), sq(4, 4)),
        (sq(1, 4), sq(3, 4)),
        (sq(7, 5), sq(4, 2)),
    ])
    assert bk.game_result() is None
    assert not bk.is_game_over()
