import pygame as pg

from frontend.visual.colors import Colors
from frontend.pgn.generate import iter_move_pairs
from frontend.visual.widgets import draw_button_row, draw_scroll_thumb


BUTTONS = [
    ("Undo", "undo"),
    ("Resign", "resign"),
    ("Draw", "draw"),
    ("Flip", "flip"),
    ("?", "help"),
]

REVIEW_BUTTONS = [
    ("Menu", "menu"),
    ("Flip", "flip"),
    ("?", "help"),
]


class RightMenu:

    def __init__(self, window, match, callbacks, board=None,
                 buttons_provider=None, audio_panel=None,
                 disabled_keys_provider=None):
        self.window = window
        self.match = match
        self.callbacks = callbacks
        self.board = board
        self.buttons_provider = buttons_provider or (lambda: BUTTONS)
        self.audio_panel = audio_panel
        self.disabled_keys_provider = disabled_keys_provider or (lambda: set())

        self.padding = 10
        self.button_gap = 6
        self.button_v_pad = 8
        self.moves_font_factor = 22
        self.button_font_factor = 28

        self.font = pg.font.SysFont("monospace", 16)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)

        self.outer_rect = pg.Rect(0, 0, 0, 0)
        self.moves_rect = pg.Rect(0, 0, 0, 0)
        self.info_rect = pg.Rect(0, 0, 0, 0)
        self.buttons_rect = pg.Rect(0, 0, 0, 0)
        self.audio_rect = pg.Rect(0, 0, 0, 0)
        self.button_rects = {}
        self.game_info = None
        self._last_outer_rect = None

        self.scroll_offset = 0
        self._total_rows = 0
        self._max_lines = 0
        self._last_scroll_activity_ms = 0
        self._move_cell_hits = []
        self._last_seen_total_rows = 0

    @property
    def backend(self):
        inner = getattr(self.match, "backend", None)
        return inner if inner is not None else self.match

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
        self._last_outer_rect = pg.Rect(rect)

        button_row_h = self.button_font.get_height() + 2 * self.button_v_pad
        inner_w = self.outer_rect.width - 2 * p
        small_gap = max(int(self.outer_rect.height * 0.01), 4)

        self.audio_rect = pg.Rect(
            self.outer_rect.x + p,
            self.outer_rect.bottom - p - button_row_h,
            inner_w,
            button_row_h,
        )

        self.buttons_rect = pg.Rect(
            self.outer_rect.x + p,
            self.audio_rect.y - small_gap - button_row_h,
            inner_w,
            button_row_h,
        )

        info_h = self._info_section_height()
        info_y = self.outer_rect.y + p
        self.info_rect = pg.Rect(self.outer_rect.x + p, info_y, inner_w, info_h)

        moves_top = info_y + info_h + (small_gap if info_h > 0 else 0)
        moves_h = max(self.buttons_rect.y - moves_top - p, 0)
        self.moves_rect = pg.Rect(self.outer_rect.x + p, moves_top, inner_w, moves_h)

    def _info_section_height(self):
        if self.game_info is None:
            return 0
        return self.font.get_linesize() * 3 + self.padding

    def set_game_info(self, info):
        self.game_info = info
        if self._last_outer_rect is not None:
            self.set_rect(self._last_outer_rect)

    def reset_for_new_game(self):
        self.scroll_offset = 0
        self._total_rows = 0
        self._last_seen_total_rows = 0
        self._last_scroll_activity_ms = 0

    def draw_menu(self):
        pg.draw.rect(self.window, Colors.dark_menu, self.outer_rect)
        if self.game_info is not None and self.info_rect.height > 0:
            self._draw_game_info(self.info_rect)
        pg.draw.rect(self.window, Colors.light_grey_menu, self.moves_rect)
        self._draw_moves(self.moves_rect)
        self._draw_scroll_indicator(self.moves_rect)
        self._draw_buttons(self.buttons_rect)
        if self.audio_panel is not None:
            self.audio_panel.set_rect(self.audio_rect)
            self.audio_panel.draw()

    def _draw_game_info(self, rect):
        info = self.game_info
        line_h = self.font.get_linesize()
        names = f"{info.get('white_name', '?')}  vs  {info.get('black_name', '?')}"
        time_control = info.get("time_minutes", 0), info.get("increment_seconds", 0)
        tc_line = f"{time_control[0]} min + {time_control[1]} sec"
        ping_ms = info.get("ping_ms")
        ping_line = f"ping: {ping_ms} ms" if ping_ms is not None else "ping: —"
        for i, line in enumerate((names, tc_line, ping_line)):
            surf = self.font.render(line, True, Colors.white)
            max_w = rect.width - 2 * self.padding
            if surf.get_width() > max_w > 0:
                surf = surf.subsurface(pg.Rect(0, 0, max_w, surf.get_height()))
            self.window.blit(
                surf,
                (rect.x + (rect.width - surf.get_width()) // 2,
                 rect.y + i * line_h),
            )

    def handle_click(self, pos):
        disabled = self.disabled_keys_provider()
        for key, rect in self.button_rects.items():
            if rect.collidepoint(pos):
                if key in disabled:
                    return True
                callback = self.callbacks.get(key)
                if callback is not None:
                    callback()
                return True
        if self.audio_panel is not None and self.audio_panel.handle_click(pos):
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
        history = self.match.move_history
        line_h = self.font.get_linesize()
        self._max_lines = max(int((rect.height - 2 * self.padding) // line_h), 0)

        pairs = list(iter_move_pairs(history))
        self._total_rows = len(pairs)

        # If new pairs have appeared and the user was scrolled up, advance the
        # offset by the same amount so their viewing window stays anchored on
        # the same plies. When at the bottom (offset == 0), auto-follow keeps
        # the latest move visible (offset stays 0).
        if (self._last_seen_total_rows
                and self._total_rows > self._last_seen_total_rows
                and self.scroll_offset > 0):
            self.scroll_offset += self._total_rows - self._last_seen_total_rows
        self._last_seen_total_rows = self._total_rows

        max_offset = max(0, self._total_rows - self._max_lines)
        self.scroll_offset = min(self.scroll_offset, max_offset)

        # In review mode, always keep the active ply visible — the user
        # explicitly navigated to it.
        if self.board is not None and self.board.review_ply is not None:
            active_ply = self._active_ply(len(history))
            if active_ply > 0:
                pair_idx = (active_ply - 1) // 2
                self.scroll_offset = self._scroll_offset_to_show_pair(pair_idx)

        end = self._total_rows - self.scroll_offset
        start = max(0, end - self._max_lines)

        active_ply = self._active_ply(len(history))
        self._move_cell_hits = []

        char_w, _ = self.font.size("0")
        prefix_chars = 5
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

    def _scroll_offset_to_show_pair(self, pair_idx):
        """Pick a scroll_offset that keeps `pair_idx` inside the visible window."""
        if self._max_lines <= 0:
            return self.scroll_offset
        max_offset = max(0, self._total_rows - self._max_lines)
        end = self._total_rows - self.scroll_offset
        start = max(0, end - self._max_lines)
        if start <= pair_idx < end:
            return self.scroll_offset
        if pair_idx >= end:
            new_end = pair_idx + 1
        else:
            new_end = pair_idx + self._max_lines
        new_offset = self._total_rows - new_end
        return max(0, min(new_offset, max_offset))

    def _draw_scroll_indicator(self, rect):
        max_offset = max(0, self._total_rows - self._max_lines)
        if max_offset == 0:
            return
        track_rect = pg.Rect(
            rect.x, rect.y + self.padding,
            rect.width, rect.height - 2 * self.padding,
        )
        offset_fraction = 1 - self.scroll_offset / max_offset
        draw_scroll_thumb(
            self.window, track_rect, self._total_rows, self._max_lines,
            offset_fraction, self._last_scroll_activity_ms,
        )

    def _draw_buttons(self, rect):
        self.button_rects = draw_button_row(
            self.window, rect, self.buttons_provider(),
            self.button_font, self.button_gap,
            disabled_keys=self.disabled_keys_provider(),
        )
