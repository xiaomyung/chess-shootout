"""TimeLine (focus/time_line.py) renders the depleting per-clock bar with the
right state color: orange for the mover, gray for the waiter, red under 10%.
Guards the extraction of the draw out of Frontend by pixel-sampling the bar."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION
from tests.focus_helpers import make_app, start_game, install_clock, FakeClock, collapse


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _rgb(color):
    c = pg.Color(color)
    return (c.r, c.g, c.b)


def _sample(app, rect):
    return tuple(app.window.get_at((rect.centerx, rect.centery)))[:3]


def _focus_line_game():
    clock = FakeClock()
    app = make_app()
    mp = pytest.MonkeyPatch()
    install_clock(mp, clock)
    start_game(app, minutes=5)
    collapse(app, clock)
    app.draw_frame()
    return app, mp


def test_mover_line_is_accent_waiter_is_muted():
    app, mp = _focus_line_game()
    try:
        top, bottom = app.time_line.rects_for(app.board, app.board.rect)
        assert not app.board.flipped
        assert _sample(app, bottom) == _rgb(Colors.accent)
        assert _sample(app, top) == _rgb(Colors.text_muted)
    finally:
        mp.undo()


def test_low_time_line_turns_red():
    app, mp = _focus_line_game()
    try:
        clock = app.match.clock
        clock.white_remaining = clock.initial_seconds * (LOW_TIME_FRACTION / 2)
        app.draw_frame()
        _top, bottom = app.time_line.rects_for(app.board, app.board.rect)
        assert _sample(app, bottom) == _rgb(Colors.check)
    finally:
        mp.undo()
