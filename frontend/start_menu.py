import pygame as pg

from frontend.colors import Colors
from frontend.widgets import draw_button_column


BUTTONS = [
    ("Single-screen", "single_screen"),
    ("Play with bot", "bot"),
    ("Play online", "online"),
]


class StartMenu:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.visible = True
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 12
        self.button_gap = 8
        self.title = "Chess"
        self.title_font_factor = 6
        self.button_font_factor = 14
        self.title_font = pg.font.SysFont("Arial", 28, bold=True)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
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

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def is_visible(self):
        return self.visible

    def draw(self):
        if not self.visible:
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

        col_top = title_y + title_surf.get_height() + self.padding
        col_rect = pg.Rect(
            rect.x + self.padding,
            col_top,
            rect.width - 2 * self.padding,
            rect.bottom - col_top - self.padding,
        )
        self.button_rects = draw_button_column(
            self.window, col_rect, BUTTONS, self.button_font, self.button_gap,
        )

    def handle_click(self, pos):
        if not self.visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.callbacks[key]()
                return True
        return False
