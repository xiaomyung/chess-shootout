import pytest

from backend.backend import Backend
from frontend.pgn.generate import generate_pgn
from tests.helpers import (
    BLACK, WHITE, K, Q, R, N, P,
    NO_CASTLING, make_backend, piece, sq,
)


CORNERS = {sq(7, 7): piece(K, WHITE), sq(0, 0): piece(K, BLACK)}


def test_simple_pawn_push():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    assert bk.move_history[-1].san == "e4"


@pytest.mark.parametrize(
    "piece_map, move, expected_san",
    [
        pytest.param(
            {sq(4, 4): piece(N, WHITE), sq(6, 0): piece(P, WHITE), **CORNERS},
            (sq(4, 4), sq(2, 5)), "Nf6",
            id="piece_move_no_disambiguation",
        ),
        pytest.param(
            {sq(4, 4): piece(P, WHITE), sq(3, 5): piece(P, BLACK), **CORNERS},
            (sq(4, 4), sq(3, 5)), "exf5",
            id="pawn_capture_uses_file_letter",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE), sq(7, 0): piece(R, WHITE),
                sq(0, 7): piece(K, BLACK),
            },
            (sq(7, 0), sq(0, 0)), "Ra8+",
            id="check_appends_plus_suffix",
        ),
        pytest.param(
            {
                sq(7, 1): piece(N, WHITE), sq(7, 3): piece(N, WHITE),
                sq(7, 7): piece(K, WHITE), sq(0, 0): piece(K, BLACK),
                sq(1, 0): piece(P, BLACK),
            },
            (sq(7, 1), sq(5, 2)), "Nbc3",
            id="two_knights_file_disambiguation",
        ),
        pytest.param(
            {
                sq(7, 0): piece(R, WHITE), sq(4, 0): piece(R, WHITE),
                sq(7, 7): piece(K, WHITE), sq(0, 7): piece(K, BLACK),
            },
            (sq(7, 0), sq(5, 0)), "R1a3",
            id="two_rooks_rank_disambiguation",
        ),
        pytest.param(
            {
                sq(7, 3): piece(Q, WHITE), sq(2, 6): piece(Q, WHITE),
                sq(4, 6): piece(P, BLACK), sq(7, 7): piece(K, WHITE),
                sq(0, 0): piece(K, BLACK),
            },
            (sq(7, 3), sq(4, 6)), "Qdxg4",
            id="two_queens_file_disambig_with_capture",
        ),
        pytest.param(
            {
                sq(7, 3): piece(Q, WHITE), sq(0, 3): piece(Q, WHITE),
                sq(7, 7): piece(K, WHITE), sq(2, 4): piece(K, BLACK),
            },
            (sq(7, 3), sq(4, 3)), "Q1d4",
            id="two_queens_same_file_rank_disambig",
        ),
        pytest.param(
            {
                sq(7, 3): piece(Q, WHITE), sq(0, 0): piece(Q, WHITE),
                sq(7, 7): piece(K, WHITE), sq(3, 5): piece(K, BLACK),
            },
            (sq(7, 3), sq(4, 3)), "Qd4",
            id="no_disambig_when_one_piece_reaches",
        ),
    ],
)
def test_single_move_san(piece_map, move, expected_san):
    """Disambiguation needs pre-move board state; the black pawn in the two-knights
    case keeps KNN v K above the insufficient-material auto-draw threshold."""
    bk = make_backend(piece_map, castling_rights=NO_CASTLING)
    bk.try_move(*move)
    assert bk.move_history[-1].san == expected_san


@pytest.mark.parametrize(
    "rook_square, target_col, expected_san",
    [
        pytest.param(sq(7, 7), 6, "O-O", id="kingside"),
        pytest.param(sq(7, 0), 2, "O-O-O", id="queenside"),
    ],
)
def test_castle_san(rook_square, target_col, expected_san):
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        rook_square: piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    bk.try_move(sq(7, 4), sq(7, target_col))
    assert bk.move_history[-1].san == expected_san


def test_mate_suffix():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 5), sq(5, 5))
    bk.try_move(sq(1, 4), sq(3, 4))
    bk.try_move(sq(6, 6), sq(4, 6))
    bk.try_move(sq(0, 3), sq(4, 7))
    assert bk.move_history[-1].san == "Qh4#"


@pytest.mark.parametrize(
    "piece_map, move, expected_san",
    [
        pytest.param(
            {
                sq(1, 0): piece(P, WHITE), sq(7, 7): piece(K, WHITE),
                sq(4, 7): piece(K, BLACK),
            },
            (sq(1, 0), sq(0, 0)), "a8=Q",
            id="promotion_san",
        ),
        pytest.param(
            {
                sq(1, 1): piece(P, WHITE), sq(0, 0): piece(R, BLACK),
                sq(7, 7): piece(K, WHITE), sq(4, 7): piece(K, BLACK),
            },
            (sq(1, 1), sq(0, 0)), "bxa8=Q",
            id="promotion_with_capture_san",
        ),
    ],
)
def test_promotion_san(piece_map, move, expected_san):
    bk = make_backend(piece_map, castling_rights=NO_CASTLING)
    bk.try_move(*move)
    bk.promote(move[1], Q)
    assert bk.move_history[-1].san == expected_san


def test_user_promotion_game_disambiguation():
    """Real-game replay where a promoted queen forces file/rank disambiguation across
    several plies; SAN must distinguish the two same-color queens at each branch."""
    bk = Backend()
    bk.new_game()

    def play(f, t):
        r = bk.try_move(f, t)
        assert r.legal, f"illegal move {f} -> {t}"
        return r

    play(sq(6, 4), sq(4, 4))
    play(sq(1, 3), sq(3, 3))
    play(sq(4, 4), sq(3, 4))
    play(sq(0, 3), sq(2, 3))
    play(sq(3, 4), sq(2, 4))
    play(sq(0, 4), sq(0, 3))
    play(sq(2, 4), sq(1, 5))
    play(sq(2, 3), sq(2, 2))
    play(sq(1, 5), sq(0, 6))
    bk.promote(sq(0, 6), Q)
    play(sq(2, 2), sq(2, 3))
    play(sq(0, 6), sq(0, 5))
    play(sq(0, 3), sq(1, 3))
    play(sq(7, 3), sq(4, 6))
    assert bk.move_history[-1].san == "Qg4+"
    play(sq(1, 3), sq(2, 2))
    play(sq(0, 5), sq(5, 5))
    assert bk.move_history[-1].san == "Qff3"
    play(sq(2, 3), sq(2, 7))
    play(sq(4, 6), sq(4, 0))
    assert bk.move_history[-1].san == "Qa4+"
    play(sq(2, 2), sq(3, 2))
    play(sq(5, 5), sq(5, 2))
    assert bk.move_history[-1].san == "Qc3+"
    play(sq(3, 2), sq(2, 1))
    play(sq(5, 2), sq(4, 1))
    assert bk.move_history[-1].san == "Qcb4#"

    pgn = generate_pgn(bk.move_history, bk.game_result())
    assert "Qff3" in pgn
    assert "Qcb4#" in pgn
    assert "8. Qff3" in pgn
    assert "11. Qcb4#" in pgn
