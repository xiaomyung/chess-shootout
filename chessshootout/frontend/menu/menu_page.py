import pygame as pg


PAGE_CARD = "card"
PAGE_HISTORY = "history"

WIDE_MARGIN = 28
WIDE_MAX_WIDTH = 860
TOP_MARGIN = 16


class MenuPage:

    def __init__(self, window, start_menu, history_view):
        self.window = window
        self.start_menu = start_menu
        self.history_view = history_view
        self.page = PAGE_CARD
        self._foregrounds = {PAGE_CARD: start_menu, PAGE_HISTORY: history_view}

    def set_page(self, page):
        self.page = page

    def _active(self):
        return self._foregrounds[self.page]

    def set_rect(self, window_rect, top_inset, card_rect):
        self.start_menu.set_rect(card_rect)
        width = min(window_rect.width - 2 * WIDE_MARGIN, WIDE_MAX_WIDTH)
        x = window_rect.centerx - width // 2
        y = top_inset + TOP_MARGIN
        height = max(window_rect.bottom - y - TOP_MARGIN, 1)
        self.history_view.set_rect(pg.Rect(x, y, width, height))

    def avoid_rect(self):
        if self.page == PAGE_CARD:
            return self.start_menu.outer_rect()
        return self._active().rect

    def logo_rect(self):
        if self.page == PAGE_CARD:
            return self.start_menu.tile_rect()
        return pg.Rect(0, 0, 0, 0)

    def draw_foreground(self):
        self._active().draw()

    def handle_click(self, pos):
        return self._active().handle_click(pos)

    def handle_scroll(self, pos, dy):
        active = self._active()
        if hasattr(active, "handle_scroll"):
            return active.handle_scroll(pos, dy)
        return False

    def handle_key(self, event):
        active = self._active()
        if hasattr(active, "handle_key"):
            return active.handle_key(event)
        return False
