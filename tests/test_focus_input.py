"""Input routing: H hotkey, Esc cascade, arrow click priority over the board,
board-press suppression, and clicks ignored during a transition. Plus the
FocusArrow reveal/hit-test at the widget level."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.focus.arrow import FocusArrow
from tests.focus_helpers import (FakeClock, make_app, start_game, install_clock,
                                 finish_transition, collapse)


def _revealed_off_app(monkeypatch):
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app = start_game(make_app())
    for _ in range(10):
        clock.advance(35)
        app.draw_frame()
    return app, clock


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _key(k):
    return pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode="")


def test_h_toggles_focus(monkeypatch):
    app = start_game(make_app())
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    assert app._handle_shortcut_key(_key(pg.K_h)) is True
    assert app.focus_transition is not None
    finish_transition(app, clock)
    assert app.focus_mode is True
    app._handle_shortcut_key(_key(pg.K_h))
    finish_transition(app, clock)
    assert app.focus_mode is False


def test_h_does_nothing_in_review():
    app = start_game(make_app())
    app.pgn_review = True
    app._handle_shortcut_key(_key(pg.K_h))
    assert app.focus_transition is None
    assert app.focus_mode is False


def test_escape_exits_focus_before_resign(monkeypatch):
    app = start_game(make_app())
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    app._handle_escape()
    assert app.focus_transition is not None
    assert app.focus_transition.collapsing is False
    assert app.confirm_modal.is_visible() is False


def test_escape_closes_modal_before_focus(monkeypatch):
    app = start_game(make_app())
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    app.help_modal.show()
    app._handle_escape()
    assert app.help_modal.is_visible() is False
    assert app.focus_mode is True
    assert app.focus_transition is None


def test_arrow_click_wins_over_board(monkeypatch):
    app, _ = _revealed_off_app(monkeypatch)
    assert app.focus_arrow.is_visible() is True
    center = app.focus_arrow._bounds.center
    hits = []
    orig = app.board.handle_click
    app.board.handle_click = lambda sq: hits.append(sq) or orig(sq)
    app._dispatch_left_click(center)
    assert app.focus_transition is not None
    assert hits == []


def test_board_press_suppressed_after_arrow_click(monkeypatch):
    app, _ = _revealed_off_app(monkeypatch)
    center = app.focus_arrow._bounds.center
    app._mouse_left_pressed(center)
    assert app._focus_click_consumed is True
    assert app.board.dragging_from is None


def test_right_menu_not_clickable_in_focus(monkeypatch):
    app = start_game(make_app())
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    calls = []
    app.right_menu.handle_click = lambda pos: calls.append(pos) or False
    panel = app.right_menu.outer_rect
    app._dispatch_left_click((panel.centerx, panel.centery))
    assert calls == []
    assert app.confirm_modal.is_visible() is False


def test_click_ignored_during_transition(monkeypatch):
    app = start_game(make_app())
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    hits = []
    app.board.handle_click = lambda sq: hits.append(sq)
    app._dispatch_left_click(app.board.rect.center)
    assert hits == []
    assert app.focus_transition is not None


def test_arrow_widget_reveals_and_hides():
    arrow = FocusArrow()
    anchor = (1380, 400)
    arrow.update(0, False, anchor, (10, 10), True)
    assert arrow.is_visible() is False
    for t in range(0, 400, 40):
        arrow.update(t, True, anchor, (10, 10), True)
    assert arrow.is_visible() is True
    assert arrow.hit_test(arrow._bounds.center) is True
    for t in range(400, 1000, 40):
        arrow.update(t, False, anchor, (10, 10), True)
    assert arrow.is_visible() is False


def test_off_arrow_hint_appears_then_hides(monkeypatch):
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app = start_game(make_app())
    monkeypatch.setattr(pg.mouse, "get_pos",
                        lambda: (app.board.rect.centerx, app.board.rect.centery))
    for _ in range(8):
        clock.advance(35)
        app.draw_frame()
    assert app.focus_arrow.is_visible() is True
    for _ in range(80):
        clock.advance(50)
        app.draw_frame()
    assert app.focus_arrow.is_visible() is False


def test_off_arrow_shows_on_panel_hover(monkeypatch):
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    app = start_game(make_app())
    monkeypatch.setattr(pg.mouse, "get_pos",
                        lambda: (app.board.rect.centerx, app.board.rect.centery))
    for _ in range(60):
        clock.advance(50)
        app.draw_frame()
    assert app.focus_arrow.is_visible() is False
    panel = app.right_menu.outer_rect
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (panel.centerx, panel.centery))
    for _ in range(10):
        clock.advance(35)
        app.draw_frame()
    assert app.focus_arrow.is_visible() is True


def test_arrow_widget_hidden_when_no_anchor():
    arrow = FocusArrow()
    for t in range(0, 400, 40):
        arrow.update(t, True, None, (10, 10), False)
    assert arrow.is_visible() is False
