"""Window-size clamping: the same MIN_WINDOW_* floor governs both construction
(``Frontend.__init__``) and live ``pg.VIDEORESIZE`` events. Undersized inputs are
raised to the floor; adequate inputs pass through untouched; one dimension can clamp
while the other does not."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.frontend import Frontend, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


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
    app.check_events()
    assert app.window_width == exp_w
    assert app.window_height == exp_h
