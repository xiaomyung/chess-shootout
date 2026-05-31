import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.draw import supersample
from frontend.visual.fonts import get_font


DEFAULT_PADDING = 12
MODAL_RADIUS = 14
MODAL_RAIL = 5

INTENT_RAIL = {
    "win": (Colors.result_win, Colors.modal_rail_win_end),
    "loss": (Colors.result_loss, Colors.modal_rail_loss_end),
    "draw": (Colors.result_neutral, Colors.modal_rail_draw_end),
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

    def content_rect(self):
        return pg.Rect(
            self.rect.x + self.padding,
            self.rect.y + MODAL_RAIL + self.padding,
            self.rect.width - 2 * self.padding,
            self.rect.height - MODAL_RAIL - 2 * self.padding,
        )

    def draw_shell(self, intent=None):
        if self.rect.width <= 0 or self.rect.height <= 0:
            return
        pg.draw.rect(self.window, Colors.modal_bg, self.rect, border_radius=MODAL_RADIUS)
        pg.draw.rect(self.window, Colors.border_strong, self.rect, width=1,
                     border_radius=MODAL_RADIUS)
        self.window.blit(self._rail_surface(intent), self.rect.topleft)

    def _rail_surface(self, intent):
        start, end = INTENT_RAIL.get(intent, (Colors.accent, Colors.accent))
        width = self.rect.width

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
