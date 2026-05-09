import pygame as pg


DEFAULT_FONT_FAMILY = "Arial"


class BasePanel:
    """Common scaffolding for persistent (non-blocking) UI panels.

    Same rect/font helpers as `modals.base.BaseModal`, but panels render
    alongside the board and don't intercept clicks unless the panel says so
    explicitly via `handle_click`.
    """

    consumes_clicks_when_visible = False

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self._on_rect_changed()

    def _on_rect_changed(self):
        pass

    def font(self, factor, min_size=12, bold=True, family=DEFAULT_FONT_FAMILY):
        size = max(int(self.rect.height / factor), min_size)
        return pg.font.SysFont(family, size, bold=bold)

    def draw(self):
        pass

    def handle_click(self, pos):
        return False
