import pygame as pg

from frontend.colors import Colors


class ResultMenu:

    def __init__(self, window):
        self.window = window
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 10

    def draw_result_window(self):
        rect = pg.Rect(
            self.x,
            self.y,
            self.width,
            self.height
        )

        pg.draw.rect(self.window, Colors.light_grey_menu, rect)

    def set_rect(self, rect):
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height