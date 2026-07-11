"""HistoryScreen: a first-class screen wrapping HistoryView, sharing the "menu" legacy mode
so it inherits the same input gating as the menu card, running the battle backdrop behind it
(paused on the game screen, never re-triggering the intro fly-in on a menu<->history hop), and
laying out the wide capped-width history rect from window size + the fixed chrome inset."""

import pygame as pg

from tests.conftest import pygame_display
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def test_switch_to_history_sets_screen_name_and_legacy_mode():
    app = make_app()
    app.switch_to("history")
    assert app.screen.name == "history"
    assert app.mode == "menu"


def test_history_escape_navigates_back_to_menu():
    app = make_app()
    app.switch_to("history")
    app.draw_frame()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_ESCAPE, "mod": 0, "unicode": ""}))
    app.input_router.check_events()
    assert app._pending_nav is not None
    assert app._pending_nav.name == "menu"
    app._execute_pending_nav()
    assert app.screen.name == "menu"


def test_backdrop_update_paused_on_game_screen(monkeypatch):
    app = make_app()
    start_single_screen(app)
    calls = []
    monkeypatch.setattr(app.menu_battle, "update", lambda *a, **k: calls.append(1))
    app.draw_frame()
    assert calls == []


def test_backdrop_update_runs_on_menu_screen(monkeypatch):
    app = make_app()
    calls = []
    monkeypatch.setattr(app.menu_battle, "update", lambda *a, **k: calls.append(1))
    app.draw_frame()
    assert calls == [1]


def test_backdrop_update_runs_on_history_screen(monkeypatch):
    app = make_app()
    app.switch_to("history")
    calls = []
    monkeypatch.setattr(app.menu_battle, "update", lambda *a, **k: calls.append(1))
    app.draw_frame()
    assert calls == [1]


def test_intro_fires_game_to_menu(monkeypatch):
    app = make_app()
    start_single_screen(app)
    app.draw_frame()
    calls = []
    monkeypatch.setattr(app.menu_battle, "begin_intro", lambda: calls.append(1))
    app.switch_to("menu")
    app.draw_frame()
    assert calls == [1]


def test_intro_does_not_fire_history_to_menu(monkeypatch):
    app = make_app()
    app.switch_to("history")
    app.draw_frame()
    calls = []
    monkeypatch.setattr(app.menu_battle, "begin_intro", lambda: calls.append(1))
    app.switch_to("menu")
    app.draw_frame()
    assert calls == []


def test_intro_does_not_fire_menu_to_history(monkeypatch):
    app = make_app()
    app.draw_frame()
    calls = []
    monkeypatch.setattr(app.menu_battle, "begin_intro", lambda: calls.append(1))
    app.switch_to("history")
    app.draw_frame()
    assert calls == []


def test_backdrop_avoid_rect_on_history_screen():
    app = make_app()
    app.switch_to("history")
    app.draw_frame()
    assert app.menu_battle.avoid_rect == app.history_view.rect


def test_backdrop_avoid_rect_on_menu_screen():
    app = make_app()
    app.draw_frame()
    assert app.menu_battle.avoid_rect == app.start_menu.outer_rect()


def test_history_relayout_wide_rect_capped_and_centered():
    app = make_app()
    app.switch_to("history")
    assert app.history_view.rect.width > 600
    assert app.history_view.rect.width <= 860
    assert abs(app.history_view.rect.centerx - 500) <= 1


def test_draw_frame_smoke_on_history_screen():
    app = make_app()
    app.switch_to("history")
    assert app.screen.name == "history"
    app.draw_frame()
