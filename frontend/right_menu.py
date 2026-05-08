import pygame as pg

from frontend.colors import Colors
from frontend.pgn import iter_move_pairs
from frontend.widgets import draw_button_row


BUTTONS = [
    ("Undo", "undo"),
    ("Resign", "resign"),
    ("Draw", "draw"),
    ("Flip", "flip"),
]

REVIEW_BUTTONS = [
    ("Menu", "menu"),
    ("Flip", "flip"),
]

SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18


class RightMenu:

    def __init__(self, window, backend, callbacks, board=None,
                 buttons_provider=None):
        self.window = window
        self.backend = backend
        self.callbacks = callbacks
        self.board = board
        self.buttons_provider = buttons_provider or (lambda: BUTTONS)

        self.padding = 10
        self.button_gap = 6
        self.button_v_pad = 8
        self.moves_font_factor = 22
        self.button_font_factor = 28

        self.font = pg.font.SysFont("monospace", 16)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)

        self.outer_rect = pg.Rect(0, 0, 0, 0)
        self.moves_rect = pg.Rect(0, 0, 0, 0)
        self.buttons_rect = pg.Rect(0, 0, 0, 0)
        self.button_rects = {}

        self.scroll_offset = 0
        self._total_rows = 0
        self._max_lines = 0
        self._last_scroll_activity_ms = 0
        self._move_cell_hits = []

    def set_rect(self, rect):
        self.font = pg.font.SysFont(
            "monospace", max(int(rect.width / self.moves_font_factor), 10)
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.width / self.button_font_factor), 10), bold=True
        )

        p = self.padding
        self.outer_rect = pg.Rect(
            rect.x + p, rect.y + p,
            rect.width - 2 * p, rect.height - 2 * p,
        )

        button_row_h = self.button_font.get_height() + 2 * self.button_v_pad
        inner_w = self.outer_rect.width - 2 * p

        self.buttons_rect = pg.Rect(
            self.outer_rect.x + p,
            self.outer_rect.bottom - p - button_row_h,
            inner_w,
            button_row_h,
        )

        moves_h = max(self.buttons_rect.y - self.outer_rect.y - 2 * p, 0)
        self.moves_rect = pg.Rect(
            self.outer_rect.x + p,
            self.outer_rect.y + p,
            inner_w,
            moves_h,
        )

    def draw_menu(self):
        pg.draw.rect(self.window, Colors.dark_menu, self.outer_rect)
        pg.draw.rect(self.window, Colors.light_grey_menu, self.moves_rect)
        pg.draw.rect(self.window, Colors.light_grey_menu, self.buttons_rect)
        self._draw_moves(self.moves_rect)
        self._draw_scroll_indicator(self.moves_rect)
        self._draw_buttons(self.buttons_rect)

    def handle_click(self, pos):
        for key, rect in self.button_rects.items():
            if rect.collidepoint(pos):
                callback = self.callbacks.get(key)
                if callback is not None:
                    callback()
                return True
        if self.board is None or not self.moves_rect.collidepoint(pos):
            return False
        for cell_rect, ply in self._move_cell_hits:
            if not cell_rect.collidepoint(pos):
                continue
            self.board.animate_review_ply(ply)
            return True
        return False

    def handle_scroll(self, pos, dy):
        if not self.moves_rect.collidepoint(pos):
            return False
        max_offset = max(0, self._total_rows - self._max_lines)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset + dy, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True

    def _draw_moves(self, rect):
        history = self.backend.move_history
        line_h = self.font.get_linesize()
        self._max_lines = max(int((rect.height - 2 * self.padding) // line_h), 0)

        pairs = list(iter_move_pairs(history))
        self._total_rows = len(pairs)

        max_offset = max(0, self._total_rows - self._max_lines)
        self.scroll_offset = min(self.scroll_offset, max_offset)

        end = self._total_rows - self.scroll_offset
        start = max(0, end - self._max_lines)

        active_ply = self._active_ply(len(history))
        self._move_cell_hits = []

        char_w, _ = self.font.size("0")
        prefix_chars = 5  # "  1. " etc.
        prefix_w = char_w * prefix_chars
        cell_pad = 4
        inner_w = rect.width - 2 * self.padding
        cell_w = max((inner_w - prefix_w) // 2 - cell_pad, char_w * 4)

        for i, pair_idx in enumerate(range(start, end)):
            number, white_entry, black_entry = pairs[pair_idx]
            white_ply = pair_idx * 2 + 1
            black_ply = pair_idx * 2 + 2 if black_entry is not None else None

            row_y = rect.y + self.padding + i * line_h
            row_x = rect.x + self.padding

            prefix_surf = self.font.render(f"{number:>3}.", True, Colors.white)
            self.window.blit(prefix_surf, (row_x, row_y))

            white_x = row_x + prefix_w
            white_cell = pg.Rect(white_x, row_y, cell_w, line_h)
            self._draw_move_cell(white_cell, white_entry.san, active_ply == white_ply)
            self._move_cell_hits.append((white_cell, white_ply))

            if black_entry is not None:
                black_x = white_x + cell_w + cell_pad
                black_cell = pg.Rect(black_x, row_y, cell_w, line_h)
                self._draw_move_cell(black_cell, black_entry.san, active_ply == black_ply)
                self._move_cell_hits.append((black_cell, black_ply))

    def _draw_move_cell(self, rect, san, active):
        if active:
            pg.draw.rect(self.window, Colors.button_hover, rect, border_radius=3)
        surf = self.font.render(san, True, Colors.white)
        self.window.blit(surf, (rect.x + 2, rect.y))

    def _active_ply(self, history_len):
        if self.board is not None and self.board.review_ply is not None:
            return self.board.review_ply
        return history_len

    def _draw_scroll_indicator(self, rect):
        max_offset = max(0, self._total_rows - self._max_lines)
        if max_offset == 0:
            return
        if pg.time.get_ticks() - self._last_scroll_activity_ms > SCROLL_FADE_MS:
            return

        track_y = rect.y + self.padding
        track_h = rect.height - 2 * self.padding
        if track_h <= 0:
            return

        thumb_h = max(SCROLL_THUMB_MIN_HEIGHT,
                      int(track_h * self._max_lines / self._total_rows))
        thumb_h = min(thumb_h, track_h)
        thumb_y = track_y + int((track_h - thumb_h) * (1 - self.scroll_offset / max_offset))
        thumb_x = rect.right - SCROLL_THUMB_RIGHT_OFFSET - SCROLL_THUMB_WIDTH

        thumb_rect = pg.Rect(thumb_x, thumb_y, SCROLL_THUMB_WIDTH, thumb_h)
        pg.draw.rect(self.window, Colors.button_hover, thumb_rect,
                     border_radius=SCROLL_THUMB_WIDTH // 2)

    def _draw_buttons(self, rect):
        self.button_rects = draw_button_row(
            self.window, rect, self.buttons_provider(),
            self.button_font, self.button_gap,
        )
