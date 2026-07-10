"""Frontend dispatch for drag-scroll: _active_scrollable mirrors the wheel
cascade (and yields None behind a blocking modal), a press-drag-release over the
move list scrolls it without ever starting a board piece-drag, a tap on a row
still fires its action on release while a flick suppresses it, and a resize
cancels an in-flight gesture."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.backend.utils import Square, Move, HistoryEntry
from chessshootout.frontend.frontend import Frontend


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _config():
    return {"mode": "single_screen", "nickname": "alice",
            "time_minutes": 5, "increment_seconds": 2, "side": "white"}


def _entry(san):
    move = Move(Square(6, 0), Square(5, 0), Piece(PieceType.PAWN, PieceColor.WHITE))
    return HistoryEntry(move=move, prev_castling_rights=(), prev_en_passant_target=None,
                        prev_halfmove_clock=0, position_key_added=("k",), san=san)


def _game_app(n_moves=200):
    app = Frontend(1000, 800)
    app._on_start_game(_config())
    app.match.backend.move_history = [_entry(f"a{i % 8 + 1}") for i in range(n_moves)]
    app.draw_frame()
    return app


def test_active_scrollable_menu_then_game():
    app = Frontend(1000, 800)
    assert app.input_router._active_scrollable() is app.menu_page
    app._on_start_game(_config())
    assert app.input_router._active_scrollable() is app.right_menu


def test_active_scrollable_prefers_visible_modal():
    app = _game_app()
    app.help_modal.show()
    assert app.input_router._active_scrollable() is app.help_modal
    app.help_modal.hide()
    app.country_picker.show("US", lambda c: None)
    assert app.input_router._active_scrollable() is app.country_picker


def test_active_scrollable_none_behind_blocking_modal():
    app = _game_app()
    app.confirm_modal.show("Sure?", lambda: None)
    assert app.input_router._active_scrollable() is None


def test_move_list_drag_scrolls_without_board_drag():
    app = _game_app()
    vp = app.right_menu._moves_viewport
    before = app.right_menu.scroll_offset
    app.input_router._mouse_left_pressed((vp.centerx, vp.y + 20))
    assert app.input_router._scroll_pressed is app.right_menu
    app.input_router._handle_left_drag_motion((vp.centerx, vp.bottom - 10))
    app.input_router._mouse_left_released((vp.centerx, vp.bottom - 10))
    assert app.right_menu.scroll_offset != before
    assert app.board.dragging_from is None
    assert app.input_router._scroll_pressed is None


def test_move_list_tap_jumps_to_ply():
    app = _game_app()
    cell_rect, ply = app.right_menu._move_cell_hits[0]
    app.input_router._mouse_left_pressed(cell_rect.center)
    app.input_router._mouse_left_released(cell_rect.center)
    assert app.board.review_ply == ply


def test_country_tap_picks_on_release():
    app = _game_app()
    picked = []
    app.country_picker.show("US", lambda c: picked.append(c))
    app.draw_frame()
    row_rect, code = app.country_picker._row_rects[3]
    app.input_router._mouse_left_pressed(row_rect.center)
    app.input_router._mouse_left_released(row_rect.center)
    assert picked == [code]
    assert app.country_picker.is_visible() is False


def test_country_flick_suppresses_pick():
    app = _game_app()
    picked = []
    app.country_picker.show("US", lambda c: picked.append(c))
    app.draw_frame()
    lr = app.country_picker._list_rect
    app.input_router._mouse_left_pressed((lr.centerx, lr.y + 160))
    app.input_router._handle_left_drag_motion((lr.centerx, lr.y + 40))
    app.input_router._mouse_left_released((lr.centerx, lr.y + 40))
    assert picked == []
    assert app.country_picker.is_visible() is True


def test_move_list_fling_through_dispatch_ticks_cleanly():
    app = _game_app()
    rm = app.right_menu
    vp = rm._moves_viewport
    rm.scroll.handle_press((vp.centerx, vp.bottom - 10), now_ms=0)
    rm.scroll.handle_motion((vp.centerx, vp.bottom - 40), now_ms=16)
    rm.scroll.handle_motion((vp.centerx, vp.y + 10), now_ms=32)
    app.input_router._scroll_pressed = rm
    app.input_router._mouse_left_released((vp.centerx, vp.y + 10))
    assert app.input_router._scroll_pressed is None
    assert rm.scroll._flinging is True
    app.draw_frame()
    app.draw_frame()


def test_resize_cancels_active_gesture():
    app = _game_app()
    vp = app.right_menu._moves_viewport
    app.input_router._mouse_left_pressed((vp.centerx, vp.y + 20))
    app.input_router._handle_left_drag_motion((vp.centerx, vp.y + 80))
    assert app.input_router._scroll_pressed is app.right_menu
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 900, "h": 700}))
    app.input_router.check_events()
    assert app.input_router._scroll_pressed is None
    assert app.right_menu.scroll.is_active() is False
