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
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.tween import Tween, out_cubic
from chessshootout.frontend.window_chrome import WindowChrome


log = logging.getLogger("chess.frontend")

MENU_RISE_MS = 520
MENU_RISE_PX = 20
VIEW_RISE_MS = 140
VIEW_RISE_PX = 10
RAIL_SLIDE_MS = 200


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
        self._transition_kind = "none"
        self._transition_duration = 0
        self._transition_tween = None
        self._scratch = None
        self._rail_slide_mode = "none"
        self._rail_slide_tween = None
        self._rail_slide_snapshot = None
        self._rail_slide_origin = None
        self._rail_scratch = None

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
        self._begin_transition("screen", MENU_RISE_MS)

    def _begin_transition(self, kind, duration_ms):
        self._transition_kind = kind
        self._transition_duration = duration_ms
        self._transition_tween = None

    def _activate(self, name):
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())
        if name == "play":
            self.card_stack.refresh()

    def exit(self):
        super().exit()
        self.views[self._active_view].exit()
        self._transition_kind = "none"
        self._transition_tween = None
        self._scratch = None
        self._end_rail_slide()
        self._rail_scratch = None

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
        self._end_rail_slide()

    def update(self, now):
        self.views[self._active_view].update(now)
        layout = self._menu_layout
        rects = [layout.rail_rect, layout.right_rail_full_rect]
        rects += self.views[self._active_view].avoid_rects()
        self.app.menu_battle.set_avoid_rects(rects)

    def draw(self):
        window = self.app.window
        now = pg.time.get_ticks()
        include_rail = self._rail_slide_mode != "in"
        if self._transition_kind == "none":
            self._draw_rail(window, now)
            self._draw_content(window, now, include_rail)
            self._draw_rail_slide(window, now)
            return
        if self._transition_tween is None:
            self._transition_tween = Tween(
                0.0, 1.0, self._transition_duration, now, ease=out_cubic)
        if self._transition_tween.done(now):
            self._transition_kind = "none"
            self._transition_tween = None
            self._draw_rail(window, now)
            self._draw_content(window, now, include_rail)
            self._draw_rail_slide(window, now)
            return
        t = self._transition_tween.value(now)
        scratch = self._ensure_scratch()
        scratch.fill((0, 0, 0, 0))
        if self._transition_kind == "screen":
            self._draw_rail(scratch, now)
            self._draw_content(scratch, now, include_rail)
            offset = int((1.0 - t) * MENU_RISE_PX)
        else:
            self._draw_rail(window, now)
            self._draw_content(scratch, now, include_rail)
            offset = int((1.0 - t) * VIEW_RISE_PX)
        scratch.set_alpha(int(255 * t))
        window.blit(scratch, (0, offset))
        self._draw_rail_slide(window, now)

    def _draw_rail(self, surface, now):
        self.rail.draw(surface, now)

    def _draw_content(self, surface, now, include_rail=True):
        self.views[self._active_view].draw(surface, self._menu_layout)
        if include_rail and self._active_view == "play":
            self._draw_right_rail_panel(surface)
            self.card_stack.draw(surface, now)

    def _draw_rail_slide(self, window, now):
        if self._rail_slide_mode == "none":
            return
        if self._rail_slide_tween is None:
            self._rail_slide_tween = Tween(0.0, 1.0, RAIL_SLIDE_MS, now, ease=out_cubic)
        t = self._rail_slide_tween.value(now)
        if self._rail_slide_mode == "out":
            origin = self._rail_slide_origin
            x = int(origin.x + t * (window.get_width() - origin.x))
            window.blit(self._rail_slide_snapshot, (x, origin.y))
        else:
            panel = self._menu_layout.right_rail_full_rect
            if panel.width > 0:
                dx = int((1.0 - t) * (window.get_width() - panel.x))
                scratch = self._ensure_rail_scratch()
                scratch.fill((0, 0, 0, 0))
                self._draw_right_rail_panel(scratch)
                self.card_stack.draw(scratch, now)
                window.blit(scratch.subsurface(panel), (panel.x + dx, panel.y))
        if self._rail_slide_tween.done(now):
            self._end_rail_slide()

    def _capture_rail_column(self, now):
        panel = self._menu_layout.right_rail_full_rect
        if panel.width <= 0:
            return None, None
        temp = pg.Surface(self.app.window.get_size(), pg.SRCALPHA)
        self._draw_right_rail_panel(temp)
        self.card_stack.draw(temp, now)
        return temp.subsurface(panel).copy(), pg.Rect(panel)

    def _arm_rail_slide(self, previous, name, snapshot, origin):
        if previous == "play" and name != "play":
            if snapshot is None:
                return
            self._rail_slide_mode = "out"
            self._rail_slide_snapshot = snapshot
            self._rail_slide_origin = origin
            self._rail_slide_tween = None
        elif previous != "play" and name == "play":
            self._rail_slide_mode = "in"
            self._rail_slide_snapshot = None
            self._rail_slide_origin = None
            self._rail_slide_tween = None

    def _ensure_rail_scratch(self):
        size = self.app.window.get_size()
        if self._rail_scratch is None or self._rail_scratch.get_size() != size:
            self._rail_scratch = pg.Surface(size, pg.SRCALPHA)
        return self._rail_scratch

    def _end_rail_slide(self):
        self._rail_slide_mode = "none"
        self._rail_slide_tween = None
        self._rail_slide_snapshot = None
        self._rail_slide_origin = None

    def _ensure_scratch(self):
        size = self.app.window.get_size()
        if self._scratch is None or self._scratch.get_size() != size:
            self._scratch = pg.Surface(size, pg.SRCALPHA)
        return self._scratch

    def _draw_right_rail_panel(self, window):
        panel = self._menu_layout.right_rail_full_rect
        if panel.width <= 0:
            return
        pg.draw.rect(window, pg.Color(Colors.surface), panel)
        pg.draw.line(window, pg.Color(Colors.border), (panel.left, panel.top),
                     (panel.left, panel.bottom - 1))

    def handle_click(self, pos):
        row = self.rail.hit_test(pos)
        if row is not None:
            self.app.input_router._click_sound_played = True
            if row != self._active_view:
                self.app.sound_manager.play_rail_click()
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
        self.app.confirm_modal.show(
            "Leaving so soon?", on_yes=self._quit_app,
            yes_label="See ya!", no_label="Cancel")
        return True

    def goto_view(self, name):
        if name == self._active_view:
            return
        previous = self._active_view
        snapshot, origin = None, None
        if previous == "play" and name != "play":
            snapshot, origin = self._capture_rail_column(pg.time.get_ticks())
        self.views[previous].exit()
        log.info("menu view %s -> %s", previous, name)
        self._active_view = name
        self.views[name].enter()
        self.rail.set_active(name, pg.time.get_ticks())
        if name == "play":
            self.card_stack.refresh()
        self.app._compute_layout()
        self._begin_transition("view", VIEW_RISE_MS)
        self._arm_rail_slide(previous, name, snapshot, origin)

    def goto_history(self):
        self.goto_view("history")

    def _quit_app(self):
        self.app.running = False

    def modals(self):
        return [ModalSpec(self.fen_input_modal)]

    def on_app_exit(self):
        self.app.settings._commit_options_exit()
