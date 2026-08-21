from typing import Any

import pygame as pg

from chessshootout.frontend.menu.layout import MenuLayout
from chessshootout.frontend.menu.view import MenuView, scale_floor
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.fonts import get_display_font, get_font


BODY_TEXT = "Coming soon."
BUTTON_TEXT = "Back to Play"
BUTTON_CUT = 8


class StubView(MenuView):
    """
    The coming-soon panel behind the Battle Pass, Armory and Social rail rows.
    Those rows are advertised on purpose -- they say what the game is heading
    towards -- so each one leads here to a title, a coming-soon line and a
    button straight back to Play rather than to a dead row
    """

    title = ""

    def __init__(self, app: Any) -> None:
        """
        Build the placeholder with nothing laid out yet; the rect, the fonts
        and the button all wait for the first relayout

        :param app: the Frontend shell, used here only to reach the menu and
            switch back to Play
        """
        super().__init__(app)
        self._rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._button_rect = pg.Rect(0, 0, 0, 0)

    def relayout(self, menu_layout: MenuLayout) -> None:
        """
        Take the space the menu gave this view and size its three fonts for
        it. Every font is built here and only read while drawing, so no frame
        ever pays to make one

        :param menu_layout: the menu's rects and scale for this window size
        """
        self._rect = pg.Rect(menu_layout.subview_rect)
        self._scale = menu_layout.scale
        self._title_font = get_display_font(scale_floor(42, self._scale, 24))
        self._body_font = get_font(scale_floor(15, self._scale, 12), bold=True)
        self._button_font = get_font(scale_floor(13, self._scale, 11), bold=True)

    def draw(self, window: pg.Surface, menu_layout: MenuLayout) -> None:
        """
        Paint the placeholder: the section title, the coming-soon line and the
        back-to-Play button, all centred in the view's space. The button's hit
        box is settled here, so it can only be clicked once the panel has been
        drawn at least once

        :param window: surface drawn to, the window or a transition scratch
            surface
        :param menu_layout: the menu's rects and scale, unused here since the
            rect and fonts were kept at relayout
        """
        rect = self._rect
        scale = self._scale
        title_font = self._title_font
        body_font = self._body_font
        button_font = self._button_font

        title = render_text(title_font, self.title, Colors.text)
        ty = rect.y + int(rect.height * 0.32)
        window.blit(title, (rect.centerx - title.get_width() // 2, ty))

        body = render_text(body_font, BODY_TEXT, Colors.text_muted)
        by = ty + title.get_height() + int(18 * scale)
        window.blit(body, (rect.centerx - body.get_width() // 2, by))

        button_w = scale_floor(168, scale, 120)
        button_h = scale_floor(46, scale, 34)
        bx = rect.centerx - button_w // 2
        byy = by + body.get_height() + int(24 * scale)
        self._button_rect = pg.Rect(bx, byy, button_w, button_h)
        hovered = self._button_rect.collidepoint(pg.mouse.get_pos())
        fill = Colors.surface_raised if hovered else Colors.surface
        window.blit(cut_rect_surface(self._button_rect.size, scale_floor(BUTTON_CUT, scale, 5),
                                     fill, border=Colors.accent, border_width=1,
                                     corners=("tr", "bl")), self._button_rect.topleft)
        label = render_text(button_font, BUTTON_TEXT, Colors.text if hovered else Colors.text_dim)
        window.blit(label, (self._button_rect.centerx - label.get_width() // 2,
                            self._button_rect.centery - label.get_height() // 2))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Take the one click this panel offers: the button that returns to Play.
        Anything else falls through, so a click elsewhere reaches the menu

        :param pos: click position in window pixels
        :returns: True when the back-to-Play button was hit
        """
        if self._button_rect.collidepoint(pos):
            self.app.menu.goto_view("play")
            return True
        return False


class BattlePassView(StubView):
    """
    The Battle Pass placeholder, opened from its own row on the nav rail
    """

    name = "battlepass"
    title = "BATTLE PASS"


class ArmoryView(StubView):
    """
    The Armory placeholder, opened from its own row on the nav rail
    """

    name = "armory"
    title = "ARMORY"


class SocialView(StubView):
    """
    The Social placeholder, opened from its own row on the nav rail
    """

    name = "social"
    title = "SOCIAL"
