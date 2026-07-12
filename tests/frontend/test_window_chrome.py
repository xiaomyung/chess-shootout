import ctypes

import pygame as pg
import pytest

from tests.conftest import pygame_display
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


_pygame_init = pygame_display(1000, 700)


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


def test_win_snap_is_noop_off_windows(chrome):
    assert chrome._snap is None
    chrome.shutdown()
    assert chrome._snap is None


def test_hit_test_resize_edges_active_when_not_maximized(chrome):
    chrome._w, chrome._h = 1000, 700
    chrome._layout_dots(1000)
    assert chrome._is_maximized() is False
    assert _hit(chrome, 1, 1) == _HITTEST_RESIZE_TOPLEFT
    assert _hit(chrome, 500, 699) == _HITTEST_RESIZE_BOTTOM


def test_maximized_suppresses_resize_hit_zones(chrome):
    import types
    chrome._w, chrome._h = 1000, 700
    chrome._layout_dots(1000)
    chrome._snap = types.SimpleNamespace(maximized=True)
    assert chrome._is_maximized() is True
    assert _hit(chrome, 1, 1) == _HITTEST_DRAGGABLE
    assert _hit(chrome, 500, 699) == _HITTEST_NORMAL


def test_smooth_dot_sprite_is_cached_per_color(chrome, monkeypatch):
    import chessshootout.frontend.window_chrome as window_chrome_module
    window_chrome_module._DOT_CACHE.clear()
    calls = []
    real_supersample = window_chrome_module.supersample

    def counting_supersample(*args, **kwargs):
        calls.append(1)
        return real_supersample(*args, **kwargs)

    monkeypatch.setattr(window_chrome_module, "supersample", counting_supersample)
    chrome._draw_smooth_dot((50, 50), Colors.amber)
    chrome._draw_smooth_dot((60, 60), Colors.amber)
    assert len(calls) == 1, "same color must reuse the cached dot sprite"
    chrome._draw_smooth_dot((70, 70), Colors.win)
    assert len(calls) == 2, "a different color must build a distinct sprite"


def test_dot_glyph_sprite_is_cached_per_key(chrome, monkeypatch):
    import chessshootout.frontend.window_chrome as window_chrome_module
    window_chrome_module._DOT_GLYPH_CACHE.clear()
    calls = []
    real_supersample = window_chrome_module.supersample

    def counting_supersample(*args, **kwargs):
        calls.append(1)
        return real_supersample(*args, **kwargs)

    monkeypatch.setattr(window_chrome_module, "supersample", counting_supersample)
    base = pg.Color(Colors.amber)
    chrome._dot_glyph("min", base)
    chrome._dot_glyph("min", base)
    assert len(calls) == 1, "same glyph key must reuse the cached glyph sprite"
    chrome._dot_glyph("max", base)
    assert len(calls) == 2, "a different glyph key must build a distinct sprite"


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
        for name in ("SDL_SetWindowHitTest", "SDL_SetWindowMinimumSize",
                     "SDL_MinimizeWindow", "SDL_RaiseWindow", "SDL_SetWindowFullscreen"):
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


def test_fullscreen_no_op_without_callback(chrome):
    """Without a fullscreen callback (or owning SDL2) the actions must no-op, not crash."""
    chrome._sdl = None
    chrome._win_ptr = None
    chrome.toggle_fullscreen()
    chrome._minimize()
    assert chrome._win_state == "normal"


def _ok_fullscreen(calls):
    def cb(enable):
        calls.append(enable)
        return True
    return cb


def test_toggle_fullscreen_invokes_callback_and_tracks_state():
    surface = pg.display.get_surface()
    calls = []
    chrome = WindowChrome(surface, on_fullscreen=_ok_fullscreen(calls))
    chrome.toggle_fullscreen()
    assert chrome._win_state == "fullscreen"
    assert calls == [True]
    chrome.toggle_fullscreen()
    assert chrome._win_state == "normal"
    assert calls == [True, False]


def test_green_dot_toggles_fullscreen():
    surface = pg.display.get_surface()
    calls = []
    chrome = WindowChrome(surface, on_fullscreen=_ok_fullscreen(calls))
    chrome._activate("max")
    assert chrome._win_state == "fullscreen"
    assert calls == [True]


def test_toggle_fullscreen_keeps_state_when_callback_fails():
    """A failed apply (callback returns falsy) must not flip _win_state, or the
    titlebar hit-test desyncs from the real window and drag/resize go dead."""
    surface = pg.display.get_surface()
    calls = []
    chrome = WindowChrome(surface, on_fullscreen=lambda enable: calls.append(enable))
    chrome.toggle_fullscreen()
    assert chrome._win_state == "normal"
    assert calls == [True]


