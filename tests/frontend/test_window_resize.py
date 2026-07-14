"""Window-size clamping: the same MIN_WINDOW_* floor governs both construction
(``Frontend.__init__``) and live ``pg.VIDEORESIZE`` events. Undersized inputs are
raised to the floor; adequate inputs pass through untouched; one dimension can clamp
while the other does not."""

import types

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.infra import env
from chessshootout.frontend.frontend import Frontend, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT


_pygame_init = pygame_display(1000, 800)


@pytest.mark.parametrize(
    "req_w, req_h, exp_w, exp_h",
    [
        pytest.param(
            MIN_WINDOW_WIDTH - 100, 600, MIN_WINDOW_WIDTH, 600,
            id="width_only_clamps",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH - 100, MIN_WINDOW_HEIGHT - 100,
            MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
            id="both_dims_clamp",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
            MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
            id="at_minimum_no_clamp",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH + 200, MIN_WINDOW_HEIGHT + 300,
            MIN_WINDOW_WIDTH + 200, MIN_WINDOW_HEIGHT + 300,
            id="above_minimum_no_clamp",
        ),
    ],
)
def test_construction_clamps_to_minimum(req_w, req_h, exp_w, exp_h):
    app = Frontend(req_w, req_h)
    assert app.window_width == exp_w
    assert app.window_height == exp_h


def test_construction_display_surface_meets_minimum():
    Frontend(600, 300)
    surface = pg.display.get_surface()
    w, h = surface.get_size()
    assert w >= MIN_WINDOW_WIDTH
    assert h >= MIN_WINDOW_HEIGHT


@pytest.mark.parametrize(
    "ev_w, ev_h, exp_w, exp_h",
    [
        pytest.param(600, 300, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT, id="too_small_both_clamp"),
        pytest.param(
            MIN_WINDOW_WIDTH + 50, MIN_WINDOW_HEIGHT + 100,
            MIN_WINDOW_WIDTH + 50, MIN_WINDOW_HEIGHT + 100,
            id="adequate_passes_through",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH + 50, 200,
            MIN_WINDOW_WIDTH + 50, MIN_WINDOW_HEIGHT,
            id="partial_clamp_only_height",
        ),
    ],
)
def test_videoresize_clamps_to_minimum(ev_w, ev_h, exp_w, exp_h):
    """A VIDEORESIZE event is clamped to MIN_WINDOW_WIDTH/HEIGHT; the too-small
    case proves the module constants are the real floor wired into the handler."""
    app = Frontend(MIN_WINDOW_WIDTH + 100, MIN_WINDOW_HEIGHT + 200)
    event = pg.event.Event(pg.VIDEORESIZE, {"w": ev_w, "h": ev_h, "size": (ev_w, ev_h)})
    pg.event.post(event)
    app.input_router.check_events()
    assert app.window_width == exp_w
    assert app.window_height == exp_h


def test_sync_reallocates_surface_when_os_window_grew(monkeypatch):
    """The Windows fix: when the OS reports a larger window than the current
    surface (native maximize / edge-drag), _sync_window_surface re-set_modes so
    the surface matches (else content renders small with black/striped margins)."""
    app = Frontend(1000, 800)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: (1400, 900))
    app._sync_window_surface()
    assert app.window.get_size() == (1400, 900)
    assert (app.window_width, app.window_height) == (1400, 900)


def test_sync_is_noop_when_surface_already_matches(monkeypatch):
    app = Frontend(1000, 800)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: app.window.get_size())
    calls = []
    monkeypatch.setattr(app, "_compute_layout", lambda: calls.append(1))
    app._sync_window_surface()
    assert calls == []


def test_sync_clamps_reported_size_to_minimum(monkeypatch):
    app = Frontend(1000, 800)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: (200, 150))
    app._sync_window_surface()
    assert app.window.get_size() == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


@pytest.mark.parametrize(
    "mode, expected",
    [
        pytest.param("fullscreen", ["fullscreen"], id="fullscreen_reuses_f11_toggle"),
        pytest.param("maximized", ["maximize"], id="maximized_calls_maximizer"),
        pytest.param("windowed", [], id="windowed_touches_neither"),
    ],
)
def test_boot_launch_mode_dispatch(monkeypatch, mode, expected):
    """CHESS_LAUNCH_MODE drives the one-shot boot dispatch: fullscreen goes through
    the same chrome.toggle_fullscreen path F11 uses (so state stays consistent),
    maximized asks the maximizer, windowed does nothing."""
    app = Frontend(1000, 800)
    calls = []
    monkeypatch.setattr(app.chrome, "toggle_fullscreen", lambda: calls.append("fullscreen"))
    monkeypatch.setattr(app, "_maximize_window", lambda: calls.append("maximize"))
    monkeypatch.setattr(env, "get_launch_mode", lambda: mode)
    app._apply_launch_mode()
    assert calls == expected


def test_maximize_window_falls_back_to_desktop_size(monkeypatch):
    """Maximize goes through chrome's ctypes SDL channel (a second
    Window.from_display_module wrapper corrupted the SDL window and
    segfaulted on drag-unmaximize). When chrome reports failure, the
    maximizer falls back to re-set_mode at the largest desktop size."""
    app = Frontend(1000, 800)
    monkeypatch.setattr(app.chrome, "maximize", lambda: False)
    monkeypatch.setattr(pg.display, "get_desktop_sizes", lambda: [(2560, 1440)])
    app._maximize_window()
    assert app.window.get_size() == (2560, 1440)
    assert (app.window_width, app.window_height) == (2560, 1440)


def test_maximize_window_uses_chrome_sdl_channel(monkeypatch):
    """Success path: chrome.maximize() is the ONLY maximize mechanism —
    no pygame._sdl2 Window wrapper may be created for it."""
    app = Frontend(1000, 800)
    calls = []
    monkeypatch.setattr(app.chrome, "maximize", lambda: calls.append("max") or True)
    app._maximize_window()
    assert calls == ["max"]
    assert app.window.get_size() == (1000, 800)


class _MaximizingChrome:
    """A chrome whose native maximize succeeds and whose client_size() reports the
    grown OS window (as WindowsSnap does via GetClientRect)."""

    def __init__(self, client_size):
        self.window = None
        self._client_size = client_size

    def maximize(self):
        return True

    def client_size(self):
        return self._client_size

    def reinit_sdl(self):
        pass


def test_maximize_launch_adopts_real_client_size_and_settle_keeps_it(monkeypatch):
    """Maximized launch on Windows: chrome.maximize() succeeds and the OS grows the
    window past the constructor size. The maximizer must adopt that real client size
    into surface + dims + layout, and the subsequent _settle_window pass must NOT
    shrink it back to the stale constructor size (the reported launch-mode bug)."""
    app = Frontend(1000, 800)
    app.chrome = _MaximizingChrome((1400, 900))

    app._maximize_window()
    assert app.window.get_size() == (1400, 900)
    assert (app.window_width, app.window_height) == (1400, 900)
    assert app._last_layout_size == (1400, 900)

    recreated = []
    real_recreate = app._recreate_window_surface

    def spy_recreate(w, h):
        recreated.append((w, h))
        real_recreate(w, h)

    monkeypatch.setattr(app, "_recreate_window_surface", spy_recreate)
    monkeypatch.setattr("chessshootout.frontend.frontend.os", types.SimpleNamespace(name="nt"))
    app._settle_window()
    assert recreated == [(1400, 900)], "settle must re-set_mode at the maximized size, not shrink"
    assert app.window.get_size() == (1400, 900)
    assert (app.window_width, app.window_height) == (1400, 900)
