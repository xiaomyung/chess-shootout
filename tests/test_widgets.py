import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.visual import widgets
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.frontend.visual.widgets import (
    BUTTON_LABEL_PADDING_PX,
    draw_button, draw_button_row,
    fit_text_to_rect,
    wrap_words,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def font():
    return get_font(14, bold=True)


def _button_fill_pixel(surface, rect):
    return surface.get_at((rect.x + 8, rect.centery))[:3]


def test_build_ko_badge_paints_and_winks_amber(font):
    plain = widgets.build_ko_badge(8, font, 28, winking=False)
    wink = widgets.build_ko_badge(8, font, 28, winking=True)
    assert plain.get_width() > 0 and plain.get_height() > 0, "the badge renders pixels"
    assert pg.image.tostring(plain, "RGBA") != pg.image.tostring(wink, "RGBA"), \
        "the amber wink recolors the badge"


@pytest.mark.parametrize(
    "force_pressed, expected_bg",
    [
        pytest.param(False, Colors.surface_raised, id="idle_fills_surface_raised"),
        pytest.param(True, Colors.surface_active, id="pressed_fills_surface_active"),
    ],
)
def test_draw_button_fills_state_color(font, force_pressed, expected_bg):
    """draw_button paints the state background (idle=surface_raised, pressed=surface_active)."""
    surface = pg.display.get_surface()
    rect = pg.Rect(10, 10, 100, 30)
    surface.fill((0, 0, 0), rect)
    draw_button(surface, rect, "OK", font, force_pressed=force_pressed)
    assert _button_fill_pixel(surface, rect) == pg.Color(expected_bg)[:3]


def test_draw_button_idle_and_pressed_render_differently(font):
    """Pixel block-diff: idle and force_pressed paint different fills (idle vs pressed)."""
    surface = pg.display.get_surface()
    rect = pg.Rect(10, 10, 100, 30)
    surface.fill((0, 0, 0), rect)
    draw_button(surface, rect, "OK", font, force_pressed=False)
    idle_fill = _button_fill_pixel(surface, rect)
    surface.fill((0, 0, 0), rect)
    draw_button(surface, rect, "OK", font, force_pressed=True)
    pressed_fill = _button_fill_pixel(surface, rect)
    assert idle_fill != pressed_fill
    assert idle_fill == pg.Color(Colors.surface_raised)[:3]
    assert pressed_fill == pg.Color(Colors.surface_active)[:3]


def test_draw_button_row_returns_keyed_rects(font):
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 300, 30)
    buttons = [("Yes", "yes"), ("No", "no")]
    rects = draw_button_row(surface, rect, buttons, font, gap=10)
    assert set(rects.keys()) == {"yes", "no"}
    assert rects["yes"].height == 30
    assert rects["yes"].width == pytest.approx(145, abs=1)


def test_fit_text_returns_original_when_label_fits():
    f = get_font(24, bold=True)
    surf = f.render("OK", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 200, 60)
    assert fit_text_to_rect(surf, rect) is surf


def test_fit_text_scales_when_too_wide():
    f = get_font(32, bold=True)
    surf = f.render("AVeryLongLabelThatWillNotFit", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 50, 30)
    fitted = fit_text_to_rect(surf, rect)
    assert fitted is not surf
    assert fitted.get_width() <= rect.width - 2 * BUTTON_LABEL_PADDING_PX
    assert fitted.get_height() <= rect.height - 2 * BUTTON_LABEL_PADDING_PX


def test_fit_text_scales_when_too_tall():
    f = get_font(80, bold=True)
    surf = f.render("X", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 200, 20)
    fitted = fit_text_to_rect(surf, rect)
    assert fitted is not surf
    assert fitted.get_height() <= rect.height - 2 * BUTTON_LABEL_PADDING_PX


def test_fit_text_clamps_to_minimum_one_pixel():
    f = get_font(200, bold=True)
    surf = f.render("Massive", True, (255, 255, 255))
    rect = pg.Rect(0, 0, 5, 5)
    fitted = fit_text_to_rect(surf, rect)
    assert fitted.get_width() >= 1 and fitted.get_height() >= 1


def test_draw_button_does_not_scale_when_label_fits(font, monkeypatch):
    """The supersample background scales to rect.size; a label that fits triggers no extra
    text-fit scale to a different size."""
    surface = pg.display.get_surface()
    rect = pg.Rect(0, 0, 200, 40)
    calls = []
    real_scale = pg.transform.smoothscale
    monkeypatch.setattr(
        widgets.pg.transform, "smoothscale",
        lambda surf, size, *a, **kw: (calls.append(size), real_scale(surf, size, *a, **kw))[1],
    )
    draw_button(surface, rect, "OK", font)
    text_scales = [size for size in calls if tuple(size) != (rect.width, rect.height)]
    assert text_scales == []


def test_draw_button_scales_long_label_to_fit(monkeypatch):
    """A too-long label forces one extra scale below rect.size (ignoring the background
    scale that targets rect.size)."""
    surface = pg.display.get_surface()
    big_font = get_font(24, bold=True)
    rect = pg.Rect(0, 0, 50, 30)
    calls = []
    real_scale = pg.transform.smoothscale
    monkeypatch.setattr(
        widgets.pg.transform, "smoothscale",
        lambda surf, size, *a, **kw: (calls.append(size), real_scale(surf, size, *a, **kw))[1],
    )
    draw_button(surface, rect, "ReallyLongButtonLabel", big_font)
    text_scales = [size for size in calls if tuple(size) != (rect.width, rect.height)]
    assert len(text_scales) == 1
    scaled_w, _ = text_scales[0]
    assert scaled_w <= rect.width - 2 * BUTTON_LABEL_PADDING_PX


def test_wrap_words_keeps_each_word_on_its_own_line_at_min_width():
    lines = wrap_words("alpha beta gamma", get_font(12, bold=True), 1)
    assert lines == ["alpha", "beta", "gamma"]


def test_wrap_words_does_not_split_a_single_word():
    font = get_font(12, bold=True)
    assert wrap_words("supercalifragilistic", font, 1) == ["supercalifragilistic"]


def test_wrap_words_stays_one_line_when_width_is_ample():
    font = get_font(12, bold=True)
    assert wrap_words("short text here", font, 10000) == ["short text here"]


def test_wrap_words_caps_at_max_lines_and_drops_the_remainder():
    font = get_font(12, bold=True)
    lines = wrap_words("alpha beta gamma delta", font, 1, max_lines=2)
    assert lines == ["alpha", "beta"]


def test_wrap_words_empty_text_returns_the_text_as_a_single_line():
    font = get_font(12, bold=True)
    assert wrap_words("", font, 100) == [""]
