"""Regression guards for the review fixes on the focus PR:
- the hidden right-menu scroll list must not capture clicks in focus (A1),
- manual focus toggle is blocked while a skill-check overlay is live (F2),
- _force_focus_off_instant clears the OFF-arrow linger timers (H2)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.focus.arrow import LONG_AGO_MS
from tests.focus_helpers import make_app, start_game, install_clock, FakeClock, collapse


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def test_scrollable_is_gated_off_in_focus_and_transition():
    clock = FakeClock()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        assert app._active_scrollable() is app.right_menu
        app._toggle_focus(True)
        assert app.focus_transition is not None
        assert app._active_scrollable() is None
        finish = clock
        for _ in range(12):
            finish.advance(40)
            app.draw_frame()
        assert app.focus_mode and app.focus_transition is None
        assert app._active_scrollable() is None


def test_toggle_blocked_while_skillcheck_overlay_active():
    clock = FakeClock()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        mp.setattr(app.skillcheck_overlay, "is_active", lambda: True)
        app._toggle_focus(True)
        assert app.focus_mode is False
        assert app.focus_transition is None


def test_force_off_instant_clears_linger_timers():
    clock = FakeClock()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        collapse(app, clock)
        app._focus_panel_hover_ms = 5_000_000
        app._focus_hint_until_ms = 5_000_000
        app._force_focus_off_instant()
        assert app.focus_mode is False
        assert app._focus_panel_hover_ms == LONG_AGO_MS
        assert app._focus_hint_until_ms == 0
