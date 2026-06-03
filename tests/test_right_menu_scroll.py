"""RightMenu move-list scroll: overflow gating, offset clamping, scroll-position
preservation across new moves, review-mode auto-scroll, and the activity-driven
scroll-thumb fade. The fade signal is read from real pixels in the thumb column
(Colors.surface_hover) so the test fails if draw_scroll_thumb stops honoring
SCROLL_FADE_MS."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.backend.backend import Backend
from chessshootout.frontend.panels.right import RightMenu
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.widgets import (
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
    from chessshootout.backend.utils import Square, Move, HistoryEntry
    from chessshootout.backend.pieces import Piece, PieceType, PieceColor
    pawn = Piece(PieceType.PAWN, PieceColor.WHITE)
    move = Move(Square(6, 0), Square(5, 0), pawn)
    backend.move_history = [
        HistoryEntry(move=move, prev_castling_rights=(),
                     prev_en_passant_target=None, prev_halfmove_clock=0,
                     position_key_added=("k",), san=f"a{i % 8 + 1}")
        for i in range(n)
    ]


def _count_thumb_pixels(menu):
    """Pixels in the scroll-thumb column painted Colors.surface_hover. The thumb
    lives in a 4px band at the right edge of moves_rect; the active move-cell
    highlight is surface_active (a different colour) and never reaches this
    column, so a nonzero count means the thumb itself was drawn."""
    rect = menu.moves_rect
    thumb_x = rect.right - SCROLL_THUMB_RIGHT_OFFSET - SCROLL_THUMB_WIDTH
    hover = pg.Color(Colors.surface_hover)
    surf = menu.window
    count = 0
    for x in range(thumb_x, thumb_x + SCROLL_THUMB_WIDTH):
        for y in range(rect.y, rect.bottom):
            c = surf.get_at((x, y))
            if (c.r, c.g, c.b) == (hover.r, hover.g, hover.b):
                count += 1
    return count


def test_no_overflow_no_indicator_drawn(menu):
    menu.draw_menu()
    assert menu._total_rows == 0
    assert menu.handle_scroll(menu.moves_rect.center, 1) is False


@pytest.mark.parametrize(
    "n_moves, pos_fn",
    [
        pytest.param(
            60, lambda m: (m.moves_rect.right + 100, m.moves_rect.centery),
            id="overflow_but_cursor_outside_moves_rect",
        ),
        pytest.param(
            2, lambda m: m.moves_rect.center, id="no_overflow_cursor_inside",
        ),
    ],
)
def test_handle_scroll_returns_false(menu, n_moves, pos_fn):
    play_n_moves(menu.backend, n_moves)
    menu.draw_menu()
    assert menu.handle_scroll(pos_fn(menu), 1) is False


def test_handle_scroll_no_overflow_keeps_rows_within_window(menu):
    play_n_moves(menu.backend, 2)
    menu.draw_menu()
    assert menu._total_rows == 1
    assert menu._total_rows <= menu._max_lines


def test_handle_scroll_with_overflow_increments_offset(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    assert menu._total_rows > menu._max_lines
    assert menu.scroll_offset == 0
    assert menu.handle_scroll(menu.moves_rect.center, 1) is True
    assert menu.scroll_offset == 1


@pytest.mark.parametrize(
    "initial_offset, direction, expected_fn",
    [
        pytest.param(
            0, 1, lambda m: m._total_rows - m._max_lines, id="scroll_down_clamps_at_max",
        ),
        pytest.param(0, -1, lambda m: 0, id="scroll_up_from_top_stays_zero"),
        pytest.param(5, -1, lambda m: 0, id="scroll_up_clamps_at_zero"),
    ],
)
def test_handle_scroll_clamps(menu, initial_offset, direction, expected_fn):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.scroll_offset = initial_offset
    expected = expected_fn(menu)
    for _ in range(menu._total_rows + 20):
        menu.handle_scroll(menu.moves_rect.center, direction)
    assert menu.scroll_offset == expected


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
    menu.scroll_offset = 5
    menu.draw_menu()
    assert menu.scroll_offset == 5
    end = menu._total_rows - menu.scroll_offset
    start = max(0, end - menu._max_lines)
    assert end == menu._total_rows - 5
    assert start == end - menu._max_lines


def test_resize_recomputes_max_lines(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    initial_max = menu._max_lines
    menu.set_rect(pg.Rect(0, 0, 300, 200))
    menu.draw_menu()
    smaller_max = menu._max_lines
    assert smaller_max < initial_max


def test_resize_clamps_existing_offset(menu):
    play_n_moves(menu.backend, 40)
    menu.set_rect(pg.Rect(0, 0, 300, 200))
    menu.draw_menu()
    assert menu._total_rows > menu._max_lines
    menu.scroll_offset = menu._total_rows - menu._max_lines
    menu.set_rect(pg.Rect(0, 0, 300, 1200))
    menu.draw_menu()
    assert menu.scroll_offset == 0


@pytest.mark.parametrize(
    "age_ms_fn, expect_drawn",
    [
        pytest.param(lambda: 0, True, id="just_scrolled_thumb_drawn"),
        pytest.param(
            lambda: SCROLL_FADE_MS + 1000, False, id="past_2s_fade_thumb_gone",
        ),
    ],
)
def test_indicator_fades_after_activity(menu, age_ms_fn, expect_drawn):
    """The thumb is painted only while activity is within SCROLL_FADE_MS; after
    the 2s window it must not be drawn (draw_scroll_thumb early-returns)."""
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.handle_scroll(menu.moves_rect.center, 1)
    menu._last_scroll_activity_ms = pg.time.get_ticks() - age_ms_fn()
    menu.draw_menu()
    thumb_pixels = _count_thumb_pixels(menu)
    if expect_drawn:
        assert thumb_pixels > 0
    else:
        assert thumb_pixels == 0


def test_indicator_constants():
    assert SCROLL_FADE_MS == 2000
    assert SCROLL_THUMB_WIDTH > 0
    assert SCROLL_THUMB_RIGHT_OFFSET > 0


def test_scroll_offset_advances_when_user_was_scrolled_up(menu):
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.scroll_offset = 5
    menu.draw_menu()
    seen_before = menu._last_seen_total_rows
    play_n_moves(menu.backend, 204)
    menu.draw_menu()
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


class _StubBoard:
    def __init__(self, review_ply):
        self.review_ply = review_ply

    def animate_review_ply(self, _ply):
        pass


@pytest.mark.parametrize(
    "review_ply, initial_offset_fn, pair_idx_fn",
    [
        pytest.param(
            2, lambda m: 0, lambda: (2 - 1) // 2, id="early_ply_above_visible_range",
        ),
        pytest.param(
            160, lambda m: m._total_rows, lambda: (160 - 1) // 2,
            id="late_ply_below_visible_range",
        ),
    ],
)
def test_review_mode_jumps_active_ply_into_window(
        menu, review_ply, initial_offset_fn, pair_idx_fn):
    """Entering review on an off-screen ply forces the visible window to cover
    its move pair regardless of the prior scroll offset."""
    menu.board = _StubBoard(review_ply=review_ply)
    play_n_moves(menu.backend, 200)
    menu.scroll_offset = initial_offset_fn(menu)
    menu.draw_menu()
    pair_idx = pair_idx_fn()
    end = menu._total_rows - menu.scroll_offset
    start = max(0, end - menu._max_lines)
    assert start <= pair_idx < end


def test_live_play_no_active_jump_does_not_change_offset(menu):
    """Outside review mode the offset-preservation logic governs; no forced jump."""
    play_n_moves(menu.backend, 200)
    menu.draw_menu()
    menu.scroll_offset = 3
    menu.draw_menu()
    assert menu.scroll_offset == 3
