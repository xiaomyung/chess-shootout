from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq,
)


def test_kvk_is_draw():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    assert bk.game_result() == 'draw_insufficient_material'


def test_kbvk_is_draw():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 5): piece(B, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() == 'draw_insufficient_material'


def test_knvk_is_draw():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 6): piece(N, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() == 'draw_insufficient_material'


def test_kbvkb_same_color_is_draw():
    # Both bishops on light squares: a1 (sum 7+0=7 odd) and h8 (0+7=7 odd) — same color.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(B, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 7): piece(B, BLACK),
    })
    assert bk.game_result() == 'draw_insufficient_material'


def test_kbvkb_opposite_color_not_draw():
    # White bishop on a1 (odd), black bishop on a8 (0+0=0 even) — opposite colors.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(B, WHITE),
        sq(0, 0): piece(B, BLACK),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != 'draw_insufficient_material'


def test_knvkn_not_draw():
    # KN vs KN is not in our auto-draw set (not FIDE-required).
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 6): piece(N, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 1): piece(N, BLACK),
    })
    assert bk.game_result() != 'draw_insufficient_material'


def test_kbb_v_k_not_draw():
    # K with two bishops on any colors v lone K — sufficient material; mate exists.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(7, 0): piece(B, WHITE),
        sq(7, 7): piece(B, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != 'draw_insufficient_material'


def test_kp_v_k_not_draw():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(6, 0): piece(P, WHITE),
        sq(0, 4): piece(K, BLACK),
    })
    assert bk.game_result() != 'draw_insufficient_material'
