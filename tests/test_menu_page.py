"""The lean menu router: it hosts the setup card and the History page over the persistent
battle backdrop, reports the avoid-rect the battle should route around for whichever page is
showing, and forwards clicks/scroll/keys to the active foreground."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.menu_page import MenuPage, PAGE_CARD, PAGE_HISTORY


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


class _Card:
    def __init__(self):
        self._outer = pg.Rect(280, 80, 440, 600)
        self._tile_rect = pg.Rect(470, 100, 60, 60)
        self.clicks = []

    def set_rect(self, rect):
        self._outer = pg.Rect(rect)

    def draw(self):
        pass

    def handle_click(self, pos):
        self.clicks.append(pos)
        return True


class _History:
    def __init__(self):
        self.rect = pg.Rect(0, 0, 0, 0)
        self.clicks = []
        self.scrolls = []

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)

    def draw(self):
        pass

    def handle_click(self, pos):
        self.clicks.append(pos)
        return True

    def handle_scroll(self, pos, dy):
        self.scrolls.append(dy)
        return True


def _page():
    card, hist = _Card(), _History()
    mp = MenuPage(pg.display.get_surface(), card, hist)
    mp.set_rect(pg.Rect(0, 0, 1000, 800), 40, pg.Rect(280, 80, 440, 600))
    return mp, card, hist


def test_defaults_to_card():
    mp, _, _ = _page()
    assert mp.page == PAGE_CARD


def test_set_page_switches():
    mp, _, _ = _page()
    mp.set_page(PAGE_HISTORY)
    assert mp.page == PAGE_HISTORY


def test_avoid_rect_follows_active_page():
    mp, card, hist = _page()
    assert mp.avoid_rect() == card._outer
    mp.set_page(PAGE_HISTORY)
    assert mp.avoid_rect() == hist.rect


def test_logo_rect_only_on_card():
    mp, card, _ = _page()
    assert mp.logo_rect() == card._tile_rect
    mp.set_page(PAGE_HISTORY)
    assert mp.logo_rect() == pg.Rect(0, 0, 0, 0)


def test_history_rect_is_wide_and_capped():
    mp, _, hist = _page()
    assert hist.rect.width > 600
    assert hist.rect.width <= 860


def test_history_rect_is_centered_in_window():
    mp, _, hist = _page()
    assert abs(hist.rect.centerx - 500) <= 1


def test_handle_click_delegates_to_active_foreground():
    mp, card, hist = _page()
    mp.handle_click((500, 400))
    assert card.clicks == [(500, 400)]
    mp.set_page(PAGE_HISTORY)
    mp.handle_click((500, 400))
    assert hist.clicks == [(500, 400)]


def test_handle_scroll_routes_to_history_only():
    mp, _, hist = _page()
    assert mp.handle_scroll((500, 400), -1) is False
    mp.set_page(PAGE_HISTORY)
    assert mp.handle_scroll((500, 400), -1) is True
    assert hist.scrolls == [-1]
