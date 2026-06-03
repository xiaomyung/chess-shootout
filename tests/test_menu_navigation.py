"""Frontend menu navigation: the History button swaps the menu foreground to the History
page (the battle keeps running behind it and its avoid-rect follows the page), Back returns to
the card, review opened from History returns to History, and an unloadable PGN restores the
menu instead of stranding a blank board."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.frontend import Frontend
from frontend.menu.menu_page import PAGE_CARD, PAGE_HISTORY
from domain.pgn.generate import generate_pgn
from backend.backend import Backend


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def make_app():
    return Frontend(1000, 800)


def _valid_pgn_text():
    backend = Backend()
    backend.new_game()
    for san in ["e4", "e5", "Nf3"]:
        backend.apply_san(san)
    return generate_pgn(backend.move_history, "white_wins",
                        white_name="alice", black_name="Bob")


def test_load_pgn_opens_history_page():
    app = make_app()
    app._on_open_history()
    assert app.menu_page.page == PAGE_HISTORY
    assert app.history_view.is_visible() is True


def test_back_returns_to_card():
    app = make_app()
    app._on_open_history()
    app._on_menu_back()
    assert app.menu_page.page == PAGE_CARD
    assert app.history_view.is_visible() is False


def test_battle_keeps_running_behind_a_menu_modal(monkeypatch):
    app = make_app()
    app._on_open_fen_modal()
    assert app._menu_overlay_active() is True
    calls = []
    monkeypatch.setattr(app.menu_battle, "update", lambda *a, **k: calls.append("u"))
    app.draw_frame()
    assert "u" in calls


def test_battle_avoid_rect_follows_active_page():
    app = make_app()
    app.draw_frame()
    assert app.menu_battle.avoid_rect == app.start_menu._outer
    app._on_open_history()
    app.draw_frame()
    assert app.menu_battle.avoid_rect == app.history_view.rect


def test_intro_overlay_draws_behind_menu_modals(monkeypatch):
    """The battle fly-in queen must paint before the modals, so she never covers an open modal."""
    app = make_app()
    order = []
    monkeypatch.setattr(app.menu_battle, "draw_intro_overlay",
                        lambda *a, **k: order.append("intro"))
    monkeypatch.setattr(app.options_modal, "draw", lambda *a, **k: order.append("options"))
    monkeypatch.setattr(app.confirm_modal, "draw", lambda *a, **k: order.append("confirm"))
    app.draw_frame()
    assert {"intro", "options", "confirm"} <= set(order)
    assert order.index("intro") < order.index("options"), \
        "the fly-in queen must draw before (behind) the options modal"
    assert order.index("intro") < order.index("confirm"), \
        "and behind every other menu modal"


def test_unloadable_pgn_restores_menu(tmp_path):
    bad = tmp_path / "broken.pgn"
    bad.write_text('[White "x"]\n\n1. e4 zz9 *')
    app = make_app()
    app._load_pgn_from_path(str(bad))
    assert app.mode == "menu"
    assert app.menu_page.page == PAGE_HISTORY
    assert app.toast.message == "Could not load PGN"


def test_review_from_history_returns_to_history(tmp_path):
    good = tmp_path / "local-20260101-120000.pgn"
    good.write_text(_valid_pgn_text())
    app = make_app()
    app._load_pgn_from_path(str(good))
    assert app.pgn_review is True
    assert app._review_return_page == PAGE_HISTORY
    app._on_back_to_menu()
    assert app.menu_page.page == PAGE_HISTORY


def test_fresh_game_after_review_returns_to_card(tmp_path):
    good = tmp_path / "local-20260101-120000.pgn"
    good.write_text(_valid_pgn_text())
    app = make_app()
    app._load_pgn_from_path(str(good))
    app._on_start_game({
        "mode": "single_screen", "nickname": "alice",
        "time_minutes": 5, "increment_seconds": 0, "side": "white",
    })
    assert app._review_return_page is None
    app._on_back_to_menu()
    assert app.menu_page.page == PAGE_CARD
