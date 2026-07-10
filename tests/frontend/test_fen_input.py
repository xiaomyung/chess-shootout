"""FEN-input modal + Frontend integration.

Invariant: the FEN modal mirrors BaseModal show/hide visibility, validates
through its on_submit callback (falsy return -> "Invalid FEN" error), and the
start menu's "From FEN" button is inert while a search/online game is selected.
"""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.domain.match import SINGLE_SCREEN
from chessshootout.frontend.modals.fen_input import FenInputModal
from tests.helpers import make_app as _make_app_at


_pygame_init = pygame_display(1000, 800)


def _make_app():
    return _make_app_at(1000, 800)


def _key(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


@pytest.fixture
def modal():
    m = FenInputModal(pg.display.get_surface())
    m.set_rect(pg.Rect(100, 100, 400, 200))
    return m


def test_visibility_follows_show_then_hide(modal):
    """Starts hidden, show() reveals + focuses, hide() conceals + blurs."""
    assert modal.is_visible() is False
    modal.show(on_submit=lambda fen: True)
    assert modal.is_visible() is True
    assert modal.text_input.focused is True
    modal.hide()
    assert modal.is_visible() is False
    assert modal.text_input.focused is False


def test_show_focuses_input(modal):
    modal.show(on_submit=lambda fen: True)
    assert modal.is_visible() is True
    assert modal.text_input.focused is True
    assert modal.error == ""


def test_hide_clears_state(modal):
    modal.show(on_submit=lambda fen: True)
    modal.text_input.text = "stuff"
    modal.hide()
    assert modal.is_visible() is False
    assert modal.text_input.focused is False


@pytest.mark.parametrize(
    "text, on_submit, expected",
    [
        pytest.param("", lambda fen: True, "empty", id="empty_text_reports_empty"),
        pytest.param("garbage", lambda fen: False, "invalid", id="rejected_fen_reports_invalid"),
    ],
)
def test_submit_sets_error(modal, text, on_submit, expected):
    modal.show(on_submit=on_submit)
    modal.text_input.text = text
    modal._submit()
    assert expected in modal.error.lower()


def test_submit_valid_clears_modal_via_callback(modal):
    submitted = {}

    def on_submit(fen):
        submitted["fen"] = fen
        modal.hide()
        return True

    modal.show(on_submit=on_submit)
    modal.text_input.text = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    modal._submit()
    assert "fen" in submitted
    assert modal.is_visible() is False


def test_enter_key_triggers_submit(modal):
    fired = []
    modal.show(on_submit=lambda fen: fired.append(fen) or True)
    modal.text_input.text = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    modal.handle_key(_key(pg.K_RETURN))
    assert len(fired) == 1


def test_fen_button_opens_modal():
    app = _make_app()
    app._on_open_fen_modal()
    assert app.fen_input_modal.is_visible() is True


def test_valid_fen_starts_single_screen_game():
    app = _make_app()
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    ok = app._start_game_from_fen(fen)
    assert ok is True
    assert app.mode == SINGLE_SCREEN
    assert app.fen_input_modal.is_visible() is False
    assert app.start_menu.is_visible() is False


def test_invalid_fen_returns_false_and_keeps_modal_open():
    app = _make_app()
    app._on_open_fen_modal()
    ok = app._start_game_from_fen("not-a-fen")
    assert ok is False
    assert app.fen_input_modal.is_visible() is True


@pytest.mark.parametrize(
    "selected_mode, expected_opened",
    [
        pytest.param("online", None, id="online_mode_disables_fen_button"),
        pytest.param(SINGLE_SCREEN, True, id="local_mode_emits_fen_callback"),
    ],
)
def test_start_menu_fen_button(selected_mode, expected_opened):
    captured = {}
    callbacks = {
        "start_game": lambda cfg: None,
        "fen": lambda: captured.setdefault("opened", True),
    }
    from chessshootout.frontend.modals.start import StartMenu
    sm = StartMenu(pg.display.get_surface(), callbacks)
    sm.set_rect(pg.Rect(100, 50, 600, 700))
    sm.selected_mode = selected_mode
    sm.show()
    sm.draw()
    sm.handle_click(sm._fen_rect.center)
    assert captured.get("opened") is expected_opened
