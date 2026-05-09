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

INTRINSIC_WIDTH = 460
ROW_HEIGHT = 28
TITLE_HEIGHT = 40
BUTTON_HEIGHT = 40
MIN_ROW_FONT = 13
MIN_TITLE_FONT = 18
MIN_BUTTON_FONT = 13


class HelpModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self.button_rects = {}

    def set_rect(self, rect):
        # Sized off content + window, not the layout-provided rect. Layout
        # gives us a hint position but the modal owns its own dimensions to
        # keep text readable even on a short window.
        win_w, win_h = self.window.get_size()
        pad = self.padding
        intrinsic_h = pad + TITLE_HEIGHT + pad + len(HOTKEYS) * ROW_HEIGHT + pad + BUTTON_HEIGHT + pad
        w = min(INTRINSIC_WIDTH, max(win_w - 32, 200))
        h = min(intrinsic_h, max(win_h - 32, 200))
        self.rect = pg.Rect((win_w - w) // 2, (win_h - h) // 2, w, h)
        self._on_rect_changed()

    def _on_rect_changed(self):
        self.title_font = pg.font.SysFont(
            "Arial", max(TITLE_HEIGHT - 16, MIN_TITLE_FONT), bold=True,
        )
        self.row_font = pg.font.SysFont(
            "Arial", max(ROW_HEIGHT - 12, MIN_ROW_FONT), bold=False,
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(BUTTON_HEIGHT - 22, MIN_BUTTON_FONT), bold=True,
        )

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

        button_h = max(BUTTON_HEIGHT, self.button_font.get_height() + 12)
        rows_top = title_band.bottom + pad
        rows_bottom = self.rect.bottom - pad - button_h - pad
        rows_height = max(rows_bottom - rows_top, 1)
        line_h = max(rows_height // max(len(HOTKEYS), 1), self.row_font.get_height() + 2)

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
            desc_lines = self._wrap_text(desc, self.row_font, desc_col_w)
            self.window.blit(
                key_surf,
                (key_rect.x, key_rect.centery - key_surf.get_height() // 2),
            )
            line_height = self.row_font.get_height()
            block_h = line_height * len(desc_lines)
            block_top = desc_rect.centery - block_h // 2
            for j, line in enumerate(desc_lines):
                surf = self.row_font.render(line, True, Colors.white)
                self.window.blit(surf, (desc_rect.x, block_top + j * line_height))

        button_row = pg.Rect(
            self.rect.x + pad, self.rect.bottom - pad - button_h,
            self.rect.width - 2 * pad, button_h,
        )
        self.button_rects = draw_button_row(
            self.window, button_row, [("Close", "close")],
            self.button_font, pad,
        )

    @staticmethod
    def _wrap_text(text, font, max_width):
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def handle_click(self, pos):
        if not self._visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.hide()
                return True
        return False
