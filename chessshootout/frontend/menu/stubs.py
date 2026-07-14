import pygame as pg

from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.fonts import get_display_font, get_font


BODY_TEXT = "Coming soon."
BUTTON_TEXT = "Back to Play"
BUTTON_CUT = 8


class StubView(MenuView):

    title = ""

    def __init__(self, app):
        super().__init__(app)
        self._rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._button_rect = pg.Rect(0, 0, 0, 0)

    def relayout(self, menu_layout):
        self._rect = pg.Rect(menu_layout.subview_rect)
        self._scale = menu_layout.scale
        self._title_font = get_display_font(max(int(42 * self._scale), 24))
        self._body_font = get_font(max(int(15 * self._scale), 12), bold=True)
        self._button_font = get_font(max(int(13 * self._scale), 11), bold=True)

    def draw(self, window, menu_layout):
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

        button_w = max(int(168 * scale), 120)
        button_h = max(int(46 * scale), 34)
        bx = rect.centerx - button_w // 2
        byy = by + body.get_height() + int(24 * scale)
        self._button_rect = pg.Rect(bx, byy, button_w, button_h)
        hovered = self._button_rect.collidepoint(pg.mouse.get_pos())
        fill = Colors.surface_raised if hovered else Colors.surface
        window.blit(cut_rect_surface(self._button_rect.size, max(int(BUTTON_CUT * scale), 5),
                                     fill, border=Colors.accent, border_width=1,
                                     corners=("tr", "bl")), self._button_rect.topleft)
        label = render_text(button_font, BUTTON_TEXT, Colors.text if hovered else Colors.text_dim)
        window.blit(label, (self._button_rect.centerx - label.get_width() // 2,
                            self._button_rect.centery - label.get_height() // 2))

    def handle_click(self, pos):
        if self._button_rect.collidepoint(pos):
            self.app.menu.goto_view("play")
            return True
        return False


class BattlePassView(StubView):

    name = "battlepass"
    title = "BATTLE PASS"


class ArmoryView(StubView):

    name = "armory"
    title = "ARMORY"


class SocialView(StubView):

    name = "social"
    title = "SOCIAL"
