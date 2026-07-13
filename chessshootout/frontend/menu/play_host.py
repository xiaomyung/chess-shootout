from chessshootout.frontend.menu.view import MenuView


class PlayView(MenuView):

    name = "play"

    def enter(self, payload=None):
        self.app.start_menu.show()

    def exit(self):
        self.app.start_menu.hide()

    def draw(self, window, menu_layout):
        self.app.start_menu.draw()

    def handle_click(self, pos):
        return self.app.start_menu.handle_click(pos)

    def handle_key(self, event):
        return self.app.start_menu.handle_key(event)

    def avoid_rects(self):
        if self.app.start_menu.is_visible():
            return [self.app.start_menu.outer_rect()]
        return []
