import pytest

from backend.backend import Backend
from domain.pgn.load import parse_pgn
from tests.helpers import (
    BLACK, WHITE, K, B, N, P,
    make_backend, piece, sq,
)


@pytest.mark.parametrize(
    "piece_map, expected",
    [
        pytest.param(
            {sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)},
            "draw_insufficient_material",
            id="kvk_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 5): piece(B, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            "draw_insufficient_material",
            id="kb_v_k_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 6): piece(N, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            "draw_insufficient_material",
            id="kn_v_k_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 0): piece(B, WHITE),
                sq(0, 4): piece(K, BLACK),
                sq(0, 7): piece(B, BLACK),
            },
            "draw_insufficient_material",
            id="kb_v_kb_same_square_color_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 6): piece(N, WHITE),
                sq(0, 4): piece(K, BLACK),
                sq(0, 1): piece(N, BLACK),
            },
            "draw_insufficient_material",
            id="kn_v_kn_draw_lichess_convention",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 1): piece(N, WHITE),
                sq(7, 6): piece(N, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            "draw_insufficient_material",
            id="knn_v_k_draw_fide_5_2_2",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 0): piece(B, WHITE),
                sq(0, 0): piece(B, BLACK),
                sq(0, 4): piece(K, BLACK),
            },
            None,
            id="kb_v_kb_opposite_square_color_not_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 5): piece(B, WHITE),
                sq(7, 6): piece(N, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            None,
            id="kbn_v_k_mate_exists_not_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(7, 0): piece(B, WHITE),
                sq(7, 7): piece(B, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            None,
            id="kbb_v_k_mate_exists_not_draw",
        ),
        pytest.param(
            {
                sq(7, 4): piece(K, WHITE),
                sq(6, 0): piece(P, WHITE),
                sq(0, 4): piece(K, BLACK),
            },
            None,
            id="kp_v_k_not_draw",
        ),
    ],
)
def test_insufficient_material(piece_map, expected):
    """FIDE auto-draw set: lone B/N and KN v KN/KNN v K draw; same-square-color
    opposite bishops draw; KBN/KBB/KP keep mating chances so game_result() is None."""
    assert make_backend(piece_map).game_result() == expected


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
    """Regression: a saved game decayed to K+N v K+N at ply 70 (35... Nxh7) but
    the PGN kept playing; the engine must auto-draw there, not at 36. Nd5+."""
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
