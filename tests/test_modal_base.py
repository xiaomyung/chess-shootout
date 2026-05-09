"""BaseModal / BasePanel scaffolding (M12)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modal_base import BaseModal, BasePanel


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((600, 400))
    yield
    pg.quit()


@pytest.fixture
def window():
    return pg.display.get_surface()


# ---------- BaseModal ----------

def test_base_modal_default_rect_is_empty(window):
    modal = BaseModal(window)
    assert modal.rect.size == (0, 0)


def test_base_modal_set_rect_stores_a_copy(window):
    modal = BaseModal(window)
    src = pg.Rect(10, 20, 100, 200)
    modal.set_rect(src)
    src.width = 999
    assert modal.rect.width == 100  # set_rect copied the rect


def test_base_modal_set_rect_calls_hook(window):
    seen = []

    class Custom(BaseModal):
        def _on_rect_changed(self):
            seen.append(self.rect.size)

    modal = Custom(window)
    modal.set_rect(pg.Rect(0, 0, 50, 60))
    assert seen == [(50, 60)]


def test_base_modal_font_scales_with_rect_height(window):
    modal = BaseModal(window)
    modal.set_rect(pg.Rect(0, 0, 200, 200))
    bigger = modal.font(factor=4).get_height()
    modal.set_rect(pg.Rect(0, 0, 200, 80))
    smaller = modal.font(factor=4).get_height()
    assert bigger > smaller


def test_base_modal_font_respects_min_size(window):
    modal = BaseModal(window)
    modal.set_rect(pg.Rect(0, 0, 200, 10))  # tiny
    f = modal.font(factor=4, min_size=18)
    # min_size guarantees the font isn't smaller than that.
    assert f.get_height() >= 18


def test_base_modal_default_visibility_and_click(window):
    modal = BaseModal(window)
    assert modal.is_visible() is False
    assert modal.handle_click((0, 0)) is False


def test_base_modal_consumes_clicks_when_visible_default_true(window):
    modal = BaseModal(window)
    assert modal.consumes_clicks_when_visible is True


# ---------- BasePanel ----------

def test_base_panel_does_not_consume_clicks_by_default(window):
    panel = BasePanel(window)
    assert panel.consumes_clicks_when_visible is False


def test_base_panel_set_rect_and_font(window):
    panel = BasePanel(window)
    panel.set_rect(pg.Rect(0, 0, 100, 200))
    assert panel.rect == pg.Rect(0, 0, 100, 200)
    assert panel.font(factor=10, min_size=12).get_height() >= 12


def test_base_panel_default_handle_click_returns_false(window):
    panel = BasePanel(window)
    assert panel.handle_click((50, 50)) is False
