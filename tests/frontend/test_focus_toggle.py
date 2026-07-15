"""Collapse/expand state machine: focus_mode flips, board resizes to the focus
square and back, exactly one real board.set_rect per direction, no re-toggle
mid-transition."""

from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.focus import layout as fl
from chessshootout.frontend.window_chrome import WindowChrome
from tests.frontend.focus_helpers import (
    FakeTicks, make_app, start_game, install_clock, finish_transition,
)


_pg = pygame_display(1000, 800)


def _focus_rect(app):
    return fl.focus_square(app.window.get_size(), WindowChrome.HEIGHT, app.game._focus_show())


def test_collapse_reaches_focus(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.game.board.rect)
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app.game._toggle_focus(True)
    assert app.game.focus_transition is not None
    finish_transition(app, clock)
    assert app.game.focus_mode is True
    assert app.game.focus_transition is None
    assert app.game.board.rect == _focus_rect(app)
    assert app.game.board.rect.width > normal.width


def test_expand_restores_normal(monkeypatch):
    app = start_game(make_app())
    normal = pg.Rect(app.game.board.rect)
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app.game._toggle_focus(True)
    finish_transition(app, clock)
    app.game._toggle_focus(False)
    assert app.game.focus_transition is not None
    finish_transition(app, clock)
    assert app.game.focus_mode is False
    assert app.game.focus_transition is None
    assert app.game.board.rect == normal


def test_one_set_rect_per_direction(monkeypatch):
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    calls = []
    orig = app.game.board.set_rect
    monkeypatch.setattr(
        app.game.board, "set_rect", lambda r: (calls.append(pg.Rect(r)), orig(r))[1])
    app.game._toggle_focus(True)
    finish_transition(app, clock)
    assert len(calls) == 1
    calls.clear()
    app.game._toggle_focus(False)
    finish_transition(app, clock)
    assert len(calls) == 1


def test_toggle_ignored_mid_transition(monkeypatch):
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app.game._toggle_focus(True)
    trans = app.game.focus_transition
    app.game._toggle_focus(False)
    assert app.game.focus_transition is trans
    app.game._toggle_focus(True)
    assert app.game.focus_transition is trans


def test_toggle_focus_plays_focus_action_on_both_directions(monkeypatch):
    app = start_game(make_app())
    app.sound_manager = MagicMock()
    clock = FakeTicks()
    install_clock(monkeypatch, clock)

    app.game._toggle_focus(True)
    app.sound_manager.play_focus_action.assert_called_once()
    finish_transition(app, clock)

    app.game._toggle_focus(False)
    assert app.sound_manager.play_focus_action.call_count == 2


def test_toggle_focus_noop_calls_do_not_replay_the_sound(monkeypatch):
    app = start_game(make_app())
    app.sound_manager = MagicMock()
    clock = FakeTicks()
    install_clock(monkeypatch, clock)

    app.game._toggle_focus(True)
    app.sound_manager.play_focus_action.reset_mock()
    app.game._toggle_focus(True)
    app.sound_manager.play_focus_action.assert_not_called()
