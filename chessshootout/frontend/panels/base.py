import pygame as pg

from chessshootout.frontend.visual.fonts import get_font


class BasePanel:

    consumes_clicks_when_visible = False

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self._on_rect_changed()

    def _on_rect_changed(self):
        pass

    def font(self, factor, min_size=12, bold=True):
        size = max(int(self.rect.height / factor), min_size)
        return get_font(size, bold=bold)

    def draw(self):
        pass

    def handle_click(self, pos):
        return False
