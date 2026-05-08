from pathlib import Path

from backend.backend import Backend
from frontend.pgn_load import parse_pgn
from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def test_kvk_is_draw():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    assert bk.game_result() == "draw_insufficient_material"


def test_kbvk_is_draw():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 5): piece(B, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() == "draw_insufficient_material"


def test_knvk_is_draw():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 6): piece(N, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() == "draw_insufficient_material"


def test_kbvkb_same_color_is_draw():
    # Both bishops on light squares: a1 (sum 7+0=7 odd) and h8 (0+7=7 odd) — same color.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(B, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 7): piece(B, BLACK),
    })
    assert bk.game_result() == "draw_insufficient_material"


def test_kbvkb_opposite_color_not_draw():
    # White bishop on a1 (odd), black bishop on a8 (0+0=0 even) — opposite colors.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(B, WHITE),
        sq(0, 0): piece(B, BLACK),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != "draw_insufficient_material"


def test_knvkn_is_draw():
    # FIDE-strict allows a helpmate, but the project follows lichess/chess.com
    # convention: K+N v K+N has no forced mate, so we auto-draw it.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 6): piece(N, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 1): piece(N, BLACK),
    })
    assert bk.game_result() == "draw_insufficient_material"


def test_knn_v_k_is_draw():
    # FIDE 5.2.2: two knights cannot force checkmate against a lone king.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 1): piece(N, WHITE),
        sq(7, 6): piece(N, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() == "draw_insufficient_material"


def test_kbn_v_k_not_draw():
    # K+B+N v K is sufficient — bishop-and-knight mate exists.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 5): piece(B, WHITE),
        sq(7, 6): piece(N, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != "draw_insufficient_material"


def test_kbb_v_k_not_draw():
    # K with two bishops on any colors v lone K — sufficient material; mate exists.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(B, WHITE),
        sq(7, 7): piece(B, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != "draw_insufficient_material"


def test_kp_v_k_not_draw():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 0): piece(P, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != "draw_insufficient_material"


def test_replay_pgn_kn_vs_kn_auto_draws():
    # Regression for the saved game that decayed to K+N v K+N but kept playing.
    # After 35... Nxh7 the position is K+N v K+N — engine must auto-draw at
    # ply 70 (the saved PGN incorrectly continued with 36. Nd5+ Kd6).
    pgn_path = Path(__file__).resolve().parents[1] / "games" / "game-20260508-134345.pgn"
    parsed = parse_pgn(pgn_path.read_text())
    bk = Backend()
    bk.new_game()
    triggered_at = None
    for i, san in enumerate(parsed.moves, start=1):
        result = bk.apply_san(san)
        if not result.legal:
            break
        if bk.game_result() == "draw_insufficient_material":
            triggered_at = i
            break
    assert triggered_at == 70, f"expected draw at ply 70 (35... Nxh7), got {triggered_at}"
