from typing import Any

import pygame as pg

from chessshootout.frontend.menu.layout import MenuLayout
from chessshootout.frontend.menu.options_rows import Fonts, OptionsBody
from chessshootout.frontend.menu.view import (
    MenuView, draw_subview_title, scale_floor, subview_title_top)
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font


TITLE_FONT_BASE = 28
TITLE_FONT_FLOOR = 20
TITLE_GAP = 20
TITLE_GAP_FLOOR = 12


class OptionsView(MenuView):
    """
    The Options sub-view of the menu -- audio, display, focus mode, game
    defaults, the server picker and the performance readouts. It draws the
    heading and hosts the scrolling list of rows; the rows themselves come
    ready-wired from the settings controller, which is also what every value
    is read from and written back to
    """

    name = "options"

    def __init__(self, app: Any) -> None:
        """
        Build the view once at startup, with an empty list and nothing placed
        yet. The rows arrive on the first visit to Options and the fonts on
        the first layout

        :param app: the Frontend shell, this view's route to the settings
            controller and the rest of the app
        """
        super().__init__(app)
        self.body = OptionsBody()
        self._rect = pg.Rect(0, 0, 0, 0)
        self._body_rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._title_top = 0
        self._title_font = get_display_font(TITLE_FONT_FLOOR)
        self._fonts_cache = None

    def enter(self, payload: dict[str, Any] | None = None) -> None:
        """
        Rebuild every row from the settings controller as the player opens
        Options, so the screen always shows what is really stored rather than
        what it happened to be showing last time

        :param payload: navigation payload from the menu shell, unused here
        """
        self.body.set_sections(self.app.settings.build_settings_sections())

    def exit(self) -> None:
        """
        Settle Options as the player leaves it. The controller commits a folder
        or a server address still being typed, drops the connection-test
        verdict, hands the new default time control to the Play view and writes
        every delayed setting to disk
        """
        self.app.settings.commit_options_exit()

    def _s(self, value: int, floor: int = 1) -> int:
        """
        Scale one design-time pixel size to the window the player actually has,
        never letting it shrink past the point of being legible

        :param value: the size in pixels as drawn at the reference window size
        :param floor: smallest result allowed, however far the window shrinks
        :returns: the scaled size in whole pixels
        """
        return scale_floor(value, self._scale, floor)

    def _fonts(self) -> Fonts:
        """
        The faces every row draws with, loaded once per layout and kept until
        a resize clears them -- reloading five fonts each frame would cost more
        than drawing the whole list

        :returns: the bundle of faces the rows share
        """
        if self._fonts_cache is None:
            self._fonts_cache = Fonts(
                title=get_font(self._s(15, 12), bold=True),
                desc=get_font(self._s(12, 10)),
                section=get_mono_font(self._s(11, 10), bold=True),
                value=get_mono_font(self._s(13, 11)),
                button=get_font(self._s(12, 11), bold=True),
            )
        return self._fonts_cache

    def relayout(self, menu_layout: MenuLayout) -> None:
        """
        Take the slot the menu gives its sub-views and place the heading and
        the list inside it, the list getting everything left under the heading.
        The cached fonts are dropped here, so the next frame rebuilds them at
        the new scale

        :param menu_layout: the menu's computed rects and scale for the current
            window size
        """
        self._rect = pg.Rect(menu_layout.subview_rect)
        self._scale = menu_layout.scale
        self._fonts_cache = None
        self._title_font = get_display_font(self._s(TITLE_FONT_BASE, TITLE_FONT_FLOOR))
        self._title_top = subview_title_top(self._rect)
        body_top = self._title_top + self._title_font.get_height() \
            + self._s(TITLE_GAP, TITLE_GAP_FLOOR)
        self._body_rect = pg.Rect(self._rect.x, body_top, self._rect.width,
                                  max(self._rect.bottom - body_top, 0))

    def draw(self, window: pg.Surface, menu_layout: MenuLayout) -> None:
        """
        Paint the heading and the settings list under it. A slot with no width,
        or one with no room left below the heading, draws nothing rather than
        guessing at a size

        :param window: surface drawn to, normally the app window
        :param menu_layout: the menu's computed rects and scale, part of the
            shared sub-view signature; the rects used here were taken at layout
            time
        """
        rect = self._rect
        if rect.width <= 0:
            return
        draw_subview_title(window, self._title_font, "OPTIONS", rect.x, self._title_top)
        if self._body_rect.height <= 0:
            return
        self.body.draw(window, self._body_rect, self._fonts())

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Hand a click to the settings list, which offers it to each row in turn

        :param pos: click position in window pixels
        :returns: True when the list took the click
        """
        return self.body.handle_click(pos)

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Hand a press to the settings list, where it may begin a scroll drag --
        unless it landed on a row's own control, which gets the click instead

        :param pos: press position in window pixels
        :returns: True when the list started a scroll gesture
        """
        return self.body.handle_press(pos)

    def handle_motion(self, pos: tuple[int, int]) -> bool:
        """
        Carry on a scroll drag the list claimed, moving the rows with the cursor

        :param pos: cursor position in window pixels
        :returns: True while a drag of the list's is in flight
        """
        return self.body.handle_motion(pos)

    def handle_release(self, pos: tuple[int, int]) -> bool:
        """
        End the scroll drag and let a quick flick coast on. Answering False
        tells the shell the gesture was really a tap, which it then delivers as
        a click

        :param pos: release position in window pixels
        :returns: True when the gesture actually scrolled
        """
        return self.body.handle_release(pos)

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Hand typing to the settings list, which routes it to whichever field is
        focused -- the games folder or the custom server address

        :param event: pygame KEYDOWN event
        :returns: True when a row consumed the key
        """
        return self.body.handle_key(event)

    def escape(self) -> bool:
        """
        Cancel a half-typed folder or address on the first Esc. Declining lets
        the menu deal with the press instead and go back to Play, so an edit
        the player abandoned is never saved by leaving the screen

        :returns: True when there was an edit to cancel
        """
        return self.body.cancel_focused_edit()

    def active_scrollable(self, pos: tuple[int, int] | None = None) -> OptionsBody:
        """
        Name what the mouse wheel moves while Options is showing, which is
        always the settings list

        :param pos: cursor position in window pixels, not needed here since the
            list is the only scrollable on this sub-view
        :returns: the settings list
        """
        return self.body

    def scrollables(self) -> list[OptionsBody]:
        """
        Every scrollable this sub-view owns, so the shell can stop all
        scrolling at once when the window is resized

        :returns: the settings list, the only scrollable here
        """
        return [self.body]
