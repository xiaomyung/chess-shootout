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


# ---- ServerAddressModal ----

def test_server_modal_starts_hidden():
    m = ServerAddressModal(pg.display.get_surface())
    assert not m.is_visible()


def test_server_modal_show_prefills_input():
    m = ServerAddressModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("chess.example.com:8000", on_connect=lambda addr: None)
    assert m.is_visible()
    assert m.input.text == "chess.example.com:8000"


def test_server_modal_connect_invokes_callback_with_addr():
    received = []
    m = ServerAddressModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("localhost:8000", on_connect=lambda addr: received.append(addr))
    m.draw()  # populates button_rects
    btn = m.button_rects["connect"]
    handled = m.handle_click(btn.center)
    assert handled
    assert received == ["localhost:8000"]
    assert not m.is_visible()


def test_server_modal_cancel_invokes_callback():
    cancelled = []
    m = ServerAddressModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("localhost:8000",
           on_connect=lambda addr: None,
           on_cancel=lambda: cancelled.append(True))
    m.draw()
    btn = m.button_rects["cancel"]
    m.handle_click(btn.center)
    assert cancelled == [True]
    assert not m.is_visible()


# ---- WaitModal ----

def test_wait_modal_starts_hidden():
    m = WaitModal(pg.display.get_surface())
    assert not m.is_visible()


def test_wait_modal_show_renders_title():
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("Searching…", on_cancel=lambda: None)
    assert m.is_visible()
    m.draw()  # must not crash
    assert "cancel" in m.button_rects


def test_wait_modal_cancel_fires_callback():
    cancelled = []
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("Searching…", on_cancel=lambda: cancelled.append(True))
    m.draw()
    m.handle_click(m.button_rects["cancel"].center)
    assert cancelled == [True]
    assert not m.is_visible()


def test_wait_modal_subtitle_renders_without_crash():
    m = WaitModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show("Searching…", on_cancel=lambda: None)
    m.set_subtitle("00:05")
    m.draw()
    assert m.subtitle == "00:05"


# ---- OnlineClient (real impl) ----

def test_online_client_drains_no_events_initially():
    c = OnlineClient()
    assert c.drain_inbound() == []
    assert c.state == "disconnected"
