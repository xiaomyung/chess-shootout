import pygame as pg

from frontend.colors import Colors
from frontend.pgn import iter_move_pairs
from frontend.widgets import draw_button_row


BUTTONS = [
    ("Undo", "undo"),
    ("Resign", "resign"),
    ("Draw", "draw"),
    ("Flip", "flip"),
]


class RightMenu:

    def __init__(self, window, backend, callbacks):
        self.window = window
        self.backend = backend
        self.callbacks = callbacks

        self.padding = 10
        self.button_gap = 6
        self.button_v_pad = 8
        self.moves_font_factor = 22
        self.button_font_factor = 28

        self.font = pg.font.SysFont("monospace", 16)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)

        self.outer_rect = pg.Rect(0, 0, 0, 0)
        self.moves_rect = pg.Rect(0, 0, 0, 0)
        self.buttons_rect = pg.Rect(0, 0, 0, 0)
        self.button_rects = {}

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

        button_row_h = self.button_font.get_height() + 2 * self.button_v_pad
        inner_w = self.outer_rect.width - 2 * p

        self.buttons_rect = pg.Rect(
            self.outer_rect.x + p,
            self.outer_rect.bottom - p - button_row_h,
            inner_w,
            button_row_h,
        )

        moves_h = max(self.buttons_rect.y - self.outer_rect.y - 2 * p, 0)
        self.moves_rect = pg.Rect(
            self.outer_rect.x + p,
            self.outer_rect.y + p,
            inner_w,
            moves_h,
        )

    def draw_menu(self):
        pg.draw.rect(self.window, Colors.dark_menu, self.outer_rect)
        pg.draw.rect(self.window, Colors.light_grey_menu, self.moves_rect)
        pg.draw.rect(self.window, Colors.light_grey_menu, self.buttons_rect)
        self._draw_moves(self.moves_rect)
        self._draw_buttons(self.buttons_rect)

    def handle_click(self, pos):
        for key, rect in self.button_rects.items():
            if rect.collidepoint(pos):
                self.callbacks[key]()
                return True
        return False

    def _draw_moves(self, rect):
        history = self.backend.move_history
        line_h = self.font.get_linesize()
        max_lines = max(int((rect.height - 2 * self.padding) // line_h), 0)

        rows = [
            f"{number:>3}. {white.san:<7} {black.san if black else ''}"
            for number, white, black in iter_move_pairs(history)
        ]
        visible = rows[-max_lines:] if max_lines else []

        for i, line in enumerate(visible):
            surf = self.font.render(line, True, Colors.white)
            self.window.blit(
                surf,
                (rect.x + self.padding, rect.y + self.padding + i * line_h),
            )

    def _draw_buttons(self, rect):
        self.button_rects = draw_button_row(
            self.window, rect, BUTTONS, self.button_font, self.button_gap,
        )
