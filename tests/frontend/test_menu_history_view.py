"""History is now a MenuScreen sub-view: HistoryMenuView wraps the existing
HistoryView (unchanged logic). It populates on view enter, lays out into the
capped subview rect, routes its scrollable, opens review with the menu return
target; navigation back to Play lives on the rail, not on this view. The menu
battle avoids its panel."""

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.domain.pgn.generate import generate_pgn
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)


def _valid_pgn_text():
    backend = Backend()
    backend.new_game()
    for san in ["e4", "e5", "Nf3"]:
        backend.apply_san(san)
    return generate_pgn(backend.move_history, "white_wins",
                        white_name="alice", black_name="Bob")


def test_goto_history_switches_the_menu_to_the_history_view():
    app = make_app()
    app.menu.goto_history()
    assert app.screen.name == "menu"
    assert app.menu._active_view == "history"
    assert app.history_view.is_visible() is True


def test_history_view_populates_itself_on_enter(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    games = tmp_path / "games"
    games.mkdir()
    (games / "local-1.pgn").write_text(
        '[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n', encoding="utf-8")
    app = make_app()

    app.menu.goto_history()

    assert app.history_view.is_visible() is True
    assert app.history_view._groups, "the sub-view loaded the games dir itself"


def test_history_view_hidden_when_switching_to_the_play_view(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = make_app()
    app.menu.goto_history()
    assert app.history_view.is_visible() is True

    app.menu.goto_view("play")

    assert app.history_view.is_visible() is False


def test_history_view_hidden_when_leaving_the_menu_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = make_app()
    app.menu.goto_history()
    assert app.history_view.is_visible() is True

    app.switch_to("game")

    assert app.history_view.is_visible() is False


def test_history_view_wide_rect_capped_and_centered_in_the_content_region():
    app = make_app()
    app.menu.goto_history()
    rect = app.history_view.rect
    assert rect.width > 600
    assert rect.width <= 860
    assert rect.centerx == app.menu._menu_layout.subview_rect.centerx


def test_empty_history_view_draws_the_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    (tmp_path / "games").mkdir()
    app = make_app()
    app.menu.goto_history()
    assert app.history_view.is_visible() is True
    assert app.history_view._groups == []
    app.draw_frame()  # empty-state renders without crashing


def test_open_review_from_history_uses_the_menu_return_target(tmp_path):
    good = tmp_path / "local-20260101-120000.pgn"
    good.write_text(_valid_pgn_text(), encoding="utf-8")
    app = make_app()
    app.menu.goto_history()

    app._open_pgn_review(str(good))
    app._execute_pending_nav()
    assert app.screen.name == "review"
    assert app.review._return_to == "menu"

    app.review._on_menu()
    app._execute_pending_nav()
    assert app.screen.name == "menu"
    assert app.menu._active_view == "history"


def test_menu_battle_avoids_the_history_panel():
    app = make_app()
    app.menu.goto_history()
    app.draw_frame()
    assert app.history_view.rect in app.menu_battle.avoid_rects
