import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.widgets import draw_button_row, fit_text_to_rect


BUTTONS = [
    ("New Game", "new_game"),
    ("Open PGN", "open_pgn"),
    ("Menu", "menu"),
]

ONLINE_BUTTONS = [
    ("Rematch", "rematch"),
    ("Open PGN", "open_pgn"),
    ("Menu", "menu"),
]


class ResultMenu:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.online_mode = False
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 12
        self.title_font = pg.font.SysFont("Arial", 28, bold=True)
        self.reason_font = pg.font.SysFont("Arial", 16)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self.title = None
        self.reason = None
        self.button_rects = {}
        self.title_font_factor = 6
        self.reason_font_factor = 12
        self.button_font_factor = 14

    def set_rect(self, rect):
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height
        self.title_font = pg.font.SysFont(
            "Arial", max(int(rect.height / self.title_font_factor), 12), bold=True
        )
        self.reason_font = pg.font.SysFont(
            "Arial", max(int(rect.height / self.reason_font_factor), 10)
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.height / self.button_font_factor), 10), bold=True
        )

    def set_text(self, title_reason):
        if title_reason is None:
            self.title = None
            self.reason = None
        else:
            self.title, self.reason = title_reason

    def is_visible(self):
        return self.title is not None

    def draw(self):
        if not self.is_visible():
            self.button_rects = {}
            return

        rect = pg.Rect(self.x, self.y, self.width, self.height)
        pg.draw.rect(self.window, Colors.light_grey_menu, rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, rect, 2, border_radius=8)

        text_band = pg.Rect(
            rect.x + self.padding, rect.y + self.padding * 2,
            rect.width - 2 * self.padding, int(rect.height * 0.45),
        )
        title_surf = fit_text_to_rect(
            self.title_font.render(self.title, True, Colors.white), text_band,
        )
        reason_surf = fit_text_to_rect(
            self.reason_font.render(self.reason, True, Colors.white), text_band,
        )

        title_y = text_band.y
        reason_y = title_y + title_surf.get_height() + 4

        self.window.blit(title_surf, (rect.centerx - title_surf.get_width() / 2, title_y))
        self.window.blit(reason_surf, (rect.centerx - reason_surf.get_width() / 2, reason_y))

        self._draw_buttons(rect)

    def handle_click(self, pos):
        if not self.is_visible():
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.callbacks[key]()
                return True
        return False

    def set_online_mode(self, online):
        self.online_mode = online

    def _draw_buttons(self, rect):
        gap = self.padding
        btn_h = max(rect.height * 0.18, 28)
        row_rect = pg.Rect(
            rect.x + gap,
            rect.bottom - gap - btn_h,
            rect.width - 2 * gap,
            btn_h,
        )
        buttons = ONLINE_BUTTONS if self.online_mode else BUTTONS
        self.button_rects = draw_button_row(
            self.window, row_rect, buttons, self.button_font, gap,
        )
