"""Escape is now a context-aware Back/Cancel that NEVER closes the window
immediately. Priority: an active skill-check swallows it; any open modal closes
(the quit/resign confirm, help, fen, country, directory, options, offer banners,
search); on the main-menu card it raises a 'Quit the game?' prompt; a menu
sub-page or review or a finished game returns to the main menu; a live game
opens the resign prompt.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.menu.menu_page import PAGE_CARD, PAGE_HISTORY
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.wheel import WheelChallenge


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _app():
    app = Frontend(1000, 800)
    app.draw_frame()
    return app


def _start_game(app):
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": 5, "increment_seconds": 0, "variant": "casual"})
    app.draw_frame()
    return app


# ---- the most important invariant -----------------------------------------

def test_escape_never_closes_window_in_menu():
    app = _app()
    app._handle_escape()
    assert app.running is True


def test_escape_never_closes_window_in_game():
    app = _start_game(_app())
    app._handle_escape()
    assert app.running is True


# ---- main-menu card -> quit prompt ----------------------------------------

def test_menu_card_escape_opens_quit_prompt():
    app = _app()
    app._handle_escape()
    assert app.confirm_modal.is_visible() is True
    assert app.start_menu.visible is False
    assert app.running is True


def test_quit_prompt_see_ya_quits():
    app = _app()
    app._handle_escape()
    app._quit_app()
    assert app.running is False


def test_second_escape_dismisses_quit_prompt_and_restores_menu():
    app = _app()
    app._handle_escape()
    app._handle_escape()
    assert app.confirm_modal.is_visible() is False
    assert app.start_menu.visible is True
    assert app.running is True


# ---- menu sub-page -> back to card ----------------------------------------

def test_menu_history_escape_returns_to_card():
    app = _app()
    app.menu_page.set_page(PAGE_HISTORY)
    app._handle_escape()
    assert app.menu_page.page == PAGE_CARD


# ---- live game -> resign prompt -------------------------------------------

def test_game_escape_opens_resign_prompt():
    app = _start_game(_app())
    app._handle_escape()
    assert app.confirm_modal.is_visible() is True
    assert app.running is True


def test_second_escape_dismisses_resign_prompt():
    app = _start_game(_app())
    app._handle_escape()
    app._handle_escape()
    assert app.confirm_modal.is_visible() is False


# ---- finished game / review -> main menu ----------------------------------

def test_finished_game_escape_returns_to_menu():
    app = _start_game(_app())
    app.manual_result = "white_wins_by_resignation"
    app._handle_escape()
    assert app.mode == "menu"


def test_review_escape_returns_to_menu():
    app = _start_game(_app())
    app.pgn_review = True
    app._handle_escape()
    assert app.mode == "menu"


# ---- an open modal closes first (does not resign) -------------------------

def test_help_modal_escape_closes_modal_not_resign():
    app = _start_game(_app())
    app.help_modal.show()
    app._handle_escape()
    assert app.help_modal.is_visible() is False
    assert app.confirm_modal.is_visible() is False


# ---- an active skill-check swallows escape ---------------------------------

def test_active_skillcheck_swallows_escape():
    app = _start_game(_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    app.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    app._handle_escape()
    assert app.skillcheck_overlay.is_active() is True
    assert app.confirm_modal.is_visible() is False
    assert app.running is True
