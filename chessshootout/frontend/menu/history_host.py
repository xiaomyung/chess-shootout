from chessshootout import paths
from chessshootout.infra import env
from chessshootout.frontend.menu.view import MenuView


PGN_PATTERN = "*.pgn"


class HistoryMenuView(MenuView):

    name = "history"

    def enter(self, payload=None):
        self.app.history_view.show(
            str(paths.get_games_dir()), PGN_PATTERN, nickname=env.get_nickname())

    def exit(self):
        self.app.history_view.hide()

    def relayout(self, menu_layout):
        self.app.history_view.set_rect(menu_layout.subview_rect)

    def draw(self, window, menu_layout):
        self.app.history_view.draw()

    def handle_click(self, pos):
        return self.app.history_view.handle_click(pos)

    def active_scrollable(self, pos=None):
        return self.app.history_view

    def scrollables(self):
        return [self.app.history_view]

    def avoid_rects(self):
        return []
