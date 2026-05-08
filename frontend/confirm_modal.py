import pygame as pg

from frontend.colors import Colors
from frontend.widgets import draw_button_row


class ConfirmModal:

    def __init__(self, window):
        self.window = window
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 12
        self.title = None
        self.on_yes = None
        self.on_no = None
        self.title_font = pg.font.SysFont("Arial", 24, bold=True)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self.title_font_factor = 6
        self.button_font_factor = 14
        self.button_rects = {}

    def set_rect(self, rect):
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height
        self.title_font = pg.font.SysFont(
            "Arial", max(int(rect.height / self.title_font_factor), 12), bold=True
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.height / self.button_font_factor), 10), bold=True
        )

    def show(self, title, on_yes, on_no=None, yes_label="Yes", no_label="Cancel"):
        self.title = title
        self.on_yes = on_yes
        self.on_no = on_no
        self.yes_label = yes_label
        self.no_label = no_label

    def hide(self):
        self.title = None
        self.on_yes = None
        self.on_no = None
        self.button_rects = {}

    def is_visible(self):
        return self.title is not None

    def draw(self):
        if not self.is_visible():
            self.button_rects = {}
            return

        rect = pg.Rect(self.x, self.y, self.width, self.height)
        pg.draw.rect(self.window, Colors.light_grey_menu, rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, rect, 2, border_radius=8)

        title_surf = self.title_font.render(self.title, True, Colors.white)
        title_y = rect.y + self.padding * 2
        self.window.blit(
            title_surf,
            (rect.centerx - title_surf.get_width() / 2, title_y),
        )

        gap = self.padding
        btn_h = max(rect.height * 0.22, 28)
        row_rect = pg.Rect(
            rect.x + gap,
            rect.bottom - gap - btn_h,
            rect.width - 2 * gap,
            btn_h,
        )
        self.button_rects = draw_button_row(
            self.window,
            row_rect,
            [(self.yes_label, "yes"), (self.no_label, "no")],
            self.button_font,
            gap,
        )

    def handle_click(self, pos):
        if not self.is_visible():
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                callback = self.on_yes if key == "yes" else self.on_no
                self.hide()
                if callback is not None:
                    callback()
                return True
        return False
