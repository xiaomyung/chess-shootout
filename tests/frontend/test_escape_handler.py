"""Escape is now a context-aware Back/Cancel that NEVER closes the window
immediately. Priority: an active skill-check swallows it; any open modal closes
(the quit/resign confirm, help, fen, country, directory, offer banners,
search); on the main-menu card it raises a 'Quit the game?' prompt; a menu
sub-page (including Options, now a view rather than a modal) or a finished
game returns to the main menu; a live game opens the resign prompt.
"""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.modals.help import HOTKEYS
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.wheel import WheelChallenge
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def _app():
    app = make_app(1000, 800, mock_sound=False)
    app.draw_frame()
    return app


def _start_game(app):
    start_single_screen(app)
    app.draw_frame()
    return app


def test_escape_never_closes_window_in_menu():
    app = _app()
    app.input_router._handle_escape()
    assert app.running is True


def test_escape_never_closes_window_in_game():
    app = _start_game(_app())
    app.input_router._handle_escape()
    assert app.running is True


def test_menu_card_escape_opens_quit_prompt():
    app = _app()
    app.input_router._handle_escape()
    assert app.confirm_modal.is_visible() is True
    assert app.menu.card_visible() is False
    assert app.running is True


def test_quit_prompt_see_ya_quits():
    app = _app()
    app.input_router._handle_escape()
    app.menu._quit_app()
    assert app.running is False


def test_second_escape_dismisses_quit_prompt_and_restores_menu():
    app = _app()
    app.input_router._handle_escape()
    app.input_router._handle_escape()
    assert app.confirm_modal.is_visible() is False
    assert app.menu.card_visible() is True
    assert app.running is True


def test_menu_history_view_escape_returns_to_play_view():
    app = _app()
    app.menu.goto_history()
    app.input_router._handle_escape()
    assert app.screen.name == "menu"
    assert app.menu._active_view == "play"


def test_game_escape_opens_resign_prompt():
    app = _start_game(_app())
    app.input_router._handle_escape()
    assert app.confirm_modal.is_visible() is True
    assert app.running is True


def test_second_escape_dismisses_resign_prompt():
    app = _start_game(_app())
    app.input_router._handle_escape()
    app.input_router._handle_escape()
    assert app.confirm_modal.is_visible() is False


def test_finished_game_escape_returns_to_menu():
    app = _start_game(_app())
    app.game.manual_result = "white_wins_by_resignation"
    app.input_router._handle_escape()
    assert app.screen is app.menu


def test_help_modal_escape_closes_modal_not_resign():
    app = _start_game(_app())
    app.help_modal.show(HOTKEYS)
    app.input_router._handle_escape()
    assert app.help_modal.is_visible() is False
    assert app.confirm_modal.is_visible() is False


def test_active_skillcheck_swallows_escape():
    app = _start_game(_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    app.game.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    app.input_router._handle_escape()
    assert app.game.skillcheck_overlay.is_active() is True
    assert app.confirm_modal.is_visible() is False
    assert app.running is True


def test_esc_matrix_per_screen_escape_return_values():
    """Consolidated per-screen Esc behavior table (task G pin): menu shows the
    quit prompt and swallows the press (True); a live game opens the resign
    confirm (True); a finished game navigates home directly (True, no Nav —
    _on_back_to_menu runs synchronously); history and review hand back a Nav
    to their own return target."""
    from chessshootout.frontend.screens.base import Nav

    menu_app = _app()
    assert menu_app.menu.escape() is True
    assert menu_app.confirm_modal.is_visible() is True

    game_app = _start_game(_app())
    assert game_app.game.escape() is True
    assert game_app.confirm_modal.is_visible() is True

    finished_app = _start_game(_app())
    finished_app.game.manual_result = "white_wins_by_resignation"
    assert finished_app.game.escape() is True
    assert finished_app.screen is finished_app.menu

    menu_history_app = _app()
    menu_history_app.menu.goto_history()
    assert menu_history_app.menu.escape() is True
    assert menu_history_app.menu._active_view == "play"

    review_app = _app()
    review_app.review._return_to = "menu"
    result = review_app.review.escape()
    assert result == Nav("menu")


def test_skillcheck_swallow_beats_the_global_modal_and_banner_pass():
    """The swallow guard sits ABOVE _dismiss_top_modal, not below it. With it
    below, an Esc pressed mid-skill-check fell through to the global dismiss pass
    and silently cleared the opponent's pending offer banner (auto-declining a
    rematch) before GameScreen.escape() ever got to swallow it."""
    from unittest.mock import MagicMock

    app = _start_game(_app())
    app.coordinator.client = MagicMock()
    app.coordinator._push_offer_banner("draw_offered")
    assert app.coordinator.offer_banners.is_empty() is False
    app.help_modal.show(HOTKEYS)

    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    app.game.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    app.input_router._handle_escape()

    assert app.coordinator.offer_banners.is_empty() is False, "the offer survives"
    assert app.help_modal.is_visible() is True, "and so does the modal under it"
    assert app.game.skillcheck_overlay.is_active() is True
