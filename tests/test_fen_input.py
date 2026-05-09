import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.match import SINGLE_SCREEN
from frontend.modals.fen_input import FenInputModal


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _make_app():
    from frontend.frontend import Frontend
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    return app


def _key(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


# ---------- FenInputModal in isolation ----------

@pytest.fixture
def modal():
    m = FenInputModal(pg.display.get_surface())
    m.set_rect(pg.Rect(100, 100, 400, 200))
    return m


def test_starts_hidden(modal):
    assert modal.is_visible() is False


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


def test_submit_empty_sets_error(modal):
    modal.show(on_submit=lambda fen: True)
    modal._submit()
    assert "empty" in modal.error.lower()


def test_submit_invalid_sets_invalid_error(modal):
    modal.show(on_submit=lambda fen: False)
    modal.text_input.text = "garbage"
    modal._submit()
    assert "invalid" in modal.error.lower()


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


# ---------- Frontend integration ----------

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


def test_start_menu_emits_fen_callback():
    captured = {}
    callbacks = {
        "start_game": lambda cfg: None,
        "fen": lambda: captured.setdefault("opened", True),
    }
    from frontend.modals.start import StartMenu
    sm = StartMenu(pg.display.get_surface(), callbacks)
    sm.set_rect(pg.Rect(100, 50, 600, 700))
    sm.show()
    sm.draw()
    sm.handle_click(sm._fen_rect.center)
    assert captured.get("opened") is True
