import pygame as pg

from frontend.colors import Colors


class RightMenu:

    def __init__(self, window):
        self.window = window
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 0

    def draw_menu(self):
        rect = pg.Rect(
            self.x + self.padding,
            self.y + self.padding,
            self.width - self.padding * 2,
            self.height - self.padding * 2
        )
        pg.draw.rect(self.window, Colors.dark_menu, rect)

    def set_rect(self, rect):
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height
        self.padding = max(rect.width * 0.05, 8)