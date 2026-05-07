from backend.backend import Backend
from frontend.pgn import generate_pgn
from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


CORNERS = {sq(7, 7): piece(K, WHITE), sq(0, 0): piece(K, BLACK)}


def _no_castling():
    return {"WK": False, "WQ": False, "BK": False, "BQ": False}


def test_simple_pawn_push():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 4), sq(4, 4))
    assert bk.move_history[-1].san == "e4"


def test_simple_piece_move_no_disambiguation():
    bk = make_backend({
        sq(4, 4): piece(N, WHITE),
        sq(6, 0): piece(P, WHITE),
        **CORNERS,
    }, castling_rights=_no_castling())
    bk.try_move(sq(4, 4), sq(2, 5))
    assert bk.move_history[-1].san == "Nf6"


def test_pawn_capture_uses_file_letter():
    bk = make_backend({
        sq(4, 4): piece(P, WHITE),
        sq(3, 5): piece(P, BLACK),
        **CORNERS,
    }, castling_rights=_no_castling())
    bk.try_move(sq(4, 4), sq(3, 5))
    assert bk.move_history[-1].san == "exf5"


def test_castle_kingside_san():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 7): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    bk.try_move(sq(7, 4), sq(7, 6))
    assert bk.move_history[-1].san == "O-O"


def test_castle_queenside_san():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    bk.try_move(sq(7, 4), sq(7, 2))
    assert bk.move_history[-1].san == "O-O-O"


def test_check_suffix():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(R, WHITE),
        sq(0, 7): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(7, 0), sq(0, 0))
    assert bk.move_history[-1].san == "Ra8+"


def test_mate_suffix():
    bk = Backend()
    bk.new_game()
    bk.try_move(sq(6, 5), sq(5, 5))
    bk.try_move(sq(1, 4), sq(3, 4))
    bk.try_move(sq(6, 6), sq(4, 6))
    bk.try_move(sq(0, 3), sq(4, 7))
    assert bk.move_history[-1].san == "Qh4#"


def test_promotion_san():
    bk = make_backend({
        sq(1, 0): piece(P, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(4, 7): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(1, 0), sq(0, 0))
    bk.promote(sq(0, 0), Q)
    assert bk.move_history[-1].san == "a8=Q"


def test_promotion_with_capture_san():
    bk = make_backend({
        sq(1, 1): piece(P, WHITE),
        sq(0, 0): piece(R, BLACK),
        sq(7, 7): piece(K, WHITE),
        sq(4, 7): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(1, 1), sq(0, 0))
    bk.promote(sq(0, 0), Q)
    assert bk.move_history[-1].san == "bxa8=Q"


def test_two_knights_file_disambiguation():
    bk = make_backend({
        sq(7, 1): piece(N, WHITE),
        sq(7, 3): piece(N, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 0): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(7, 1), sq(5, 2))
    assert bk.move_history[-1].san == "Nbc3"


def test_two_rooks_rank_disambiguation():
    # Two white rooks on a-file (a1 and a4). Move a1 to a3 (a4 also reaches a3).
    # Black king tucked away so the OTHER rook doesn't accidentally check.
    bk = make_backend({
        sq(7, 0): piece(R, WHITE),
        sq(4, 0): piece(R, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(0, 7): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(7, 0), sq(5, 0))
    assert bk.move_history[-1].san == "R1a3"


def test_two_queens_after_promotion_file_disambiguation():
    # Two queens on d1 and g6 — both can reach g4. Kings far away.
    bk = make_backend({
        sq(7, 3): piece(Q, WHITE),
        sq(2, 6): piece(Q, WHITE),
        sq(4, 6): piece(P, BLACK),
        sq(7, 7): piece(K, WHITE),
        sq(0, 0): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(7, 3), sq(4, 6))
    assert bk.move_history[-1].san == "Qdxg4"


def test_two_queens_same_file_uses_rank_disambiguation():
    # Two queens on the d-file (d1 and d8). Both reach d4. Black king on e6 — not on
    # any line either queen attacks before or after the move.
    bk = make_backend({
        sq(7, 3): piece(Q, WHITE),
        sq(0, 3): piece(Q, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(2, 4): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(7, 3), sq(4, 3))
    assert bk.move_history[-1].san == "Q1d4"


def test_no_disambiguation_when_only_one_piece_can_reach():
    # Two queens (d1 and a8) but only d1 shares a line with d4. Black king on f5 sits
    # off every attack line.
    bk = make_backend({
        sq(7, 3): piece(Q, WHITE),
        sq(0, 0): piece(Q, WHITE),
        sq(7, 7): piece(K, WHITE),
        sq(3, 5): piece(K, BLACK),
    }, castling_rights=_no_castling())
    bk.try_move(sq(7, 3), sq(4, 3))
    assert bk.move_history[-1].san == "Qd4"


def test_user_promotion_game_disambiguation():
    bk = Backend()
    bk.new_game()

    def play(f, t):
        r = bk.try_move(f, t)
        assert r.legal, f"illegal move {f} -> {t}"
        return r

    play(sq(6, 4), sq(4, 4))   # 1. e4
    play(sq(1, 3), sq(3, 3))   # 1...d5
    play(sq(4, 4), sq(3, 4))   # 2. e5
    play(sq(0, 3), sq(2, 3))   # 2...Qd6
    play(sq(3, 4), sq(2, 4))   # 3. e6
    play(sq(0, 4), sq(0, 3))   # 3...Kd8
    play(sq(2, 4), sq(1, 5))   # 4. exf7
    play(sq(2, 3), sq(2, 2))   # 4...Qc6
    play(sq(1, 5), sq(0, 6))   # 5. f-pawn -> g8
    bk.promote(sq(0, 6), Q)    # =Q
    play(sq(2, 2), sq(2, 3))   # 5...Qd6
    play(sq(0, 6), sq(0, 5))   # 6. Qxf8+
    play(sq(0, 3), sq(1, 3))   # 6...Kd7
    play(sq(7, 3), sq(4, 6))   # 7. d1 -> g4 (only this queen can reach)
    assert bk.move_history[-1].san == "Qg4+"
    play(sq(1, 3), sq(2, 2))   # 7...Kc6
    play(sq(0, 5), sq(5, 5))   # 8. f8 queen -> f3 (g4 queen can ALSO reach f3, must disambiguate)
    assert bk.move_history[-1].san == "Qff3"
    play(sq(2, 3), sq(2, 7))   # 8...Qh6
    play(sq(4, 6), sq(4, 0))   # 9. Qa4+ (only g4 queen reaches a4)
    assert bk.move_history[-1].san == "Qa4+"
    play(sq(2, 2), sq(3, 2))   # 9...Kc5
    play(sq(5, 5), sq(5, 2))   # 10. Qc3+ (only f3 queen reaches c3)
    assert bk.move_history[-1].san == "Qc3+"
    play(sq(3, 2), sq(2, 1))   # 10...Kb6
    play(sq(5, 2), sq(4, 1))   # 11. c3 queen -> b4 (a4 queen also reaches; disambiguate)
    assert bk.move_history[-1].san == "Qcb4#"

    pgn = generate_pgn(bk.move_history, bk.game_result())
    assert "Qff3" in pgn
    assert "Qcb4#" in pgn
    assert "8. Qff3" in pgn
    assert "11. Qcb4#" in pgn
