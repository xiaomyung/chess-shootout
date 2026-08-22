from typing import Any

import pygame as pg

from chessshootout.frontend.menu.layout import MenuLayout
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import scale_floor
from chessshootout.frontend.visual.widgets import avatar_palette


__all__ = ["MenuView", "scale_floor", "subview_title_top", "draw_subview_title",
           "seeded_avatar_palette"]

TITLE_TOP_FRAC = 0.05


def subview_title_top(rect: pg.Rect) -> int:
    """
    Where a sub-view's big heading starts. Every sub-view that shows one --
    Profile, Options -- measures from here, so their headings sit on the same
    line and their content below it starts level at any window size

    :param rect: the sub-view's content rect, from the menu layout
    :returns: window y of the heading's top edge, in pixels
    """
    return rect.y + int(rect.height * TITLE_TOP_FRAC)


def draw_subview_title(window: pg.Surface, font: pg.font.Font, text: str, x: int,
                       top: int) -> None:
    """
    Paint a sub-view's heading in the shared style, so PROFILE and OPTIONS are
    drawn one way rather than each view rolling its own. One of the three
    helpers this module hands the sub-views, next to scale_floor and
    seeded_avatar_palette

    :param window: surface drawn to, the window or a transition scratch surface
    :param font: display font already sized for this window
    :param text: heading text, written upper case by the caller
    :param x: window x of the heading's left edge, in pixels
    :param top: window y of its top edge, normally from subview_title_top
    """
    window.blit(render_text(font, text, Colors.text), (x, top))


def seeded_avatar_palette(nickname: str, cached_seed: str | None,
                          cached_palette: tuple[pg.Color, pg.Color] | None
                          ) -> tuple[str, tuple[pg.Color, pg.Color]]:
    """
    Keep a player's avatar colors in step with their nickname without hashing
    the name on every frame. The Profile sub-view and the right-rail profile
    card both go through this, which is why the same player wears the same
    tile color in both places

    :param nickname: the name the colors are derived from, may be empty
    :param cached_seed: nickname the cached palette was built for, None before
        anything has been cached
    :param cached_palette: tile fill and letter color kept from last time, or
        None when there is nothing cached yet
    :returns: the seed to remember and the palette to draw with, rebuilt only
        when the nickname has changed
    """
    if cached_palette is None or cached_seed != nickname:
        return nickname, avatar_palette(nickname)
    return cached_seed, cached_palette


class MenuView:
    """
    The contract every menu sub-view implements -- Play, Profile, Options,
    History and the coming-soon stubs. The menu shell builds one of each at
    startup, shows exactly one at a time and drives it only through the hooks
    below, each of which defaults to doing nothing so a view overrides just
    what it needs
    """

    name = ""

    def __init__(self, app: Any) -> None:
        """
        Bind the sub-view to the app shell that hosts it. Sub-views are built
        once and reused for the whole run, never rebuilt when the player
        switches between them

        :param app: the Frontend shell, this view's route to the window,
            sound, toasts, settings and the online coordinator
        """
        self.app = app

    def enter(self, payload: dict[str, Any] | None = None) -> None:
        """
        Become the showing sub-view, called by the menu shell right after the
        previous one exited. Entry always starts from a clean baseline, so
        landing here twice in a row is well defined

        :param payload: optional plain-data payload from whoever asked for
            this view; None means it was opened with nothing to say
        """
        pass

    def exit(self) -> None:
        """
        Stop showing and cancel everything view-local -- typing focus, open
        popovers, drags -- so nothing from this visit leaks into the sub-view
        that replaces it
        """
        pass

    def update(self, now: int) -> None:
        """
        Advance the sub-view one frame before it is drawn, which is where its
        animations step

        :param now: pygame tick count in milliseconds since pygame init
        """
        pass

    def draw(self, window: pg.Surface, menu_layout: MenuLayout) -> None:
        """
        Paint the sub-view into the space the menu gave it. During a menu
        transition the surface is a scratch layer rather than the window, so
        the whole view can be faded and lifted as one piece

        :param window: surface drawn to, the window or a scratch surface
        :param menu_layout: the menu's rects and scale for this window size
        """
        pass

    def relayout(self, menu_layout: MenuLayout) -> None:
        """
        Recompute every rect and font the sub-view owns for a new window size.
        The shell calls it at startup, on a resize and on every view swap,
        including for the views that are not showing

        :param menu_layout: the menu's rects and scale for this window size
        """
        pass

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Handle a left click the rail and the right-hand cards did not already
        take, which is how buttons and rows inside a sub-view are pressed

        :param pos: click position in window pixels
        :returns: True when the sub-view took the click
        """
        return False

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Begin a left-button press, which is where a drag on a control such as
        the time picker's drum starts

        :param pos: press position in window pixels
        :returns: True when the sub-view took the press
        """
        return False

    def handle_motion(self, pos: tuple[int, int]) -> bool:
        """
        Follow the cursor, both while a drag is in flight and while merely
        hovering, which drives drag handling and hover highlighting

        :param pos: cursor position in window pixels
        :returns: True when the sub-view took the motion
        """
        return False

    def handle_release(self, pos: tuple[int, int]) -> bool:
        """
        Finish a left-button drag the sub-view had running

        :param pos: release position in window pixels
        :returns: True when the sub-view took the release
        """
        return False

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Handle a key press, which is where typing into the nickname and server
        fields ends up. Esc and F11 never arrive here

        :param event: pygame KEYDOWN event, key code and unicode both readable
        :returns: True when the sub-view took the key
        """
        return False

    def escape(self) -> bool:
        """
        Handle Esc as a step back inside this sub-view, such as closing an
        open popover. Answering False hands Esc back to the menu, which then
        returns to Play or raises the quit confirmation

        :returns: True when the sub-view dealt with Esc itself
        """
        return False

    def active_scrollable(self, pos: tuple[int, int] | None = None) -> Any:
        """
        Name the widget the mouse wheel should move while this sub-view is
        showing, so the wheel lands on the innermost list that has somewhere
        to go

        :param pos: cursor position in window pixels, or None when the caller
            has no position to offer
        :returns: the scrollable widget, or None when nothing here scrolls
        """
        return None

    def scrollables(self) -> list[Any]:
        """
        List every scrollable this sub-view owns, showing or not, so the shell
        can cancel all scrolling at once when the window is resized

        :returns: the scrollable widgets this view owns
        """
        return []

    def avoid_rects(self) -> list[pg.Rect]:
        """
        Name the areas the pieces skirmishing behind the menu must keep out
        of, which is how a solid panel stops the backdrop showing through it.
        A view that covers nothing opaque claims nothing

        :returns: window-space rects the backdrop battle must avoid
        """
        return []
