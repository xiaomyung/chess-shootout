"""Collapse/expand state machine: focus_mode flips, board resizes to the focus
square and back, exactly one real board.set_rect per direction, no re-toggle
mid-transition."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.focus import layout as fl
from chessshootout.frontend.window_chrome import WindowChrome
from tests.frontend.focus_helpers import (
    FakeTicks, make_app, start_game, install_clock, finish_transition,
)


_pg = pygame_display(1000, 800)


def _focus_rect(app):
    return fl.focus_square(app.window.get_size(), WindowChrome.HEIGHT, app._focus_show())


def test_collapse_reaches_focus(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.board.rect)
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    assert app.focus_transition is not None
    finish_transition(app, clock)
    assert app.focus_mode is True
    assert app.focus_transition is None
    assert app.board.rect == _focus_rect(app)
    assert app.board.rect.width > normal.width


def test_expand_restores_normal(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.board.rect)
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    finish_transition(app, clock)
    app._toggle_focus(False)
    assert app.focus_transition is not None
    finish_transition(app, clock)
    assert app.focus_mode is False
    assert app.focus_transition is None
    assert app.board.rect == normal


def test_one_set_rect_per_direction(monkeypatch):
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    calls = []
    orig = app.board.set_rect
    monkeypatch.setattr(app.board, "set_rect", lambda r: (calls.append(pg.Rect(r)), orig(r))[1])
    app._toggle_focus(True)
    finish_transition(app, clock)
    assert len(calls) == 1
    calls.clear()
    app._toggle_focus(False)
    finish_transition(app, clock)
    assert len(calls) == 1


def test_toggle_ignored_mid_transition(monkeypatch):
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    trans = app.focus_transition
    app._toggle_focus(False)
    assert app.focus_transition is trans
    app._toggle_focus(True)
    assert app.focus_transition is trans
