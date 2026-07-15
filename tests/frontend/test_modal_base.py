"""BaseModal's set_rect/font scaffolding plus its visibility contract.

set_rect copies the rect and fires _on_rect_changed; fonts scale off rect
height with a min_size floor; show()/hide()/is_visible() flip a real
`visible` attribute.
"""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.modals.base import BaseModal, MODAL_CUT


_pygame_init = pygame_display(600, 400)


@pytest.fixture
def window():
    return pg.display.get_surface()


def test_base_modal_default_contract(window):
    """Empty rect + inert handle_click out of the box."""
    modal = BaseModal(window)
    assert modal.rect == pg.Rect(0, 0, 0, 0)
    assert modal.rect.size == (0, 0)
    assert modal.handle_click((0, 0)) is False
    assert modal.handle_click((50, 50)) is False


def test_base_modal_is_hidden_by_default(window):
    assert BaseModal(window).is_visible() is False


def test_base_modal_show_hide_toggle_visible(window):
    """The default show()/hide() flip the real `visible` attribute is_visible() reads."""
    modal = BaseModal(window)
    assert modal.visible is False
    modal.show()
    assert modal.visible is True
    assert modal.is_visible() is True
    modal.hide()
    assert modal.visible is False
    assert modal.is_visible() is False


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


def test_draw_shell_wears_the_cut_corner_notch():
    """The panel shell is a notch polygon, not a rounded rect: tr/bl corners are

    transparent past the cut on an owned surface, while the body and the
    untouched corners stay opaque.
    """
    w, h = 200, 120
    owned = pg.Surface((w, h), pg.SRCALPHA)
    modal = BaseModal(owned)
    modal.set_rect(pg.Rect(0, 0, w, h))
    modal.draw_shell()
    assert owned.get_at((w - 2, 2))[3] == 0
    assert owned.get_at((2, h - 2))[3] == 0
    assert owned.get_at((w // 2, h // 2))[3] == 255
    assert owned.get_at((2, 2))[3] == 255
    assert owned.get_at((w - 2, h - 2))[3] == 255
    assert owned.get_at((w - MODAL_CUT - 4, 2))[3] == 255
