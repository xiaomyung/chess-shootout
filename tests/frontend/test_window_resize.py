"""Window-size clamping: the same MIN_WINDOW_* floor governs both construction
(``Frontend.__init__``) and live ``pg.VIDEORESIZE`` events. Undersized inputs are
raised to the floor; adequate inputs pass through untouched; one dimension can clamp
while the other does not."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
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
