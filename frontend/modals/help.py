import pygame as pg

from frontend.visual.colors import Colors
from frontend.modals.base import BaseModal
from frontend.visual.widgets import draw_button_row, fit_text_to_rect


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


class HelpModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self.button_rects = {}

    def _on_rect_changed(self):
        self.title_font = self.font(factor=14, min_size=14, bold=True)
        self.row_font = self.font(factor=28, min_size=10, bold=False)
        self.button_font = self.font(factor=24, min_size=11, bold=True)

    def show(self):
        self._visible = True

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
            self.rect.width - 2 * pad, max(self.title_font.get_height(), 28),
        )
        title_surf = fit_text_to_rect(
            self.title_font.render("Hotkeys", True, Colors.white), title_band,
        )
        self.window.blit(
            title_surf,
            (self.rect.centerx - title_surf.get_width() / 2, title_band.y),
        )

        button_h = self.button_font.get_height() + 16
        rows_top = title_band.bottom + pad
        rows_bottom = self.rect.bottom - pad - button_h - pad
        rows_height = max(rows_bottom - rows_top, 1)
        line_h = max(rows_height // max(len(HOTKEYS), 1), 1)

        inner_w = self.rect.width - 2 * pad
        key_col_w = int(inner_w * 0.35)
        desc_col_w = inner_w - key_col_w - pad
        for i, (key, desc) in enumerate(HOTKEYS):
            row_y = rows_top + i * line_h
            if row_y + line_h > rows_bottom:
                break
            key_rect = pg.Rect(self.rect.x + pad, row_y, key_col_w, line_h)
            desc_rect = pg.Rect(
                self.rect.x + pad + key_col_w + pad, row_y, desc_col_w, line_h,
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

        button_row = pg.Rect(
            self.rect.x + pad, self.rect.bottom - pad - button_h,
            self.rect.width - 2 * pad, button_h,
        )
        self.button_rects = draw_button_row(
            self.window, button_row, [("Close", "close")],
            self.button_font, pad,
        )

    def handle_click(self, pos):
        if not self._visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.hide()
                return True
        return False
