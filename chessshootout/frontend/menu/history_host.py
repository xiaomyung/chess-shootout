from typing import Any

import pygame as pg

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.frontend.menu.layout import MenuLayout
from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.panels.history_view import HistoryView, PGN_PATTERN


class HistoryMenuView(MenuView):
    """
    The History row of the menu: the browser of saved games, shown in the
    sub-view slot beside the nav rail. History is a menu sub-view rather than a
    screen of its own, and this host keeps no state -- the shell's single
    HistoryView widget does the loading, drawing and clicking, and this only
    shows it, hides it and forwards events to it
    """

    name = "history"

    def enter(self, payload: dict[str, Any] | None = None) -> None:
        """
        Open the browser on the player's saved games. The games folder is read
        afresh every time, so a game that finished a moment ago is already in
        the list, and the player's own name is passed in because that is what
        decides which side each saved result is read from

        :param payload: navigation payload from the menu shell, unused because
            this view always opens on the full list
        """
        self.app.history_view.show(
            str(paths.get_games_dir()), PGN_PATTERN, nickname=env.get_nickname())

    def exit(self) -> None:
        """
        Hide the browser and let it drop everything it had loaded, so a list
        nobody is looking at costs nothing while another sub-view is showing
        """
        self.app.history_view.hide()

    def relayout(self, menu_layout: MenuLayout) -> None:
        """
        Give the browser the menu's sub-view slot, the space between the nav
        rail and the window edge

        :param menu_layout: the menu geometry computed for this window size
        """
        self.app.history_view.set_rect(menu_layout.subview_rect)

    def draw(self, window: pg.Surface, menu_layout: MenuLayout) -> None:
        """
        Paint the browser into the menu, onto whichever surface the shell is
        compositing this frame -- the window itself, or a scratch surface while
        a sub-view transition is running

        :param window: surface to draw on, the window or a scratch surface
        :param menu_layout: the menu geometry for this window size, unused here
            because the browser was given its rect at layout time
        """
        self.app.history_view.draw_onto(window)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Hand a click to the browser, where it switches the filter, folds a
        series open or shut, or opens one saved game for review

        :param pos: click position in window pixels
        :returns: True when the browser took the click
        """
        return self.app.history_view.handle_click(pos)

    def active_scrollable(self, pos: tuple[int, int] | None = None) -> HistoryView:
        """
        Name the browser as what the mouse wheel should move while History is
        showing, it being the only thing on this sub-view that scrolls

        :param pos: cursor position in window pixels, unused because the
            browser fills the whole sub-view slot
        :returns: the saved-game browser
        """
        return self.app.history_view

    def scrollables(self) -> list[HistoryView]:
        """
        List the browser so the shell can cancel its scrolling along with every
        other list in the app when the window is resized

        :returns: the saved-game browser, the only scrollable here
        """
        return [self.app.history_view]

    def avoid_rects(self) -> list[pg.Rect]:
        """
        Say which areas the pieces skirmishing behind the menu must keep out
        of. History claims none, so they roam freely behind the list

        :returns: no rects to avoid
        """
        return []
