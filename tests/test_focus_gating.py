"""_toggle_focus(True) is a no-op unless focus is available: not in menu / review /
finished game / active skill-check (passive spectate included) / pending promotion /
blocking modal / active drag."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.wheel import WheelChallenge
from tests.focus_helpers import make_app, start_game


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _assert_blocked(app):
    app._toggle_focus(True)
    assert app.focus_transition is None
    assert app.focus_mode is False


def test_available_in_live_game():
    app = start_game(make_app())
    assert app._focus_available() is True


def test_blocked_in_menu():
    app = make_app()
    _assert_blocked(app)


def test_blocked_in_review():
    app = start_game(make_app())
    app.pgn_review = True
    assert app._focus_available() is False
    _assert_blocked(app)


def test_blocked_with_result():
    app = start_game(make_app())
    app.manual_result = "white_wins_by_resignation"
    _assert_blocked(app)


def test_blocked_during_skillcheck():
    app = start_game(make_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    app.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    assert app.skillcheck_overlay.is_active() is True
    _assert_blocked(app)


def test_blocked_during_passive_spectate_skillcheck():
    app = start_game(make_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0,
                                 passive=True)
    app.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    assert app.skillcheck_overlay.is_active() is True
    assert app._skillcheck_swallows_input() is False
    _assert_blocked(app)


def test_blocked_with_pending_promotion():
    app = start_game(make_app())
    app.board.pending_promotion_square = Square(0, 0)
    _assert_blocked(app)


def test_blocked_with_blocking_modal():
    app = start_game(make_app())
    app.help_modal.show()
    _assert_blocked(app)


def test_blocked_while_dragging():
    app = start_game(make_app())
    app.board.dragging_from = Square(6, 4)
    assert app.board.is_dragging() is True
    _assert_blocked(app)
