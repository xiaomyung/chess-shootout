"""Help modal + R/D + Q/R/B/N hotkeys.

Drives keys through GameScreen.handle_key / _handle_promotion_key to verify
resign/draw open the right confirm prompt and a pending promotion both
consumes the piece key and shadows the resign hotkey. The confirm-modal guard
and the any-key-closes-help behavior are dispatched earlier by the router's
check_events (before frontend.screen.handle_key is ever reached), so those
tests drive a real KEYDOWN through check_events instead.
"""

from collections import Counter

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.modals.help import HOTKEYS
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def _make_app():
    return start_single_screen(make_app(1000, 800), nickname="a",
                               time_minutes=None, increment_seconds=5, side="white")


def _key_event(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


def _dispatch(app, event):
    pg.event.clear()
    pg.event.post(event)
    app.input_router.check_events()


def test_help_modal_starts_hidden():
    app = _make_app()
    assert app.help_modal.is_visible() is False


def test_question_mark_opens_help():
    app = _make_app()
    app.game.handle_key(_key_event(pg.K_SLASH, unicode="?"))
    assert app.help_modal.is_visible() is True


def test_any_key_closes_help():
    """The modal registry (not GameScreen.handle_key) owns this now: help's
    handle_key hides unconditionally, and check_events reaches it before
    frontend.screen.handle_key."""
    app = _make_app()
    app.help_modal.show(HOTKEYS)
    _dispatch(app, _key_event(pg.K_a))
    assert app.help_modal.is_visible() is False


def test_help_modal_close_button_hides_it():
    app = _make_app()
    app.help_modal.show(HOTKEYS)
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
    app.game.handle_key(_key_event(key))
    assert app.confirm_modal.is_visible() is True
    assert app.confirm_modal.title == title
    assert app.confirm_modal.yes_label == yes_label


def test_r_key_no_op_when_game_over():
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.handle_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is False


def _setup_promotion_pending(app, color):
    app.game.skillcheck.enabled = False
    bk = app.game.match.backend
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
    app.game.board.handle_click(src)
    app.game.board.handle_click(dst)
    if app.game.board.is_animating():
        for a in list(app.game.board.animations):
            a.start_ms = pg.time.get_ticks() - 10_000
        app.game.board._draw_animations()
    assert app.game.board.pending_promotion_square == dst
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
    handled = app.game.handle_key(_key_event(key))
    assert handled is True
    assert app.game.board.pending_promotion_square is None
    promoted = app.game.match.backend.state[dst.row][dst.col]
    assert promoted.type == expected
    assert promoted.color == PieceColor.WHITE


def test_promotion_hotkey_no_op_when_no_pending_promotion():
    """With nothing to promote, Q falls through (_handle_promotion_key returns False)."""
    app = _make_app()
    handled = app.game._handle_promotion_key(_key_event(pg.K_q))
    assert handled is False


def test_r_during_promotion_picks_rook_not_resign():
    """Promotion picker takes priority over the resign hotkey when active."""
    app = _make_app()
    _setup_promotion_pending(app, PieceColor.WHITE)
    app.game.handle_key(_key_event(pg.K_r))
    assert app.confirm_modal.is_visible() is False
    assert app.game.board.pending_promotion_square is None


def test_confirm_modal_blocks_promotion_hotkey():
    """Regression: Q/R/B/N used to reach _handle_promotion_key before the
    confirm-modal guard, so a promotion could be applied behind an open
    resign-confirm modal. The router's check_events forwards keys to the
    topmost visible modal and never reaches screen.handle_key at all."""
    app = _make_app()
    dst = _setup_promotion_pending(app, PieceColor.WHITE)
    app.confirm_modal.show("Tap out?", on_yes=lambda: None)
    history_before = list(app.game.match.move_history)
    _dispatch(app, _key_event(pg.K_q))
    assert app.game.board.pending_promotion_square == dst
    assert app.game.match.move_history == history_before
    assert app.game.match.backend.state[dst.row][dst.col].type == PieceType.PAWN


def test_fullscreen_hotkey_is_documented():
    assert any(key == "F11" and "fullscreen" in label.lower() for key, label in HOTKEYS)


def test_focus_mode_hotkey_is_documented():
    assert any(key == "H" and "focus" in label.lower() for key, label in HOTKEYS)


def test_hotkeys_keys_are_ascii_only():
    """Regression: a non-ASCII key label (the old left/right arrow glyphs)
    tofu'd on some bundled-font builds. Every HOTKEYS key label must stay
    plain ASCII so it never depends on glyph coverage."""
    for key, _ in HOTKEYS:
        assert key.isascii(), key