def test_apply_fullscreen_toggles_sdl_flag_on_same_window():
    """The no-recreation path: SDL_SetWindowFullscreen flips the desktop-fullscreen
    flag on the existing window and raises it (to keep focus)."""
    surface = pg.display.get_surface()
    chrome = WindowChrome(surface)
    sdl = _FakeSDL(0xABCD)
    chrome._sdl = sdl
    chrome._win_ptr = 0xABCD
    assert chrome.apply_fullscreen(True) is True
    assert sdl.SDL_SetWindowFullscreen.calls[-1] == (0xABCD, 0x00001001)
    assert sdl.SDL_RaiseWindow.calls
    assert chrome.apply_fullscreen(False) is True
    assert sdl.SDL_SetWindowFullscreen.calls[-1] == (0xABCD, 0)


def test_apply_fullscreen_false_without_handle():
    surface = pg.display.get_surface()
    chrome = WindowChrome(surface)
    chrome._win_ptr = None
    assert chrome.apply_fullscreen(True) is False


def test_fullscreen_titlebar_is_not_draggable(chrome):
    chrome._win_state = "fullscreen"
    assert _hit(chrome, 500, 5) == _HITTEST_NORMAL


def test_drag_on_fullscreen_titlebar_exits_fullscreen(chrome, monkeypatch):
    calls = []
    monkeypatch.setattr(chrome, "toggle_fullscreen", lambda: calls.append(1))
    chrome._win_state = "fullscreen"
    chrome.draw()
    pos = (chrome._w // 2, 5)
    assert chrome.handle_click(pos) is True
    assert chrome._fs_press_pos == pos
    chrome.handle_title_motion((pos[0] + 30, pos[1]))
    assert calls == [1]
    assert chrome._fs_press_pos is None


def test_tap_on_fullscreen_titlebar_does_not_exit(chrome, monkeypatch):
    calls = []
    monkeypatch.setattr(chrome, "toggle_fullscreen", lambda: calls.append(1))
    chrome._win_state = "fullscreen"
    chrome.draw()
    pos = (chrome._w // 2, 5)
    chrome.handle_click(pos)
    chrome.handle_title_motion((pos[0] + 2, pos[1]))
    assert calls == []
    chrome.clear_title_press()
    assert chrome._fs_press_pos is None


def test_normal_titlebar_click_does_not_toggle_fullscreen(chrome, monkeypatch):
    """The double-click-to-fullscreen affordance was removed: the title area is
    OS-draggable in normal state, so pygame never received the click and it never
    fired. A title click in normal state is consumed but must not toggle."""
    calls = []
    monkeypatch.setattr(chrome, "toggle_fullscreen", lambda: calls.append(1))
    chrome.draw()
    pos = (chrome._w // 2, 4)
    assert chrome.handle_click(pos) is True
    assert chrome.handle_click(pos) is True
    assert calls == []


def _stats_band(chrome):
    cy = chrome.HEIGHT // 2
    right = min(rect.left for rect in chrome._dot_rects.values()) - chrome.STATS_PAD
    left = chrome._wordmark_right_edge() + chrome.STATS_PAD
    return [tuple(chrome.window.get_at((x, cy))) for x in range(left, right)]


def test_stats_paint_band_when_enabled_and_clear_when_off(chrome):
    chrome.window.fill("black")
    chrome.draw([])
    off = _stats_band(chrome)
    chrome.window.fill("black")
    chrome.draw(["60 FPS", "PING 32 ms"])
    on = _stats_band(chrome)
    assert on != off, "enabling stats should paint glyphs in the band left of the dots"
    bg = pg.Color(Colors.titlebar_bg)
    assert all(px[:3] == bg[:3] for px in off), "no stats should be drawn when toggled off"


def test_stats_stay_left_of_dots(chrome):
    chrome.window.fill("black")
    chrome.draw(["60 FPS", "PING 32 ms"])
    cy = chrome.HEIGHT // 2
    leftmost_dot = min(rect.left for rect in chrome._dot_rects.values())
    bg = pg.Color(Colors.titlebar_bg)[:3]
    band = [chrome.window.get_at((x, cy))[:3]
            for x in range(leftmost_dot - chrome.STATS_PAD + 1, leftmost_dot)]
    assert all(px == bg for px in band), "stats must not intrude into the dot padding"


def test_layout_reserves_titlebar_and_keeps_board_playable_at_min_size():
    from chessshootout.infra import env
    env.init_paths()
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(900, 500)
    assert app.game.board.board_offset_y >= app.chrome.HEIGHT - 1
    assert app.game.board.cell_size > 40
