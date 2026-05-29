import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.widgets import draw_button_row, fit_text_to_rect
from frontend.visual.fonts import get_font


class WaitModal:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.padding = 12
        self.title = None
        self.subtitle = ""
        self.on_cancel = None
        self.title_font = get_font(22, bold=True)
        self.subtitle_font = get_font(14)
        self.button_font = get_font(14, bold=True)
        self.button_rects = {}

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self.title_font = get_font(max(int(rect.height / 6), 18), bold=True)
        self.subtitle_font = get_font(max(int(rect.height / 12), 14))
        self.button_font = get_font(max(int(rect.height / 14), 12), bold=True)

    def show(self, title, on_cancel):
        self.title = title
        self.subtitle = ""
        self.on_cancel = on_cancel

    def set_subtitle(self, subtitle):
        self.subtitle = subtitle

    def hide(self):
        self.title = None
        self.subtitle = ""
        self.on_cancel = None
        self.button_rects = {}

    def is_visible(self):
        return self.title is not None

    def draw(self):
        if not self.is_visible():
            return
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)

        gap = self.padding
        btn_h = max(self.rect.height * 0.22, 28)
        text_top = self.rect.y + self.padding
        text_bottom = self.rect.bottom - gap - btn_h - self.padding
        text_height = max(text_bottom - text_top, 1)
        max_w = self.rect.width - 2 * self.padding

        if self.subtitle:
            title_max = pg.Rect(self.rect.x + self.padding, text_top,
                                max_w, int(text_height * 0.45))
            subtitle_max = pg.Rect(self.rect.x + self.padding, text_top,
                                   max_w, int(text_height * 0.35))
            title_surf = fit_text_to_rect(
                self.title_font.render(self.title, True, Colors.white), title_max,
            )
            sub_surf = fit_text_to_rect(
                self.subtitle_font.render(self.subtitle, True, Colors.white), subtitle_max,
            )
            leftover = text_height - title_surf.get_height() - sub_surf.get_height()
            inner_gap = min(max(leftover, 4), self.padding)
            block_h = title_surf.get_height() + inner_gap + sub_surf.get_height()
            block_top = text_top + (text_height - block_h) / 2
            self.window.blit(title_surf,
                             (self.rect.centerx - title_surf.get_width() / 2, block_top))
            self.window.blit(sub_surf,
                             (self.rect.centerx - sub_surf.get_width() / 2,
                              block_top + title_surf.get_height() + inner_gap))
        else:
            title_max = pg.Rect(self.rect.x + self.padding, text_top, max_w, text_height)
            title_surf = fit_text_to_rect(
                self.title_font.render(self.title, True, Colors.white), title_max,
            )
            title_y = text_top + (text_height - title_surf.get_height()) / 2
            self.window.blit(title_surf,
                             (self.rect.centerx - title_surf.get_width() / 2, title_y))

        row_rect = pg.Rect(
            self.rect.x + gap,
            self.rect.bottom - gap - btn_h,
            self.rect.width - 2 * gap,
            btn_h,
        )
        self.button_rects = draw_button_row(
            self.window, row_rect, [("Cancel", "cancel")],
            self.button_font, gap,
        )

    def handle_click(self, pos):
        if not self.is_visible():
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                callback = self.on_cancel
                self.hide()
                if callback is not None:
                    callback()
                return True
        return False
