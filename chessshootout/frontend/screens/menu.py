from chessshootout.frontend.screens.base import Screen


class MenuScreen(Screen):

    name = "menu"
    uses_battle_backdrop = True

    def update(self, now):
        app = self.app
        app.menu_battle.set_avoid_rect(app.start_menu.outer_rect())
        app.menu_battle.set_logo_rect(app.start_menu.tile_rect())

    def draw(self):
        app = self.app
        if not app._menu_overlay_active():
            app.start_menu.draw()

    def handle_click(self, pos):
        return self.app.start_menu.handle_click(pos)

    def handle_key(self, event):
        return self.app.start_menu.handle_key(event)
