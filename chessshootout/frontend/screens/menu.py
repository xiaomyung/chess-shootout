import logging

import pygame as pg

from chessshootout.infra import env
from chessshootout.infra.open_external import open_with_default_app
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.menu.layout import compute_menu_layout
from chessshootout.frontend.menu.rail import MenuRail
from chessshootout.frontend.menu.rail_cards import CardStack
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
        self.card_stack = CardStack(app)
        self.card_stack.refresh()
        self._active_view = "play"
        self._menu_layout = None
        self._load_pgn_available = False

    @property
    def play_view(self):
        return self.views["play"]

    def show_card(self):
        self.play_view.show()

    def hide_card(self):
        self.play_view.hide()

    def card_visible(self):
        return self.play_view.is_visible()

    def set_reconnect_available(self, available):
        self.play_view.set_reconnect_available(available)

    def apply_default_time_settings(self):
        self.play_view.apply_default_time_settings()

    def apply_resume_config(self, resume):
        color = resume["your_color"]
        self.set_nickname(resume["white_name"] if color == "white" else resume["black_name"])
        self.play_view.apply_resume_config(resume)

    def set_nickname(self, text):
        env.set_nickname(text)

    def build_play_config(self):
        return self.play_view.build_config()

    def set_load_pgn_available(self, available):
        self._load_pgn_available = available

    def enter(self, **payload):
        self._activate(payload.get("view") or self._active_view)

    def _activate(self, name):
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())
        if name == "play":
            self.card_stack.refresh()

    def exit(self):
        super().exit()
        self.views[self._active_view].exit()

    def relayout(self, size):
        right_rail = self._active_view == "play"
        self._menu_layout = compute_menu_layout(
            size[0], size[1], WindowChrome.HEIGHT, right_rail=right_rail)
        self.rail.set_rect(self._menu_layout.rail_rect, self._menu_layout.scale)
        self.rail.set_active(self._active_view, pg.time.get_ticks())
        self.card_stack.set_rect(self._menu_layout.right_rail_rect, self._menu_layout.scale)
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
        if self._active_view == "play":
            self.card_stack.draw(app.window, now)

    def handle_click(self, pos):
        row = self.rail.hit_test(pos)
        if row is not None:
            self.goto_view(row)
            return True
        if self.rail.handle_footer_click(pos):
            return True
        if self._active_view == "play" and self.card_stack.handle_click(pos):
            return True
        return self.views[self._active_view].handle_click(pos)

    def handle_key(self, event):
        return self.views[self._active_view].handle_key(event)

    def handle_press(self, pos):
        return self.views[self._active_view].handle_press(pos)

    def handle_motion(self, pos):
        return self.views[self._active_view].handle_motion(pos)

    def handle_release(self, pos):
        return self.views[self._active_view].handle_release(pos)

    def active_scrollable(self):
        if self._active_view != "play":
            return self.views[self._active_view].active_scrollable()
        picker = self.views["play"].active_scrollable()
        if picker is not None:
            return picker
        if self.card_stack.scroll.scrollable():
            return self.card_stack
        return None

    def scrollables(self):
        result = [self.card_stack]
        for view in self.views.values():
            result.extend(view.scrollables())
        return result

    def escape(self):
        if self.views[self._active_view].escape():
            return True
        if self._active_view != "play":
            self.goto_view("play")
            return True
        self.hide_card()
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
        if name == "play":
            self.card_stack.refresh()
        self.app._compute_layout()

    def goto_history(self):
        self.goto_view("history")

    def _quit_app(self):
        self.app.running = False

    def _cancel_quit(self):
        self.show_card()

    def modals(self):
        return [ModalSpec(self.fen_input_modal)]

    def on_app_exit(self):
        self.app.settings._commit_options_exit()
