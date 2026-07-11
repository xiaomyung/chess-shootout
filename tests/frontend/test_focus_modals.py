"""Modals + arrow behave correctly in focus mode.

Two regressions guarded here:
1. Board-relative modals (confirm / help / wait / fen / match-found / result menu)
   must recenter on the grown FOCUS board, not the old normal-mode board rect.
2. The right-edge reveal arrow must NOT appear while a blocking modal is open in
   focus (it did nothing but still showed) — matching the OFF-mode arrow, which is
   already suppressed by _menu_overlay_active().
"""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.frontend.focus_helpers import make_app, start_game, install_clock, FakeTicks, collapse

BOARD_MODALS = ("confirm_modal", "help_modal", "wait_modal",
                "fen_input_modal", "match_found_modal", "reconnecting_modal")

COORDINATOR_MODALS = ("wait_modal", "match_found_modal", "reconnecting_modal")


def _modal(app, name):
    return getattr(app.coordinator if name in COORDINATOR_MODALS else app, name)


_pg = pygame_display(1000, 800)


def test_board_modals_center_on_focus_board():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        collapse(app, clock)
        assert app.focus_mode
        bc = app.board.rect.center
        for name in BOARD_MODALS:
            modal = _modal(app, name)
            assert abs(modal.rect.centerx - bc[0]) <= 2, name
            assert abs(modal.rect.centery - bc[1]) <= 2, name
        assert abs(app.result_menu.rect.centerx - bc[0]) <= 2
        assert abs(app.result_menu.rect.centery - bc[1]) <= 2


def test_focus_modal_center_differs_from_normal():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        normal_cx = app.confirm_modal.rect.centerx
        collapse(app, clock)
        focus_cx = app.confirm_modal.rect.centerx
    assert focus_cx != normal_cx
    assert abs(focus_cx - app.window.get_width() // 2) <= 2
    assert normal_cx < app.window.get_width() // 2


def test_resign_confirm_opens_centered_on_focus_board():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        collapse(app, clock)
        app._on_resign()
        assert app.confirm_modal.is_visible()
        bc = app.board.rect.center
        assert abs(app.confirm_modal.rect.centerx - bc[0]) <= 2
        assert abs(app.confirm_modal.rect.centery - bc[1]) <= 2


def _hover_edge_and_draw(app, clock, mp, frames=12):
    zone = app._focus_edge_zone_rect()
    mp.setattr(pg.mouse, "get_pos", lambda: zone.center)
    for _ in range(frames):
        clock.advance(40)
        app.draw_frame()


def test_edge_arrow_reveals_without_modal():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        collapse(app, clock)
        _hover_edge_and_draw(app, clock, mp)
        assert app.focus_arrow.is_visible()


def test_edge_arrow_suppressed_under_modal():
    clock = FakeTicks()
    app = make_app()
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        start_game(app)
        collapse(app, clock)
        app._on_resign()
        assert app.confirm_modal.is_visible()
        _hover_edge_and_draw(app, clock, mp)
        assert not app.focus_arrow.is_visible()


def test_toast_center_x_tracks_board_and_mode():
    clock = FakeTicks()
    app = make_app()
    seen = []
    orig = app.toast.draw
    app.toast.draw = lambda *a, **k: seen.append(k.get("center_x")) or orig(*a, **k)
    with pytest.MonkeyPatch().context() as mp:
        install_clock(mp, clock)
        app.draw_frame()
        assert seen[-1] is None
        start_game(app)
        app.draw_frame()
        normal_cx = app.board.rect.centerx
        assert seen[-1] == normal_cx
        assert normal_cx < app.window.get_width() // 2
        collapse(app, clock)
        app.draw_frame()
        assert seen[-1] == app.board.rect.centerx
        assert seen[-1] != normal_cx
