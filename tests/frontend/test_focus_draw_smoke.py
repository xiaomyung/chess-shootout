"""draw_frame runs clean in every steady + transition state and in each show mode;
present forces a full flip during a transition and region-presents in steady focus."""


import pytest

from tests.conftest import pygame_display
from chessshootout.infra import env
from tests.frontend.focus_helpers import (
    FakeTicks, make_app, start_game, install_clock, finish_transition, collapse,
)


_pg = pygame_display(1000, 800)


@pytest.fixture(autouse=True)
def _clean_focus_env(monkeypatch):
    monkeypatch.delenv("CHESS_FOCUS_SHOW", raising=False)
    yield
    monkeypatch.delenv("CHESS_FOCUS_SHOW", raising=False)


@pytest.mark.parametrize("size", [(1000, 800), (1600, 900)])
@pytest.mark.parametrize("show", ["nothing", "line", "strips"])
def test_steady_focus_draws(monkeypatch, size, show):
    env.set_focus_show(show)
    app = start_game(make_app(*size))
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    assert app.focus_mode is True
    app.draw_frame()
    assert app._focus_show() == show


def test_transition_frames_draw(monkeypatch):
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    clock.advance(40)
    app.draw_frame()
    assert app.focus_transition is not None
    finish_transition(app, clock)
    app._toggle_focus(False)
    clock.advance(40)
    app.draw_frame()
    assert app.focus_transition is not None
    finish_transition(app, clock)


def test_off_arrow_present_region(monkeypatch):
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app = start_game(make_app())
    for _ in range(10):
        clock.advance(35)
        app.draw_frame()
    assert app.focus_arrow.is_visible() is True
    app._needs_full_present = False
    app.toast.hide()
    assert app._needs_full_redraw(False) is False
    rects = app._present_rects(False)
    arrow = app.focus_arrow.dirty_rect()
    assert any(r.contains(arrow) or r == arrow for r in rects)


def test_transition_forces_full_redraw(monkeypatch):
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app._toggle_focus(True)
    clock.advance(40)
    app.draw_frame()
    assert app._needs_full_redraw(False) is True


def test_steady_focus_region_presents(monkeypatch):
    env.set_focus_show("nothing")
    app = start_game(make_app())
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    collapse(app, clock)
    app._needs_full_present = False
    app.toast.hide()
    assert app._needs_full_redraw(False) is False
    assert app._present_rects(False) is not None
