import logging

import pygame as pg

from chessshootout.infra import env
from chessshootout.infra.open_external import open_with_default_app
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.menu.layout import compute_menu_layout
from chessshootout.frontend.menu.rail import MenuRail
from chessshootout.frontend.menu.shell import build_views
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.fen_input import FenInputModal
from chessshootout.frontend.screens.base import Screen
from chessshootout.frontend.window_chrome import WindowChrome


log = logging.getLogger("chess.frontend")


class MenuScreen(Screen):

    name = "menu"
    uses_battle_backdrop = True

    def __init__(self, app):
        super().__init__(app)
        self.fen_input_modal = FenInputModal(app.window)
        self.views = build_views(app)
        self.rail = MenuRail(app.window, {"open_url": open_with_default_app})
        self._active_view = "play"
        self._menu_layout = None

    def enter(self, **payload):
        self._activate(payload.get("view") or self._active_view)

    def _activate(self, name):
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())

    def exit(self):
        super().exit()
        self.views[self._active_view].exit()

    def relayout(self, size):
        self._menu_layout = compute_menu_layout(size[0], size[1], WindowChrome.HEIGHT)
        self.rail.set_rect(self._menu_layout.rail_rect, self._menu_layout.scale)
        self.rail.set_active(self._active_view, pg.time.get_ticks())
        for view in self.views.values():
            view.relayout(self._menu_layout)
        r = compute_layout(
            size[0], size[1], mode=self.name, focus_mode=False,
            focus_show=env.get_focus_show(), board_size=self.app.game.board.SIZE)
        self.fen_input_modal.set_rect(r.flex_rect)

    def update(self, now):
        self.views[self._active_view].update(now)
        layout = self._menu_layout
        rects = [layout.rail_rect, layout.right_rail_rect]
        rects += self.views[self._active_view].avoid_rects()
        self.app.menu_battle.set_avoid_rects(rects)

    def draw(self):
        app = self.app
        if app._blocking_modal_visible():
            return
        now = pg.time.get_ticks()
        self.rail.draw(app.window, now)
        self.views[self._active_view].draw(app.window, self._menu_layout)

    def handle_click(self, pos):
        row = self.rail.hit_test(pos)
        if row is not None:
            self._on_rail_row(row)
            return True
        if self.rail.handle_footer_click(pos):
            return True
        return self.views[self._active_view].handle_click(pos)

    def handle_key(self, event):
        return self.views[self._active_view].handle_key(event)

    def active_scrollable(self):
        return self.views[self._active_view].active_scrollable()

    def scrollables(self):
        result = []
        for view in self.views.values():
            result.extend(view.scrollables())
        return result

    def escape(self):
        if self.views[self._active_view].escape():
            return True
        if self._active_view != "play":
            self.goto_view("play")
            return True
        self.app.start_menu.hide()
        self.app.confirm_modal.show(
            "Leaving so soon?", on_yes=self._quit_app, on_no=self._cancel_quit,
            yes_label="See ya!", no_label="Cancel")
        return True

    def goto_view(self, name):
        if name == self._active_view:
            return
        previous = self._active_view
        self.views[previous].exit()
        log.info("menu view %s -> %s", previous, name)
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())
        self.app._compute_layout()

    def goto_history(self):
        self.goto_view("history")

    def _on_rail_row(self, row):
        if row == "options":
            self.app.settings._on_open_options()
            return
        self.goto_view(row)

    def _quit_app(self):
        self.app.running = False

    def _cancel_quit(self):
        self.app.start_menu.show()

    def modals(self):
        return [ModalSpec(self.fen_input_modal)]
