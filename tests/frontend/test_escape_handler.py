"""Escape is now a context-aware Back/Cancel that NEVER closes the window
immediately. Priority: an active skill-check swallows it; any open modal closes
(the quit/resign confirm, help, fen, country, directory, options, offer banners,
search); on the main-menu card it raises a 'Quit the game?' prompt; a menu
sub-page or review or a finished game returns to the main menu; a live game
opens the resign prompt.
"""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.menu.menu_page import PAGE_CARD, PAGE_HISTORY
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
    assert app.start_menu.visible is False
    assert app.running is True


def test_quit_prompt_see_ya_quits():
    app = _app()
    app.input_router._handle_escape()
    app.input_router._quit_app()
    assert app.running is False


def test_second_escape_dismisses_quit_prompt_and_restores_menu():
    app = _app()
    app.input_router._handle_escape()
    app.input_router._handle_escape()
    assert app.confirm_modal.is_visible() is False
    assert app.start_menu.visible is True
    assert app.running is True


def test_menu_history_escape_returns_to_card():
    app = _app()
    app.menu_page.set_page(PAGE_HISTORY)
    app.input_router._handle_escape()
    assert app.menu_page.page == PAGE_CARD


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
    app.manual_result = "white_wins_by_resignation"
    app.input_router._handle_escape()
    assert app.mode == "menu"


def test_review_escape_returns_to_menu():
    app = _start_game(_app())
    app.pgn_review = True
    app.input_router._handle_escape()
    assert app.mode == "menu"


def test_help_modal_escape_closes_modal_not_resign():
    app = _start_game(_app())
    app.help_modal.show()
    app.input_router._handle_escape()
    assert app.help_modal.is_visible() is False
    assert app.confirm_modal.is_visible() is False


def test_file_browser_over_options_closes_before_options(tmp_path):
    from chessshootout.infra import env
    env._ENV_PATH = tmp_path / ".env"
    app = _app()
    app.settings._on_open_options()
    assert app.options_modal.is_visible() is True
    app.directory_browser.show(str(tmp_path), lambda p: None)
    assert app.directory_browser.is_visible() is True
    app.input_router._handle_escape()
    assert app.directory_browser.is_visible() is False
    assert app.options_modal.is_visible() is True
    app.input_router._handle_escape()
    assert app.options_modal.is_visible() is False


def test_country_picker_over_options_closes_before_options(tmp_path):
    from chessshootout.infra import env
    env._ENV_PATH = tmp_path / ".env"
    app = _app()
    app.settings._on_open_options()
    app.country_picker.show("US", lambda c: None)
    assert app.country_picker.is_visible() is True
    app.input_router._handle_escape()
    assert app.country_picker.is_visible() is False
    assert app.options_modal.is_visible() is True


def test_active_skillcheck_swallows_escape():
    app = _start_game(_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    app.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    app.input_router._handle_escape()
    assert app.skillcheck_overlay.is_active() is True
    assert app.confirm_modal.is_visible() is False
    assert app.running is True
