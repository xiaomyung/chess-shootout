import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend import widgets
from frontend.widgets import (
    BUTTON_LABEL_PADDING_PX,
    draw_button, draw_button_row, draw_button_column, draw_selector,
    fit_text_to_rect,
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


def testdraw_button_smoke_idle(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 100, 30)
    draw_button(surface, rect, "OK", font)


def testdraw_button_smoke_force_pressed(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 100, 30)
    draw_button(surface, rect, "OK", font, force_pressed=True)


def testdraw_button_row_returns_keyed_rects(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 300, 30)
    buttons = [("Yes", "yes"), ("No", "no")]
    rects = draw_button_row(surface, rect, buttons, font, gap=10)
    assert set(rects.keys()) == {"yes", "no"}
    assert rects["yes"].height == 30
    # Width: (300 - 10) / 2 = 145.
    assert rects["yes"].width == pytest.approx(145, abs=1)


def testdraw_button_column_returns_keyed_rects(font):
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


def test_fit_text_returns_original_when_label_fits():
    f = pg.font.SysFont("Arial", 24, bold=True)
    surf = f.render("OK", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 200, 60)
    assert fit_text_to_rect(surf, rect) is surf


def test_fit_text_scales_when_too_wide():
    f = pg.font.SysFont("Arial", 32, bold=True)
    surf = f.render("AVeryLongLabelThatWillNotFit", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 50, 30)
    fitted = fit_text_to_rect(surf, rect)
    assert fitted is not surf
    assert fitted.get_width() <= rect.width - 2 * BUTTON_LABEL_PADDING_PX
    assert fitted.get_height() <= rect.height - 2 * BUTTON_LABEL_PADDING_PX


def test_fit_text_scales_when_too_tall():
    f = pg.font.SysFont("Arial", 80, bold=True)
    surf = f.render("X", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 200, 20)
    fitted = fit_text_to_rect(surf, rect)
    assert fitted is not surf
    assert fitted.get_height() <= rect.height - 2 * BUTTON_LABEL_PADDING_PX


def test_fit_text_clamps_to_minimum_one_pixel():
    f = pg.font.SysFont("Arial", 200, bold=True)
    surf = f.render("Massive", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 5, 5)
    fitted = fit_text_to_rect(surf, rect)
    assert fitted.get_width() >= 1 and fitted.get_height() >= 1


def test_draw_button_does_not_scale_when_label_fits(font, monkeypatch):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 200, 40)
    calls = []
    real_scale = pg.transform.smoothscale
    monkeypatch.setattr(
        widgets.pg.transform, "smoothscale",
        lambda surf, size, *a, **kw: (calls.append(size), real_scale(surf, size, *a, **kw))[1],
    )
    draw_button(surface, rect, "OK", font)
    assert calls == []


def test_draw_button_scales_long_label_to_fit(monkeypatch):
    surface = pg.display.get_surface()
    big_font = pg.font.SysFont("Arial", 24, bold=True)
    rect = pg.Rect(0, 0, 50, 30)
    calls = []
    real_scale = pg.transform.smoothscale
    monkeypatch.setattr(
        widgets.pg.transform, "smoothscale",
        lambda surf, size, *a, **kw: (calls.append(size), real_scale(surf, size, *a, **kw))[1],
    )
    draw_button(surface, rect, "ReallyLongButtonLabel", big_font)
    assert len(calls) == 1
    scaled_w, _ = calls[0]
    assert scaled_w <= rect.width - 2 * BUTTON_LABEL_PADDING_PX
