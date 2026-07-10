import os

import pygame as pg

from chessshootout.backend.pieces import PieceType
from chessshootout.frontend.menu.menu_page import PAGE_CARD
from chessshootout.frontend.window_chrome import MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT


PROMOTION_KEYS = {
    pg.K_q: PieceType.QUEEN,
    pg.K_r: PieceType.ROOK,
    pg.K_b: PieceType.BISHOP,
    pg.K_n: PieceType.KNIGHT,
}


class InputRouter:

    def __init__(self, frontend):
        self.frontend = frontend
        self._scroll_pressed = None
        self._click_sound_played = False
        self._focus_click_consumed = False

    def _handle_escape(self):
        frontend = self.frontend
        if frontend.skillcheck_session._skillcheck_swallows_input():
            return
        if self._dismiss_top_modal():
            return
        if frontend.mode == "menu":
            if frontend.menu_page.page != PAGE_CARD:
                frontend._on_menu_back()
            else:
                self._show_quit_modal()
            return
        if not frontend.board_interactive():
            frontend._on_back_to_menu()
            return
        if frontend.focus_mode or frontend.focus_transition is not None:
            frontend._toggle_focus(False)
            return
        frontend._on_resign()

    def _dismiss_confirm(self):
        frontend = self.frontend
        frontend.confirm_modal.hide()
        if frontend.mode == "menu":
            frontend.start_menu.show()

    def _top_visible_modal(self):
        for spec in self.frontend._modal_registry:
            if spec.obj.is_visible():
                return spec
        return None

    def _dismiss_top_modal(self):
        frontend = self.frontend
        for spec in frontend._modal_registry:
            if spec.esc_dismiss and spec.obj.is_visible():
                spec.on_dismiss()
                return True
        if not frontend.offer_banners.is_empty():
            if frontend._rematch_offered:
                frontend._decline_rematch()
            frontend.offer_banners.clear()
            return True
        return False

    def _show_quit_modal(self):
        frontend = self.frontend
        frontend.start_menu.hide()
        frontend.confirm_modal.show(
            "Leaving so soon?", on_yes=self._quit_app, on_no=self._cancel_quit,
            yes_label="See ya!", no_label="Cancel")

    def _quit_app(self):
        self.frontend.running = False

    def _cancel_quit(self):
        self.frontend.start_menu.show()

    def _right_click_pressed(self, pos):
        frontend = self.frontend
        if frontend.mode == "menu" or frontend.current_result() is not None:
            frontend.sound_manager.play_ui_click()
            return
        sq = frontend.board.cell_at(pos)
        if sq is None:
            frontend.sound_manager.play_ui_click()
            return
        if frontend.board.dragging_from is not None:
            if not frontend.board.queue_premove_from_drag(sq):
                frontend.sound_manager.play_ui_click()
            return
        frontend.board.begin_right_press(pos)
        frontend.sound_manager.play_ui_click()

    def _right_click_released(self, pos):
        frontend = self.frontend
        if frontend.mode == "menu":
            return
        frontend.board.end_right_press(pos)

    def _active_scrollable(self):
        frontend = self.frontend
        top = self._top_visible_modal()
        if top is not None:
            return top.obj if top.scrollable else None
        if frontend._result_modal_should_show():
            return None
        if frontend.mode == "menu":
            return frontend.menu_page
        if frontend.focus_mode or frontend.focus_transition is not None:
            return None
        return frontend.right_menu

    def _cancel_all_scroll(self):
        frontend = self.frontend
        self._scroll_pressed = None
        frontend.right_menu.scroll.cancel()
        frontend.history_view.scroll.cancel()
        for spec in frontend._modal_registry:
            if spec.scrollable:
                spec.obj.scroll.cancel()

    def _handle_left_drag_motion(self, pos):
        frontend = self.frontend
        if self._scroll_pressed is not None:
            if not self._scroll_pressed.is_visible():
                self._scroll_pressed = None
            elif self._scroll_pressed.handle_motion(pos):
                return
        if not frontend.audio_panel.handle_drag(pos, True):
            frontend.board.update_drag_motion(pos)

    def mouse_left_clicked(self, pos, *, ui_click=True):
        frontend = self.frontend
        self._click_sound_played = False
        self._dispatch_left_click(pos)
        if ui_click and not self._click_sound_played:
            frontend.sound_manager.play_ui_click()

    def _dispatch_left_click(self, pos):
        frontend = self.frontend
        if frontend.chrome.handle_click(pos):
            return
        if frontend.focus_transition is not None:
            return
        if (frontend.current_result() is not None
                and frontend._result_first_seen_at_ms is not None
                and not frontend._result_modal_should_show()):
            frontend._skip_result_fade()
            return
        top = self._top_visible_modal()
        if top is not None:
            top.obj.handle_click(pos)
            return
        if frontend.offer_banners.handle_click(pos):
            return
        if frontend.mode == "menu":
            frontend.menu_page.handle_click(pos)
            return
        if (frontend.focus_arrow.is_visible() and frontend._focus_arrow_allowed()
                and frontend.focus_arrow.handle_click(pos)):
            frontend._toggle_focus(not frontend.focus_mode)
            self._focus_click_consumed = True
            self._click_sound_played = True
            return
        if not frontend.focus_mode and frontend.result_menu.handle_click(pos):
            return
        if not frontend.focus_mode and frontend.right_menu.handle_click(pos):
            return
        if frontend.current_result() is not None:
            return
        if frontend.board.pending_promotion_square is not None:
            frontend.board.pick_promotion_at(pos)
            self._click_sound_played = True
            return
        square = frontend.board.cell_at(pos)
        if square is not None:
            if frontend.board.review_ply is None and not frontend.board.is_square_annotated(square):
                frontend.board.clear_annotations()
            signal = frontend.board.handle_click(square)
            if signal:
                self._click_sound_played = True
                if signal == "select":
                    frontend.sound_manager.play_pickup()

    def _handle_shortcut_key(self, event):
        frontend = self.frontend
        if frontend._menu_overlay_active():
            return False
        if self._handle_promotion_key(event):
            return True
        if event.key == pg.K_h:
            frontend._toggle_focus(not frontend.focus_mode)
            return True
        if getattr(event, "unicode", "") == "?":
            frontend.help_modal.show()
            return True
        if event.key == pg.K_f:
            frontend._on_flip()
            return True
        if event.key == pg.K_r:
            frontend._on_resign()
            return True
        if event.key == pg.K_d:
            frontend._on_draw()
            return True
        if event.key == pg.K_z and (event.mod & pg.KMOD_CTRL):
            frontend._on_undo()
            return True
        if event.key == pg.K_LEFT:
            self._step_review(-1)
            return True
        if event.key == pg.K_RIGHT:
            self._step_review(1)
            return True
        if event.key == pg.K_HOME:
            frontend.board.jump_to_review_ply(0)
            return True
        if event.key == pg.K_END:
            frontend.board.jump_to_review_ply(None)
            return True
        return False

    def _handle_promotion_key(self, event):
        frontend = self.frontend
        if frontend.board.pending_promotion_square is None:
            return False
        chosen = PROMOTION_KEYS.get(event.key)
        if chosen is None:
            return False
        frontend.board.pick_promotion(chosen)
        return True

    def _step_review(self, delta):
        frontend = self.frontend
        history_len = len(frontend.match.move_history)
        if history_len == 0:
            return
        current = frontend.board.review_anchor(history_len)
        new_ply = max(0, min(history_len, current + delta))
        if new_ply == current:
            return
        if delta > 0:
            frontend.board.animate_review_ply(new_ply)
        else:
            frontend.board.jump_to_review_ply(new_ply)

    def _mouse_left_pressed(self, pos):
        frontend = self.frontend
        self._focus_click_consumed = False
        scrollable = self._active_scrollable()
        if scrollable is not None and scrollable.handle_press(pos):
            self._scroll_pressed = scrollable
            return
        self.mouse_left_clicked(pos)
        if (frontend.mode != "menu"
                and pos[1] >= frontend.chrome.HEIGHT
                and frontend.current_result() is None
                and frontend.board.pending_promotion_square is None
                and not frontend._menu_overlay_active()
                and not self._focus_click_consumed
                and frontend.focus_transition is None):
            frontend.board.begin_press(pos)

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
        was_dragging = frontend.board.dragging_from is not None
        if was_dragging and frontend.current_result() is None:
            self.mouse_left_clicked(pos, ui_click=False)
        frontend.board.end_press()
        if was_dragging and frontend.current_result() is None:
            frontend.sound_manager.play_drop()

    def check_events(self):
        frontend = self.frontend
        events = pg.event.get()
        for event in events:
            if event.type == pg.QUIT:
                frontend.running = False

            elif event.type == pg.KEYDOWN:
                if not frontend.skillcheck_session._skillcheck_swallows_input():
                    frontend.sound_manager.play_ui_click()
                if event.key == pg.K_ESCAPE:
                    self._handle_escape()
                    continue
                if event.key == pg.K_F11:
                    frontend.chrome.toggle_fullscreen()
                    continue
                if frontend.skillcheck_session._skillcheck_swallows_input():
                    frontend.skillcheck_overlay.handle_event(event)
                    continue
                top = self._top_visible_modal()
                if top is not None:
                    if top.handles_keys:
                        top.obj.handle_key(event)
                    continue
                if frontend.mode == "menu":
                    frontend.menu_page.handle_key(event)
                    continue
                self._handle_shortcut_key(event)

            elif event.type == pg.MOUSEBUTTONDOWN:
                if frontend.skillcheck_session._skillcheck_swallows_input():
                    if event.button == 1 and frontend.chrome.handle_click(event.pos):
                        continue
                    frontend.skillcheck_overlay.handle_event(event)
                    continue
                if event.button == 1:
                    self._mouse_left_pressed(event.pos)
                elif event.button == 3:
                    self._right_click_pressed(event.pos)

            elif event.type == pg.MOUSEBUTTONUP:
                if frontend.skillcheck_session._skillcheck_swallows_input():
                    continue
                if event.button == 1:
                    frontend.chrome.clear_title_press()
                    self._mouse_left_released(event.pos)
                elif event.button == 3:
                    self._right_click_released(event.pos)

            elif event.type == pg.MOUSEMOTION:
                frontend.chrome.update_cursor(event.pos)
                if event.buttons[0]:
                    frontend.chrome.handle_title_motion(event.pos)
                    self._handle_left_drag_motion(event.pos)

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
                frontend._abort_transition_for_resize()
                frontend._compute_layout()
        return bool(events)
