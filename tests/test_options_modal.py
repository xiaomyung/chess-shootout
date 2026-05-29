"""OptionsModal / PathRow: draw lays out close + Change/Reset rects, clicks
route to the right callback, the value getter is re-read every frame, and
out-of-bounds clicks are consumed while the modal stays open."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modals.options import OptionsModal, PathRow
from frontend.visual.colors import Colors


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((900, 700))
    yield
    pg.quit()


def _modal():
    modal = OptionsModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(100, 100, 420, 320))
    return modal


def test_show_makes_visible_and_draw_paints_modal():
    """draw paints the light_grey_menu fill and lays out the close button."""
    modal = _modal()
    row = PathRow("Data folder", lambda: "/tmp/x", lambda: None, lambda: None)
    modal.show([row])
    assert modal.is_visible() is True
    modal.draw()
    fill_px = modal.window.get_at((modal.rect.x + 2, modal.rect.centery))[:3]
    assert fill_px == pg.Color(Colors.light_grey_menu)[:3]
    assert modal._close_rect.width > 0 and modal.rect.contains(modal._close_rect)


def test_close_button_hides_and_calls_on_close():
    modal = _modal()
    closed = []
    modal.show([], on_close=lambda: closed.append(True))
    modal.draw()
    modal.handle_click(modal._close_rect.center)
    assert modal.is_visible() is False
    assert closed == [True]


@pytest.mark.parametrize(
    "rect_attr, callback_index",
    [
        pytest.param("_change_rect", 0, id="change_button_invokes_on_change"),
        pytest.param("_reset_rect", 1, id="reset_button_invokes_on_reset"),
    ],
)
def test_pathrow_button_click_invokes_callback(rect_attr, callback_index):
    """Clicking a PathRow button fires its callback and reports consumed."""
    fired = [[], []]
    row = PathRow(
        "Data folder", lambda: "/tmp/x",
        lambda: fired[0].append(True), lambda: fired[1].append(True),
    )
    modal = _modal()
    modal.show([row])
    modal.draw()
    assert modal.handle_click(getattr(row, rect_attr).center) is True
    assert fired[callback_index] == [True]
    assert fired[1 - callback_index] == []


def test_click_outside_is_consumed_and_stays_open():
    modal = _modal()
    modal.show([])
    modal.draw()
    assert modal.handle_click((5, 5)) is True
    assert modal.is_visible() is True


def test_pathrow_value_getter_read_each_frame():
    """draw re-invokes the getter every frame so live path changes show up."""
    calls = {"n": 0}

    def getter():
        calls["n"] += 1
        return "/a"

    row = PathRow("Data folder", getter, lambda: None, lambda: None)
    modal = _modal()
    modal.show([row])
    modal.draw()
    after_first = calls["n"]
    assert after_first >= 1
    modal.draw()
    assert calls["n"] > after_first
