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


def test_minimum_constants_match_module():
    # Width may evolve as the right menu grows; pin the height floor and assert
    # width remains at or above 900 (the historical minimum).
    assert MIN_WINDOW_WIDTH >= 900
    assert MIN_WINDOW_HEIGHT == 500


def test_construction_clamps_width_only():
    app = Frontend(MIN_WINDOW_WIDTH - 100, 600)
    assert app.window_width == MIN_WINDOW_WIDTH
    assert app.window_height == 600


def test_construction_clamps_both_dims():
    app = Frontend(MIN_WINDOW_WIDTH - 100, MIN_WINDOW_HEIGHT - 100)
    assert app.window_width == MIN_WINDOW_WIDTH
    assert app.window_height == MIN_WINDOW_HEIGHT


def test_construction_no_clamp_when_at_minimum():
    app = Frontend(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert app.window_width == MIN_WINDOW_WIDTH
    assert app.window_height == MIN_WINDOW_HEIGHT


def test_construction_no_clamp_when_above_minimum():
    app = Frontend(MIN_WINDOW_WIDTH + 200, MIN_WINDOW_HEIGHT + 300)
    assert app.window_width == MIN_WINDOW_WIDTH + 200
    assert app.window_height == MIN_WINDOW_HEIGHT + 300


def test_construction_display_surface_meets_minimum():
    Frontend(600, 300)
    surface = pg.display.get_surface()
    w, h = surface.get_size()
    assert w >= MIN_WINDOW_WIDTH
    assert h >= MIN_WINDOW_HEIGHT


def test_videoresize_too_small_clamps():
    app = Frontend(MIN_WINDOW_WIDTH + 100, MIN_WINDOW_HEIGHT + 200)
    event = pg.event.Event(pg.VIDEORESIZE, {"w": 600, "h": 300, "size": (600, 300)})
    pg.event.post(event)
    app.check_events()
    assert app.window_width == MIN_WINDOW_WIDTH
    assert app.window_height == MIN_WINDOW_HEIGHT


def test_videoresize_adequate_passes_through():
    app = Frontend(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT + 200)
    big_w = MIN_WINDOW_WIDTH + 50
    big_h = MIN_WINDOW_HEIGHT + 100
    event = pg.event.Event(pg.VIDEORESIZE, {"w": big_w, "h": big_h, "size": (big_w, big_h)})
    pg.event.post(event)
    app.check_events()
    assert app.window_width == big_w
    assert app.window_height == big_h


def test_videoresize_partial_clamp_only_height():
    app = Frontend(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT + 200)
    big_w = MIN_WINDOW_WIDTH + 50
    event = pg.event.Event(pg.VIDEORESIZE, {"w": big_w, "h": 200, "size": (big_w, 200)})
    pg.event.post(event)
    app.check_events()
    assert app.window_width == big_w
    assert app.window_height == MIN_WINDOW_HEIGHT
