import pygame as pg

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.frontend.screens.base import Nav, Screen
from chessshootout.frontend.window_chrome import WindowChrome


WIDE_MARGIN = 28
WIDE_MAX_WIDTH = 860
TOP_MARGIN = 16

PGN_PATTERN = "*.pgn"


class HistoryScreen(Screen):

    name = "history"
    uses_battle_backdrop = True

    def enter(self, **payload):
        self.app.history_view.show(
            str(paths.get_games_dir()), PGN_PATTERN, nickname=env.get_nickname())

    def exit(self):
        super().exit()
        self.app.history_view.hide()

    def relayout(self, size):
        window_rect = pg.Rect(0, 0, size[0], size[1])
        top_inset = WindowChrome.HEIGHT
        width = min(window_rect.width - 2 * WIDE_MARGIN, WIDE_MAX_WIDTH)
        x = window_rect.centerx - width // 2
        y = top_inset + TOP_MARGIN
        height = max(window_rect.bottom - y - TOP_MARGIN, 1)
        self.app.history_view.set_rect(pg.Rect(x, y, width, height))

    def update(self, now):
        app = self.app
        app.menu_battle.set_avoid_rect(app.history_view.rect)
        app.menu_battle.set_logo_rect(pg.Rect(0, 0, 0, 0))

    def draw(self):
        app = self.app
        if not app._blocking_modal_visible():
            app.history_view.draw()

    def handle_click(self, pos):
        return self.app.history_view.handle_click(pos)

    def active_scrollable(self):
        return self.app.history_view

    def scrollables(self):
        return [self.app.history_view]

    def escape(self):
        return Nav("menu")
