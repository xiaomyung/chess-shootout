import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modals.options import OptionsModal, PathRow


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


def test_show_makes_visible_and_draw_runs():
    modal = _modal()
    row = PathRow("Data folder", lambda: "/tmp/x", lambda: None, lambda: None)
    modal.show([row])
    assert modal.is_visible() is True
    modal.draw()  # must not raise


def test_close_button_hides_and_calls_on_close():
    modal = _modal()
    closed = []
    modal.show([], on_close=lambda: closed.append(True))
    modal.draw()
    modal.handle_click(modal._close_rect.center)
    assert modal.is_visible() is False
    assert closed == [True]


def test_change_and_reset_invoke_callbacks():
    changed, reset = [], []
    row = PathRow(
        "Data folder", lambda: "/tmp/x",
        lambda: changed.append(True), lambda: reset.append(True),
    )
    modal = _modal()
    modal.show([row])
    modal.draw()
    assert modal.handle_click(row._change_rect.center) is True
    assert changed == [True]
    assert modal.handle_click(row._reset_rect.center) is True
    assert reset == [True]


def test_click_outside_is_consumed_and_stays_open():
    modal = _modal()
    modal.show([])
    modal.draw()
    assert modal.handle_click((5, 5)) is True
    assert modal.is_visible() is True


def test_pathrow_value_is_read_live():
    box = {"v": "/a"}
    row = PathRow("Data folder", lambda: box["v"], lambda: None, lambda: None)
    modal = _modal()
    modal.show([row])
    modal.draw()
    box["v"] = "/b"
    modal.draw()  # re-reads the getter each frame
    assert row.value_getter() == "/b"
