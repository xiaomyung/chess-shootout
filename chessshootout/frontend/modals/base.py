import pygame as pg

from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.fonts import get_font

_RAIL_CACHE = new_cache()


DEFAULT_PADDING = 12
MODAL_RADIUS = 14
MODAL_RAIL = 5
MODAL_MAX_WIDTH = 440
BUTTON_VPAD = 16

INTENT_RAIL = {
    "win": (Colors.win, Colors.modal_rail_win_end),
    "loss": (Colors.loss, Colors.modal_rail_loss_end),
    "draw": (Colors.text_dim, Colors.modal_rail_draw_end),
}


class BaseModal:

    consumes_clicks_when_visible = True

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.padding = DEFAULT_PADDING

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self._on_rect_changed()

    def _on_rect_changed(self):
        pass

    def font(self, factor, min_size=12, bold=True):
        size = max(int(self.rect.height / factor), min_size)
        return get_font(size, bold=bold)

    def is_visible(self):
        return False

    def draw(self):
        pass

    def handle_click(self, pos):
        return False

    def content_rect(self, rect=None):
        r = rect if rect is not None else self.rect
        return pg.Rect(
            r.x + self.padding,
            r.y + MODAL_RAIL + self.padding,
            r.width - 2 * self.padding,
            r.height - MODAL_RAIL - 2 * self.padding,
        )

    def draw_shell(self, intent=None, rect=None):
        r = rect if rect is not None else self.rect
        if r.width <= 0 or r.height <= 0:
            return
        pg.draw.rect(self.window, Colors.surface_raised, r, border_radius=MODAL_RADIUS)
        pg.draw.rect(self.window, Colors.border_strong, r, width=1,
                     border_radius=MODAL_RADIUS)
        self.window.blit(self._rail_surface(intent, r.width), r.topleft)

    def _rail_surface(self, intent, width):
        start, end = INTENT_RAIL.get(intent, (Colors.accent, Colors.accent))

        def build():
            def render(surf, k):
                w, _ = surf.get_size()
                railpx = int(MODAL_RAIL * k)
                c0, c1 = pg.Color(start), pg.Color(end)
                for x in range(w):
                    surf.fill(c0.lerp(c1, x / max(w - 1, 1)), pg.Rect(x, 0, 1, railpx))
                mask = pg.Surface(surf.get_size(), pg.SRCALPHA)
                pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                             border_top_left_radius=int(MODAL_RADIUS * k),
                             border_top_right_radius=int(MODAL_RADIUS * k))
                surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
            return supersample((width, MODAL_RADIUS), render)
        return memoized_surface(_RAIL_CACHE, (intent, width, str(start), str(end)), build)
