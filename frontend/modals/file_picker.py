import pygame as pg

from frontend.pgn.load import result_mark, scan_pgn_summaries
from frontend.visual.colors import Colors
from frontend.visual.widgets import draw_button, draw_scroll_thumb, fit_text_to_rect
from frontend.visual.fonts import get_font


COLUMN_TITLES = ("Time", "Type", "Time Control", "White", "Black", "Result")
COLUMN_WEIGHTS = (0.25, 0.10, 0.13, 0.21, 0.21, 0.10)
ROW_PAD_Y = 8


class FilePicker:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.visible = False
        self.title = "History"
        self.entries = []
        self.on_select = None
        self.on_cancel = None
        self.nickname = None
        self.scroll_offset = 0
        self.padding = 14
        self.title_font = get_font(22, bold=True)
        self.header_font = get_font(14, bold=True)
        self.row_font = get_font(14)
        self.button_font = get_font(14, bold=True)
        self._row_rects = []
        self._cancel_rect = pg.Rect(0, 0, 0, 0)
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._max_visible = 0
        self._last_scroll_activity_ms = 0

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self.title_font = get_font(max(int(rect.height / 18), 16), bold=True)
        self.header_font = get_font(max(int(rect.height / 30), 13), bold=True)
        self.row_font = get_font(max(int(rect.height / 30), 12))
        self.button_font = get_font(max(int(rect.height / 30), 12), bold=True)

    def show(self, directory, pattern, on_select, on_cancel=None, nickname=None):
        self.entries = scan_pgn_summaries(directory, pattern)
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.nickname = nickname
        self.scroll_offset = 0
        self.visible = True

    def hide(self):
        self.visible = False
        self.entries = []
        self.on_select = None
        self.on_cancel = None
        self._row_rects = []
        self._cancel_rect = pg.Rect(0, 0, 0, 0)

    def is_visible(self):
        return self.visible

    def _column_rects(self, inner_x, inner_w, y, h):
        rects = []
        x = inner_x
        for i, weight in enumerate(COLUMN_WEIGHTS):
            if i == len(COLUMN_WEIGHTS) - 1:
                w = inner_x + inner_w - x
            else:
                w = inner_w * weight
            rects.append(pg.Rect(x, y, w, h))
            x += w
        return rects

    def _blit_centered(self, surf, cell):
        self.window.blit(surf, surf.get_rect(center=cell.center))

    def draw(self):
        if not self.visible:
            return

        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)

        inner_x = self.rect.x + self.padding
        inner_w = self.rect.width - 2 * self.padding

        title_surf = fit_text_to_rect(
            self.title_font.render(self.title, True, Colors.white),
            pg.Rect(inner_x, self.rect.y + self.padding, inner_w,
                    self.title_font.get_height()),
        )
        self.window.blit(
            title_surf,
            title_surf.get_rect(
                centerx=self.rect.centerx, top=self.rect.y + self.padding,
            ),
        )

        list_top = self.rect.y + self.padding * 2 + title_surf.get_height()
        header_h = self.header_font.get_height() + ROW_PAD_Y
        btn_h = max(int(self.rect.height * 0.1), 28)
        body_top = list_top + header_h
        body_bottom = self.rect.bottom - self.padding * 2 - btn_h
        row_h = self.row_font.get_height() + ROW_PAD_Y
        body_height = max(body_bottom - body_top, 0)
        max_visible = max(int(body_height // row_h), 1)
        self._max_visible = max_visible
        self._list_rect = pg.Rect(inner_x, body_top, inner_w, max_visible * row_h)
        self._row_rects = []

        max_offset = max(0, len(self.entries) - max_visible)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

        visible = self.entries[
            self.scroll_offset: self.scroll_offset + max_visible
        ]

        if visible:
            sep_bottom = body_top + len(visible) * row_h
            for cell in self._column_rects(inner_x, inner_w, list_top, 1)[:-1]:
                pg.draw.line(
                    self.window, Colors.button_border,
                    (cell.right, list_top), (cell.right, sep_bottom), 1,
                )

        header_cells = self._column_rects(inner_x, inner_w, list_top, header_h)
        for cell, title in zip(header_cells, COLUMN_TITLES):
            surf = fit_text_to_rect(
                self.header_font.render(title, True, Colors.white), cell,
            )
            self._blit_centered(surf, cell)
        pg.draw.line(
            self.window, Colors.button_border,
            (inner_x, list_top + header_h),
            (inner_x + inner_w, list_top + header_h), 1,
        )

        if not self.entries:
            empty_surf = self.row_font.render(
                "No saved games found", True, Colors.button_border,
            )
            self.window.blit(
                empty_surf,
                empty_surf.get_rect(
                    centerx=self.rect.centerx, top=body_top + self.padding,
                ),
            )
        else:
            prev_clip = self.window.get_clip()
            self.window.set_clip(self._list_rect)
            try:
                for i, summary in enumerate(visible):
                    row_rect = pg.Rect(
                        inner_x, body_top + i * row_h, inner_w, row_h,
                    )
                    self._row_rects.append((row_rect, summary.path))
                    if row_rect.collidepoint(pg.mouse.get_pos()):
                        pg.draw.rect(self.window, Colors.button_hover, row_rect)
                    cells = self._column_rects(
                        inner_x, inner_w, row_rect.y, row_h,
                    )
                    fields = (
                        summary.time, summary.type, summary.time_control,
                        summary.white, summary.black,
                    )
                    for cell, field in zip(cells, fields):
                        surf = fit_text_to_rect(
                            self.row_font.render(field, True, Colors.white), cell,
                        )
                        self._blit_centered(surf, cell)
                    symbol, color = result_mark(
                        summary.result_code, summary.white, summary.black,
                        self.nickname,
                    )
                    symbol_surf = fit_text_to_rect(
                        self.header_font.render(symbol, True, color), cells[-1],
                    )
                    self._blit_centered(symbol_surf, cells[-1])
            finally:
                self.window.set_clip(prev_clip)

        self._draw_scroll_indicator()

        cancel_rect = pg.Rect(
            inner_x,
            self.rect.bottom - self.padding - btn_h,
            inner_w,
            btn_h,
        )
        self._cancel_rect = cancel_rect
        draw_button(self.window, cancel_rect, "Cancel", self.button_font)

    def _draw_scroll_indicator(self):
        total = len(self.entries)
        max_offset = max(0, total - self._max_visible)
        if max_offset == 0:
            return
        offset_fraction = self.scroll_offset / max_offset
        draw_scroll_thumb(
            self.window, self._list_rect, total, self._max_visible,
            offset_fraction, self._last_scroll_activity_ms,
        )

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._cancel_rect.collidepoint(pos):
            cb = self.on_cancel
            self.hide()
            if cb is not None:
                cb()
            return True
        for row_rect, path in self._row_rects:
            if row_rect.collidepoint(pos):
                cb = self.on_select
                self.hide()
                if cb is not None:
                    cb(path)
                return True
        if self.rect.collidepoint(pos):
            return True
        return False

    def handle_scroll(self, pos, dy):
        if not self.visible:
            return False
        if not self._list_rect.collidepoint(pos):
            return False
        max_offset = max(0, len(self.entries) - self._max_visible)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset - dy, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True
