import logging
import os
from typing import Any

import pygame as pg

from chessshootout.frontend.modal_registry import ModalSpec, dismiss_topmost
from chessshootout.frontend.screens.base import Nav
from chessshootout.frontend.window_chrome import MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT


log = logging.getLogger("chess.frontend")


class InputRouter:
    """
    The app's one event pump. Every frame it drains the pygame queue and hands
    what it finds -- keys, clicks, drags, the wheel, window resizes -- to the
    window chrome, then to whatever is layered over the screen, then to the
    active screen itself. It only ever dispatches: it holds no state about
    what any screen is showing and never reaches into one by name
    """

    def __init__(self, frontend: Any) -> None:
        """
        Build the router once at startup, owned by the shell for the whole
        run. All it remembers between frames is the widget an in-flight scroll
        drag belongs to and whether the click being handled already sounded

        :param frontend: the Frontend shell, the router's route to the window
            chrome, the modal list, the sound service and the active screen
        """
        self.frontend = frontend
        self._scroll_pressed = None
        self._click_sound_played = False

    def _handle_escape(self) -> None:
        """
        Handle Esc, which is always a context Back or Cancel and never closes
        the window from here. A screen that is grabbing raw input keeps Esc
        for itself; otherwise the frontmost dismissable overlay closes, and
        only when nothing is layered over the screen does the screen answer,
        which is where the menu can finally raise its quit confirmation
        """
        frontend = self.frontend
        if frontend.screen.swallows_input():
            return
        if self._dismiss_top_modal():
            return
        result = frontend.screen.escape()
        if isinstance(result, Nav):
            frontend.request_nav(result)

    def _dismiss_confirm(self) -> None:
        """
        Close the shared confirmation card when Esc cancels it, and put the
        menu back on its Play view so cancelling never strands the player on
        an empty screen. Registered as that card's dismiss action
        """
        frontend = self.frontend
        frontend.confirm_modal.hide()
        if frontend.screen is frontend.menu:
            frontend.menu.show_play_view()

    def _top_visible_modal(self) -> ModalSpec | None:
        """
        Find the card that currently owns input. The merged list puts the
        shell's own modals ahead of the active screen's, so the first visible
        one in that order is the one on top for clicks and for keys alike

        :returns: the frontmost visible modal spec, or None when none is open
        """
        for spec in self.frontend._active_modal_specs():
            if spec.modal.is_visible():
                return spec
        return None

    def _dismiss_top_modal(self) -> bool:
        """
        Take one step back out of whatever is layered over the screen: the
        frontmost Esc-dismissable card first, and failing that the offer
        banners, where waving away a rematch offer also declines it so the
        opponent is not left waiting

        :returns: True when something closed and Esc should go no further
        """
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

    def _active_scrollable(self) -> Any:
        """
        Decide what the wheel and a scroll drag should move. A visible card
        always outranks the screen behind it, and one that does not scroll
        swallows the wheel rather than letting it fall through to the screen

        :returns: the widget to scroll, or None when nothing here scrolls
        """
        frontend = self.frontend
        top = self._top_visible_modal()
        if top is not None:
            return top.modal if top.scrollable else None
        return frontend.screen.active_scrollable()

    def _cancel_all_scroll(self) -> None:
        """
        Stop every scroll in the app at once, on screens and cards that are
        not even showing. The shell calls this on a window resize, where all
        that content moves underneath a drag that is still in flight
        """
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

    def _handle_left_drag_motion(self, pos: tuple[int, int]) -> None:
        """
        Route cursor movement while the left button is down. A scroll drag
        that started earlier keeps the motion to itself; everything else goes
        to the active screen, which is how a dragged piece follows the mouse

        :param pos: cursor position in window pixels
        """
        frontend = self.frontend
        if self._scroll_pressed is not None:
            if not self._scroll_pressed.is_visible():
                self._scroll_pressed = None
            elif self._scroll_pressed.handle_motion(pos):
                return
        frontend.screen.handle_motion(pos)

    def mouse_left_clicked(self, pos: tuple[int, int], *, ui_click: bool = True) -> None:
        """
        Deliver one left click and play the interface click sound afterwards,
        unless whatever took the click already made a sound of its own. Every
        click goes through here, so nothing else has to think about the sound

        :param pos: click position in window pixels
        :param ui_click: False to stay silent, for a synthetic click that is
            not the player pressing a control
        """
        frontend = self.frontend
        self._click_sound_played = False
        self._dispatch_left_click(pos)
        if ui_click and not self._click_sound_played:
            frontend.sound_manager.play_ui_click()

    def suppress_click_sound(self) -> None:
        """
        Say that the click being dispatched right now already made its own
        sound, so the generic interface click is not layered on top. Called
        from inside a click handler, while that click is still being handled
        """
        self._click_sound_played = True

    def _dispatch_left_click(self, pos: tuple[int, int]) -> None:
        """
        Offer a left click to each layer in turn and stop at the first taker:
        the window chrome, then the frontmost visible card, then the offer
        banners, then the active screen. A screen answering with a navigation
        intent has it queued instead of run, so no screen is replaced from
        inside its own click handler

        :param pos: click position in window pixels
        """
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

    def _mouse_left_pressed(self, pos: tuple[int, int]) -> None:
        """
        Begin a left press. A scrollable under the cursor claims it as a
        possible scroll drag; otherwise it counts as a click straight away,
        and the press is passed on to the screen too when it landed below the
        title bar and nothing is blocking input

        :param pos: press position in window pixels
        """
        frontend = self.frontend
        scrollable = self._active_scrollable()
        if scrollable is not None and scrollable.handle_press(pos):
            self._scroll_pressed = scrollable
            return
        self.mouse_left_clicked(pos)
        if pos[1] >= frontend.chrome.HEIGHT and not frontend._blocking_modal_visible():
            frontend.screen.handle_press(pos)

    def _mouse_left_released(self, pos: tuple[int, int]) -> None:
        """
        Finish a left press. A scroll drag the player never actually moved is
        treated as a plain click on that widget instead, so tapping a row in a
        list still works; anything else goes to the screen to end its drag

        :param pos: release position in window pixels
        """
        frontend = self.frontend
        if self._scroll_pressed is not None:
            scrollable = self._scroll_pressed
            self._scroll_pressed = None
            dragged = scrollable.handle_release(pos)
            if not dragged and scrollable.is_visible():
                scrollable.handle_click(pos)
            return
        frontend.screen.handle_release(pos)

    def check_events(self) -> bool:
        """
        Drain the pygame queue once per frame and route everything in it --
        the whole app's input in a single pass. A screen change asked for
        along the way is only queued here; the shell runs it after this
        dispatch pass finishes, and every event still queued behind it is
        dropped so nothing reaches a screen that is about to be replaced. A
        request to close the window is honoured whatever else is pending

        :returns: True when the queue held at least one event, which is what
            tells the shell to present this frame in full
        """
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
