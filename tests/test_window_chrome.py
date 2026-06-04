import ctypes
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.window_chrome import (
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
    assert window.get_at((500, 4))[:3] == pg.Color(Colors.titlebar_bg)[:3]
    assert window.get_at((500, chrome.HEIGHT - 1))[:3] == pg.Color(Colors.border)[:3]


def test_traffic_dots_use_their_colors(chrome):
    chrome.draw()
    window = pg.display.get_surface()
    expected = {
        "min": Colors.amber,
        "max": Colors.win,
        "close": Colors.loss,
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
    assert chrome.handle_click((500, 4)) is True
    assert chrome.handle_click((500, chrome.HEIGHT + 10)) is False


def test_hit_test_regions(chrome):
    chrome._w, chrome._h = 1000, 700
    chrome._layout_dots(1000)
    assert _hit(chrome, 300, chrome.HEIGHT // 2) == _HITTEST_DRAGGABLE
    assert _hit(chrome, *chrome._dot_rects["close"].center) == _HITTEST_NORMAL
    assert _hit(chrome, 300, 200) == _HITTEST_NORMAL
    assert _hit(chrome, 1, 1) == _HITTEST_RESIZE_TOPLEFT
    assert _hit(chrome, 999, 350) == _HITTEST_RESIZE_RIGHT
    assert _hit(chrome, 500, 699) == _HITTEST_RESIZE_BOTTOM


def test_cursor_for_resize_edges_and_dots(chrome):
    chrome._w, chrome._h = 1000, 700
    chrome._layout_dots(1000)
    assert chrome._cursor_for((1, 1)) == pg.SYSTEM_CURSOR_SIZENWSE
    assert chrome._cursor_for((999, 1)) == pg.SYSTEM_CURSOR_SIZENESW
    assert chrome._cursor_for((999, 350)) == pg.SYSTEM_CURSOR_SIZEWE
    assert chrome._cursor_for((500, 699)) == pg.SYSTEM_CURSOR_SIZENS
    assert chrome._cursor_for(chrome._dot_rects["close"].center) == pg.SYSTEM_CURSOR_HAND
    assert chrome._cursor_for((300, chrome.HEIGHT // 2)) == pg.SYSTEM_CURSOR_ARROW
    assert chrome._cursor_for((300, 300)) == pg.SYSTEM_CURSOR_ARROW


def test_dot_draws_glyph_on_hover(chrome, monkeypatch):
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (0, 0))
    chrome.window.fill("black")
    chrome.draw()
    center = chrome._dot_rects["close"].center
    plain = tuple(chrome.window.get_at(center))
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: center)
    chrome.window.fill("black")
    chrome.draw()
    hovered = tuple(chrome.window.get_at(center))
    assert hovered != plain, "hovered close dot should show its × glyph"


class _FakeFn:
    def __init__(self, ret=0):
        self.ret = ret
        self.restype = None
        self.argtypes = None
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.ret


class _FakeSDL:
    """Stand-in for a ctypes-loaded SDL2 handle. GetWindowFromID returns win_ptr_ret;
    a 0 return models the wrong-instance case (empty window registry)."""
    def __init__(self, win_ptr_ret):
        self.SDL_GetWindowFromID = _FakeFn(win_ptr_ret)
        for name in ("SDL_GetWindowFlags", "SDL_SetWindowHitTest", "SDL_SetWindowMinimumSize",
                     "SDL_MaximizeWindow", "SDL_RestoreWindow", "SDL_MinimizeWindow"):
            setattr(self, name, _FakeFn(0))


def test_resolve_owning_sdl_skips_wrong_instance(chrome, monkeypatch):
    """The fix: a second SDL2 instance (empty window registry → NULL) is rejected and
    the candidate whose SDL_GetWindowFromID resolves the window is chosen."""
    import chessshootout.frontend.window_chrome as wc
    wrong, right = _FakeSDL(0), _FakeSDL(0xABCD)
    monkeypatch.setattr(wc, "_iter_sdl_candidates", lambda: iter([wrong, right]))
    chrome._sdl = None
    chrome._win_ptr = None
    chrome._resolve_owning_sdl(7)
    assert chrome._sdl is right
    assert chrome._win_ptr == 0xABCD
    assert wrong.SDL_GetWindowFromID.calls == [(7,)]


def test_resolve_owning_sdl_disables_when_no_instance_owns_window(chrome, monkeypatch):
    import chessshootout.frontend.window_chrome as wc
    monkeypatch.setattr(wc, "_iter_sdl_candidates", lambda: iter([_FakeSDL(0), _FakeSDL(0)]))
    chrome._sdl = None
    chrome._win_ptr = None
    chrome._resolve_owning_sdl(7)
    assert chrome._sdl is None
    assert not chrome._win_ptr


def test_toggle_maximize_no_op_when_chrome_disabled(chrome):
    """With no owning SDL2 instance the min/max actions must no-op, not crash."""
    chrome._sdl = None
    chrome._win_ptr = None
    chrome._toggle_maximize()
    chrome._minimize()
    assert chrome._is_maximized() is False


def test_layout_reserves_titlebar_and_keeps_board_playable_at_min_size():
    from chessshootout.infra import env
    env.init_paths()
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(900, 500)
    assert app.board.board_offset_y >= app.chrome.HEIGHT - 1
    assert app.board.cell_size > 40
