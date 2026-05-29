import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.online.client import OnlineClient
from frontend.modals.server import ServerAddressModal
from frontend.modals.wait import WaitModal


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((600, 400))
    yield
    pg.quit()


@pytest.mark.parametrize(
    "modal_cls",
    [
        pytest.param(ServerAddressModal, id="server_modal"),
        pytest.param(WaitModal, id="wait_modal"),
    ],
)
def test_modal_starts_hidden(modal_cls):
    m = modal_cls(pg.display.get_surface())
    assert not m.is_visible()
    assert m.button_rects == {}


def test_server_modal_show_prefills_input():
    m = ServerAddressModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("chess.example.com:8000", on_connect=lambda addr: None)
    assert m.is_visible()
    assert m.title == "Connect to server"
    assert m.input.text == "chess.example.com:8000"


def test_server_modal_connect_invokes_callback_with_stripped_addr():
    received = []
    m = ServerAddressModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("  localhost:8000  ", on_connect=lambda addr: received.append(addr))
    m.draw()
    handled = m.handle_click(m.button_rects["connect"].center)
    assert handled
    assert received == ["localhost:8000"]
    assert not m.is_visible()
    assert m.button_rects == {}


def test_server_modal_cancel_invokes_callback_without_connecting():
    received = []
    cancelled = []
    m = ServerAddressModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("localhost:8000",
           on_connect=lambda addr: received.append(addr),
           on_cancel=lambda: cancelled.append(True))
    m.draw()
    handled = m.handle_click(m.button_rects["cancel"].center)
    assert handled
    assert cancelled == [True]
    assert received == []
    assert not m.is_visible()


def test_server_modal_draw_lays_out_both_buttons_within_rect():
    m = ServerAddressModal(pg.display.get_surface())
    rect = pg.Rect(0, 0, 400, 220)
    m.set_rect(rect)
    m.show("localhost:8000", on_connect=lambda addr: None)
    m.draw()
    assert set(m.button_rects) == {"connect", "cancel"}
    for br in m.button_rects.values():
        assert rect.contains(br)
    assert m.button_rects["connect"].right <= m.button_rects["cancel"].left


def test_wait_modal_show_lays_out_cancel_button_within_rect():
    m = WaitModal(pg.display.get_surface())
    rect = pg.Rect(0, 0, 400, 220)
    m.set_rect(rect)
    m.show("Searching…", on_cancel=lambda: None)
    assert m.is_visible()
    assert m.title == "Searching…"
    m.draw()
    assert set(m.button_rects) == {"cancel"}
    assert rect.contains(m.button_rects["cancel"])


def test_wait_modal_cancel_fires_callback():
    cancelled = []
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("Searching…", on_cancel=lambda: cancelled.append(True))
    m.draw()
    handled = m.handle_click(m.button_rects["cancel"].center)
    assert handled
    assert cancelled == [True]
    assert not m.is_visible()
    assert m.button_rects == {}


def test_wait_modal_subtitle_stored_and_button_still_laid_out():
    m = WaitModal(pg.display.get_surface())
    rect = pg.Rect(0, 0, 400, 220)
    m.set_rect(rect)
    m.show("Searching…", on_cancel=lambda: None)
    m.set_subtitle("00:05")
    m.draw()
    assert m.subtitle == "00:05"
    assert rect.contains(m.button_rects["cancel"])


def test_online_client_drains_no_events_initially():
    c = OnlineClient()
    assert c.drain_inbound() == []
    assert c.state == "disconnected"
