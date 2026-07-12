"""focus/layout.py geometry: centered square, sizes vs the normal board, strip
flanking, and the shared square_stack refactor guard."""


import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.focus import layout as fl
from chessshootout.frontend import layout as L
from chessshootout.frontend.window_chrome import WindowChrome

TOP = WindowChrome.HEIGHT
SHR = L.STRIP_HEIGHT_RATIO
SGR = L.STRIP_GAP_RATIO


_pg = pygame_display(1000, 800)


def _normal_board_width(w, h):
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(w, h)
    app.draw_frame()
    return app.game.board.rect.width


@pytest.mark.parametrize("size", [(1000, 800), (1600, 900), (1200, 1000)])
def test_line_board_equals_nothing_full_square(size):
    nothing = fl.focus_square(size, TOP, "nothing")
    line = fl.focus_square(size, TOP, "line")
    assert line == nothing


@pytest.mark.parametrize("size", [(1000, 800), (1600, 900)])
def test_focus_board_is_centered_square(size):
    r = fl.focus_square(size, TOP, "nothing")
    w, h = size
    assert r.width == r.height
    assert abs(r.centerx - w // 2) <= 1
    assert abs(r.centery - (TOP + (h - TOP) // 2)) <= 1


@pytest.mark.parametrize("size", [(1000, 800), (1600, 900)])
def test_focus_nothing_bigger_than_normal(size):
    focus = fl.focus_square(size, TOP, "nothing").width
    assert focus > _normal_board_width(*size)


def test_time_line_rects_in_board_margins():
    board = fl.focus_square((1000, 800), TOP, "line")
    grid_top, grid_bottom = board.top + 40, board.bottom - 40
    grid_left, grid_w = board.left + 40, board.width - 80
    top, bottom = fl.time_line_rects(board, grid_top, grid_bottom, grid_left, grid_w)
    assert top.width == grid_w and bottom.width == grid_w
    assert top.left == grid_left and bottom.left == grid_left
    assert abs(top.centery - grid_top) <= 1
    assert abs(bottom.centery - grid_bottom) <= 1
    assert top.height == bottom.height
    assert 3 <= top.height <= 6


def test_time_line_height_scales_and_clamps():
    assert fl.time_line_height(1000) > fl.time_line_height(300)
    assert fl.time_line_height(300) == 3
    assert fl.time_line_height(5000) == 6


@pytest.mark.parametrize("area", [(628, 760), (952, 760), (500, 500)])
def test_square_stack_reserve_matches_manual(area):
    aw, ah = area
    board, sh, sg, stack = fl.square_stack(aw, ah, True, SHR, SGR, 12)
    factor = 1 + 2 * (SHR + SGR)
    manual = max(min(aw - 24, (ah - 24) / factor), fl.MIN_BOARD_PX)
    assert board == manual
    assert stack == board + 2 * (sh + sg)


def test_square_stack_no_reserve_is_plain_square():
    board, sh, sg, stack = fl.square_stack(1000, 760, False, SHR, SGR, 24)
    assert sh == 0.0 and sg == 0.0
    assert stack == board
    assert board == max(min(1000 - 48, 760 - 48), fl.MIN_BOARD_PX)
