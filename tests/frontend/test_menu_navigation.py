"""Frontend menu navigation: the History button swaps the active screen to HistoryScreen
(the battle keeps running behind it and its avoid-rect follows the active screen), Back
returns to the menu card, review opened from History returns to History, and an unloadable
PGN restores the History screen instead of stranding a blank board."""


from tests.conftest import pygame_display
from chessshootout.domain.pgn.generate import generate_pgn
from chessshootout.backend.backend import Backend
from tests.helpers import make_app as _shared_make_app


_pygame_init = pygame_display(1000, 800)


def make_app():
    return _shared_make_app(1000, 800, mock_sound=False)


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
    app._execute_pending_nav()
    assert app.screen.name == "history"
    assert app.mode == "menu"
    assert app.history_view.is_visible() is True


def test_back_returns_to_card():
    app = make_app()
    app._on_open_history()
    app._execute_pending_nav()
    app._on_menu_back()
    app._execute_pending_nav()
    assert app.screen.name == "menu"
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
    app._execute_pending_nav()
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


def test_unloadable_pgn_restores_history(tmp_path):
    bad = tmp_path / "broken.pgn"
    bad.write_text('[White "x"]\n\n1. e4 zz9 *', encoding="utf-8")
    app = make_app()
    app._open_pgn_review(str(bad))
    app._execute_pending_nav()
    app._execute_pending_nav()
    assert app.mode == "menu"
    assert app.screen.name == "history"
    assert app.toast.message == "Could not load PGN"


def test_review_from_history_returns_to_history(tmp_path):
    good = tmp_path / "local-20260101-120000.pgn"
    good.write_text(_valid_pgn_text(), encoding="utf-8")
    app = make_app()
    app._open_pgn_review(str(good))
    app._execute_pending_nav()
    assert app.screen.name == "review"
    app.review._on_menu()
    app._execute_pending_nav()
    assert app.screen.name == "history"


def test_fresh_game_after_review_returns_to_card(tmp_path):
    good = tmp_path / "local-20260101-120000.pgn"
    good.write_text(_valid_pgn_text(), encoding="utf-8")
    app = make_app()
    app._open_pgn_review(str(good))
    app._execute_pending_nav()
    assert app.screen.name == "review"
    app._on_start_game({
        "mode": "single_screen", "nickname": "alice",
        "time_minutes": 5, "increment_seconds": 0, "side": "white",
    })
    assert app.screen.name == "game"
    app._on_back_to_menu()
    assert app.screen.name == "menu"
