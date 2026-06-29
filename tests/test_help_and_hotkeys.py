"""Help modal + R/D + Q/R/B/N hotkeys.

Drives keys through Frontend._handle_shortcut_key / _handle_promotion_key to
verify the help modal toggles, resign/draw open the right confirm prompt, and a
pending promotion both consumes the piece key and shadows the resign hotkey.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.modals.help import HelpModal, HOTKEYS


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _make_app():
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


def _key_event(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


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
    app.help_modal.draw()
    close_rect = app.help_modal.button_rects.get("close")
    assert close_rect is not None
    app.help_modal.handle_click(close_rect.center)
    assert app.help_modal.is_visible() is False


@pytest.mark.parametrize("key,title,yes_label", [
    pytest.param(pg.K_r, "Tap out?", "I'm done", id="r_opens_resign_confirm"),
    pytest.param(pg.K_d, "Offer a draw?", "Offer draw", id="d_opens_draw_confirm"),
])
def test_action_hotkey_opens_confirm(key, title, yes_label):
    app = _make_app()
    app._handle_shortcut_key(_key_event(key))
    assert app.confirm_modal.is_visible() is True
    assert app.confirm_modal.title == title
    assert app.confirm_modal.yes_label == yes_label


def test_r_key_no_op_when_game_over():
    app = _make_app()
    app.manual_result = "white_wins"
    app._handle_shortcut_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is False


def _setup_promotion_pending(app, color):
    app.skillcheck.enabled = False
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
    src = Square(1 if color == PieceColor.WHITE else 6, 0)
    dst = Square(0 if color == PieceColor.WHITE else 7, 0)
    app.board.handle_click(src)
    app.board.handle_click(dst)
    if app.board.is_animating():
        for a in list(app.board.animations):
            a.start_ms = pg.time.get_ticks() - 10_000
        app.board._draw_animations()
    assert app.board.pending_promotion_square == dst
    return dst


@pytest.mark.parametrize("key,expected", [
    pytest.param(pg.K_q, PieceType.QUEEN, id="q_promotes_to_queen"),
    pytest.param(pg.K_r, PieceType.ROOK, id="r_promotes_to_rook"),
    pytest.param(pg.K_b, PieceType.BISHOP, id="b_promotes_to_bishop"),
    pytest.param(pg.K_n, PieceType.KNIGHT, id="n_promotes_to_knight"),
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
    """With nothing to promote, Q falls through (_handle_promotion_key returns False)."""
    app = _make_app()
    handled = app._handle_promotion_key(_key_event(pg.K_q))
    assert handled is False


def test_r_during_promotion_picks_rook_not_resign():
    """Promotion picker takes priority over the resign hotkey when active."""
    app = _make_app()
    _setup_promotion_pending(app, PieceColor.WHITE)
    app._handle_shortcut_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is False
    assert app.board.pending_promotion_square is None


def test_fullscreen_hotkey_is_documented():
    assert any(key == "F11" and "fullscreen" in label.lower() for key, label in HOTKEYS)


def test_review_row_uses_real_arrow_glyphs():
    """Regression: the review-step row shows real left/right arrows.

    The SANS body font lacks U+2190/U+2192 and rendered them as the .notdef
    box (tofu); the key column uses the mono font, which has the glyphs. Render
    each arrow and assert it differs from a guaranteed-missing glyph's box.
    """
    assert any("←" in key and "→" in key for key, _ in HOTKEYS)
    modal = HelpModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(200, 150, 420, 420))
    modal.show()
    modal.draw()
    tofu = pg.image.tobytes(
        modal.key_font.render(chr(0xE000), True, (255, 255, 255)), "RGBA")
    for arrow in ("←", "→"):
        glyph = pg.image.tobytes(
            modal.key_font.render(arrow, True, (255, 255, 255)), "RGBA")
        assert glyph != tofu
