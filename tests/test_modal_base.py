"""BaseModal / BasePanel share set_rect/font scaffolding.

Both copy the rect on set_rect, fire _on_rect_changed, and size fonts off rect
height with a min_size floor. They diverge only on consumes_clicks_when_visible
(modal True, panel False) and is_visible (modal-only, defaults hidden).
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modals.base import BaseModal
from frontend.panels.base import BasePanel


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((600, 400))
    yield
    pg.quit()


@pytest.fixture
def window():
    return pg.display.get_surface()


@pytest.mark.parametrize(
    "cls, expected_consumes",
    [
        pytest.param(BaseModal, True, id="modal_consumes_clicks_when_visible"),
        pytest.param(BasePanel, False, id="panel_does_not_consume_clicks"),
    ],
)
def test_base_widget_default_contract(window, cls, expected_consumes):
    """Both bases share an empty rect + inert handle_click; only the consume flag differs."""
    widget = cls(window)
    assert widget.rect == pg.Rect(0, 0, 0, 0)
    assert widget.rect.size == (0, 0)
    assert widget.consumes_clicks_when_visible is expected_consumes
    assert widget.handle_click((0, 0)) is False
    assert widget.handle_click((50, 50)) is False


def test_base_modal_is_hidden_by_default(window):
    """BaseModal defines is_visible (panels do not); the unconfigured default is hidden."""
    assert BaseModal(window).is_visible() is False


def test_base_modal_set_rect_stores_a_copy(window):
    """set_rect copies the rect, so later mutation of the source does not leak in."""
    modal = BaseModal(window)
    src = pg.Rect(10, 20, 100, 200)
    modal.set_rect(src)
    assert modal.rect == pg.Rect(10, 20, 100, 200)
    src.update(999, 999, 999, 999)
    assert modal.rect == pg.Rect(10, 20, 100, 200)


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
    """A tiny rect (height/factor below the floor) clamps to min_size, not the raw size."""
    modal = BaseModal(window)
    modal.set_rect(pg.Rect(0, 0, 200, 10))
    floored = modal.font(factor=4, min_size=18).get_height()
    raw = modal.font(factor=4, min_size=1).get_height()
    assert floored >= 18
    assert floored > raw


def test_base_panel_set_rect_and_font(window):
    """Panel stores its rect verbatim and sizes fonts off height once above the floor."""
    panel = BasePanel(window)
    panel.set_rect(pg.Rect(0, 0, 100, 200))
    assert panel.rect == pg.Rect(0, 0, 100, 200)
    tall = panel.font(factor=10, min_size=12).get_height()
    panel.set_rect(pg.Rect(0, 0, 100, 100))
    short = panel.font(factor=10, min_size=12).get_height()
    assert tall >= 12
    assert tall > short
