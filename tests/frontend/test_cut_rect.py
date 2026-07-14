import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.visual.draw import cut_rect_surface
from tests.helpers import rgb, scan_region


_pygame_init = pygame_display(80, 80)

SIZE = 60
CUT = 16
FILL = "#334455"
BORDER = "#ffcc00"


def _has_color_in(surface, color, x0, y0, x1, y1):
    return scan_region(surface, pg.Rect(x0, y0, x1 - x0, y1 - y0), color)


def test_fill_color_inside_body():
    surf = cut_rect_surface((SIZE, SIZE), CUT, FILL, corners=("tr",))
    px = surf.get_at((SIZE // 2, SIZE // 2))
    assert px[:3] == rgb(FILL)
    assert px[3] == 255


def test_transparent_outside_clipped_diagonal():
    surf = cut_rect_surface((SIZE, SIZE), CUT, FILL, corners=("tr",))
    assert surf.get_at((SIZE - 3, 3))[3] == 0


@pytest.mark.parametrize("corners,inside_point,outside_point", [
    pytest.param(("tl",), (SIZE - 3, 3), (3, 3), id="tl"),
    pytest.param(("tr",), (3, 3), (SIZE - 3, 3), id="tr"),
    pytest.param(("br",), (3, 3), (SIZE - 3, SIZE - 3), id="br"),
    pytest.param(("bl",), (SIZE - 3, 3), (3, SIZE - 3), id="bl"),
])
def test_each_corner_variant_clips_only_that_corner(corners, inside_point, outside_point):
    surf = cut_rect_surface((SIZE, SIZE), CUT, FILL, corners=corners)
    assert surf.get_at(inside_point)[3] == 255
    assert surf.get_at(outside_point)[3] == 0


def test_border_follows_edge_and_diagonal():
    surf = cut_rect_surface((SIZE, SIZE), CUT, FILL, border=BORDER, border_width=2,
                             corners=("tr",))
    assert _has_color_in(surf, BORDER, 0, 0, 10, 4)
    assert _has_color_in(surf, BORDER, SIZE - CUT - 4, 0, SIZE, CUT + 4)


def test_memoization_same_args_same_object():
    a = cut_rect_surface((SIZE, SIZE), CUT, FILL, border=BORDER, corners=("tr", "bl"))
    b = cut_rect_surface((SIZE, SIZE), CUT, FILL, border=BORDER, corners=("tr", "bl"))
    assert a is b


def test_memoization_distinguishes_corner_order():
    a = cut_rect_surface((SIZE, SIZE), CUT, FILL, corners=("tr", "bl"))
    b = cut_rect_surface((SIZE, SIZE), CUT, FILL, corners=("bl", "tr"))
    assert a is b


def test_degenerate_cut_zero_is_plain_rect():
    surf = cut_rect_surface((SIZE, SIZE), 0, FILL, corners=("tr",))
    for point in [(1, 1), (SIZE - 2, 1), (1, SIZE - 2), (SIZE - 2, SIZE - 2)]:
        assert surf.get_at(point)[3] == 255
