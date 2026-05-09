import pygame as pg


DEFAULT_FONT_FAMILY = "Arial"
DEFAULT_PADDING = 12


class BaseModal:

    consumes_clicks_when_visible = True

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.padding = DEFAULT_PADDING

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self._on_rect_changed()

    def _on_rect_changed(self):
        pass

    def font(self, factor, min_size=12, bold=True, family=DEFAULT_FONT_FAMILY):
        size = max(int(self.rect.height / factor), min_size)
        return pg.font.SysFont(family, size, bold=bold)

    def is_visible(self):
        return False

    def draw(self):
        pass

    def handle_click(self, pos):
        return False
