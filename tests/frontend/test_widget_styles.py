import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.frontend.visual.widgets import draw_button, draw_button_row
from chessshootout.frontend.visual.toast import ENTER_MS as TOAST_ENTER_MS, Toast


_pygame_init = pygame_display(900, 400)


@pytest.fixture
def font():
    return get_font(16, bold=True)


def test_selected_button_fills_pressed_color(font):
    surface = pg.display.get_surface()
    surface.fill((0, 0, 0))
    rect = pg.Rect(20, 20, 120, 40)
    draw_button(surface, rect, "X", font, selected=True)
    assert surface.get_at((rect.centerx, rect.y + 4))[:3] == pg.Color(Colors.surface_active)[:3]


def test_primary_button_uses_accent_fill(font):
    surface = pg.display.get_surface()
    surface.fill((0, 0, 0))
    rect = pg.Rect(20, 20, 160, 44)
    draw_button(surface, rect, "START", font, primary=True)
    assert surface.get_at((rect.x + 6, rect.centery))[:3] == pg.Color(Colors.accent)[:3]


def test_button_row_guards_empty_and_narrow(font):
    surface = pg.display.get_surface()
    assert draw_button_row(surface, pg.Rect(0, 0, 200, 30), [], font, 6) == {}
    narrow = pg.Rect(0, 0, 4, 30)
    assert draw_button_row(surface, narrow, [("a", "a"), ("b", "b"), ("c", "c")],
                           font, 6) == {}


def _band_has_color(surface, rgb):
    return any(
        surface.get_at((x, y))[:3] == rgb
        for y in range(8, 60) for x in range(0, surface.get_width(), 3)
    )


def _settle_draw(toast, surface):
    now = toast._bubbles[-1]["shown_at_ms"] + TOAST_ENTER_MS
    for step in range(0, 500, 16):
        surface.fill((0, 0, 0))
        toast.draw(now + step)


def test_toast_info_and_hype_use_distinct_backgrounds():
    surface = pg.display.get_surface()
    toast = Toast(surface)
    toast.show("reconnected", kind="info")
    _settle_draw(toast, surface)
    assert _band_has_color(surface, pg.Color(Colors.surface)[:3])

    toast.hide()
    toast.show("first blood", kind="hype")
    _settle_draw(toast, surface)
    assert _band_has_color(surface, pg.Color(Colors.accent)[:3])


def test_toast_renders_below_top_inset():
    surface = pg.display.get_surface()
    toast = Toast(surface)
    toast.top_inset = 50
    toast.show("synced", kind="info")
    _settle_draw(toast, surface)
    bg = pg.Color(Colors.surface)[:3]

    def band_has(y0, y1):
        return any(surface.get_at((x, y))[:3] == bg
                   for y in range(y0, y1) for x in range(0, surface.get_width(), 3))

    assert not band_has(0, 50), "toast must not paint over the title-bar inset"
    assert band_has(50, 100), "toast should appear just below the inset"
