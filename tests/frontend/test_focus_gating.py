"""_toggle_focus(True) is a no-op unless focus is available: not in menu /
finished game / active skill-check (passive spectate included) / pending promotion /
blocking modal / active drag."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.modals.help import HOTKEYS
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.wheel import WheelChallenge
from tests.frontend.focus_helpers import make_app, start_game


_pg = pygame_display(1000, 800)


def _assert_blocked(app):
    app.game._toggle_focus(True)
    assert app.game.focus_transition is None
    assert app.game.focus_mode is False


def test_available_in_live_game():
    app = start_game(make_app())
    assert app.game._focus_available() is True


def test_blocked_in_menu():
    app = make_app()
    _assert_blocked(app)


def test_blocked_with_result():
    app = start_game(make_app())
    app.game.manual_result = "white_wins_by_resignation"
    _assert_blocked(app)


def test_blocked_during_skillcheck():
    app = start_game(make_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    app.game.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    assert app.game.skillcheck_overlay.is_active() is True
    _assert_blocked(app)


def test_blocked_during_passive_spectate_skillcheck():
    app = start_game(make_app())
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0,
                                 passive=True)
    app.game.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)
    assert app.game.skillcheck_overlay.is_active() is True
    assert app.game.skillcheck_session.skillcheck_swallows_input() is False
    _assert_blocked(app)


def test_blocked_with_pending_promotion():
    app = start_game(make_app())
    app.game.board.pending_promotion_square = Square(0, 0)
    _assert_blocked(app)


def test_blocked_with_blocking_modal():
    app = start_game(make_app())
    app.help_modal.show(HOTKEYS)
    _assert_blocked(app)


def test_blocked_while_dragging():
    app = start_game(make_app())
    app.game.board.dragging_from = Square(6, 4)
    assert app.game.board.is_dragging() is True
    _assert_blocked(app)
