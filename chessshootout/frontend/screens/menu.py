from chessshootout.infra import env
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.fen_input import FenInputModal
from chessshootout.frontend.screens.base import Screen


class MenuScreen(Screen):

    name = "menu"
    uses_battle_backdrop = True

    def __init__(self, app):
        super().__init__(app)
        self.fen_input_modal = FenInputModal(app.window)

    def enter(self, **payload):
        self.app.start_menu.show()

    def relayout(self, size):
        r = compute_layout(
            size[0], size[1], mode=self.name, focus_mode=False,
            focus_show=env.get_focus_show(), board_size=self.app.game.board.SIZE)
        self.fen_input_modal.set_rect(r.flex_rect)

    def update(self, now):
        app = self.app
        app.menu_battle.set_avoid_rect(app.start_menu.outer_rect())
        app.menu_battle.set_logo_rect(app.start_menu.tile_rect())

    def draw(self):
        app = self.app
        if not app._blocking_modal_visible():
            app.start_menu.draw()

    def handle_click(self, pos):
        return self.app.start_menu.handle_click(pos)

    def handle_key(self, event):
        return self.app.start_menu.handle_key(event)

    def escape(self):
        self.app.start_menu.hide()
        self.app.confirm_modal.show(
            "Leaving so soon?", on_yes=self._quit_app, on_no=self._cancel_quit,
            yes_label="See ya!", no_label="Cancel")
        return True

    def _quit_app(self):
        self.app.running = False

    def _cancel_quit(self):
        self.app.start_menu.show()

    def modals(self):
        return [ModalSpec(self.fen_input_modal)]

    def caption(self):
        return ""

    def debug_state(self):
        return {}
