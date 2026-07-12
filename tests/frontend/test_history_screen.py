"""HistoryScreen: a first-class screen wrapping HistoryView, inheriting the same
input gating as the menu card, running the battle backdrop behind it
(paused on the game screen, never re-triggering the intro fly-in on a menu<->history hop), and
laying out the wide capped-width history rect from window size + the fixed chrome inset."""

import pygame as pg

from tests.conftest import pygame_display
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def test_switch_to_history_sets_screen_name():
    app = make_app()
    app.switch_to("history")
    assert app.screen.name == "history"
    assert app.screen is app.history


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


def test_history_screen_populates_itself_on_enter(tmp_path, monkeypatch):
    """HistoryScreen must be self-sufficient: switch_to("history") alone has to
    render the saved-games list. The shell used to prime history_view.show(...)
    inside _on_open_history BEFORE navigating, so entering the screen by any other
    route (Esc back from review, a direct switch_to) landed on an empty view."""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    games = tmp_path / "games"
    games.mkdir()
    (games / "local-1.pgn").write_text(
        '[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n', encoding="utf-8")
    app = make_app()

    app.switch_to("history")

    assert app.history_view.is_visible() is True
    assert app.history_view._groups, "the screen loaded the games dir itself"


def test_history_screen_hides_its_view_on_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = make_app()
    app.switch_to("history")
    assert app.history_view.is_visible() is True

    app.switch_to("menu")

    assert app.history_view.is_visible() is False
