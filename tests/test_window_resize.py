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


def test_minimum_constants_are_900_and_500():
    assert MIN_WINDOW_WIDTH == 900
    assert MIN_WINDOW_HEIGHT == 500


def test_construction_clamps_width_only():
    app = Frontend(800, 600)
    assert app.window_width == 900
    assert app.window_height == 600


def test_construction_clamps_both_dims():
    app = Frontend(800, 400)
    assert app.window_width == 900
    assert app.window_height == 500


def test_construction_no_clamp_when_at_minimum():
    app = Frontend(900, 500)
    assert app.window_width == 900
    assert app.window_height == 500


def test_construction_no_clamp_when_above_minimum():
    app = Frontend(1200, 800)
    assert app.window_width == 1200
    assert app.window_height == 800


def test_construction_display_surface_meets_minimum():
    Frontend(600, 300)
    surface = pg.display.get_surface()
    w, h = surface.get_size()
    assert w >= MIN_WINDOW_WIDTH
    assert h >= MIN_WINDOW_HEIGHT


def test_videoresize_too_small_clamps():
    app = Frontend(1000, 800)
    event = pg.event.Event(pg.VIDEORESIZE, {"w": 600, "h": 300, "size": (600, 300)})
    pg.event.post(event)
    app.check_events()
    assert app.window_width == MIN_WINDOW_WIDTH
    assert app.window_height == MIN_WINDOW_HEIGHT


def test_videoresize_adequate_passes_through():
    app = Frontend(1000, 800)
    event = pg.event.Event(pg.VIDEORESIZE, {"w": 1100, "h": 700, "size": (1100, 700)})
    pg.event.post(event)
    app.check_events()
    assert app.window_width == 1100
    assert app.window_height == 700


def test_videoresize_partial_clamp_only_height():
    app = Frontend(1000, 800)
    event = pg.event.Event(pg.VIDEORESIZE, {"w": 1100, "h": 200, "size": (1100, 200)})
    pg.event.post(event)
    app.check_events()
    assert app.window_width == 1100
    assert app.window_height == MIN_WINDOW_HEIGHT
