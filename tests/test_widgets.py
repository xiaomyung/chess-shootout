import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.widgets import (
    _draw_button, draw_button_row, draw_button_column, draw_selector,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def font():
    return pg.font.SysFont("Arial", 14, bold=True)


def test_draw_button_smoke_idle(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 100, 30)
    _draw_button(surface, rect, "OK", font)


def test_draw_button_smoke_force_pressed(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 100, 30)
    _draw_button(surface, rect, "OK", font, force_pressed=True)


def test_draw_button_row_returns_keyed_rects(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 300, 30)
    buttons = [("Yes", "yes"), ("No", "no")]
    rects = draw_button_row(surface, rect, buttons, font, gap=10)
    assert set(rects.keys()) == {"yes", "no"}
    assert rects["yes"].height == 30
    # Width: (300 - 10) / 2 = 145.
    assert rects["yes"].width == pytest.approx(145, abs=1)


def test_draw_button_column_returns_keyed_rects(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 100, 200)
    buttons = [("A", "a"), ("B", "b"), ("C", "c")]
    rects = draw_button_column(surface, rect, buttons, font, gap=8)
    assert set(rects.keys()) == {"a", "b", "c"}
    assert rects["a"].width == 100


def test_draw_selector_returns_keyed_rects(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 400, 40)
    options = [("5 min", 5), ("10 min", 10), ("15 min", 15)]
    rects = draw_selector(surface, rect, options, font, gap=6, selected_key=10)
    assert set(rects.keys()) == {5, 10, 15}
    # Shouldn't crash for any selected key.
    draw_selector(surface, rect, options, font, gap=6, selected_key=None)


def test_draw_selector_button_widths_are_equal(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 400, 40)
    options = [("a", 1), ("b", 2), ("c", 3), ("d", 4)]
    rects = draw_selector(surface, rect, options, font, gap=6, selected_key=2)
    widths = sorted({r.width for r in rects.values()})
    # Allow tiny float tolerance.
    assert max(widths) - min(widths) < 1
