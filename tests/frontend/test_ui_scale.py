"""The game/review UI-scale is the same formula the menu uses. ``compute_layout`` stamps
``scale`` onto its ``LayoutRects`` via the shared ``compute_ui_scale``, so a game window and
a menu window of the same size resolve to an identical scale, and the helper clamps to the
shared ``[UI_SCALE_MIN, UI_SCALE_MAX]`` bounds. ``scale_floor`` now lives in ``visual.draw``
and is re-exported from ``menu.view`` as the same object so every menu sub-view keeps
importing it unchanged."""

from chessshootout.frontend.layout import (
    compute_layout, compute_ui_scale, UI_SCALE_MIN, UI_SCALE_MAX)
from chessshootout.frontend.menu.layout import compute_menu_layout
from chessshootout.frontend.window_chrome import WindowChrome
from chessshootout.frontend.visual.draw import scale_floor as draw_scale_floor
from chessshootout.frontend.menu.view import scale_floor as view_scale_floor


def test_compute_layout_scale_matches_menu_formula():
    """compute_layout(...).scale reproduces compute_ui_scale for the same avail-height
    inputs, and equals the value the menu layout derives for the same window."""
    top = WindowChrome.HEIGHT
    rects = compute_layout(
        1200, 900, mode="local", focus_mode=False, focus_show="line", board_size=8)
    assert rects.scale == compute_ui_scale(1200, 900 - top)
    assert rects.scale == compute_menu_layout(1200, 900, top).scale


def test_scale_floor_shared_object_across_modules():
    """scale_floor moved to visual.draw; menu.view re-exports the SAME object so every
    menu sub-view keeps importing it from menu.view unchanged."""
    assert view_scale_floor is draw_scale_floor
    assert view_scale_floor(10, 2) == 20


def test_compute_ui_scale_clamps_to_bounds():
    """A huge window saturates at UI_SCALE_MAX, a tiny one floors at UI_SCALE_MIN."""
    assert compute_ui_scale(100000, 100000) == UI_SCALE_MAX
    assert compute_ui_scale(1, 1) == UI_SCALE_MIN
