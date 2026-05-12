import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from backend.backend import Backend
from frontend.panels.right import RightMenu
from frontend.visual.widgets import (
    SCROLL_FADE_MS, SCROLL_THUMB_RIGHT_OFFSET, SCROLL_THUMB_WIDTH,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


@pytest.fixture
def menu():
    backend = Backend()
    backend.new_game()
    rm = RightMenu(pg.display.get_surface(), backend, {
        "undo": lambda: None,
        "resign": lambda: None,
        "draw": lambda: None,
        "flip": lambda: None,
    })
    rm.set_rect(pg.Rect(0, 0, 300, 600))
    return rm


def play_n_moves(backend, n):
    # Synthesize fake history entries; we only care about the row count for scroll.
    from backend.utils import Square, Move, HistoryEntry
    from backend.pieces import Piece, PieceType, PieceColor
    pawn = Piece(PieceType.PAWN, PieceColor.WHITE)
    move = Move(Square(6, 0), Square(5, 0), pawn)
    backend.move_history = [
        HistoryEntry(move=move, prev_castling_rights=(),
                     prev_en_passant_target=None, prev_halfmove_clock=0,
                     position_key_added=("k",), san=f"a{i % 8 + 1}")
        for i in range(n)
    ]


def test_no_overflow_no_indicator_drawn(menu):
    menu.draw_menu()
    # _total_rows is 0 (no moves), no indicator.
    assert menu._total_rows == 0
    # handle_scroll over an empty list returns False.
    assert menu.handle_scroll(menu.moves_rect.center, 1) is False


def test_handle_scroll_outside_moves_rect_returns_false(menu):
    play_n_moves(menu.backend, 60)
    menu.draw_menu()
    outside = (menu.moves_rect.right + 100, menu.moves_rect.centery)
    assert menu.handle_scroll(outside, 1) is False


def test_handle_scroll_no_overflow_returns_false(menu):
    play_n_moves(menu.backend, 2)
    menu.draw_menu()
    assert menu._total_rows == 1
    assert menu._total_rows <= menu._max_lines
    assert menu.handle_scroll(menu.moves_rect.center, 1) is False


def test_handle_scroll_with_overflow_increments_offset(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    assert menu._total_rows > menu._max_lines
    assert menu.scroll_offset == 0
    assert menu.handle_scroll(menu.moves_rect.center, 1) is True
    assert menu.scroll_offset == 1


def test_handle_scroll_clamps_at_max(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    max_offset = menu._total_rows - menu._max_lines
    for _ in range(max_offset + 10):
        menu.handle_scroll(menu.moves_rect.center, 1)
    assert menu.scroll_offset == max_offset


def test_handle_scroll_clamps_at_zero(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.scroll_offset = 5
    for _ in range(20):
        menu.handle_scroll(menu.moves_rect.center, -1)
    assert menu.scroll_offset == 0


def test_handle_scroll_records_activity_timestamp(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    assert menu._last_scroll_activity_ms == 0
    before = pg.time.get_ticks()
    menu.handle_scroll(menu.moves_rect.center, 1)
    assert menu._last_scroll_activity_ms >= before


def test_visible_rows_slice_reflects_scroll_offset(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    # At offset=0, last `_max_lines` rows shown. At offset=N, slice shifts up by N.
    menu.scroll_offset = 5
    menu.draw_menu()
    # We can't directly assert what was rendered, but the offset is preserved.
    assert menu.scroll_offset == 5


def test_resize_recomputes_max_lines(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    initial_max = menu._max_lines
    menu.set_rect(pg.Rect(0, 0, 300, 200))
    menu.draw_menu()
    smaller_max = menu._max_lines
    assert smaller_max < initial_max


def test_resize_clamps_existing_offset(menu):
    # Modest history so a large resize fully accommodates everything.
    play_n_moves(menu.backend, 40)
    menu.set_rect(pg.Rect(0, 0, 300, 200))  # tight: forces overflow
    menu.draw_menu()
    assert menu._total_rows > menu._max_lines
    menu.scroll_offset = menu._total_rows - menu._max_lines
    menu.set_rect(pg.Rect(0, 0, 300, 1200))  # spacious: no overflow
    menu.draw_menu()
    assert menu.scroll_offset == 0


def test_indicator_visible_within_fade_window(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.handle_scroll(menu.moves_rect.center, 1)
    # Within 2s, indicator should be drawable. We exercise the draw path.
    menu.draw_menu()  # must not raise
    # The fade window check uses pg.time.get_ticks(); we just confirm logic.
    assert pg.time.get_ticks() - menu._last_scroll_activity_ms < SCROLL_FADE_MS


def test_indicator_fades_after_2s(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    # Pretend last activity was 3s ago.
    menu._last_scroll_activity_ms = pg.time.get_ticks() - SCROLL_FADE_MS - 1000
    # Drawing must not raise; indicator simply not drawn.
    menu.draw_menu()


def test_indicator_constants():
    assert SCROLL_FADE_MS == 2000
    assert SCROLL_THUMB_WIDTH > 0
    assert SCROLL_THUMB_RIGHT_OFFSET > 0


# ---------- M10: scroll preservation across new moves ----------

def test_scroll_offset_advances_when_user_was_scrolled_up(menu):
    play_n_moves(menu.backend, 200)  # plenty of overflow
    menu.draw_menu()
    menu.scroll_offset = 5
    menu.draw_menu()  # capture _last_seen_total_rows = current total
    seen_before = menu._last_seen_total_rows
    play_n_moves(menu.backend, 204)  # 2 more pairs
    menu.draw_menu()
    # The viewing window should have anchored on the same plies — offset bumped
    # by the same amount as total rows grew.
    assert menu.scroll_offset == 5 + (menu._total_rows - seen_before)


def test_scroll_offset_at_bottom_stays_at_bottom_when_new_moves_arrive(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    assert menu.scroll_offset == 0
    play_n_moves(menu.backend, 204)
    menu.draw_menu()
    assert menu.scroll_offset == 0


def test_reset_for_new_game_clears_scroll_state(menu):
    play_n_moves(menu.backend, 60)
    menu.draw_menu()
    menu.scroll_offset = 4
    menu.draw_menu()
    menu.reset_for_new_game()
    assert menu.scroll_offset == 0
    assert menu._total_rows == 0
    assert menu._last_seen_total_rows == 0
    assert menu._last_scroll_activity_ms == 0


# ---------- M10: review-mode auto-scroll to active ply ----------

class _StubBoard:
    def __init__(self, review_ply):
        self.review_ply = review_ply

    def animate_review_ply(self, _ply):
        pass


def test_review_mode_jumps_into_window_when_above_visible_range(menu):
    menu.board = _StubBoard(review_ply=2)  # very early ply
    play_n_moves(menu.backend, 200)
    menu.scroll_offset = 0  # at the bottom
    menu.draw_menu()
    # Review jumped to ply 2 (pair 0). The visible window must cover it.
    end = menu._total_rows - menu.scroll_offset
    start = max(0, end - menu._max_lines)
    assert start <= 0 < end


def test_review_mode_jumps_into_window_when_below_visible_range(menu):
    menu.board = _StubBoard(review_ply=160)  # late-game ply
    play_n_moves(menu.backend, 200)
    menu.scroll_offset = menu._total_rows  # silly large; clamps later
    menu.draw_menu()
    pair_idx = (160 - 1) // 2
    end = menu._total_rows - menu.scroll_offset
    start = max(0, end - menu._max_lines)
    assert start <= pair_idx < end


def test_live_play_no_active_jump_does_not_change_offset(menu):
    """When not in review mode the previous offset-preservation logic still
    governs (no review-mode forced jump)."""
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.scroll_offset = 3
    menu.draw_menu()
    assert menu.scroll_offset == 3
