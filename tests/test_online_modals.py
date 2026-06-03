import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from online.client import OnlineClient
from frontend.modals.wait import WaitModal


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((600, 400))
    yield
    pg.quit()


def test_modal_starts_hidden():
    m = WaitModal(pg.display.get_surface())
    assert not m.is_visible()
    assert m.button_rects == {}


def test_wait_modal_show_stores_search_info_and_lays_out_cancel():
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 440, 400))
    m.show("Rapid", "10 + 5", on_cancel=lambda: None)
    assert m.is_visible()
    assert m.mode_label == "Rapid"
    assert m.tc_text == "10 + 5"
    m.draw()
    assert set(m.button_rects) == {"cancel"}


def test_wait_modal_cancel_fires_callback():
    cancelled = []
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 440, 400))
    m.show("Blitz", "5 + 0", on_cancel=lambda: cancelled.append(True))
    m.draw()
    handled = m.handle_click(m.button_rects["cancel"].center)
    assert handled
    assert cancelled == [True]
    assert not m.is_visible()
    assert m.button_rects == {}


def test_wait_modal_elapsed_updates():
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 440, 400))
    m.show("Rapid", "10 + 5", on_cancel=lambda: None)
    m.set_elapsed(7)
    assert m.elapsed == 7


def test_online_client_drains_no_events_initially():
    c = OnlineClient()
    assert c.drain_inbound() == []
    assert c.state == "disconnected"
