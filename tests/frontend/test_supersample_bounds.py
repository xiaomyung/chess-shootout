"""supersample is the last-resort backstop under every hand-drawn shape (Deck
#96, layer 3): a degenerate rect from some future layout bug must degrade to an
empty surface, never raise 'Invalid resolution for Surface' mid-frame. The real
fix is the clamped layout, pinned with positive-rect tests in
test_window_resize.py, so this guard cannot hide a layout regression."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    cut_rect_surface, rounded_rect_surface, supersample,
)


_pygame_init = pygame_display(200, 200)


def _render_spy(calls):
    def render(big, scale):
        calls.append((big.get_size(), scale))
        pg.draw.rect(big, (255, 0, 0, 255), big.get_rect())
    return render


@pytest.mark.parametrize("size, expected", [
    pytest.param((-5, 10), (0, 10), id="negative_width"),
    pytest.param((10, -5), (10, 0), id="negative_height"),
    pytest.param((-18, -51), (0, 0), id="both_negative"),
    pytest.param((0, 5), (0, 5), id="zero_width"),
    pytest.param((0, 0), (0, 0), id="zero_area"),
    pytest.param(-3, (0, 0), id="negative_square"),
    pytest.param(0, (0, 0), id="zero_square"),
])
def test_degenerate_sizes_degrade_to_an_empty_surface(size, expected):
    calls = []
    out = supersample(size, _render_spy(calls), scale=4)
    assert out.get_size() == expected
    assert calls == [((expected[0] * 4, expected[1] * 4), 4)]
    assert out.get_flags() & pg.SRCALPHA


@pytest.mark.parametrize("size, expected", [
    pytest.param((12, 7), (12, 7), id="rect"),
    pytest.param(9, (9, 9), id="square"),
])
def test_normal_sizes_are_untouched(size, expected):
    calls = []
    out = supersample(size, _render_spy(calls), scale=3)
    assert out.get_size() == expected
    assert calls == [((expected[0] * 3, expected[1] * 3), 3)]
    r, g, b, a = out.get_at((expected[0] // 2, expected[1] // 2))
    assert r >= 250 and g == b == 0 and a >= 250


def test_cut_rect_surface_with_the_shipped_crash_size_does_not_raise():
    out = cut_rect_surface((-18, -51), 16, Colors.surface, border=Colors.border)
    assert out.get_size() == (0, 0)


def test_cut_rect_surface_with_a_negative_height_keeps_the_width():
    out = cut_rect_surface((49, -21), 16, Colors.surface, border=Colors.border)
    assert out.get_size() == (49, 0)


def test_rounded_rect_surface_with_a_negative_width_does_not_raise():
    out = rounded_rect_surface((-38, 79), 6, Colors.well_deep)
    assert out.get_size() == (0, 79)
