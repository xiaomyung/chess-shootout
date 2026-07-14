import pygame as pg

from chessshootout.frontend.menu.options_rows import OptionsBody, _Fonts
from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font


TITLE_TOP_FRAC = 0.05
TITLE_FONT_BASE = 28
TITLE_FONT_FLOOR = 20
TITLE_GAP = 20
TITLE_GAP_FLOOR = 12


class OptionsView(MenuView):

    name = "options"

    def __init__(self, app):
        super().__init__(app)
        self.body = OptionsBody()
        self._rect = pg.Rect(0, 0, 0, 0)
        self._body_rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._title_top = 0
        self._title_font = get_display_font(TITLE_FONT_FLOOR)
        self._fonts_cache = None

    def enter(self, payload=None):
        self.body.set_sections(self.app.settings._build_settings_sections())

    def exit(self):
        self.app.settings._commit_options_exit()

    def _s(self, value, floor=1):
        return max(int(value * self._scale), floor)

    def _fonts(self):
        if self._fonts_cache is None:
            self._fonts_cache = _Fonts(
                title=get_font(self._s(15, 12), bold=True),
                desc=get_font(self._s(12, 10)),
                section=get_mono_font(self._s(11, 10), bold=True),
                value=get_mono_font(self._s(13, 11)),
                button=get_font(self._s(12, 11), bold=True),
            )
        return self._fonts_cache

    def relayout(self, menu_layout):
        self._rect = pg.Rect(menu_layout.subview_rect)
        self._scale = menu_layout.scale
        self._fonts_cache = None
        self._title_font = get_display_font(self._s(TITLE_FONT_BASE, TITLE_FONT_FLOOR))
        self._title_top = self._rect.y + int(self._rect.height * TITLE_TOP_FRAC)
        body_top = self._title_top + self._title_font.get_height() \
            + self._s(TITLE_GAP, TITLE_GAP_FLOOR)
        self._body_rect = pg.Rect(self._rect.x, body_top, self._rect.width,
                                  max(self._rect.bottom - body_top, 0))

    def draw(self, window, menu_layout):
        rect = self._rect
        if rect.width <= 0:
            return
        title = render_text(self._title_font, "OPTIONS", Colors.text)
        window.blit(title, (rect.x, self._title_top))
        if self._body_rect.height <= 0:
            return
        self.body.draw(window, self._body_rect, self._fonts())

    def handle_click(self, pos):
        return self.body.handle_click(pos)

    def handle_press(self, pos):
        return self.body.handle_press(pos)

    def handle_motion(self, pos):
        return self.body.handle_motion(pos)

    def handle_release(self, pos):
        return self.body.handle_release(pos)

    def handle_key(self, event):
        return self.body.handle_key(event)

    def active_scrollable(self, pos=None):
        return self.body

    def scrollables(self):
        return [self.body]
