import logging
import os

import pygame as pg

from chessshootout.frontend.modal_registry import dismiss_topmost
from chessshootout.frontend.screens.base import Nav
from chessshootout.frontend.window_chrome import MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT


log = logging.getLogger("chess.frontend")


class InputRouter:

    def __init__(self, frontend):
        self.frontend = frontend
        self._scroll_pressed = None
        self._click_sound_played = False

    def _handle_escape(self):
        frontend = self.frontend
        if frontend.screen.swallows_input():
            return
        if self._dismiss_top_modal():
            return
        result = frontend.screen.escape()
        if isinstance(result, Nav):
            frontend.request_nav(result)

    def _dismiss_confirm(self):
        frontend = self.frontend
        frontend.confirm_modal.hide()
        if frontend.screen is frontend.menu:
            frontend.menu.show_play_view()

    def _top_visible_modal(self):
        for spec in self.frontend._active_modal_specs():
            if spec.modal.is_visible():
                return spec
        return None

    def _dismiss_top_modal(self):
        frontend = self.frontend
        if dismiss_topmost(frontend._active_modal_specs()):
            return True
        offer_banners = frontend.coordinator.offer_banners
        if not offer_banners.is_empty():
            if frontend.coordinator._rematch_offered:
                frontend.coordinator._decline_rematch()
            offer_banners.clear()
            return True
        return False

    def _active_scrollable(self):
        frontend = self.frontend
        top = self._top_visible_modal()
        if top is not None:
            return top.modal if top.scrollable else None
        return frontend.screen.active_scrollable()

    def _cancel_all_scroll(self):
        frontend = self.frontend
        self._scroll_pressed = None
        for spec in frontend._modal_registry:
            if spec.scrollable:
                spec.modal.scroll.cancel()
        for screen in frontend.screens.values():
            for scrollable in screen.scrollables():
                scrollable.scroll.cancel()
            for spec in screen.modals():
                if spec.scrollable:
                    spec.modal.scroll.cancel()

    def _handle_left_drag_motion(self, pos):
        frontend = self.frontend
        if self._scroll_pressed is not None:
            if not self._scroll_pressed.is_visible():
                self._scroll_pressed = None
            elif self._scroll_pressed.handle_motion(pos):
                return
        if not frontend.audio_panel.handle_drag(pos, True):
            frontend.screen.handle_motion(pos)

    def mouse_left_clicked(self, pos, *, ui_click=True):
        frontend = self.frontend
        self._click_sound_played = False
        self._dispatch_left_click(pos)
        if ui_click and not self._click_sound_played:
            frontend.sound_manager.play_ui_click()

    def suppress_click_sound(self):
        self._click_sound_played = True

    def _dispatch_left_click(self, pos):
        frontend = self.frontend
        if frontend.chrome.handle_click(pos):
            return
        top = self._top_visible_modal()
        if top is not None:
            top.modal.handle_click(pos)
            return
        if frontend.coordinator.offer_banners.handle_click(pos):
            return
        result = frontend.screen.handle_click(pos)
        if isinstance(result, Nav):
            frontend.request_nav(result)

    def _mouse_left_pressed(self, pos):
        frontend = self.frontend
        scrollable = self._active_scrollable()
        if scrollable is not None and scrollable.handle_press(pos):
            self._scroll_pressed = scrollable
            return
        self.mouse_left_clicked(pos)
        if pos[1] >= frontend.chrome.HEIGHT and not frontend._blocking_modal_visible():
            frontend.screen.handle_press(pos)

    def _mouse_left_released(self, pos):
        frontend = self.frontend
        frontend.audio_panel.end_drag()
        if self._scroll_pressed is not None:
            scrollable = self._scroll_pressed
            self._scroll_pressed = None
            dragged = scrollable.handle_release(pos)
            if not dragged and scrollable.is_visible():
                scrollable.handle_click(pos)
            return
        frontend.screen.handle_release(pos)

    def check_events(self):
        frontend = self.frontend
        events = pg.event.get()
        dropped = 0
        for event in events:
            if event.type == pg.QUIT:
                frontend.running = False
                continue

            if frontend._pending_nav is not None:
                dropped += 1
                continue

            if event.type == pg.KEYDOWN:
                if not frontend.screen.swallows_input():
                    frontend.sound_manager.play_ui_click()
                if event.key == pg.K_ESCAPE:
                    self._handle_escape()
                    continue
                if event.key == pg.K_F11:
                    frontend.chrome.toggle_fullscreen()
                    continue
                if frontend.screen.swallows_input():
                    frontend.screen.forward_swallowed_event(event)
                    continue
                top = self._top_visible_modal()
                if top is not None:
                    if top.handles_keys:
                        top.modal.handle_key(event)
                    continue
                result = frontend.screen.handle_key(event)
                if isinstance(result, Nav):
                    frontend.request_nav(result)

            elif event.type == pg.MOUSEBUTTONDOWN:
                if frontend.screen.swallows_input():
                    if event.button == 1 and frontend.chrome.handle_click(event.pos):
                        continue
                    frontend.screen.forward_swallowed_event(event)
                    continue
                if event.button == 1:
                    self._mouse_left_pressed(event.pos)
                elif event.button == 3:
                    if not frontend.screen.handle_right_press(event.pos):
                        frontend.sound_manager.play_ui_click()

            elif event.type == pg.MOUSEBUTTONUP:
                if frontend.screen.swallows_input():
                    continue
                if event.button == 1:
                    frontend.chrome.clear_title_press()
                    self._mouse_left_released(event.pos)
                elif event.button == 3:
                    frontend.screen.handle_right_release(event.pos)

            elif event.type == pg.MOUSEMOTION:
                frontend.chrome.update_cursor(event.pos)
                if event.buttons[0]:
                    frontend.chrome.handle_title_motion(event.pos)
                    self._handle_left_drag_motion(event.pos)
                elif (event.pos[1] >= frontend.chrome.HEIGHT
                        and not frontend._blocking_modal_visible()):
                    frontend.screen.handle_motion(event.pos)

            elif event.type == pg.MOUSEWHEEL:
                scrollable = self._active_scrollable()
                if scrollable is not None:
                    scrollable.handle_scroll(pg.mouse.get_pos(), event.y)

            elif event.type == pg.VIDEORESIZE:
                w = max(event.w, MIN_WINDOW_WIDTH)
                h = max(event.h, MIN_WINDOW_HEIGHT)
                if os.name == "nt" or (w, h) != (event.w, event.h):
                    frontend._recreate_window_surface(w, h)
                frontend.window_width = w
                frontend.window_height = h
                self._cancel_all_scroll()
                frontend.screen.on_resize()
                frontend._compute_layout()
        if dropped:
            log.debug("dropped %d stale events pending nav %s",
                      dropped, frontend._pending_nav.name)
        return bool(events)
