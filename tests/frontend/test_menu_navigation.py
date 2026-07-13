"""Menu shell navigation: the rail swaps sub-views (logged "menu view a -> b"),
Esc walks non-Play -> Play -> quit confirm, the menu remembers its active view
across a screen round-trip, review opened from history returns to the history
view, and the battle keeps running behind menu modals while avoiding the rail +
the active view's panels."""

import logging

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


def test_goto_view_switches_and_logs_the_transition(caplog):
    app = make_app()
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.menu.goto_view("history")
    assert app.menu._active_view == "history"
    assert any(r.getMessage() == "menu view play -> history" for r in caplog.records)


def test_goto_view_to_the_same_view_is_a_noop(caplog):
    app = make_app()
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.menu.goto_view("play")
    assert not any("menu view" in r.getMessage() for r in caplog.records)


def test_rail_hit_test_routes_each_nav_row():
    app = make_app()
    app.draw_frame()
    for row in ("battlepass", "armory", "social", "history", "play"):
        rect = app.menu.rail._row_rects[row]
        app.menu.handle_click(rect.center)
        assert app.menu._active_view == row


def test_options_rail_row_opens_the_options_modal_without_switching_view():
    app = make_app()
    app.draw_frame()
    rect = app.menu.rail._row_rects["options"]
    app.menu.handle_click(rect.center)
    assert app.options_modal.is_visible() is True
    assert app.menu._active_view == "play"


def test_stub_view_escape_returns_to_play():
    app = make_app()
    app.menu.goto_view("battlepass")
    assert app.menu.escape() is True
    assert app.menu._active_view == "play"


def test_play_view_escape_opens_the_quit_confirm():
    app = make_app()
    assert app.menu._active_view == "play"
    assert app.menu.escape() is True
    assert app.confirm_modal.is_visible() is True


def test_menu_remembers_its_active_view_across_a_screen_roundtrip():
    app = make_app()
    app.menu.goto_history()
    app.switch_to("game")
    app.switch_to("menu")
    assert app.menu._active_view == "history"


def test_review_from_history_returns_to_the_history_view(tmp_path):
    good = tmp_path / "local-20260101-120000.pgn"
    good.write_text(_valid_pgn_text(), encoding="utf-8")
    app = make_app()
    app.menu.goto_history()
    app._open_pgn_review(str(good))
    app._execute_pending_nav()
    assert app.screen.name == "review"

    app.review._on_menu()
    app._execute_pending_nav()
    assert app.screen.name == "menu"
    assert app.menu._active_view == "history"


def test_unloadable_pgn_returns_to_the_history_view(tmp_path):
    bad = tmp_path / "broken.pgn"
    bad.write_text('[White "x"]\n\n1. e4 zz9 *', encoding="utf-8")
    app = make_app()
    app.menu.goto_history()
    app._open_pgn_review(str(bad))
    app._execute_pending_nav()
    app._execute_pending_nav()
    assert app.screen.name == "menu"
    assert app.menu._active_view == "history"
    assert app.toast.message == "Could not load PGN"


def test_battle_keeps_running_behind_a_menu_modal(monkeypatch):
    app = make_app()
    app._on_open_fen_modal()
    assert app._blocking_modal_visible() is True
    calls = []
    monkeypatch.setattr(app.menu_battle, "update", lambda *a, **k: calls.append("u"))
    app.draw_frame()
    assert "u" in calls


def test_battle_avoids_the_rail_and_the_active_views_panels():
    app = make_app()
    app.draw_frame()
    battle = app.menu_battle
    hero = app.menu.play_view
    assert app.menu._menu_layout.rail_rect in battle.avoid_rects
    # the hero's real drawn blocks are the obstacles now, not a single card
    assert hero._title_block in battle.avoid_rects
    assert hero._chips_block in battle.avoid_rects
    assert any(r.contains(hero._cta_rect) for r in battle.avoid_rects)
    # the empty right column no longer blocks the battle (P4 fills it with cards)
    assert app.menu._menu_layout.right_rail_rect not in battle.avoid_rects

    app.menu.goto_history()
    app.draw_frame()
    assert app.history_view.rect in app.menu_battle.avoid_rects
