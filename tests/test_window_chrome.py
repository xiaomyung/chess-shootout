import ctypes
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.visual.colors import Colors
from frontend.window_chrome import (
    WindowChrome,
    _SDLPoint,
    _HITTEST_NORMAL,
    _HITTEST_DRAGGABLE,
    _HITTEST_RESIZE_TOPLEFT,
    _HITTEST_RESIZE_RIGHT,
    _HITTEST_RESIZE_BOTTOM,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 700))
    yield
    pg.quit()


@pytest.fixture
def chrome():
    window = pg.display.get_surface()
    window.fill("black")
    return WindowChrome(window)


def _hit(chrome, x, y):
    pt = _SDLPoint(x, y)
    return chrome._hit_test(None, ctypes.pointer(pt), None)


def test_titlebar_renders_background_and_border(chrome):
    chrome.draw()
    window = pg.display.get_surface()
    # bar background well clear of logo/wordmark/dots
    assert window.get_at((500, 4))[:3] == pg.Color(Colors.titlebar_bg)[:3]
    # 1px hairline at the bottom of the bar
    assert window.get_at((500, chrome.HEIGHT - 1))[:3] == pg.Color(Colors.button_border)[:3]


def test_traffic_dots_use_their_colors(chrome):
    chrome.draw()
    window = pg.display.get_surface()
    expected = {
        "min": Colors.titlebar_min,
        "max": Colors.titlebar_max,
        "close": Colors.titlebar_close,
    }
    for key, rect in chrome._dot_rects.items():
        assert window.get_at(rect.center)[:3] == pg.Color(expected[key])[:3]


def test_close_dot_click_posts_quit(chrome):
    chrome.draw()
    pg.event.clear()
    handled = chrome.handle_click(chrome._dot_rects["close"].center)
    assert handled is True
    assert pg.event.get(pg.QUIT), "close dot must post a QUIT event"


def test_titlebar_consumes_clicks_but_passes_below(chrome):
    chrome.draw()
    # a click anywhere on the bar is consumed (so it can't reach the board)
    assert chrome.handle_click((500, 4)) is True
    # a click below the bar falls through to the rest of the UI
    assert chrome.handle_click((500, chrome.HEIGHT + 10)) is False


def test_hit_test_regions(chrome):
    chrome._w, chrome._h = 1000, 700
    chrome._layout_dots(1000)
    # title-bar background is draggable
    assert _hit(chrome, 300, chrome.HEIGHT // 2) == _HITTEST_DRAGGABLE
    # over a traffic dot it is normal (so pygame gets the click)
    assert _hit(chrome, *chrome._dot_rects["close"].center) == _HITTEST_NORMAL
    # content area below the bar is normal
    assert _hit(chrome, 300, 200) == _HITTEST_NORMAL
    # window edges resize
    assert _hit(chrome, 1, 1) == _HITTEST_RESIZE_TOPLEFT
    assert _hit(chrome, 999, 350) == _HITTEST_RESIZE_RIGHT
    assert _hit(chrome, 500, 699) == _HITTEST_RESIZE_BOTTOM


def test_layout_reserves_titlebar_and_keeps_board_playable_at_min_size():
    from frontend import env
    env.init_paths()
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    # board sits fully below the title bar
    assert app.board.board_offset_y >= app.chrome.HEIGHT - 1
    # board stays comfortably playable at the minimum window size
    assert app.board.cell_size > 40
