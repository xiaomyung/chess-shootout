"""Menu shell navigation: the rail swaps sub-views (logged "menu view a -> b"),
Esc walks non-Play -> Play -> quit confirm, the menu remembers its active view
across a screen round-trip, review opened from history returns to the history
view, and the battle keeps running behind menu modals while avoiding the rail
+ the history view's panel -- the play view's chips and popovers contribute no
avoid rects at all, so battle entities fight freely behind them."""

import logging

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.domain.pgn.generate import generate_pgn
from chessshootout.frontend.visual.colors import Colors
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
    for row in ("battlepass", "armory", "social", "history", "options", "play"):
        rect = app.menu.rail._row_rects[row]
        app.menu.handle_click(rect.center)
        assert app.menu._active_view == row


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
    assert app.menu.card_visible() is True


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


def test_menu_paints_the_rail_and_panel_under_the_confirm_modal():
    app = make_app()
    app.menu.escape()
    assert app.confirm_modal.is_visible() is True
    app.draw_frame()
    panel = app.menu._menu_layout.right_rail_full_rect
    point = (panel.right - 4, panel.centery)
    assert app.window.get_at(point)[:3] == pg.Color(Colors.surface)[:3]


def test_avoid_rects_still_cover_the_rails_while_the_confirm_modal_is_up():
    app = make_app()
    app.menu.escape()
    assert app.confirm_modal.is_visible() is True
    app.draw_frame()
    assert app.menu._menu_layout.rail_rect in app.menu_battle.avoid_rects
    assert app.menu._menu_layout.right_rail_full_rect in app.menu_battle.avoid_rects


def test_battle_avoids_the_rail_and_the_active_views_panels():
    app = make_app()
    app.draw_frame()
    battle = app.menu_battle
    hero = app.menu.play_view
    assert app.menu._menu_layout.rail_rect in battle.avoid_rects
    # cp2: the play view contributes no colliders at all -- chips, title, CTA and
    # FEN link all draw over the battle, so entities fight freely behind them
    assert hero.avoid_rects() == []
    assert hero._title_block not in battle.avoid_rects
    assert not any(r.contains(hero._cta_rect) for r in battle.avoid_rects)
    # cp2: the full right rail column (opaque panel, edge-to-edge, chrome-to-bottom)
    # is the collider now -- like the left rail -- so entities/KO/bubbles never enter it
    assert app.menu._menu_layout.right_rail_full_rect in battle.avoid_rects
    assert app.menu._menu_layout.right_rail_rect not in battle.avoid_rects

    app.menu.goto_history()
    app.draw_frame()
    assert app.history_view.rect not in app.menu_battle.avoid_rects


def test_play_view_avoid_rects_stay_empty_with_a_popover_open():
    """The scope grew past just the chip row: an OPEN time/side popover used to
    add its own collider too. Neither does anymore -- the battle roams and fires
    straight through an open popover panel exactly as it does through the chips."""
    app = make_app()
    hero = app.menu.play_view
    app.draw_frame()

    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_open is True
    assert hero.avoid_rects() == []

    app.menu.handle_click(hero._title_pos)
    app.menu.handle_click(hero._side_chip.center)
    assert hero._side_open is True
    assert hero.avoid_rects() == []
