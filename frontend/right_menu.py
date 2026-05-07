import pygame as pg

from frontend.colors import Colors


class RightMenu:

    def __init__(self, window):
        self.window = window
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 10

    def draw_menu(self):
        rect_out = pg.Rect(
            self.x + self.padding,
            self.y + self.padding,
            self.width - self.padding * 2,
            self.height - self.padding * 2
        )

        rect_moves_section = pg.Rect(
            rect_out.x + self.padding,
            rect_out.y + self.padding,
            rect_out.width - self.padding * 2,
            rect_out.height * 0.9
        )

        rect_buttons_section = pg.Rect(
            rect_moves_section.x,
            rect_moves_section.y + rect_moves_section.height + self.padding,
            rect_out.width - self.padding * 2,
            rect_out.height - rect_moves_section.height - self.padding * 3
        )

        pg.draw.rect(self.window, Colors.dark_menu, rect_out)
        pg.draw.rect(self.window, Colors.light_grey_menu, rect_moves_section)
        pg.draw.rect(self.window, Colors.light_grey_menu, rect_buttons_section)

    def set_rect(self, rect):
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height