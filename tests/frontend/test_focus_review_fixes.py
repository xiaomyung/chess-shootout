"""Regression guards for the review fixes on the focus PR:
- the hidden right-menu scroll list must not capture clicks in focus (A1),
- manual focus toggle is blocked while a skill-check overlay is live (F2),
- _force_focus_off_instant clears the OFF-arrow linger timers (H2)."""


import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.focus.arrow import LONG_AGO_MS
from tests.frontend.focus_helpers import make_app, start_game, install_clock, FakeTicks, collapse


_pg = pygame_display(1000, 800)


def test_scrollable_is_gated_off_in_focus_and_transition():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        assert app.input_router._active_scrollable() is app.game.right_menu
        app.game._toggle_focus(True)
        assert app.game.focus_transition is not None
        assert app.input_router._active_scrollable() is None
        finish = clock
        for _ in range(12):
            finish.advance(40)
            app.draw_frame()
        assert app.game.focus_mode and app.game.focus_transition is None
        assert app.input_router._active_scrollable() is None


def test_toggle_blocked_while_skillcheck_overlay_active():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        mp.setattr(app.game.skillcheck_overlay, "is_active", lambda: True)
        app.game._toggle_focus(True)
        assert app.game.focus_mode is False
        assert app.game.focus_transition is None


def test_force_off_instant_clears_linger_timers():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        collapse(app, clock)
        app.game._focus_panel_hover_ms = 5_000_000
        app.game._focus_hint_until_ms = 5_000_000
        app.game._force_focus_off_instant()
        assert app.game.focus_mode is False
        assert app.game._focus_panel_hover_ms == LONG_AGO_MS
        assert app.game._focus_hint_until_ms == 0
