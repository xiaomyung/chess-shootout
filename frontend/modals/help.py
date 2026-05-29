import pygame as pg

from frontend.visual.colors import Colors
from frontend.modals.base import BaseModal
from frontend.visual.widgets import draw_button_row, fit_text_to_rect
from frontend.visual.fonts import get_font


HOTKEYS = [
    ("?", "Open this help"),
    ("F", "Flip board"),
    ("Ctrl+Z", "Undo move"),
    ("R", "Resign"),
    ("D", "Offer / accept draw"),
    ("Q  R  B  N", "Promotion picker (when shown)"),
    ("← →", "Step through moves (review)"),
    ("Home", "Jump to first move (review)"),
    ("End", "Return to live play"),
    ("Esc", "Close window"),
]

ROW_FONT_SIZE = 15
TITLE_FONT_SIZE = 22
BUTTON_FONT_SIZE = 14
ROW_PAD_Y = 10
MIN_WIDTH = 320
MIN_HEIGHT = 280


class HelpModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self.button_rects = {}
        self.scroll_offset = 0
        self._max_scroll_offset = 0
        self._rows_rect = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect):
        win_w, win_h = self.window.get_size()
        margin = 16
        cx = rect.centerx
        cy = rect.centery
        w = min(max(rect.width, MIN_WIDTH), max(win_w - margin, MIN_WIDTH))
        h = min(max(rect.height, MIN_HEIGHT), max(win_h - margin, MIN_HEIGHT))
        x = max(margin // 2, min(cx - w // 2, win_w - w - margin // 2))
        y = max(margin // 2, min(cy - h // 2, win_h - h - margin // 2))
        self.rect = pg.Rect(x, y, w, h)
        self._on_rect_changed()

    def _on_rect_changed(self):
        self.title_font = get_font(TITLE_FONT_SIZE, bold=True)
        self.row_font = get_font(ROW_FONT_SIZE, bold=False)
        self.button_font = get_font(BUTTON_FONT_SIZE, bold=True)

    def show(self):
        self._visible = True
        self.scroll_offset = 0

    def hide(self):
        self._visible = False
        self.button_rects = {}

    def is_visible(self):
        return self._visible

    def draw(self):
        if not self._visible:
            return
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)

        pad = self.padding
        title_band = pg.Rect(
            self.rect.x + pad, self.rect.y + pad,
            self.rect.width - 2 * pad, self.title_font.get_height() + 8,
        )
        title_surf = fit_text_to_rect(
            self.title_font.render("Hotkeys", True, Colors.white), title_band,
        )
        self.window.blit(
            title_surf,
            (self.rect.centerx - title_surf.get_width() / 2, title_band.y),
        )

        button_h = self.button_font.get_height() + 16
        button_row = pg.Rect(
            self.rect.x + pad, self.rect.bottom - pad - button_h,
            self.rect.width - 2 * pad, button_h,
        )

        rows_top = title_band.bottom + pad
        rows_bottom = button_row.y - pad
        self._rows_rect = pg.Rect(
            self.rect.x + pad, rows_top,
            self.rect.width - 2 * pad, max(rows_bottom - rows_top, 1),
        )
        self._draw_rows(self._rows_rect)

        self.button_rects = draw_button_row(
            self.window, button_row, [("Close", "close")],
            self.button_font, pad,
        )

    def _draw_rows(self, rows_rect):
        line_h = self.row_font.get_height() + ROW_PAD_Y
        visible = max(rows_rect.height // line_h, 1)
        self._max_scroll_offset = max(0, len(HOTKEYS) - visible)
        self.scroll_offset = min(self.scroll_offset, self._max_scroll_offset)

        prev_clip = self.window.get_clip()
        self.window.set_clip(rows_rect)
        try:
            inner_w = rows_rect.width
            key_col_w = int(inner_w * 0.35)
            desc_col_w = inner_w - key_col_w - self.padding
            start = self.scroll_offset
            end = min(start + visible, len(HOTKEYS))
            for i, idx in enumerate(range(start, end)):
                key, desc = HOTKEYS[idx]
                row_y = rows_rect.y + i * line_h
                key_rect = pg.Rect(rows_rect.x, row_y, key_col_w, line_h)
                desc_rect = pg.Rect(
                    rows_rect.x + key_col_w + self.padding, row_y,
                    desc_col_w, line_h,
                )
                key_surf = fit_text_to_rect(
                    self.row_font.render(key, True, Colors.white), key_rect,
                )
                desc_surf = fit_text_to_rect(
                    self.row_font.render(desc, True, Colors.white), desc_rect,
                )
                self.window.blit(
                    key_surf,
                    (key_rect.x, key_rect.centery - key_surf.get_height() // 2),
                )
                self.window.blit(
                    desc_surf,
                    (desc_rect.x, desc_rect.centery - desc_surf.get_height() // 2),
                )
                if i < end - start - 1:
                    sep_y = row_y + line_h - 1
                    pg.draw.line(
                        self.window, Colors.button_border,
                        (rows_rect.x, sep_y), (rows_rect.right, sep_y), 1,
                    )
        finally:
            self.window.set_clip(prev_clip)

    def handle_click(self, pos):
        if not self._visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.hide()
                return True
        return False

    def handle_scroll(self, pos, dy):
        if not self._visible:
            return False
        if not self._rows_rect.collidepoint(pos):
            return False
        if self._max_scroll_offset == 0:
            return False
        self.scroll_offset = max(
            0, min(self.scroll_offset - dy, self._max_scroll_offset),
        )
        return True
