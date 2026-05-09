
from backend.backend import Backend
from frontend.pgn.load import parse_pgn
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


_KN_VS_KN_PGN = """\
[Event "Casual Game"]
[Site "?"]
[Date "2026.05.08"]
[Round "?"]
[White "Player 1"]
[Black "Player 2"]
[Result "0-1"]
[TimeControl "600+5"]

1. f4 d5 2. e4 dxe4 3. f5 e3 4. dxe3 Qxd1+ 5. Kxd1 Bxf5 6. Bb5+ Nc6 7. Bd2 O-O-O \
8. Nf3 g5 9. Nxg5 Nf6 10. Nxf7 e5 11. Nxh8 Bc5 12. Ng6 hxg6 13. Rf1 Bd3 14. Rxf6 \
e4 15. Rxg6 Bxe3 16. Rg3 Nd4 17. Rxe3 Nxc2 18. Nc3 Bxb5 19. Rf3 e3 20. Rxe3 Nxe3+ \
21. Ke1 Rxd2 22. Rd1 Nxg2+ 23. Kxd2 Bd7 24. Ke2 c5 25. Rxd7 c4 26. Rxb7 Nf4+ \
27. Ke3 Ne6 28. Rxa7 Nc5 29. b3 cxb3 30. Rc7+ Kxc7 31. axb3 Nxb3 32. h4 Nc5 \
33. h5 Ne6 34. h6 Ng5 35. h7 Nxh7 36. Nd5+ Kd6 0-1
"""


def test_replay_pgn_kn_vs_kn_auto_draws():
    # Regression for the saved game that decayed to K+N v K+N but kept playing.
    # After 35... Nxh7 the position is K+N v K+N — engine must auto-draw at
    # ply 70 (the saved PGN incorrectly continued with 36. Nd5+ Kd6).
    parsed = parse_pgn(_KN_VS_KN_PGN)
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
