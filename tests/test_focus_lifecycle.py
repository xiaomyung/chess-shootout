"""Focus resets off on new game / menu / disconnect, auto-exits when the game
ends, and aborts cleanly if a result lands mid-transition."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from tests.focus_helpers import (FakeClock, make_app, start_game, install_clock,
                                 finish_transition, collapse)


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def test_reset_to_new_game_clears_focus(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.board.rect)
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    assert app.focus_mode is True
    app._reset_to_new_game()
    assert app.focus_mode is False
    assert app.focus_transition is None
    assert app.board.rect == normal


def test_return_to_menu_clears_focus(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.board.rect)
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    app.mode = "menu"
    app.draw_frame()
    assert app.focus_mode is False
    assert app.focus_transition is None
    app.mode = "single_screen"
    app._compute_layout()
    assert app.board.rect == normal


def test_game_over_auto_exits_focus(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.board.rect)
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    app.manual_result = "white_wins_by_resignation"
    app.draw_frame()
    assert app.focus_transition is not None
    assert app.focus_transition.collapsing is False
    finish_transition(app, clock)
    assert app.focus_mode is False
    assert app.focus_transition is None
    assert app.board.rect == normal


def test_result_during_collapse_expands_smoothly(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.board.rect)
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    clock.advance(40)
    app.draw_frame()
    app.manual_result = "black_wins_by_resignation"
    finish_transition(app, clock)
    finish_transition(app, clock)
    assert app.focus_transition is None
    assert app.focus_mode is False
    assert app.board.rect == normal
