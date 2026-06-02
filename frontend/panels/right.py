import pygame as pg

from frontend.visual.colors import Colors
from frontend.pgn.generate import iter_move_pairs
from frontend.visual.widgets import draw_button_row, draw_scroll_thumb, draw_pill
from server.protocol import GIVE_TIME_SECONDS
from frontend.visual.fonts import get_font


BUTTONS = [
    [("Undo", "undo"), ("Resign", "resign"), ("Draw", "draw")],
    [(f"Give {GIVE_TIME_SECONDS} sec", "give_time"), ("Flip", "flip"), ("?", "help")],
]

UNTIMED_BUTTONS = [
    [("Undo", "undo"), ("Resign", "resign"), ("Draw", "draw")],
    [("Flip", "flip"), ("?", "help")],
]

REVIEW_BUTTONS = [
    [("Menu", "menu"), ("Flip", "flip"), ("?", "help")],
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
        self.moves_font_factor = 24
        self.button_font_factor = 28

        self.font = get_font(13, mono=True)
        self.moves_font = get_font(14, bold=True)
        self.button_font = get_font(14, bold=True)
        self.pill_font = get_font(11, bold=True)
        self.round_font = get_font(11, bold=True)

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
        self._last_review_ply = None

    @property
    def backend(self):
        return getattr(self.match, "backend", self.match)

    def set_rect(self, rect):
        self.font = get_font(max(int(rect.width / self.moves_font_factor), 10), mono=True)
        self.moves_font = get_font(
            max(int(rect.width / self.moves_font_factor), 10), bold=True)
        self.button_font = get_font(max(int(rect.width / self.button_font_factor), 10), bold=True)
        self.pill_font = get_font(max(int(rect.width / 34), 9), bold=True)
        self.round_font = get_font(max(int(rect.width / 34), 9), bold=True)

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

        n_rows = max(len(self.buttons_provider()), 1)
        buttons_block_h = n_rows * button_row_h + (n_rows - 1) * small_gap
        self.buttons_rect = pg.Rect(
            self.outer_rect.x + p,
            self.audio_rect.y - small_gap - buttons_block_h,
            inner_w,
            buttons_block_h,
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
        header_h = self.pill_font.get_height() + 12
        lines = self.game_info.get("lines", [])
        return header_h + self._info_line_height() * len(lines) + self.padding

    def _info_line_height(self):
        return self.font.get_linesize() + 2

    def set_game_info(self, info):
        self.game_info = info
        if self._last_outer_rect is not None:
            self.set_rect(self._last_outer_rect)

    def reset_for_new_game(self):
        self.scroll_offset = 0
        self._total_rows = 0
        self._last_seen_total_rows = 0
        self._last_scroll_activity_ms = 0
        self._last_review_ply = None

    OUTER_RADIUS = 10
    INNER_RADIUS = 8

    def draw_menu(self):
        pg.draw.rect(self.window, Colors.dark_menu, self.outer_rect,
                     border_radius=self.OUTER_RADIUS)
        if self.game_info is not None and self.info_rect.height > 0:
            self._draw_game_info(self.info_rect)
        pg.draw.rect(self.window, Colors.surface_inset, self.moves_rect,
                     border_radius=self.INNER_RADIUS)
        self._draw_moves(self.moves_rect)
        self._draw_scroll_indicator(self.moves_rect)
        self._draw_buttons(self.buttons_rect)
        if self.audio_panel is not None:
            rows = self.buttons_provider()
            n_cols = len(rows[0]) if rows else 5
            self.audio_panel.set_rect(
                self.audio_rect, button_font=self.button_font,
                n_columns=n_cols, gap=self.button_gap,
            )
            self.audio_panel.draw()

    def _draw_game_info(self, rect):
        info = self.game_info
        header_h = self.pill_font.get_height() + 12
        cx = rect.x
        cy = rect.y + header_h // 2
        mode = info.get("mode")
        if mode:
            cx = self._draw_mode_pill(mode.upper(), cx, cy) + 10
        tc = info.get("time_control")
        if tc:
            tc_surf = self.font.render(tc, True, Colors.white)
            self.window.blit(tc_surf, (cx, cy - tc_surf.get_height() / 2))
            cx += tc_surf.get_width() + 10
        rnd = info.get("round")
        if rnd:
            rnd_surf = self.round_font.render(f"ROUND {rnd}", True, Colors.text_mute)
            sep_x = rect.right - rnd_surf.get_width() - 12
            pg.draw.line(self.window, Colors.button_border,
                         (sep_x, cy - rnd_surf.get_height() // 2),
                         (sep_x, cy + rnd_surf.get_height() // 2))
            self.window.blit(rnd_surf, (rect.right - rnd_surf.get_width(),
                                        cy - rnd_surf.get_height() / 2))
        line_h = self._info_line_height()
        for i, line in enumerate(info.get("lines", [])):
            surf = self.font.render(line, True, Colors.text_dim)
            max_w = rect.width
            if surf.get_width() > max_w > 0:
                surf = surf.subsurface(pg.Rect(0, 0, max_w, surf.get_height()))
            self.window.blit(surf, (rect.x, rect.y + header_h + i * line_h))

    def _draw_mode_pill(self, text, x, cy):
        return draw_pill(self.window, text, x, cy, self.pill_font)

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
            self.board.jump_to_review_ply(ply)
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
        line_h = self.moves_font.get_linesize() + 2
        self._max_lines = max(int((rect.height - 2 * self.padding) // line_h), 0)

        pairs = list(iter_move_pairs(history))
        self._total_rows = len(pairs)

        if (self._last_seen_total_rows
                and self._total_rows > self._last_seen_total_rows
                and self.scroll_offset > 0):
            self.scroll_offset += self._total_rows - self._last_seen_total_rows
        self._last_seen_total_rows = self._total_rows

        max_offset = max(0, self._total_rows - self._max_lines)
        self.scroll_offset = min(self.scroll_offset, max_offset)

        self._reveal_active_ply_on_nav(len(history))

        end = self._total_rows - self.scroll_offset
        start = max(0, end - self._max_lines)

        active_ply = self._active_ply(len(history))
        self._move_cell_hits = []

        char_w, _ = self.font.size("0")
        prefix_w = char_w * 5
        cell_pad = 4
        inner_w = rect.width - 2 * self.padding
        cell_w = max((inner_w - prefix_w) // 2 - cell_pad, char_w * 4)

        for i, pair_idx in enumerate(range(start, end)):
            number, white_entry, black_entry = pairs[pair_idx]
            white_ply = pair_idx * 2 + 1
            black_ply = pair_idx * 2 + 2 if black_entry is not None else None

            row_y = rect.y + self.padding + i * line_h
            row_x = rect.x + self.padding

            prefix_surf = self.font.render(f"{number:>3}.", True, Colors.text_mute)
            self.window.blit(prefix_surf, (row_x, row_y + (line_h - prefix_surf.get_height()) // 2))

            white_x = row_x + prefix_w
            white_cell = pg.Rect(white_x, row_y, cell_w, line_h)
            self._draw_move_cell(white_cell, white_entry, active_ply == white_ply)
            self._move_cell_hits.append((white_cell, white_ply))

            if black_entry is not None:
                black_x = white_x + cell_w + cell_pad
                black_cell = pg.Rect(black_x, row_y, cell_w, line_h)
                self._draw_move_cell(black_cell, black_entry, active_ply == black_ply)
                self._move_cell_hits.append((black_cell, black_ply))

    def _reveal_active_ply_on_nav(self, history_len):
        review_ply = self.board.review_ply if self.board is not None else None
        if review_ply == self._last_review_ply:
            return
        self._last_review_ply = review_ply
        if review_ply is None or review_ply <= 0:
            return
        pair_idx = (review_ply - 1) // 2
        self.scroll_offset = self._scroll_offset_to_show_pair(pair_idx)

    def _draw_move_cell(self, rect, entry, active):
        if active:
            pg.draw.rect(self.window, Colors.button_pressed, rect, border_radius=4)
            pg.draw.rect(self.window, Colors.accent, rect, width=1, border_radius=4)
        color = Colors.white if active else Colors.text_dim
        surf = self.moves_font.render(entry.san, True, color)
        self.window.blit(surf, (rect.x + 4, rect.centery - surf.get_height() / 2))

    def _active_ply(self, history_len):
        if self.board is not None and self.board.review_ply is not None:
            return self.board.review_ply
        return history_len

    def _scroll_offset_to_show_pair(self, pair_idx):
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
        rows = self.buttons_provider()
        self.button_rects = {}
        if not rows:
            return
        row_h = (rect.height - (len(rows) - 1) * self.button_gap) / len(rows)
        disabled = self.disabled_keys_provider()
        for i, row in enumerate(rows):
            row_rect = pg.Rect(
                rect.x,
                round(rect.y + i * (row_h + self.button_gap)),
                rect.width,
                round(row_h),
            )
            self.button_rects.update(draw_button_row(
                self.window, row_rect, row, self.button_font, self.button_gap,
                disabled_keys=disabled,
            ))
