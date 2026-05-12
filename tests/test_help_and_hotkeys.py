"""Help modal + R/D + Q/R/B/N hotkeys (M13)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square


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
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


def _key_event(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


# ---------- Help modal ----------

def test_help_modal_starts_hidden():
    app = _make_app()
    assert app.help_modal.is_visible() is False


def test_question_mark_opens_help():
    app = _make_app()
    app._handle_shortcut_key(_key_event(pg.K_SLASH, unicode="?"))
    assert app.help_modal.is_visible() is True


def test_any_key_closes_help():
    app = _make_app()
    app.help_modal.show()
    app._handle_shortcut_key(_key_event(pg.K_a))
    assert app.help_modal.is_visible() is False


def test_help_modal_close_button_hides_it():
    app = _make_app()
    app.help_modal.show()
    app.help_modal.draw()  # builds button rects
    close_rect = app.help_modal.button_rects.get("close")
    assert close_rect is not None
    app.help_modal.handle_click(close_rect.center)
    assert app.help_modal.is_visible() is False


# ---------- Resign / Draw hotkeys ----------

def test_r_key_opens_resign_confirm():
    app = _make_app()
    app._handle_shortcut_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is True


def test_d_key_opens_draw_confirm():
    app = _make_app()
    app._handle_shortcut_key(_key_event(pg.K_d))
    assert app.confirm_modal.is_visible() is True


def test_r_key_no_op_when_game_over():
    app = _make_app()
    app.manual_result = "white_wins"
    app._handle_shortcut_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is False


# ---------- Promotion hotkeys ----------

def _setup_promotion_pending(app, color):
    bk = app.backend
    bk.state = [[None] * 8 for _ in range(8)]
    bk.state[1 if color == PieceColor.WHITE else 6][0] = Piece(
        PieceType.PAWN, color)
    bk.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    bk.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    bk.turn = color
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1
    # White e7 -> e8 (or black analogue) puts the pawn one row from promotion.
    src = Square(1 if color == PieceColor.WHITE else 6, 0)
    dst = Square(0 if color == PieceColor.WHITE else 7, 0)
    app.board.handle_click(src)
    app.board.handle_click(dst)
    # Drive any animation to completion so the picker is set.
    if app.board.is_animating():
        for a in list(app.board.animations):
            a.start_ms = pg.time.get_ticks() - 10_000
        app.board._draw_animations()
    assert app.board.pending_promotion_square == dst
    return dst


@pytest.mark.parametrize("key,expected", [
    (pg.K_q, PieceType.QUEEN),
    (pg.K_r, PieceType.ROOK),
    (pg.K_b, PieceType.BISHOP),
    (pg.K_n, PieceType.KNIGHT),
])
def test_promotion_hotkey_picks_piece(key, expected):
    app = _make_app()
    dst = _setup_promotion_pending(app, PieceColor.WHITE)
    handled = app._handle_shortcut_key(_key_event(key))
    assert handled is True
    assert app.board.pending_promotion_square is None
    promoted = app.backend.state[dst.row][dst.col]
    assert promoted.type == expected
    assert promoted.color == PieceColor.WHITE


def test_promotion_hotkey_no_op_when_no_pending_promotion():
    app = _make_app()
    # No promotion pending — Q key falls through to the regular flow (returns
    # False from _handle_promotion_key, then nothing in the chain matches Q).
    handled = app._handle_promotion_key(_key_event(pg.K_q))
    assert handled is False


def test_r_during_promotion_picks_rook_not_resign():
    """Promotion picker takes priority over the resign hotkey when active."""
    app = _make_app()
    _setup_promotion_pending(app, PieceColor.WHITE)
    app._handle_shortcut_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is False  # resign NOT triggered
    assert app.board.pending_promotion_square is None  # rook chosen instead
